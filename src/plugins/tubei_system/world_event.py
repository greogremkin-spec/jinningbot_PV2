""" 晋宁会馆·秃贝五边形 5.0 世界事件系统（收尾定稿版）
定位：
1. 世界事件是全服同步事件，所有游戏群（core + allied）统一经历
2. 事件状态存储在 bot_status.json 中
3. 保留三大事件：
- 灵潮爆发：聚灵收益提升
- 嘿咻暴动：定时刷嘿咻
- 无限失控：厨房必出美味
4. 保留查询指令与定时任务能力
5. 当前版本目标：
- 结构清晰
- 广播范围清楚
- 触发 / 结束 / 查询分层明确
- 为未来事件注册表化预留干净边界
6. 本轮增强：
- 嘿咻暴动改为每群独立任务 / 独立时序
"""
from __future__ import annotations

import random
import asyncio
import time
import logging
from typing import Dict

from nonebot import on_command, require, get_bot
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from src.common.data_manager import data_manager
from src.common.group_manager import group_manager
from src.common.ui_renderer import ui
from src.plugins.tubei_system.config import game_config
from src.common.utils import get_current_hour, format_duration

try:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler
except ImportError:
    scheduler = None

logger = logging.getLogger("tubei.world_event")


# ==================== 嘿咻暴动任务表 ====================

_HEIXIU_FRENZY_GROUP_TASKS: Dict[int, asyncio.Task] = {}


# ==================== 基础工具 ====================

def _is_curfew() -> bool:
    start = game_config.sleep_start
    end = game_config.sleep_end
    now = get_current_hour()
    if start <= end:
        return start <= now < end
    return now >= start or now < end


async def _broadcast_to_game_groups(message: str):
    """向所有支持游戏玩法的群广播。"""
    if _is_curfew():
        return
    try:
        bot = get_bot()
        for gid in group_manager.get_all_game_groups():
            if group_manager.is_debug_group(gid):
                continue
            try:
                await bot.send_group_msg(group_id=gid, message=message)
                await asyncio.sleep(0.25)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"[WorldEvent] 通报失败: {e}")


# ==================== 事件状态管理 ====================

async def get_active_events() -> dict:
    status = await data_manager.get_bot_status()
    return status.get("world_events", {})


async def is_event_active(event_id: str) -> bool:
    events = await get_active_events()
    event = events.get(event_id, {})
    if not event.get("active", False):
        return False

    end_time = event.get("end_time", 0)
    if time.time() >= end_time:
        await _deactivate_event(event_id)
        return False
    return True


async def get_event_bonus(event_id: str) -> float:
    if not await is_event_active(event_id):
        return 0.0
    config = game_config.get("world_events", event_id, default={})
    return config.get("bonus", 0.0)


async def _activate_event(event_id: str, duration: int):
    now = time.time()
    status = await data_manager.get_bot_status()
    events = status.get("world_events", {})
    events[event_id] = {
        "active": True,
        "start_time": now,
        "end_time": now + duration,
    }
    await data_manager.update_bot_status({"world_events": events})


async def _deactivate_event(event_id: str):
    status = await data_manager.get_bot_status()
    events = status.get("world_events", {})
    if event_id in events:
        events[event_id] = {"active": False}
        await data_manager.update_bot_status({"world_events": events})

    if event_id == "heixiu_frenzy":
        await _stop_heixiu_frenzy_tasks()


# ==================== 灵潮爆发 ====================

async def trigger_spirit_tide():
    config = game_config.get("world_events", "spirit_tide", default={})
    duration = config.get("duration", 7200)
    bonus_pct = int(config.get("bonus", 0.30) * 100)
    await _activate_event("spirit_tide", duration)

    hours = duration // 3600
    msg = ui.render_panel(
        "⚡【灵潮预警】",
        f"天地灵气异常涌动！\n\n"
        f"效果：聚灵收益 +{bonus_pct}%\n"
        f"持续：{hours} 小时\n\n"
        f"抓紧修行！",
    )
    await _broadcast_to_game_groups(msg)
    logger.info(f"[WorldEvent] 灵潮爆发已触发，持续 {hours} 小时")


async def end_spirit_tide():
    if await is_event_active("spirit_tide"):
        return
    await _broadcast_to_game_groups("⚡灵潮已退去，天地归于平静。")


# ==================== 嘿咻暴动 ====================

async def trigger_heixiu_frenzy():
    config = game_config.get("world_events", "heixiu_frenzy", default={})
    duration = config.get("duration", 7200)
    interval = config.get("spawn_interval", 1800)

    await _activate_event("heixiu_frenzy", duration)

    hours = duration // 3600
    msg = ui.render_panel(
        "【嘿咻暴动】",
        f"大量嘿咻涌入会馆！\n\n"
        f"效果：每群约每 {interval // 60} 分钟刷新一只嘿咻\n"
        f"持续：{hours} 小时\n\n"
        f"全员准备捕捉！",
    )
    await _broadcast_to_game_groups(msg)
    logger.info(f"[WorldEvent] 嘿咻暴动已触发，持续 {hours} 小时")

    end_time = time.time() + duration
    for gid in group_manager.get_all_game_groups():
        if group_manager.is_debug_group(gid):
            continue

        old_task = _HEIXIU_FRENZY_GROUP_TASKS.get(gid)
        if old_task and not old_task.done():
            continue

        task = asyncio.create_task(_heixiu_frenzy_group_loop(gid, end_time, interval))
        _HEIXIU_FRENZY_GROUP_TASKS[gid] = task


async def _heixiu_frenzy_group_loop(group_id: int, end_time: float, interval: int):
    """单群独立暴动循环。"""
    from src.plugins.tubei_entertainment.heixiu_catcher import spawn_heixiu_in_group

    try:
        # 首次刷新采用随机延迟，避免所有群同步开刷
        initial_delay = random.randint(0, max(1, interval))
        await asyncio.sleep(initial_delay)

        while time.time() < end_time:
            if not await is_event_active("heixiu_frenzy"):
                break

            try:
                await spawn_heixiu_in_group(group_id, spawn_source="frenzy")
            except Exception as e:
                logger.error(f"[WorldEvent] 暴动刷新嘿咻失败 @group={group_id}: {e}")

            if time.time() >= end_time:
                break

            next_interval = interval + random.randint(-600, 600)
            next_interval = max(300, next_interval)
            await asyncio.sleep(next_interval)

    except asyncio.CancelledError:
        raise
    finally:
        current = _HEIXIU_FRENZY_GROUP_TASKS.get(group_id)
        if current is asyncio.current_task():
            _HEIXIU_FRENZY_GROUP_TASKS.pop(group_id, None)


async def _stop_heixiu_frenzy_tasks():
    tasks = list(_HEIXIU_FRENZY_GROUP_TASKS.items())
    _HEIXIU_FRENZY_GROUP_TASKS.clear()

    for gid, task in tasks:
        if task and not task.done():
            task.cancel()

    for gid, task in tasks:
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass


# ==================== 无限失控 ====================

async def trigger_kitchen_chaos():
    config = game_config.get("world_events", "kitchen_chaos", default={})
    duration = config.get("duration", 3600)
    await _activate_event("kitchen_chaos", duration)

    hours = duration // 3600
    mins = (duration % 3600) // 60
    time_str = f"{hours}小时" if hours > 0 else f"{mins}分钟"

    msg = ui.render_panel(
        "【无限失控】",
        f"无限大人的灵力突然暴走了！\n\n"
        f"效果：厨房全部变为绝世珍馐\n"
        f"持续：{time_str}\n\n"
        f"快去厨房蹭饭！",
    )
    await _broadcast_to_game_groups(msg)
    logger.info(f"[WorldEvent] 无限失控已触发，持续 {time_str}")

    asyncio.create_task(_kitchen_chaos_end(duration))


async def _kitchen_chaos_end(duration: int):
    await asyncio.sleep(duration)
    await _deactivate_event("kitchen_chaos")
    await _broadcast_to_game_groups("无限大人冷静下来了... 厨房恢复了原本的「味道」。")


# ==================== 每日随机触发 ====================

async def daily_event_roll():
    """每日事件抽签。"""
    now_hour = get_current_hour()
    events_config = game_config.get("world_events", default={})

    for event_id, config in events_config.items():
        if not isinstance(config, dict):
            continue

        daily_chance = config.get("daily_chance", 0)
        min_hour = config.get("min_hour", 10)
        max_hour = config.get("max_hour", 22)

        if await is_event_active(event_id):
            continue
        if random.random() >= daily_chance:
            continue

        trigger_hour = random.randint(min_hour, max_hour - 1)
        delay_seconds = max(0, (trigger_hour - now_hour) * 3600 + random.randint(0, 3599))
        if delay_seconds <= 0:
            continue

        logger.info(
            f"[WorldEvent] 今日将触发 [{config.get('name', event_id)}]，预计 {trigger_hour}:xx"
        )
        asyncio.create_task(_delayed_trigger(event_id, delay_seconds))


async def _delayed_trigger(event_id: str, delay: int):
    await asyncio.sleep(delay)
    if await is_event_active(event_id):
        return

    trigger_map = {
        "spirit_tide": trigger_spirit_tide,
        "heixiu_frenzy": trigger_heixiu_frenzy,
        "kitchen_chaos": trigger_kitchen_chaos,
    }
    trigger_func = trigger_map.get(event_id)
    if trigger_func:
        await trigger_func()


# ==================== 查询指令 ====================

event_status_cmd = on_command("世界事件", aliases={"事件", "灵潮"}, priority=5, block=True)


@event_status_cmd.handle()
async def handle_event_status(bot: Bot, event: MessageEvent):
    events = await get_active_events()
    events_config = game_config.get("world_events", default={})
    rows = []

    for event_id, config in events_config.items():
        if not isinstance(config, dict):
            continue

        name = config.get("name", event_id)
        effect = config.get("effect", "未知效果")
        event_state = events.get(event_id, {})

        if event_state.get("active", False):
            end_time = event_state.get("end_time", 0)
            remaining = int(end_time - time.time())
            if remaining > 0:
                time_str = format_duration(remaining)
                rows.append((name, f"生效中 (剩余 {time_str})"))
                rows.append(("效果", effect))
                rows.append(("", ""))
            else:
                rows.append((f"⚪{name}", "今日未触发"))
        else:
            rows.append((f"⚪{name}", "今日未触发"))

    if not rows:
        rows.append(("当前无事件", "天下太平"))

    card = ui.render_data_card(
        "世界事件 · 实时监控",
        rows,
        footer="事件每日随机触发，敬请期待~",
    )
    await event_status_cmd.finish(card)


# ==================== 定时任务注册 ====================

if scheduler:
    scheduler.add_job(
        daily_event_roll,
        "cron",
        hour=10,
        minute=0,
        id="daily_event_roll",
        replace_existing=True,
    )


async def check_expired_events():
    events = await get_active_events()
    now = time.time()

    for event_id, state in events.items():
        if state.get("active") and now >= state.get("end_time", 0):
            await _deactivate_event(event_id)
            logger.info(f"[WorldEvent] 事件 {event_id} 已自然结束")

            if event_id == "heixiu_frenzy":
                await _broadcast_to_game_groups("嘿咻暴动结束了，妖灵们恢复了平静。")
            elif event_id == "spirit_tide":
                await _broadcast_to_game_groups("⚡灵潮已退去，天地归于平静。")

if scheduler:
    scheduler.add_job(
        check_expired_events,
        "interval",
        minutes=5,
        id="check_expired_events",
        replace_existing=True,
    )