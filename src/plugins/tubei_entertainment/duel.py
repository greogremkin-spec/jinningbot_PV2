""" 晋宁会馆·秃贝五边形 5.0 灵质空间 · 斗帅宫（第三阶段收尾定稿版）

收尾定稿目标：
1. 保留当前群档切磋结算
2. 保留每日演武次数限制（默认 3 次）
3. 保留顿悟机制（第一版）
4. 保留“灵质鉴定结果”投影
5. 成就 / 统计：
   - total_duel_wins
   - total_duel_enlighten
   - 越战越悟
6. 本轮后冻结
"""

from __future__ import annotations

import random

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.adapters import Message

from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.common.utils import ensure_daily_reset
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.mutex import check_mutex, MutexError
from src.plugins.tubei_system.recorder import recorder
from src.plugins.tubei_cultivation.achievement import achievement_engine


duel_cmd = on_command(
    "灵力切磋",
    aliases={"切磋", "PK", "领域较量"},
    priority=5,
    block=True,
)


def _get_duel_daily_limit() -> int:
    return 3


def _build_duel_flavor(win: bool, my_name: str, target_name: str, p_me: int, p_target: int) -> str:
    diff = abs(p_me - p_target)

    if win:
        if diff >= 100:
            return f"{my_name} 的灵压如潮水般压下，{target_name} 几乎没有还手之力。"
        if diff >= 30:
            return f"{my_name} 抓住破绽稳稳压制了 {target_name}，这一战颇有章法。"
        return f"{my_name} 与 {target_name} 激烈交锋，最终险胜一筹。"

    if diff >= 100:
        return f"{target_name} 的灵压完全盖过了 {my_name}，胜负几乎在一瞬间就已分明。"
    if diff >= 30:
        return f"{my_name} 奋力抵挡，但还是被 {target_name} 抓住节奏压了下去。"
    return f"{my_name} 与 {target_name} 斗得难解难分，可惜最终还是差了一线。"


async def _try_enlighten(uid: str, group_id: int, bonus_rate: float = 1.0) -> tuple[bool, int]:
    base_chance = 0.15
    chance = min(1.0, base_chance * bonus_rate)

    if random.random() >= chance:
        data = await data_manager.get_spirit_data(uid, group_id)
        return False, data.get("permanent_meditation_bonus", 0)

    data = await data_manager.get_spirit_data(uid, group_id)
    new_bonus = data.get("permanent_meditation_bonus", 0) + 1
    await data_manager.update_spirit_data(uid, group_id, {
        "permanent_meditation_bonus": new_bonus,
    })
    return True, new_bonus


def _apply_appraise_effect(
    p_me: int,
    target_sp: int,
    appraise_result: dict | None,
) -> tuple[int, int, float, str | None]:
    if not appraise_result or not isinstance(appraise_result, dict):
        return p_me, 0, 1.0, None

    effect = appraise_result.get("duel_effect", "")
    effect_name = appraise_result.get("name", "未知灵质")
    note = None

    steal_bonus = 0
    enlighten_rate = 1.0

    if effect == "stable":
        p_me = int(p_me * 1.03)
        note = f"【{effect_name}】让你的灵压更加稳定。"

    elif effect == "stable_plus":
        p_me = int(p_me * 1.06)
        note = f"【{effect_name}】让你的灵压几乎没有多余杂波。"

    elif effect == "burst":
        p_me = int(p_me * 1.08)
        note = f"【{effect_name}】在战斗中激起了更高的爆发上限。"

    elif effect == "burst_plus":
        p_me = int(p_me * 1.12)
        note = f"【{effect_name}】令你的爆发灵压明显更强。"

    elif effect == "pressure":
        steal_bonus = max(1, int(target_sp * 0.005))
        note = f"【{effect_name}】让你的压制更具锋芒。"

    elif effect == "pressure_plus":
        steal_bonus = max(2, int(target_sp * 0.008))
        note = f"【{effect_name}】让你的压制感几乎具现成形。"

    elif effect == "guard":
        note = f"【{effect_name}】使你在对抗中更沉稳。"

    elif effect == "guard_plus":
        note = f"【{effect_name}】使你的灵压像磐石一样稳固。"

    elif effect == "insight":
        enlighten_rate = 1.5
        note = f"【{effect_name}】让你的神念更接近顿悟边缘。"

    elif effect == "insight_plus":
        enlighten_rate = 2.0
        note = f"【{effect_name}】让你更容易在战后触及顿悟。"

    elif effect == "initiative":
        p_me += 10
        note = f"【{effect_name}】让你的灵压启动更快一步。"

    elif effect == "initiative_plus":
        p_me += 18
        note = f"【{effect_name}】让你仿佛比对手更早进入战斗。"

    elif effect == "chaos":
        p_me = int(p_me * random.uniform(0.95, 1.15))
        note = f"【{effect_name}】让你的灵压结果更难预测。"

    elif effect == "chaos_plus":
        p_me = int(p_me * random.uniform(0.90, 1.25))
        note = f"【{effect_name}】让你的灵压充满混沌而危险的波动。"

    elif effect == "balanced_plus":
        p_me = int(p_me * 1.05)
        steal_bonus = max(1, int(target_sp * 0.003))
        enlighten_rate = 1.25
        note = f"【{effect_name}】给了你全面而平衡的提升。"

    return p_me, steal_bonus, enlighten_rate, note


def _consume_appraise_result(buffs: dict) -> tuple[dict, dict | None]:
    buffs = dict(buffs)
    result = buffs.pop("appraise_result", None)
    return buffs, result


@duel_cmd.handle()
async def handle_duel(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    if ctx.is_private:
        await duel_cmd.finish(
            ui.render_panel(
                "灵质空间 · 斗帅宫",
                "切磋需要在群内 @目标进行。\n\n"
                "请前往目标群发送：\n"
                "切磋 @某人",
                footer="私聊中暂不支持切磋",
            )
        )

    perm = await check_permission(
        event,
        "灵质空间 · 斗帅宫",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await duel_cmd.finish(perm.deny_message)

    try:
        await check_mutex(uid, ctx.group_id, "entertainment")
    except MutexError as e:
        await duel_cmd.finish(e.message)

    my_data = await data_manager.get_spirit_data(uid, ctx.group_id)
    daily = ensure_daily_reset(my_data, extra_fields={"duel": 0})
    duel_limit = _get_duel_daily_limit()

    if daily.get("duel", 0) >= duel_limit:
        await duel_cmd.finish(
            ui.render_panel(
                "灵质空间 · 斗帅宫",
                f"你今天已经完成 {duel_limit} 场演武了。\n\n"
                "今日感悟已满，明日再来切磋吧。",
                footer=" 输入 聚灵 | 档案",
            )
        )

    target_id = ""
    for seg in event.message:
        if seg.type == "at":
            target_id = str(seg.data["qq"])
            break

    if not target_id:
        await duel_cmd.finish(
            ui.render_panel(
                "灵质空间 · 斗帅宫",
                "与其他妖灵进行友好的灵力比拼。\n\n"
                "⚔规则：比拼灵力总值 (含±20%波动)\n"
                "🏆胜者：吸取对方 1% 灵力 (上限 20)\n"
                "🛡保护：对方灵力<50 时不吸取\n"
                "😵败者：无损失 (仅颜面扫地)\n"
                "🧠演武结束后有概率获得【顿悟】\n"
                f"📅每日演武上限：{duel_limit} 次\n"
                "🔬若事先做过灵质鉴定，鉴定结果会投影到本次演武中",
                footer=" 输入 切磋 @某人",
            )
        )

    if target_id == uid:
        await duel_cmd.finish(ui.error("不能和自己切磋~"))

    group_members = await data_manager.get_group_members(ctx.group_id)
    if uid not in group_members:
        await duel_cmd.finish(ui.info("你尚未在当前群建立可用于切磋的档案。"))
    if target_id not in group_members:
        await duel_cmd.finish(ui.error("对方未在当前群建立档案，无法切磋。"))

    me_data = await data_manager.get_spirit_data(uid, ctx.group_id)
    target_data = await data_manager.get_spirit_data(target_id, ctx.group_id)

    my_sp = me_data.get("sp", 0)
    target_sp = target_data.get("sp", 0)

    fluct = game_config.duel_fluctuation
    p_me = int(my_sp * random.uniform(1 - fluct, 1 + fluct))
    p_target = int(target_sp * random.uniform(1 - fluct, 1 + fluct))

    my_member = await data_manager.get_member_info(uid)
    target_member = await data_manager.get_member_info(target_id)
    my_group_profile = await data_manager.get_member_group_profile(uid, ctx.group_id)
    target_group_profile = await data_manager.get_member_group_profile(target_id, ctx.group_id)

    my_name = (
        (my_group_profile or {}).get("spirit_name")
        or (my_member or {}).get("spirit_name")
        or "你"
    )
    target_name = (
        (target_group_profile or {}).get("spirit_name")
        or (target_member or {}).get("spirit_name")
        or f"对手({target_id})"
    )

    daily["duel"] = daily.get("duel", 0) + 1

    my_buffs = dict(me_data.get("buffs", {}))
    my_buffs, appraise_result = _consume_appraise_result(my_buffs)
    p_me, steal_bonus, enlighten_rate, appraise_note = _apply_appraise_effect(
        p_me, target_sp, appraise_result
    )

    await data_manager.update_spirit_data(uid, ctx.group_id, {
        "daily_counts": daily,
        "buffs": my_buffs,
    })

    if p_me > p_target:
        steal_rate = game_config.duel_steal_rate
        steal_cap = game_config.duel_steal_cap
        protection = game_config.duel_protection_threshold

        steal = min(steal_cap, int(target_sp * steal_rate))
        steal += steal_bonus

        if target_sp < protection:
            steal = 0

        await data_manager.update_spirit_data(uid, ctx.group_id, {
            "sp": my_sp + steal,
        })

        if steal > 0:
            await data_manager.update_spirit_data(target_id, ctx.group_id, {
                "sp": max(0, target_sp - steal),
            })

        await data_manager.increment_group_stat(uid, ctx.group_id, "total_duel_wins", 1)

        await recorder.add_event("duel_win", int(uid), {
            "opponent": target_id,
            "steal": steal,
            "group_id": ctx.group_id,
            "appraise_effect": appraise_result.get("duel_effect") if appraise_result else None,
        })

        await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)

        enlightened, new_bonus = await _try_enlighten(uid, ctx.group_id, bonus_rate=enlighten_rate)
        flavor = _build_duel_flavor(True, my_name, target_name, p_me, p_target)

        extra_lines = []
        if appraise_note:
            extra_lines.append(appraise_note)
        extra_lines.append(flavor)

        if enlightened:
            await data_manager.increment_group_stat(uid, ctx.group_id, "total_duel_enlighten", 1)
            await achievement_engine.try_unlock(uid, "越战越悟", bot, event, group_id=ctx.group_id)
            await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)
            extra_lines.append(f"🧠顿悟降临！永久聚灵收益 +1（当前永久聚灵加成：+{new_bonus}）")

        card = ui.render_result_card(
            "灵质空间 · 切磋结果",
            "🏆胜利！",
            stats=[
                ("你的灵压", str(p_me)),
                ("对手灵压", str(p_target)),
                ("", ""),
                ("结果", f"{my_name} 压制了 {target_name}"),
                ("吸取灵力", f"+{steal}" if steal > 0 else "对方灵力过低，未吸取"),
                ("今日演武", f"{daily['duel']}/{duel_limit}"),
            ],
            extra="\n".join(extra_lines),
            footer=" 输入 切磋 @某人 再战",
        )
    else:
        flavor = _build_duel_flavor(False, my_name, target_name, p_me, p_target)
        enlightened, new_bonus = await _try_enlighten(uid, ctx.group_id, bonus_rate=enlighten_rate)

        extra_lines = []
        if appraise_note:
            extra_lines.append(appraise_note)
        extra_lines.append(flavor)

        if enlightened:
            await data_manager.increment_group_stat(uid, ctx.group_id, "total_duel_enlighten", 1)
            await achievement_engine.try_unlock(uid, "越战越悟", bot, event, group_id=ctx.group_id)
            await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)
            extra_lines.append(f"🧠虽败犹悟！永久聚灵收益 +1（当前永久聚灵加成：+{new_bonus}）")

        card = ui.render_result_card(
            "灵质空间 · 切磋结果",
            "😵惜败...",
            stats=[
                ("你的灵压", str(p_me)),
                ("对手灵压", str(p_target)),
                ("", ""),
                ("结果", f"{target_name} 更胜一筹"),
                ("损失", "无 (仅颜面扫地)"),
                ("今日演武", f"{daily['duel']}/{duel_limit}"),
            ],
            extra="\n".join(extra_lines),
            footer=" 输入 聚灵 提升实力 | 切磋 再战",
        )

    await duel_cmd.finish(MessageSegment.at(uid) + "\n" + card)