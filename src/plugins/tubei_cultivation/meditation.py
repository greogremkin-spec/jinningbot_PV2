""" 晋宁会馆·秃贝五边形 5.0 聚灵台 —— 聚灵修行 + 每日灵签 + 个人档案（升级收口版）

v5.0 目标：
1. 全部数据读写显式接入 group_id（通过 GroupContext）
2. 私聊通过绑定群操作数据
3. 不再依赖旧式 DataManager 兼容桥
4. 共享指针档自动跟随主档
5. 世界事件全服同步检查
6. 祭坛税收仍为全局
7. 保留全部原有机制：
   - 时段文案
   - 等级晋升
   - 运势加成
   - buff 处理
   - 永久加成
   - 吉兆
   - 深夜成就
   - 档案展示（当前群 + 全局并列）
8. 本轮增强：
   - 灵签宜忌按 tier 分层读取
   - 聚灵写回拆分，降低并发覆盖风险
   - 保持原有功能不删减
"""

from __future__ import annotations

import random
import time
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment

from src.common.data_manager import data_manager
from src.common.response_manager import resp_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.common.group_manager import group_manager
from src.common.utils import (
    get_today_str, ensure_daily_reset, timestamp_now, get_current_hour, check_blessing,
)
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.recorder import recorder
from src.plugins.tubei_system.mutex import check_mutex, MutexError
from src.plugins.tubei_cultivation.achievement import achievement_engine

# ==================== 指令注册 ====================
meditate_cmd = on_command("聚灵", aliases={"聚灵修行"}, priority=5, block=True)
fortune_cmd = on_command("求签", aliases={"每日灵签"}, priority=5, block=True)
profile_cmd = on_command("我的档案", aliases={"个人信息", "状态", "档案"}, priority=5, block=True)


# ==================== 时段判断 ====================
def _get_time_period() -> str:
    """根据当前小时数返回时段标识。"""
    h = get_current_hour()
    if 5 <= h < 9:
        return "dawn"
    if 9 <= h < 14:
        return "noon"
    if 14 <= h < 18:
        return "afternoon"
    if 18 <= h < 22:
        return "dusk"
    return "night"


async def _get_scene_text() -> str:
    """根据时段获取聚灵场景文案。"""
    period = _get_time_period()
    period_key = f"cultivation.meditate_scene_{period}"
    pool = resp_manager.get_list(period_key)
    if pool:
        return random.choice(pool)
    return await resp_manager.get_text("cultivation.meditate_scene")


# ==================== 等级检查 ====================
async def check_levelup(uid: str, group_id: int, current_sp: int, current_level: int) -> str:
    """检查是否晋升等级。"""
    level_map = game_config.level_map
    level_titles = game_config.level_titles

    new_level = current_level
    for lv in sorted(level_map.keys(), reverse=True):
        if lv > current_level and current_sp >= level_map[lv]:
            new_level = lv
            break

    if new_level > current_level:
        await data_manager.update_spirit_data(uid, group_id, {"level": new_level})
        title = level_titles.get(new_level, "未知")

        spirit = await data_manager.get_spirit_data(uid, group_id)
        history = spirit.get("title_history", [])
        history.append({
            "level": new_level,
            "title": title,
            "date": get_today_str(),
        })
        await data_manager.update_spirit_data(uid, group_id, {"title_history": history})

        return await resp_manager.get_text(
            "cultivation.levelup",
            {"level": new_level, "title": title},
        )
    return ""


# ==================== 聚灵修行 ====================
@meditate_cmd.handle()
async def handle_meditate(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "聚灵台 · 灵质修行",
        min_tier="allied",
        require_registered=True,
        deny_promotion=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await meditate_cmd.finish(perm.deny_message)

    try:
        await check_mutex(uid, ctx.group_id, "meditation")
    except MutexError as e:
        await meditate_cmd.finish(e.message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)

    # 冷却检查保持不变：额外机会只是不占 normal 次数，不代表无视冷却
    if timestamp_now() - data.get("last_meditate_time", 0) < game_config.meditation_cooldown:
        msg = await resp_manager.get_text("system.cooldown", {"nickname": "小友"})
        await meditate_cmd.finish(msg)

    daily = ensure_daily_reset(
        data,
        extra_fields={
            "meditation": 0,
            "spirit_tide_bonus_used": False,
            "spirit_tide_bonus_date": "",
        },
    )

    from src.plugins.tubei_system.world_event import is_event_active
    tide_active = await is_event_active("spirit_tide")

    today = get_today_str()
    normal_available = daily.get("meditation", 0) < game_config.meditation_daily_limit
    tide_bonus_available = (
        tide_active
        and not (
            daily.get("spirit_tide_bonus_date", "") == today
            and daily.get("spirit_tide_bonus_used", False)
        )
    )

    used_mode = None
    if normal_available:
        used_mode = "normal"
    elif tide_bonus_available:
        used_mode = "spirit_tide_bonus"
    else:
        if not await data_manager.is_daily_reset_active():
            await meditate_cmd.finish("今日修行已达上限，请明日再来。")

    # 先检查晋升（用当前灵力先做一次补偿检查）
    levelup_msg = await check_levelup(uid, ctx.group_id, data.get("sp", 0), data.get("level", 1))
    if levelup_msg:
        await meditate_cmd.finish(levelup_msg)

    # ===== 计算收益 =====
    level = data.get("level", 1)
    level_bonus_list = game_config.meditation_level_bonus
    lvl_bonus = level_bonus_list[min(level, len(level_bonus_list) - 1)]
    base = random.randint(game_config.meditation_base_min, game_config.meditation_base_max)

    # Buff
    buffs = dict(data.get("buffs", {}))
    bf_bonus = 0.0
    if buffs.pop("蓝玉果", None):
        base = game_config.meditation_base_max
    if buffs.pop("聚气 Lv1", None):
        bf_bonus += 0.05
    if buffs.pop("聚气 MAX", None):
        bf_bonus += 0.20
    if buffs.pop("天佑", None):
        base = game_config.meditation_base_max

    # 运势
    fortune_mults = game_config.fortune_mults
    fortune_today = data.get("fortune_today", "平")
    blessing_active = check_blessing(buffs, "meditation")
    if blessing_active:
        fortune_today = "大吉"

    mult = fortune_mults.get(fortune_today, 0)
    if buffs.pop("灵心草", None):
        mult += 0.5

    # 世界事件：灵潮（收益加成本身保留）
    from src.plugins.tubei_system.world_event import get_event_bonus
    tide_bonus = await get_event_bonus("spirit_tide")
    if tide_bonus > 0:
        mult += tide_bonus

    # 祭坛 Buff（全局）
    bot_status = await data_manager.get_bot_status()
    ritual_buff = bot_status.get("ritual_buff_active", False)
    if ritual_buff:
        base += game_config.altar_buff_bonus

    # 永久加成
    permanent_bonus = data.get("permanent_meditation_bonus", 0)
    final_sp = int((base + lvl_bonus + permanent_bonus) * (1 + mult + bf_bonus))
    if final_sp < 0:
        final_sp = 0

    msg_tail = ""
    current_sp = data.get("sp", 0)
    new_sp = current_sp + final_sp

    # ===== 更新 daily =====
    if used_mode == "normal":
        daily["meditation"] = daily.get("meditation", 0) + 1
    elif used_mode == "spirit_tide_bonus":
        daily["spirit_tide_bonus_used"] = True
        daily["spirit_tide_bonus_date"] = today

    # 写回群档（拆分写回，降低并发覆盖风险）
    await data_manager.update_spirit_data(
        uid,
        ctx.group_id,
        {
            "sp": new_sp,
            "last_meditate_time": timestamp_now(),
        },
    )
    await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
    await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)

    # 统计
    await data_manager.increment_group_stat(uid, ctx.group_id, "total_meditation_count", 1)
    await data_manager.increment_group_stat(uid, ctx.group_id, "total_sp_earned", final_sp)

    # 检查晋升
    levelup_msg_2 = await check_levelup(uid, ctx.group_id, new_sp, level)
    if levelup_msg_2:
        msg_tail += "\n" + levelup_msg_2

    # 祭坛税收（全局）
    tax = max(1, int(final_sp * game_config.altar_tax_rate))
    await data_manager.update_altar_energy(tax)
    await data_manager.increment_global_stat(uid, "altar_contributions", tax)

    # 日志
    await recorder.add_event(
        "meditation",
        int(uid),
        {
            "sp_gain": final_sp,
            "group_id": ctx.group_id,
            "mode": used_mode,
        },
    )

    # 成就
    if final_sp >= 50:
        await achievement_engine.try_unlock(uid, "一夜暴富", bot, event, group_id=ctx.group_id)
    if get_current_hour() == 0:
        await achievement_engine.try_unlock(uid, "深夜修行者", bot, event, group_id=ctx.group_id)
    await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)

    # ===== 构建反馈 =====
    scene = await _get_scene_text()
    tags = []
    if blessing_active:
        tags.append("吉兆加持")
    if fortune_today != "平":
        tags.append(f"运势:{fortune_today}")
    if tide_bonus > 0:
        tags.append("⚡灵潮")
    if used_mode == "spirit_tide_bonus":
        tags.append("⚡灵潮额外机会")
    if ritual_buff:
        tags.append("⛩祭坛 Buff")
    if permanent_bonus > 0:
        tags.append(f"永久+{permanent_bonus}")
    for bk in list(buffs.keys()):
        if bk.startswith(("风行", "聚气", "丰收")):
            tags.append(bk)

    stats_rows = [
        ("运势", fortune_today),
        ("基础", str(base)),
        ("等级加成", f"+{lvl_bonus}"),
    ]
    if permanent_bonus > 0:
        stats_rows.append(("永久加成", f"+{permanent_bonus}"))
    stats_rows.append(("灵力", f"+{final_sp} (当前: {new_sp})"))

    extra_lines = []
    if msg_tail.strip():
        extra_lines.append(msg_tail.strip())
    if used_mode == "spirit_tide_bonus":
        extra_lines.append("本次为灵潮额外机会，不占今日正常聚灵次数。")
    extra_text = "\n".join(extra_lines) if extra_lines else None

    footer_text = "输入 求签 | 聚灵 | 档案"
    if ctx.is_private:
        footer_text += f"\n 当前操作群：{ctx.group_name}"

    result = ui.render_result_card(
        "聚灵台 · 修行报告",
        scene,
        stats=stats_rows,
        tags=tags if tags else None,
        extra=extra_text,
        footer=footer_text,
    )
    await meditate_cmd.finish(MessageSegment.at(uid) + "\n" + result)


# ==================== 每日灵签 ====================
@fortune_cmd.handle()
async def handle_fortune(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "每日灵签",
        min_tier="public",
        ctx=ctx,
    )
    if not perm.allowed:
        await fortune_cmd.finish(perm.deny_message)

    try:
        await check_mutex(uid, ctx.group_id, "meditation")
    except MutexError as e:
        await fortune_cmd.finish(e.message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    today = get_today_str()

    if data.get("last_fortune_date") == today:
        old_fortune = data.get("fortune_today", "平")
        await fortune_cmd.finish(f"今日已求过签啦~ 你今日的运势是【{old_fortune}】，明日再来~")

    fortune_names = game_config.fortune_names
    fortune_weights = game_config.fortune_weights
    result = random.choices(fortune_names, weights=fortune_weights, k=1)[0]

    await data_manager.update_spirit_data(
        uid,
        ctx.group_id,
        {
            "last_fortune_date": today,
            "fortune_today": result,
        },
    )

    yi_pool = resp_manager.get_tiered_list(
        "fortune_yi",
        ctx.group_tier,
        default=["聚灵"],
    )
    ji_pool = resp_manager.get_tiered_list(
        "fortune_ji",
        ctx.group_tier,
        default=["熬夜"],
    )

    yi = random.choice(yi_pool) if yi_pool else "聚灵"
    ji_candidates = [x for x in ji_pool if x != yi]
    ji = random.choice(ji_candidates) if ji_candidates else "无"

    if result in ["大吉", "中吉", "小吉"]:
        key = "cultivation.fortune_good"
    else:
        key = "cultivation.fortune_bad"

    msg = await resp_manager.get_text(key, {"result": result, "yi": yi, "ji": ji})

    footer = "输入 聚灵 | 档案"
    if ctx.is_private:
        footer += f"\n 当前操作群：{ctx.group_name}"
    card = ui.render_panel("聚灵台 · 每日灵签", msg, footer=footer)
    await fortune_cmd.finish(MessageSegment.at(uid) + "\n" + card)


# ==================== 个人档案 ====================
@profile_cmd.handle()
async def handle_profile(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "妖灵档案",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await profile_cmd.finish(perm.deny_message)

    member = await data_manager.get_member_info(uid)
    if not member:
        await profile_cmd.finish("请先发送 /登记 建立档案。")

    spirit = await data_manager.get_spirit_data(uid, ctx.group_id)
    global_spirit = await data_manager.get_spirit_global(uid)
    group_profile = await data_manager.get_member_group_profile(uid, ctx.group_id)

    spirit_name = (
        (group_profile or {}).get("spirit_name") or member.get("spirit_name", "")
    )

    level_titles = game_config.level_titles
    lv = spirit.get("level", 1)
    title = level_titles.get(lv, "灵识觉醒")
    equipped_title = spirit.get("equipped_title", "")
    name_display = f"[{equipped_title}] {spirit_name}" if equipped_title else spirit_name

    identity = (
        (group_profile or {}).get("identity") or member.get("global_identity", "guest")
    )
    identity_tags = {
        "decision": "决策组",
        "admin": "管理组",
        "core_member": "馆内成员",
        "outer_member": "馆外成员",
        "guest": "访客",
    }
    identity_tag = identity_tags.get(identity, "未知")

    achs = spirit.get("achievements", [])
    ach_count = len(achs)
    perm_med_bonus = spirit.get("permanent_meditation_bonus", 0)
    perm_exp_bonus = spirit.get("permanent_expedition_bonus", 0)

    buff_tags = []
    buffs = spirit.get("buffs", {})
    blessing = buffs.get("blessing")
    if blessing and isinstance(blessing, dict) and time.time() < blessing.get("expire", 0):
        active_systems = []
        if blessing.get("kitchen"):
            active_systems.append("厨房")
        if blessing.get("meditation"):
            active_systems.append("聚灵")
        if blessing.get("resonance"):
            active_systems.append("鉴定")
        if blessing.get("smelting"):
            active_systems.append("熔炼")
        if active_systems:
            buff_tags.append(f"吉兆({'/'.join(active_systems)})")

    if buffs.get("taste_loss_active", False):
        buff_tags.append("味蕾丧失")

    for k in buffs:
        if k.startswith(("风行", "聚气", "丰收")) or k == "天佑":
            buff_tags.append(k)

    for buff_name in [
        "灵心草", "蓝玉果", "空间简片", "万宝如意", "护身符",
        "清心露", "混沌残片", "鸾草", "凤羽花", "涪灵丹",
    ]:
        if buffs.get(buff_name):
            buff_tags.append(buff_name)

    today = get_today_str()
    if spirit.get("last_fortune_date") == today:
        fortune = spirit.get("fortune_today", "平")
        buff_tags.append(fortune)

    buff_str = ui.render_status_tags(buff_tags) if buff_tags else "状态正常"

    bag_count = sum(
        v for v in spirit.get("items", {}).values()
        if isinstance(v, int) and v > 0
    )

    heixiu_group = spirit.get("heixiu_count", 0)
    heixiu_global = global_spirit.get("total_heixiu_count", 0)

    registered_groups = await data_manager.get_registered_groups(uid)
    reg_group_names = [group_manager.get_group_name(gid) for gid in registered_groups]
    reg_display = " | ".join(reg_group_names) if reg_group_names else "无"

    rows = [
        ("身份", identity_tag),
        ("QQ", uid),
        ("当前群", ctx.group_name),
        ("已登记", reg_display),
        ("", ""),
        ("境界", f"Lv.{lv} [{title}]"),
        ("灵力", str(spirit.get("sp", 0))),
    ]

    if perm_med_bonus > 0 or perm_exp_bonus > 0:
        bonus_parts = []
        if perm_med_bonus > 0:
            bonus_parts.append(f"聚灵+{perm_med_bonus}")
        if perm_exp_bonus > 0:
            bonus_parts.append(f"派遣+{perm_exp_bonus}")
        rows.append(("永久加成", " | ".join(bonus_parts)))

    unlocked = spirit.get("unlocked_locations", [])
    if unlocked:
        rows.append(("钥匙解锁", f"{len(unlocked)} 个区域"))

    rows.extend([
        ("背包", f"{bag_count} 件"),
        ("嘿咻", f"{heixiu_group} 只 (全服 {heixiu_global})"),
        ("成就", f"{ach_count} 个"),
        ("", ""),
        ("状态", buff_str),
    ])

    altar_contrib = global_spirit.get("altar_contributions", 0)
    if altar_contrib > 0:
        rows.append(("", ""))
        rows.append(("⛩祭坛贡献", str(altar_contrib)))

    footer = "输入 成就 | 背包 | 排行榜 | 图鉴"
    if ctx.is_private:
        footer += f"\n 私聊绑定群：{ctx.group_name}"

    card = ui.render_data_card(
        f"{name_display} 的修行档案",
        rows,
        footer=footer,
    )
    await profile_cmd.finish(card)