""" 晋宁会馆·秃贝五边形 5.0 灵力宿命（今日灵伴）+ 灵质鉴定 + 今日老婆（结构收口版）

收口目标：
1. 保留全部现有能力，不删减功能
2. 灵伴 / 今日老婆 / 退出彩蛋 / 鉴定职责分层更清晰
3. 鉴定继续保持：
   - 递增消耗
   - 稀有词条判定
   - appraise_result 写入 buff
   - 演武投影兼容
4. 尽量不改现有文案与用户体验
"""
from __future__ import annotations

import random
import hashlib
import logging
import math
from datetime import datetime

from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    MessageEvent,
    MessageSegment,
    GroupMessageEvent,
)

from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.common.utils import get_today_str, check_blessing, ensure_daily_reset
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.mutex import check_mutex, MutexError
from src.plugins.tubei_system.recorder import recorder
from src.plugins.tubei_cultivation.achievement import achievement_engine

logger = logging.getLogger("tubei.resonance")

# ==================== 灵质鉴定结果定义（定稿版） ====================
APPRAISE_NORMAL_RESULTS = [
    {
        "name": "清澄",
        "duel_effect": "stable",
        "desc": "灵质纯净，灵压波动更稳定",
        "duel_text": "下一场演武中，你的灵压波动将更稳定。",
    },
    {
        "name": "暴走",
        "duel_effect": "burst",
        "desc": "灵质躁动，灵压上限会更高",
        "duel_text": "下一场演武中，你的灵压上限将略微提升。",
    },
    {
        "name": "凝锋",
        "duel_effect": "pressure",
        "desc": "灵质如刃，压制对手时更具锋芒",
        "duel_text": "下一场演武中，你更容易在优势局中扩大压制。",
    },
    {
        "name": "镇流",
        "duel_effect": "guard",
        "desc": "灵质沉稳，更擅长守势与缓冲",
        "duel_text": "下一场演武中，你对被吸取灵力的抗性会略有提升。",
    },
    {
        "name": "回响",
        "duel_effect": "insight",
        "desc": "灵质回响，神念更容易触及顿悟边缘",
        "duel_text": "下一场演武后，你触发顿悟的概率会略有提升。",
    },
    {
        "name": "空鸣",
        "duel_effect": "initiative",
        "desc": "灵质轻盈，灵压更容易快速启动",
        "duel_text": "下一场演武中，你的起手灵压会略微上浮。",
    },
    {
        "name": "混沌",
        "duel_effect": "chaos",
        "desc": "灵质紊乱，却蕴含难以预测的可能",
        "duel_text": "下一场演武中，你的灵压结果将更不可预测。",
    },
]

APPRAISE_RARE_RESULTS = [
    {
        "name": "虚空之主",
        "duel_effect": "burst_plus",
        "desc": "灵质边缘出现虚空纹理，爆发力异常惊人",
        "duel_text": "下一场演武中，你的灵压上限将显著提升。",
    },
    {
        "name": "天选之子",
        "duel_effect": "insight_plus",
        "desc": "灵质轨迹自然顺遂，似乎连运势都在偏向你",
        "duel_text": "下一场演武中，你更容易在战后触发顿悟。",
    },
    {
        "name": "万灵归宗",
        "duel_effect": "stable_plus",
        "desc": "灵质回路高度归一，几乎没有多余杂波",
        "duel_text": "下一场演武中，你的灵压将非常稳定。",
    },
    {
        "name": "星辰之眼",
        "duel_effect": "pressure_plus",
        "desc": "灵质深处闪烁着细碎星辉，压制感极强",
        "duel_text": "下一场演武中，你的压制效果将更明显。",
    },
    {
        "name": "时空旅者",
        "duel_effect": "initiative_plus",
        "desc": "灵质边界轻微错位，像是提前一步进入了战斗",
        "duel_text": "下一场演武中，你的先发灵压会更强。",
    },
    {
        "name": "不朽神性",
        "duel_effect": "guard_plus",
        "desc": "灵质中带着极淡却顽固的余辉，难以被轻易撼动",
        "duel_text": "下一场演武中，你将更难被对手吸取灵力。",
    },
    {
        "name": "混沌本源",
        "duel_effect": "chaos_plus",
        "desc": "灵质完全无法被稳定描述，却蕴含惊人的不可测性",
        "duel_text": "下一场演武中，你的结果将极不稳定，但上限更高。",
    },
    {
        "name": "灵界行者",
        "duel_effect": "balanced_plus",
        "desc": "灵质呈现罕见的平衡态，像是天生适合行走战场",
        "duel_text": "下一场演武中，你会获得更均衡的综合提升。",
    },
]


# ==================== 指令注册 ====================
soulmate_slash_cmd = on_command("灵伴", aliases={"今日灵伴", "宿命共鸣"}, priority=5, block=True)
waifu_slash_cmd = on_command("今日老婆", aliases={"群友老婆"}, priority=5, block=True)
appraise_cmd = on_command("灵质鉴定", aliases={"鉴定", "灵力检测"}, priority=5, block=True)


# ==================== 工具函数：配对 / 展示 ====================
def _build_pairs(member_ids: list[str], date_str: str, salt: str = "") -> dict[str, str]:
    if len(member_ids) < 2:
        return {}

    sorted_ids = sorted(member_ids)
    seed = int(hashlib.sha256(f"{salt}_{date_str}".encode()).hexdigest(), 16)
    rng = random.Random(seed)
    rng.shuffle(sorted_ids)

    pairs: dict[str, str] = {}
    i = 0
    while i + 1 < len(sorted_ids):
        a = sorted_ids[i]
        b = sorted_ids[i + 1]
        pairs[a] = b
        pairs[b] = a
        i += 2

    if len(sorted_ids) % 2 == 1:
        last = sorted_ids[-1]
        first = sorted_ids[0]
        pairs[last] = first

    return pairs


async def _get_group_members(bot: Bot, event: GroupMessageEvent):
    group_id = event.group_id
    bot_id = str(event.self_id)

    try:
        group_members = await bot.get_group_member_list(group_id=group_id)
    except Exception as e:
        logger.error(f"[Resonance] 获取群成员列表失败: {e}")
        return None

    all_member_ids = []
    member_info_map = {}
    for m in group_members:
        mid = str(m["user_id"])
        if mid == bot_id:
            continue
        all_member_ids.append(mid)
        member_info_map[mid] = {
            "nickname": m.get("nickname", ""),
            "card": m.get("card", ""),
        }

    return all_member_ids, member_info_map


def _get_display_name(member_info_map: dict, uid: str) -> str:
    info = member_info_map.get(uid, {})
    return info.get("card") or info.get("nickname") or f"妖灵{uid}"


def _avatar_url(qq: str) -> str:
    return f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640"


def _calc_resonance(sp_a: int, sp_b: int) -> int:
    base = min(sp_a, sp_b)
    rand_part = random.randint(5, 15)
    sqrt_part = int(math.sqrt(base))
    return rand_part + sqrt_part


def _get_appraise_cost(daily_count: int) -> int:
    return game_config.appraise_cost + max(0, daily_count) * 2


def _roll_appraise_result(is_rare: bool) -> dict:
    if is_rare:
        return random.choice(APPRAISE_RARE_RESULTS)
    return random.choice(APPRAISE_NORMAL_RESULTS)


def _build_soulmate_result(date_seed: str, ctx: GroupContext, all_member_ids: list[str], uid: str) -> Optional[str]:
    pairs = _build_pairs(all_member_ids, date_seed, salt=f"soulmate_{ctx.group_id}")
    return pairs.get(uid)


def _build_waifu_result(date_seed: str, ctx: GroupContext, all_member_ids: list[str], uid: str) -> Optional[str]:
    pairs = _build_pairs(all_member_ids, date_seed, salt=f"waifu_{ctx.group_id}")
    return pairs.get(uid)


# ==================== 工具函数：灵伴奖励 ====================
async def _apply_soulmate_bonus(
    uid: str,
    partner_id: str,
    group_id: int,
) -> tuple[str, int]:
    """返回 (resonance_msg, gain)。"""
    group_members = await data_manager.get_group_members(group_id)

    a_registered = uid in group_members
    b_registered = partner_id in group_members

    today_str = get_today_str()

    if not a_registered:
        return "\n\n 建立灵力档案后可激活灵力共鸣~\n/登记", 0

    a_spirit = await data_manager.get_spirit_data(uid, group_id)
    already_claimed = (a_spirit.get("last_soulmate_bonus_date") == today_str)
    if already_claimed:
        return "\n 今日已感应过灵伴的共鸣，加成已生效。", 0

    sp_a = a_spirit.get("sp", 0)

    if b_registered:
        b_spirit = await data_manager.get_spirit_data(partner_id, group_id)
        sp_b = b_spirit.get("sp", 0)

        gain = _calc_resonance(sp_a, sp_b)
        new_sp = sp_a + gain
        await data_manager.update_spirit_data(uid, group_id, {
            "sp": new_sp,
            "last_soulmate_bonus_date": today_str,
        })
        await recorder.add_event(
            "soulmate_resonance",
            int(uid),
            {
                "partner": partner_id,
                "gain": gain,
                "type": "full",
                "group_id": group_id,
            },
        )
        return (
            f"\n\n☯ 灵力共鸣激活！\n"
            f"共鸣强度：{gain}\n"
            f"灵力 +{gain}",
            gain,
        )

    full_gain = _calc_resonance(sp_a, 0)
    gain = max(1, full_gain // 2)
    new_sp = sp_a + gain

    await data_manager.update_spirit_data(uid, group_id, {
        "sp": new_sp,
        "last_soulmate_bonus_date": today_str,
    })
    await recorder.add_event(
        "soulmate_resonance",
        int(uid),
        {
            "partner": partner_id,
            "gain": gain,
            "type": "half",
            "group_id": group_id,
        },
    )
    return (
        f"\n\n☯ 微弱共鸣...\n"
        f"共鸣强度：{gain}\n"
        f"灵力 +{gain}\n"
        f"（对方尚未在当前群建立灵力档案）",
        gain,
    )


# ==================== 工具函数：鉴定 ====================
def _build_appraise_result_payload(result_cfg: dict, is_rare: bool, score: int) -> dict:
    return {
        "name": result_cfg["name"],
        "rarity": "rare" if is_rare else "normal",
        "score": score,
        "duel_effect": result_cfg["duel_effect"],
        "desc": result_cfg["desc"],
        "duel_text": result_cfg["duel_text"],
        "expire_mode": "next_duel",
        "created_at": int(datetime.now().timestamp()),
    }


def _build_appraise_tags(result_cfg: dict, is_rare: bool) -> list[str]:
    tags = []
    if is_rare:
        tags.append("稀有灵质")
    tags.append(f"演武投影:{result_cfg['duel_effect']}")
    return tags


async def _consume_appraise_cost_and_count(uid: str, group_id: int, current_sp: int, cost: int, daily: dict):
    await data_manager.update_spirit_data(uid, group_id, {"sp": current_sp - cost})
    await data_manager.update_spirit_daily_counts(uid, group_id, daily, merge=False)


def _pick_appraise_rarity(buffs: dict) -> tuple[bool, dict]:
    buffs = dict(buffs)

    is_rare = False
    if buffs.pop("鸾草", None):
        is_rare = True
    elif check_blessing(buffs, "resonance"):
        is_rare = True
    else:
        is_rare = random.random() < game_config.rare_chance

    return is_rare, buffs


# ==================== 今日灵伴 ====================
async def _handle_soulmate(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await bot.send(event, "灵伴匹配需要在群内使用~\n 去群里发送 今日灵伴 试试吧")
        return

    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "灵力宿命 · 今日灵伴",
        min_tier="allied",
        deny_promotion=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await bot.send(event, perm.deny_message)
        return

    result = await _get_group_members(bot, event)
    if result is None:
        await bot.send(event, ui.error("获取群成员列表失败，请稍后再试~"))
        return

    all_member_ids, member_info_map = result
    if len(all_member_ids) < 2:
        await bot.send(event, ui.info("群内人数不足，无法匹配灵伴~"))
        return

    today = datetime.now().strftime("%Y%m%d")
    partner_id = _build_soulmate_result(today, ctx, all_member_ids, uid)
    if not partner_id:
        await bot.send(event, ui.info("今日灵伴匹配异常，请稍后再试~"))
        return

    partner_name = _get_display_name(member_info_map, partner_id)
    resonance_msg, _ = await _apply_soulmate_bonus(uid, partner_id, ctx.group_id)

    msg = (
        MessageSegment.at(event.user_id)
        + " 检测到灵力共鸣！你今日的灵伴是:\n"
        + MessageSegment.image(_avatar_url(partner_id))
        + f"\n【{partner_name}】({partner_id})\n"
        + "你们的灵质空间产生了宿命般的共振 ✨"
        + resonance_msg
    )
    await bot.send(event, msg)


@soulmate_slash_cmd.handle()
async def handle_soulmate_slash(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await soulmate_slash_cmd.finish(
            ui.info(
                "灵伴匹配需要在群内使用~\n"
                "去群里发送 /灵伴 试试吧"
            )
        )

    await _handle_soulmate(bot, event)
    await soulmate_slash_cmd.finish()


# ==================== 今日老婆 ====================
async def _handle_waifu(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await bot.send(event, "今日老婆需要在群内使用哦~")
        return

    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    result = await _get_group_members(bot, event)
    if result is None:
        await bot.send(event, "获取群成员列表失败，请稍后再试~")
        return

    all_member_ids, member_info_map = result
    if len(all_member_ids) < 2:
        await bot.send(event, "群内人数不足，无法匹配~")
        return

    today = datetime.now().strftime("%Y%m%d")
    partner_id = _build_waifu_result(today, ctx, all_member_ids, uid)
    if not partner_id:
        await bot.send(event, "匹配异常，请稍后再试~")
        return

    partner_name = _get_display_name(member_info_map, partner_id)
    now_time = datetime.now().strftime("%H:%M:%S")

    from src.common.group_manager import TIER_DANGER, TIER_PUBLIC
    group_tier = ctx.group_tier

    if group_tier in (TIER_DANGER, TIER_PUBLIC):
        msg = (
            MessageSegment.at(event.user_id)
            + "\n 你今天的群友老婆是:\n"
            + MessageSegment.image(_avatar_url(partner_id))
            + f"\n【{partner_name}】({partner_id})\n"
            + "\n"
            + "[疯狂致敬膜拜 Sam 的萝卜 2 号机]\n"
            + "[反馈请联系 3141451467]\n"
            + "[秃贝 2154181438]\n"
            + "发送[退出此群]让我退出\n"
            + "自动报刀故障维修中。\n"
            + "From [广播系统]\n"
            + f"{now_time}"
        )
    else:
        msg = (
            MessageSegment.at(event.user_id)
            + "\n 你今天的群友老婆是:\n"
            + MessageSegment.image(_avatar_url(partner_id))
            + f"\n【{partner_name}】({partner_id})\n"
            + "\n"
            + "[疯狂致敬膜拜 Sam 的萝卜 2 号机]\n"
            + "[反馈请联系：3141451467]\n"
            + "[晋宁会馆 564234162]\n"
            + "发送[退出此群]让我退出\n"
            + "自动报刀故障维修中。\n"
            + "From [广播系统]\n"
            + f"{now_time}"
        )

    await bot.send(event, msg)


@waifu_slash_cmd.handle()
async def handle_waifu_slash(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        await waifu_slash_cmd.finish("今日老婆需要在群内使用~")

    await _handle_waifu(bot, event)
    await waifu_slash_cmd.finish()


# ==================== 退出彩蛋 ====================
async def _handle_quit_easter_egg(bot: Bot, event: MessageEvent):
    if not isinstance(event, GroupMessageEvent):
        return

    responses = [
        "哎呀~秃贝的这个功能只是为了致敬萝卜前辈啦！你不会真的想让俺退群吧 (嘿咻)",
        "呜哇！别别别！秃贝只是在 cos 萝卜前辈而已！退群什么的才不会呢 (OvO)",
        "你认真的吗？！这只是致敬萝卜的彩蛋啦~秃贝才不走呢，哼！",
        "这是致敬萝卜前辈的经典功能~但秃贝可不会真的退群哦，这里是我的家嘛 (嘿咻)",
        "检测到退群指令...正在执行...\n\n 开玩笑的啦！这只是致敬萝卜前辈的彩蛋功能，并非实际指令，秃贝哪儿也不去~ (OvO)",
    ]
    await bot.send(event, random.choice(responses))


# ==================== 灵质鉴定 ====================
@appraise_cmd.handle()
async def handle_appraise(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "灵质鉴定",
        min_tier="public",
        ctx=ctx,
    )
    if not perm.allowed:
        await appraise_cmd.finish(perm.deny_message)

    try:
        await check_mutex(uid, ctx.group_id, "resonance")
    except MutexError as e:
        await appraise_cmd.finish(e.message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    daily = ensure_daily_reset(data, extra_fields={"appraise": 0})

    current_sp = data.get("sp", 0)
    appraise_count_today = daily.get("appraise", 0)
    cost = _get_appraise_cost(appraise_count_today)

    if current_sp < cost:
        footer = " 输入 聚灵 | 档案"
        if ctx.is_private:
            footer += f"\n 当前操作群：{ctx.group_name}"

        await appraise_cmd.finish(
            ui.render_data_card(
                "灵质鉴定",
                [
                    ("本次消耗", f"{cost} 灵力"),
                    ("当前", f"{current_sp} 灵力"),
                    ("今日已鉴定", f"{appraise_count_today} 次"),
                    ("", ""),
                    ("提示", "连续鉴定会越来越耗灵力"),
                ],
                footer=footer,
            )
        )

    # 先扣费与计次
    daily["appraise"] = appraise_count_today + 1
    await _consume_appraise_cost_and_count(uid, ctx.group_id, current_sp, cost, daily)

    await data_manager.increment_group_stat(uid, ctx.group_id, "total_appraise_count", 1)

    buffs = dict(data.get("buffs", {}))
    is_rare, buffs = _pick_appraise_rarity(buffs)

    score = random.randint(0, 100)
    result_cfg = _roll_appraise_result(is_rare)
    appraise_result = _build_appraise_result_payload(result_cfg, is_rare, score)

    buffs["appraise_result"] = appraise_result
    await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)

    await recorder.add_event(
        "resonance",
        int(uid),
        {
            "score": score,
            "keyword": result_cfg["name"],
            "rare": is_rare,
            "group_id": ctx.group_id,
            "duel_effect": result_cfg["duel_effect"],
        },
    )

    if is_rare:
        await achievement_engine.try_unlock(uid, "稀有灵质", bot, event, group_id=ctx.group_id)

    await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)

    prefix = " " if is_rare else "✨"
    rarity_text = "稀有" if is_rare else "普通"
    tags = _build_appraise_tags(result_cfg, is_rare)

    footer = " 输入 鉴定 再来一次 | 切磋 @某人"
    if ctx.is_private:
        footer += f"\n 当前操作群：{ctx.group_name}"

    card = ui.render_result_card(
        "灵质鉴定报告",
        f"{prefix} 鉴定完成！",
        stats=[
            ("灵力纯度", f"{score}%"),
            ("灵质属性", f"【{result_cfg['name']}】({rarity_text})"),
            ("灵质描述", result_cfg["desc"]),
            ("演武投影", result_cfg["duel_text"]),
            ("消耗", f"-{cost} 灵力"),
        ],
        tags=tags,
        extra=f"今日第 {daily['appraise']} 次鉴定，下一次鉴定消耗会继续上升。",
        footer=footer,
    )
    await appraise_cmd.finish(MessageSegment.at(uid) + "\n" + card)