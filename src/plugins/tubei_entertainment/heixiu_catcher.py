""" 晋宁会馆·秃贝五边形 5.0 嘿咻捕获计划（升级收口版）

目标：
1. 嘿咻是空间系生灵，不会被真正抓进背包
2. 捕捉成功只记录次数
3. 有概率掉落不同类型的毛球副产物
4. 保持群级嘿咻状态 / 群级捕捉 / 全局统计
5. 保留世界事件暴动对群级刷新接口的复用
6. 本轮增强：
   - 毛球掉落配置统一从 game_balance.yaml 读取
   - 不在业务代码中重复写死 fur_drop 常量
"""

from __future__ import annotations

import random
import asyncio
import time
import logging
from typing import Dict

from nonebot import on_command, on_message, require, get_bot
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, MessageSegment

from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from src.common.group_manager import group_manager
from src.common.utils import get_current_hour
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.recorder import recorder
from src.plugins.tubei_cultivation.achievement import achievement_engine

logger = logging.getLogger("tubei.heixiu")

try:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler
except ImportError:
    scheduler = None

# ==================== 群级运行时锁 ====================
_HEIXIU_LOCKS: Dict[int, asyncio.Lock] = {}


def _get_heixiu_lock(group_id: int) -> asyncio.Lock:
    if group_id not in _HEIXIU_LOCKS:
        _HEIXIU_LOCKS[group_id] = asyncio.Lock()
    return _HEIXIU_LOCKS[group_id]


def _get_heixiu_fur_drop_config() -> dict:
    raw = game_config.heixiu_fur_drop
    if not isinstance(raw, dict):
        return {}

    result = {}
    for heixiu_type, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue

        item = cfg.get("item")
        chance = cfg.get("chance", 0)
        if not item:
            continue

        try:
            chance = float(chance)
        except Exception:
            chance = 0.0

        result[str(heixiu_type)] = {
            "item": str(item),
            "chance": max(0.0, min(1.0, chance)),
        }

    return result


# ==================== 文案池 ====================
SPAWN_MESSAGES = [
    "✨草丛里好像有什么在动...\n 发送「捕捉」试试看！",
    "✨角落里传来窸窸窣窣的声音...\n 发送「捕捉」抓住它！",
    "✨有什么毛茸茸的东西一闪而过！\n 快发送「捕捉」！",
    "✨嘿咻的气息... 就在附近！\n 发送「捕捉」寻找它！",
    "✨空气中弥漫着嘿咻的味道...\n 发送「捕捉」碰碰运气！",
]

ESCAPE_MESSAGES = [
    "嘿咻灵活地躲开了你的手，溜走了！",
    "差一点就抓到了... 嘿咻消失在草丛中。",
    "嘿咻吐了吐舌头，一溜烟跑了！",
    "你扑了个空！嘿咻已经不见踪影。",
    "嘿咻：「嘿咻！」(翻译：再见！) 然后跑了。",
    "手滑了！嘿咻趁机逃之夭夭...",
    "嘿咻假装被抓住，然后... 溜了。",
]

HEIXIU_TYPES = {
    "normal": {
        "name": "野生嘿咻",
        "catch_icon": "🧶",
        "reveal_text": "你成功留下了这次捕捉记录，还从它身上蹭下了一点毛茸茸的痕迹！",
    },
    "rainbow": {
        "name": "彩虹嘿咻",
        "catch_icon": "🌈",
        "reveal_text": "等等... 这只嘿咻在发光！？\n 居然是传说中的【彩虹嘿咻】！",
    },
    "golden": {
        "name": "黄金嘿咻",
        "catch_icon": "⭐",
        "reveal_text": "天哪... 金光闪闪的！！\n⭐这是...【黄金嘿咻】！！千载难逢！",
    },
    "shadow": {
        "name": "暗影嘿咻",
        "catch_icon": "🌑",
        "reveal_text": "咦... 它好像咬了你一口...\n 是一只【暗影嘿咻】... 好疼。",
    },
}

# ==================== 指令注册 ====================
help_cmd = on_command("嘿咻捕捉", aliases={"嘿咻捕获计划"}, priority=5, block=True)
capture_handler = on_message(priority=20, block=False)

# ==================== 群状态辅助 ====================
async def _get_group_heixiu_state(group_id: int) -> dict:
    status = await data_manager.get_group_status(group_id)
    state = status.get("heixiu_state", {})
    if not isinstance(state, dict):
        return {
            "active": False,
            "heixiu_type": "normal",
            "start_time": 0,
            "expire_time": 0,
        }
    return state


async def _update_group_heixiu_state(group_id: int, patch: dict):
    status = await data_manager.get_group_status(group_id)
    state = status.get("heixiu_state", {})
    if not isinstance(state, dict):
        state = {
            "active": False,
            "heixiu_type": "normal",
            "start_time": 0,
            "expire_time": 0,
        }
    state.update(patch)
    await data_manager.update_group_status(group_id, {"heixiu_state": state})


async def _deactivate_heixiu(group_id: int):
    await _update_group_heixiu_state(
        group_id,
        {
            "active": False,
            "heixiu_type": "normal",
            "start_time": 0,
            "expire_time": 0,
            "spawn_source": "",
        },
    )


async def _cleanup_if_expired(group_id: int, state: dict) -> dict:
    """若当前群嘿咻已过期，则显式清理并返回 inactive 状态。"""
    if not isinstance(state, dict):
        state = {
            "active": False,
            "heixiu_type": "normal",
            "start_time": 0,
            "expire_time": 0,
        }

    if not state.get("active", False):
        return state

    expire_time = int(state.get("expire_time", 0) or 0)
    if expire_time <= 0:
        return state

    if time.time() >= expire_time:
        await _deactivate_heixiu(group_id)
        return {
            "active": False,
            "heixiu_type": "normal",
            "start_time": 0,
            "expire_time": 0,
            "spawn_source": "",
        }

    return state


# ==================== 帮助 ====================
@help_cmd.handle()
async def handle_help(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    group_id = getattr(event, "group_id", 0) or 0

    if group_id <= 0:
        bind_gid = await data_manager.get_private_bind_group(uid)
        group_id = bind_gid or 0

    data = await data_manager.get_spirit_data(uid, group_id) if group_id > 0 else {}
    count = data.get("heixiu_count", 0)

    card = ui.render_panel(
        "嘿咻捕获计划",
        f"会馆角落偶尔会出现嘿咻的踪迹！\n\n"
        f"• 触发：系统随机在群内通报\n"
        f"• 捕获：发送「捕捉」（先到先得）\n"
        f"• 概率：80% 成功 / 20% 逃跑\n"
        f"• 可爱又神秘的空间系灵体~\n"
        f"• 但有概率从它身上蹭下毛球副产物\n"
        f"• 成就：累计捕捉 10 次解锁 [嘿咻牧场主]\n\n"
        f"你当前群档已捕捉：{count} 次",
        footer="嘿咻出现时发送 捕捉 即可",
    )
    await help_cmd.finish(card)


# ==================== 捕捉逻辑 ====================
@capture_handler.handle()
async def handle_capture(bot: Bot, event: GroupMessageEvent):
    text = event.get_plaintext().strip()
    if text != "捕捉":
        return

    from src.common.group_manager import TIER_DANGER
    if group_manager.get_group_tier(event.group_id) == TIER_DANGER:
        return

    state = await _get_group_heixiu_state(event.group_id)
    state = await _cleanup_if_expired(event.group_id, state)
    if not state.get("active", False):
        return

    lock = _get_heixiu_lock(event.group_id)
    async with lock:
        state = await _get_group_heixiu_state(event.group_id)
        state = await _cleanup_if_expired(event.group_id, state)
        if not state.get("active", False):
            return

        uid = str(event.user_id)
        heixiu_type = state.get("heixiu_type", "normal")
        type_info = HEIXIU_TYPES.get(heixiu_type, HEIXIU_TYPES["normal"])

        await _deactivate_heixiu(event.group_id)

        catch_rate = game_config.get("heixiu", "catch_success_rate", default=0.80)
        is_success = random.random() < catch_rate

        if not is_success:
            escape_msg = random.choice(ESCAPE_MESSAGES)
            await recorder.add_event(
                "heixiu_capture",
                int(uid),
                {
                    "type": heixiu_type,
                    "success": False,
                    "group_id": event.group_id,
                },
            )
            await capture_handler.finish(MessageSegment.at(uid) + "\n" + escape_msg)

        # ===== 捕捉成功：只记录捕捉次数，不获得嘿咻实体 =====
        data = await data_manager.get_spirit_data(uid, event.group_id)
        count = data.get("heixiu_count", 0) + 1

        rewards_config = game_config.get("heixiu", "rewards", heixiu_type, default={})
        sp_reward = rewards_config.get("sp", 0)
        item_rewards = dict(rewards_config.get("items", {}))
        should_announce = rewards_config.get("announcement", False)

        current_sp = data.get("sp", 0)
        new_sp = max(0, current_sp + sp_reward)

        # 毛球副产物（从配置读取）
        fur_drop_cfg = _get_heixiu_fur_drop_config()
        fur_cfg = fur_drop_cfg.get(heixiu_type, {})
        fur_drop_text = None
        if fur_cfg and random.random() < float(fur_cfg.get("chance", 0) or 0):
            fur_item = str(fur_cfg.get("item", "")).strip()
            if fur_item:
                item_rewards[fur_item] = item_rewards.get(fur_item, 0) + 1
                fur_drop_text = f"{fur_item} x1"

        items = dict(data.get("items", {}))
        for item_name, item_count in item_rewards.items():
            items[item_name] = items.get(item_name, 0) + item_count

        await data_manager.update_spirit_data(
            uid,
            event.group_id,
            {
                "heixiu_count": count,
                "sp": new_sp,
                "items": items,
            },
        )
        await data_manager.increment_global_stat(uid, "total_heixiu_count", 1)

        await recorder.add_event(
            "heixiu_capture",
            int(uid),
            {
                "type": heixiu_type,
                "success": True,
                "group_id": event.group_id,
                "fur_drop": fur_drop_text,
            },
        )

        stats = [
            ("类型", f"{type_info['catch_icon']} {type_info['name']}"),
            ("总数", f"{count} 次"),
        ]

        extra_lines = []
        if sp_reward > 0:
            stats.append(("灵力", f"+{sp_reward}"))
        elif sp_reward < 0:
            stats.append(("灵力", f"{sp_reward} (被咬了！)"))
            extra_lines.append("嘿咻咬了你一口，但似乎掉了什么...")

        if item_rewards:
            items_str = "、".join(f"{k} x{v}" for k, v in item_rewards.items())
            stats.append(("副产物", items_str))

        ach_msg = ""
        if count >= 10:
            result = await achievement_engine.try_unlock(uid, "嘿咻牧场主", bot, event, group_id=event.group_id)
            if result:
                ach_msg += "\n🏅解锁成就：【嘿咻牧场主】！"

        if heixiu_type == "rainbow":
            result = await achievement_engine.try_unlock(uid, "彩虹猎手", bot, event, group_id=event.group_id)
            if result:
                ach_msg += "\n🏅解锁成就：【彩虹猎手】！"

        if heixiu_type == "golden":
            result = await achievement_engine.try_unlock(uid, "黄金传说", bot, event, group_id=event.group_id)
            if result:
                ach_msg += "\n🏅解锁成就：【黄金传说】！"

        if heixiu_type == "shadow":
            result = await achievement_engine.try_unlock(uid, "暗影幸存者", bot, event, group_id=event.group_id)
            if result:
                ach_msg += "\n🏅解锁成就：【暗影幸存者】！"

        extra_text = "\n".join(extra_lines) + ach_msg if (extra_lines or ach_msg) else None

        card = ui.render_result_card(
            "嘿咻捕获成功！",
            type_info["reveal_text"],
            stats=stats,
            extra=extra_text.strip() if extra_text else None,
        )
        await capture_handler.finish(MessageSegment.at(uid) + "\n" + card)

        if should_announce:
            member = await data_manager.get_member_info(uid)
            group_profile = await data_manager.get_member_group_profile(uid, event.group_id)
            name = (
                (group_profile or {}).get("spirit_name")
                or (member or {}).get("spirit_name")
                or f"妖灵{uid}"
            )

            announce = f"{type_info['catch_icon']}【全服通报】{name} 捕捉到了一次 {type_info['name']} 的踪迹！"

            for gid in group_manager.get_all_game_groups():
                if gid == event.group_id or group_manager.is_debug_group(gid):
                    continue
                try:
                    await bot.send_group_msg(group_id=gid, message=announce)
                except Exception:
                    pass


# ==================== 刷新逻辑 ====================
def _is_curfew() -> bool:
    h = get_current_hour()
    start = game_config.sleep_start
    end = game_config.sleep_end

    if start <= end:
        return start <= h < end
    return h >= start or h < end


def _roll_heixiu_type() -> str:
    weights_config = game_config.get("heixiu", "type_weights", default={})
    types = list(weights_config.keys())
    weights = [weights_config[t] for t in types]
    if not types:
        return "normal"
    return random.choices(types, weights=weights, k=1)[0]


async def spawn_heixiu():
    if _is_curfew():
        return

    candidates = []
    for gid in group_manager.get_all_game_groups():
        if not group_manager.is_debug_group(gid):
            candidates.append(gid)

    if not candidates:
        return

    target = random.choice(candidates)
    await spawn_heixiu_in_group(target, spawn_source="normal")


async def spawn_heixiu_in_group(group_id: int, spawn_source: str = "normal"):
    if _is_curfew():
        return

    lock = _get_heixiu_lock(group_id)
    async with lock:
        state = await _get_group_heixiu_state(group_id)
        state = await _cleanup_if_expired(group_id, state)
        if state.get("active", False):
            return

        now = time.time()
        heixiu_type = _roll_heixiu_type()
        escape_timeout = int(game_config.heixiu_escape_timeout)

        await _update_group_heixiu_state(
            group_id,
            {
                "active": True,
                "group_id": group_id,
                "start_time": now,
                "expire_time": now + escape_timeout,
                "heixiu_type": heixiu_type,
                "last_spawn_ts": now,
                "spawn_source": spawn_source,
            },
        )

    try:
        bot = get_bot()
        spawn_msg = random.choice(SPAWN_MESSAGES)
        await bot.send_group_msg(group_id=group_id, message=spawn_msg)
    except Exception as e:
        logger.error(f"[Heixiu] 刷新通报失败: {e}")
        async with lock:
            await _deactivate_heixiu(group_id)
        return


if scheduler:
    scheduler.add_job(
        spawn_heixiu,
        "interval",
        hours=game_config.heixiu_spawn_interval,
        jitter=game_config.heixiu_spawn_jitter,
        id="heixiu_spawn",
        replace_existing=True,
    )