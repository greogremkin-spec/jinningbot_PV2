""" 晋宁会馆·秃贝五边形 5.0 消息拦截器（升级收口版）

职责：
1. 特权豁免
2. 封禁状态检查
3. 防刷屏频率限制
4. 核心群深夜劝睡
5. 身份感知检查（不阻塞主流程）

说明：
- 当前仍保留 v4.1 的整体拦截策略，但按 v5 配置与语义做了结构收口
- 馆禁时间劝睡逻辑仅对核心群普通成员生效
- 管理员与决策组仍享有豁免
- 本轮增强：
  - 深夜劝睡文案改为 tier-aware 读取
  - 便于未来 allied / public 场景按需复用
"""

from __future__ import annotations

import time
import random
from typing import Dict, List
from nonebot.adapters.onebot.v11 import (
    Bot, GroupMessageEvent, MessageEvent, MessageSegment,
)
from nonebot.message import event_preprocessor
from nonebot.exception import IgnoredException
from nonebot.log import logger

from .config import system_config, game_config
from .recorder import recorder
from src.common.group_manager import group_manager
from src.common.identity import identity_manager
from src.common.response_manager import resp_manager
from src.common.utils import get_current_hour

# ==================== 内存缓存 ====================
# 用户消息时间戳历史
SPAM_CACHE: Dict[int, List[float]] = {}
# 封禁列表：{uid: 解封时间戳}
BAN_LIST: Dict[int, float] = {}
# 劝睡冷却缓存：{uid: last_warn_ts}
SLEEP_COOLDOWN: Dict[int, float] = {}

# ==================== 配置快捷引用 ====================
SUPERUSERS = system_config.superusers
ADMINS = system_config.tubei_admins
THRESHOLD = system_config.tubei_spam_threshold
BAN_DURATION = system_config.tubei_ban_duration


def _is_curfew_now() -> bool:
    """判断当前是否处于馆禁/劝睡时段。"""
    start_h = game_config.sleep_start
    end_h = game_config.sleep_end
    now_h = get_current_hour()

    if start_h <= end_h:
        return start_h <= now_h < end_h
    return now_h >= start_h or now_h < end_h


def _get_nickname(event: MessageEvent) -> str:
    """提取用户昵称。"""
    if isinstance(event, GroupMessageEvent) and event.sender.card:
        return event.sender.card
    if event.sender.nickname:
        return event.sender.nickname
    return "小友"


async def _try_identity_check(user_id: str, group_id: int, bot: Bot):
    """尝试进行身份感知检查。

    如果用户身份发生变更，通过私聊通知用户。
    """
    try:
        notify_msg = await identity_manager.check_and_update(user_id, group_id)
        if notify_msg:
            try:
                await bot.send_private_msg(
                    user_id=int(user_id),
                    message=notify_msg,
                )
            except Exception:
                # 私聊发送失败（对方未添加好友等），忽略
                logger.debug(f"[Interceptor] 无法私聊通知 {user_id} 身份变更")
    except Exception as e:
        logger.debug(f"[Interceptor] 身份检查异常: {e}")


async def _try_sleep_persuasion(bot: Bot, event: MessageEvent, current_time: float, user_id: str, uid_int: int):
    """尝试发送深夜劝睡消息。

    条件：
    - 仅核心群
    - 仅深夜时段
    - 管理员 / 决策组豁免
    - 每人 30 分钟冷却
    - 5% 概率触发

    本轮增强：
    - 文案改为 tier-aware 读取
    - 当前虽然仍只在 core 群触发，但后续若要扩展其他 tier，可直接复用
    """
    if not isinstance(event, GroupMessageEvent):
        return
    if not group_manager.is_core_group(event.group_id):
        return
    if user_id in SUPERUSERS or user_id in ADMINS:
        return
    if not _is_curfew_now():
        return

    last_warn = SLEEP_COOLDOWN.get(uid_int, 0)
    if current_time - last_warn <= 1800:
        return
    if random.random() >= 0.05:
        return

    SLEEP_COOLDOWN[uid_int] = current_time

    group_tier = group_manager.get_group_tier(event.group_id)
    text = resp_manager.get_tiered_random_from(
        "system.sleep_persuasion",
        group_tier,
        default="夜深了，早点休息吧。"
    )

    try:
        await bot.send(event, MessageSegment.reply(event.message_id) + text)
    except Exception:
        pass


@event_preprocessor
async def system_guard(bot: Bot, event: MessageEvent):
    """全局消息拦截器。

    处理顺序：
    1. 特权豁免
    2. 封禁状态检查
    3. 核心群深夜劝睡（不阻塞）
    4. 频率限制检查
    5. 身份感知检查（不阻塞）
    """
    user_id = str(event.user_id)
    uid_int = int(event.user_id)
    current_time = time.time()

    # ==================== 1. 特权豁免 ====================
    if user_id in SUPERUSERS or user_id in ADMINS:
        # 管理员也触发身份感知（但不阻塞）
        if isinstance(event, GroupMessageEvent):
            await _try_identity_check(user_id, event.group_id, bot)
        return

    # ==================== 2. 封禁状态检查 ====================
    if uid_int in BAN_LIST:
        unlock_time = BAN_LIST[uid_int]
        if current_time < unlock_time:
            raise IgnoredException("User Banned")
        else:
            del BAN_LIST[uid_int]
            if uid_int in SPAM_CACHE:
                del SPAM_CACHE[uid_int]
            logger.info(f"[Interceptor] 用户 {user_id} 封禁已解除")

    # ==================== 3. 核心群深夜劝睡（不阻塞） ====================
    await _try_sleep_persuasion(bot, event, current_time, user_id, uid_int)

    # ==================== 4. 频率限制检查 ====================
    if uid_int not in SPAM_CACHE:
        SPAM_CACHE[uid_int] = []

    # 清理 60 秒之前的记录
    history = [t for t in SPAM_CACHE[uid_int] if current_time - t <= 60]
    history.append(current_time)
    SPAM_CACHE[uid_int] = history
    count = len(history)

    if count <= THRESHOLD:
        # 未超限，触发身份感知
        if isinstance(event, GroupMessageEvent):
            await _try_identity_check(user_id, event.group_id, bot)
        return

    # 超限警告
    if count == THRESHOLD + 1:
        nickname = _get_nickname(event)
        await recorder.add_event("spam_block", uid_int, {"level": "warning"})
        msg = f"呼... {nickname}小友，灵力感应太频繁了，让我喘口气嘛 (冒烟)"
        try:
            await bot.send(event, msg)
        except Exception:
            pass
        raise IgnoredException("Spam Warning")

    # 超限封禁
    if count >= THRESHOLD + 2:
        BAN_LIST[uid_int] = current_time + BAN_DURATION
        await recorder.add_event("spam_block", uid_int, {"level": "ban"})
        ban_minutes = BAN_DURATION // 60
        msg = f"⚠灵力回路过载！强制进入 {ban_minutes} 分钟休眠模式。"
        try:
            if isinstance(event, GroupMessageEvent):
                await bot.send(event, MessageSegment.at(uid_int) + msg)
            else:
                await bot.send(event, msg)
        except Exception:
            pass

        logger.warning(f"[Interceptor] 用户 {user_id} 因刷屏被封禁 {ban_minutes} 分钟")
        raise IgnoredException("Spam Ban Triggered")