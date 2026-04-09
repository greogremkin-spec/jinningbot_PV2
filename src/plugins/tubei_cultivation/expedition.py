""" 晋宁会馆·秃贝五边形 5.0
灵风传送 —— 妖灵派遣（9 大灵域版，结构收口版）

v5.0 收口目标：
1. 派遣状态按群隔离
2. 自动结算按群扫描
3. 通知优先群消息，失败降级私聊
4. 保留全部原有机制：
   - 等级/钥匙检查
   - buff 加速
   - 护身符 / 凤羽花
   - 永久派遣加成
   - 丰收 buff
   - 探索区域记录
   - 成就检查
"""
from __future__ import annotations

import time
import random
import logging

from nonebot import on_command, require, get_bot
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.params import CommandArg
from nonebot.adapters import Message

from src.common.data_manager import data_manager
from src.common.response_manager import resp_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.common.utils import format_duration, timestamp_now
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.recorder import recorder
from src.plugins.tubei_cultivation.achievement import achievement_engine

try:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler
except ImportError:
    scheduler = None

logger = logging.getLogger("tubei.expedition")

# ==================== 指令注册 ====================
exped_cmd = on_command("派遣", aliases={"妖灵派遣", "灵风传送"}, priority=5, block=True)
recall_cmd = on_command("召回", aliases={"强制召回"}, priority=5, block=True)


# ==================== 工具函数：地点访问 ====================
def _can_access_location(user_level: int, req_level: int, loc_name: str, unlocked: list) -> bool:
    if user_level >= req_level:
        return True
    if loc_name in unlocked:
        return True
    return False


def _get_lock_status(user_level: int, req_level: int, loc_name: str, unlocked: list) -> str:
    if user_level >= req_level:
        return " "
    if loc_name in unlocked:
        return " "
    return " "


# ==================== 工具函数：奖励结算 ====================
def _apply_expedition_buffs_to_gain_and_drops(data: dict, cfg: dict) -> tuple[int, list[str], dict]:
    """根据用户 buff 和地点配置，计算最终灵力收益、掉落列表，并返回更新后的 items。"""
    sp_min = cfg.get("sp_min", 5)
    sp_max = cfg.get("sp_max", 5)
    sp_gain = random.randint(sp_min, sp_max)

    buffs = dict(data.get("buffs", {}))

    # 护身符 Buff：灵力+20%
    if buffs.get("护身符"):
        sp_gain = int(sp_gain * 1.2)

    # 永久派遣加成
    permanent_exped_bonus = data.get("permanent_expedition_bonus", 0)
    sp_gain += permanent_exped_bonus

    drop_list = []
    items = dict(data.get("items", {}))

    # 丰收 Buff
    drop_bonus = 0.0
    if buffs.get("丰收 Lv1"):
        drop_bonus = 0.1

    # 凤羽花 Buff：必出法宝碎片
    force_fragment = bool(buffs.get("凤羽花"))

    for item_name, prob in cfg.get("drops", {}).items():
        if item_name == "法宝碎片" and force_fragment:
            items[item_name] = items.get(item_name, 0) + 1
            drop_list.append(item_name)
        elif random.random() < (prob + drop_bonus):
            items[item_name] = items.get(item_name, 0) + 1
            drop_list.append(item_name)

    if force_fragment and "法宝碎片" not in drop_list:
        items["法宝碎片"] = items.get("法宝碎片", 0) + 1
        drop_list.append("法宝碎片")

    return sp_gain, drop_list, items


def _consume_expedition_once_buffs(buffs: dict) -> dict:
    """消耗派遣相关的一次性 buff。"""
    buffs = dict(buffs)
    buffs.pop("护身符", None)
    buffs.pop("丰收 Lv1", None)
    buffs.pop("凤羽花", None)
    return buffs


def _build_expedition_finish_card(loc_name: str, sp_gain: int, drop_list: list[str], extra_text: Optional[str] = None) -> str:
    drop_str = "、".join(drop_list) if drop_list else "无"
    return ui.render_result_card(
        "灵风传送 · 探索归来",
        f"你从【{loc_name}】安全返回了~",
        stats=[
            (" 地点", loc_name),
            ("✨灵力", f"+{sp_gain}"),
            (" 掉落", drop_str),
        ],
        extra=extra_text,
        footer=" 输入 派遣 继续探索 | 背包",
    )


async def _notify_expedition_finish(uid: str, group_id: int, message: str):
    """通知优先群消息，失败降级私聊。"""
    try:
        bot = get_bot()
    except Exception as e:
        logger.error(f"[Expedition] 获取 Bot 实例失败: {e}")
        return

    # 先尝试群消息
    if group_id > 0:
        try:
            await bot.send_group_msg(group_id=int(group_id), message=message)
            return
        except Exception as e:
            logger.warning(f"[Expedition] 群通知失败，降级私聊 uid={uid} gid={group_id}: {e}")

    # 再尝试私聊
    try:
        await bot.send_private_msg(user_id=int(uid), message=message)
    except Exception as e:
        logger.warning(f"[Expedition] 私聊通知失败 uid={uid}: {e}")


# ==================== 自动结算 ====================
async def auto_settle_expeditions():
    """定时任务：自动结算所有已完成的派遣。
    v5.0：扫描所有 spirit，解析 group_data 中的 full 档。
    """
    now = time.time()
    spirits_raw = data_manager.spirits_raw

    for uid, user_data in spirits_raw.items():
        if not isinstance(user_data, dict):
            continue

        # v4 旧结构兼容
        if "group_data" not in user_data and "global" not in user_data:
            exped = user_data.get("expedition", {})
            if exped.get("status") == "exploring" and now >= exped.get("end_time", 0):
                group_id = 0
                member = data_manager.members_raw.get(uid, {})
                group_id = member.get("primary_group") or member.get("register_group") or 0
                if group_id:
                    await _settle_expedition(uid, int(group_id))
            continue

        # v5 结构
        for gid_str, profile in user_data.get("group_data", {}).items():
            if not isinstance(profile, dict):
                continue
            if profile.get("_type") == "pointer":
                continue

            exped = profile.get("expedition", {})
            if exped.get("status") == "exploring" and now >= exped.get("end_time", 0):
                await _settle_expedition(uid, int(gid_str))


async def _settle_expedition(uid: str, group_id: int):
    """结算单个用户在某群的派遣。"""
    data = await data_manager.get_spirit_data(uid, group_id)
    exped = data.get("expedition", {})

    if exped.get("status") != "exploring":
        return

    locations = game_config.expedition_locations
    loc_name = exped.get("location", "晋宁老街")
    cfg = locations.get(loc_name)
    if not cfg:
        cfg = list(locations.values())[0] if locations else {}

    sp_gain, drop_list, items = _apply_expedition_buffs_to_gain_and_drops(data, cfg)

    new_sp = data.get("sp", 0) + sp_gain

    # 记录已探索区域
    explored = list(data.get("explored_locations", []))
    if loc_name not in explored:
        explored.append(loc_name)

    # 消耗一次性派遣 buff
    new_buffs = _consume_expedition_once_buffs(data.get("buffs", {}))

    await data_manager.update_spirit_data(
        uid,
        group_id,
        {
            "sp": new_sp,
            "items": items,
            "expedition": {"status": "idle"},
            "buffs": new_buffs,
            "explored_locations": explored,
        },
    )

    await data_manager.increment_group_stat(uid, group_id, "total_expedition_count", 1)

    await recorder.add_event(
        "expedition_finish",
        int(uid),
        {
            "loc": loc_name,
            "sp": sp_gain,
            "drops": drop_list,
            "group_id": group_id,
        },
    )

    # 成就检查：晋宁旅者
    all_locations = list(game_config.expedition_locations.keys())
    if len(explored) >= len(all_locations):
        await achievement_engine.try_unlock(uid, "晋宁旅者", group_id=group_id)
    await achievement_engine.check_stat_achievements(uid, group_id=group_id)

    extra_lines = []
    permanent_exped_bonus = data.get("permanent_expedition_bonus", 0)
    if permanent_exped_bonus > 0:
        extra_lines.append(f" 永久加成：+{permanent_exped_bonus}")
    extra_text = "\n".join(extra_lines) if extra_lines else None

    # 优先使用派遣发起来源群；若缺失则退回当前群档
    origin_group_id = int(exped.get("origin_group_id", 0) or 0) or int(group_id)

    card = _build_expedition_finish_card(loc_name, sp_gain, drop_list, extra_text=extra_text)
    await _notify_expedition_finish(uid, origin_group_id, card)


if scheduler:
    scheduler.add_job(
        auto_settle_expeditions,
        "interval",
        minutes=10,
        id="expedition_auto_settle",
        replace_existing=True,
    )


# ==================== 强制召回 ====================
@recall_cmd.handle()
async def handle_recall(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "灵风传送 · 强制召回",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await recall_cmd.finish(perm.deny_message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    exped = data.get("expedition", {})
    if exped.get("status") != "exploring":
        await recall_cmd.finish(ui.info("当前没有正在进行的派遣任务。"))

    penalty = game_config.expedition_recall_penalty
    new_sp = max(0, data.get("sp", 0) - penalty)

    await data_manager.update_spirit_data(
        uid,
        ctx.group_id,
        {
            "sp": new_sp,
            "expedition": {"status": "idle"},
        },
    )

    await recall_cmd.finish(
        ui.render_result_card(
            "灵风传送 · 强制召回",
            "灵体已强制返回！",
            stats=[(" 灵力", f"-{penalty} (当前: {new_sp})")],
            footer=" 输入 派遣 重新出发",
        )
    )


# ==================== 工具函数：列表渲染 ====================
def _build_location_rows(data: dict, user_lv: int, unlocked: list) -> list[tuple[str, str]]:
    locations = game_config.expedition_locations
    explored = set(data.get("explored_locations", []))
    permanent_exped_bonus = data.get("permanent_expedition_bonus", 0)

    groups = {}
    for name, info in locations.items():
        req_lv = info.get("level", 1)
        groups.setdefault(req_lv, []).append((name, info))

    rows = []
    for lv in sorted(groups.keys()):
        rows.append(("", f"── Lv.{lv} 区域 ──"))
        for name, info in groups[lv]:
            hours = info.get("time", 3600) // 3600
            visited = "✅" if name in explored else "⬜"
            lock = _get_lock_status(user_lv, lv, name, unlocked)
            desc = info.get("desc", "")[:20]

            if lock == " ":
                rows.append((f" {visited} {name}", f"{hours}h | {desc}..."))
            else:
                rows.append((f" {visited} {name}", f"{hours}h | {desc}..."))

    rows.append(("", ""))
    rows.append((" 已探索", f"{len(explored)} / {len(locations)} 区域"))

    if permanent_exped_bonus > 0:
        rows.append((" 永久加成", f"+{permanent_exped_bonus} 灵力/次"))

    return rows


# ==================== 派遣主指令 ====================
@exped_cmd.handle()
async def handle_expedition(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "灵风传送 · 妖灵派遣",
        min_tier="allied",
        require_registered=True,
        deny_promotion=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await exped_cmd.finish(perm.deny_message)

    arg_text = args.extract_plain_text().strip()
    data = await data_manager.get_spirit_data(uid, ctx.group_id)

    exped_data = data.get("expedition", {})
    status = exped_data.get("status", "idle")
    now = timestamp_now()

    locations = game_config.expedition_locations
    user_lv = data.get("level", 1)
    unlocked = data.get("unlocked_locations", [])

    # ===== 自动结算 =====
    if status == "exploring" and now >= exped_data.get("end_time", 0):
        await _settle_expedition(uid, ctx.group_id)
        data = await data_manager.get_spirit_data(uid, ctx.group_id)
        exped_data = data.get("expedition", {})
        status = exped_data.get("status", "idle")

    # ===== 查询进度 =====
    if status == "exploring":
        remain = int(exped_data.get("end_time", 0) - now)
        time_str = format_duration(remain)
        loc = exped_data.get("location", "未知")
        loc_cfg = locations.get(loc, {})
        desc = loc_cfg.get("desc", "")

        card = ui.render_data_card(
            "灵风传送 · 探索中",
            [
                (" 地点", loc),
                (" 描述", desc),
                ("⏳剩余", time_str),
            ],
            footer=" 输入 召回 强制返回",
        )
        await exped_cmd.finish(card)

    # ===== 无参数 → 显示地点列表 =====
    if not arg_text:
        rows = _build_location_rows(data, user_lv, unlocked)

        footer = " 输入 派遣 [地点名] 出发\n = 钥匙解锁 = 等级不足"
        if ctx.is_private:
            footer += f"\n 当前操作群：{ctx.group_name}"

        card = ui.render_data_card(
            "灵风传送 · 九大灵域",
            rows,
            footer=footer,
        )
        await exped_cmd.finish(card)

    # ===== 发起派遣 =====
    target_loc = arg_text
    if target_loc not in locations:
        await exped_cmd.finish(ui.error("未知地点。请使用 /派遣 查看可选目的地。"))

    cfg = locations[target_loc]
    req_level = cfg.get("level", 1)

    if not _can_access_location(user_lv, req_level, target_loc, unlocked):
        await exped_cmd.finish(
            ui.error(
                f"等级不足！需要 Lv.{req_level}。\n"
                f" 你当前 Lv.{user_lv}\n"
                f" 使用【析沐的钥匙】可提前解锁"
            )
        )

    buffs = dict(data.get("buffs", {}))
    duration = cfg.get("time", 3600)

    time_reduce = 1.0
    if buffs.get("空间简片"):
        time_reduce *= 0.5
    if buffs.get("风行 Lv1"):
        time_reduce *= 0.9
    if buffs.get("风行 MAX"):
        time_reduce *= 0.7

    duration = int(duration * time_reduce)

    # 发起时消耗一次性“加速类”buff
    start_buffs = dict(buffs)
    start_buffs.pop("空间简片", None)
    start_buffs.pop("风行 Lv1", None)
    start_buffs.pop("风行 MAX", None)

    await data_manager.update_spirit_data(
        uid,
        ctx.group_id,
        {
            "expedition": {
                "status": "exploring",
                "location": target_loc,
                "start_time": now,
                "end_time": now + duration,
                "origin_group_id": ctx.group_id,
            },
            "buffs": start_buffs,
        },
    )

    await recorder.add_event(
        "expedition_start",
        int(uid),
        {
            "loc": target_loc,
            "group_id": ctx.group_id,
        },
    )

    hours = round(duration / 3600, 1)
    desc = cfg.get("desc", "")

    extra_lines = []
    if time_reduce < 1.0:
        extra_lines.append("⚡加速生效！耗时已缩短")
    if _get_lock_status(user_lv, req_level, target_loc, unlocked) == " ":
        extra_lines.append(" 通过析沐的钥匙解锁")

    extra_text = "\n".join(extra_lines) if extra_lines else None

    footer = " 输入 派遣 查看进度 | 召回 强制返回"
    if ctx.is_private:
        footer += f"\n 当前操作群：{ctx.group_name}"

    card = ui.render_result_card(
        "灵风传送 · 出发！",
        f"灵体已传送至【{target_loc}】",
        stats=[
            (" 目的地", target_loc),
            (" 描述", desc),
            ("⏳预计耗时", f"{hours} 小时"),
        ],
        extra=extra_text,
        footer=footer,
    )
    await exped_cmd.finish(card)