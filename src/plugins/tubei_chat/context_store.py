""" 晋宁会馆·秃贝五边形 5.0 AI 上下文存储层
职责：
1. 管理用户连续对话缓存 CONTEXT_CACHE
2. 管理群公共消息缓存 GROUP_MESSAGE_CACHE
3. 管理每群插话冷却 LAST_INTERJECTION_AT
4. 提供群消息过滤、活跃度判断、recent messages 获取等工具
5. 尽量把“缓存层逻辑”从 AI 主装配文件中拆出去

设计说明：
- CONTEXT_CACHE 用于主动聊天的连续上下文
- GROUP_MESSAGE_CACHE 用于群主动聊天的公共语境与随机插话“读空气”
- 随机插话默认不依赖长期历史，因此插话的真正历史上下文不在这里持久使用
"""
from __future__ import annotations

import re
import time
from typing import Dict, Any, List, Optional

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.plugins.tubei_system.config import game_config

# ==================== 用户对话上下文缓存 ====================
CONTEXT_CACHE: Dict[str, Dict[str, Any]] = {}
MAX_CONTEXT_LEN = 10
CONTEXT_EXPIRE_SECONDS = 21600  # 6 小时

# ==================== 群公共消息缓存 ====================
GROUP_MESSAGE_CACHE: Dict[int, Dict[str, Any]] = {}
GROUP_MESSAGE_MAX_LEN = 30
GROUP_MESSAGE_EXPIRE_SECONDS = 1800  # 30 分钟
GROUP_MESSAGE_ACTIVE_WINDOW = 180  # 最近 3 分钟
GROUP_MESSAGE_ACTIVE_MIN_COUNT = 4  # 至少 4 条有效消息才认为群聊活跃

# ==================== 每群插话冷却 ====================
LAST_INTERJECTION_AT: Dict[int, float] = {}


# ================================================================
# context key
# ================================================================
def get_context_key(event) -> str:
    """主动聊天上下文 key。
    - 群聊：按 群+用户 隔离
    - 私聊：普通私聊按 private_{uid}
    - 群临时会话：按 temp_{source_group_id}_{uid}
    """
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

    user_id = str(event.user_id)

    if isinstance(event, GroupMessageEvent):
        return f"group_{event.group_id}_{user_id}"

    if isinstance(event, PrivateMessageEvent):
        source_group_id = None
        try:
            sender = getattr(event, "sender", None)
            if sender is not None:
                maybe_gid = getattr(sender, "group_id", None)
                if maybe_gid:
                    source_group_id = int(maybe_gid)
        except Exception:
            source_group_id = None

        if source_group_id:
            return f"temp_{source_group_id}_{user_id}"
        return f"private_{user_id}"

    return f"user_{user_id}"


def get_interjection_context_key(group_id: int) -> str:
    """随机插话上下文 key：按群隔离。"""
    return f"interject_group_{int(group_id)}"


# ================================================================
# 清理逻辑
# ================================================================
def cleanup_expired_contexts():
    now = time.time()
    expired_keys = [
        k for k, v in CONTEXT_CACHE.items()
        if now - v.get("last_active", 0) > CONTEXT_EXPIRE_SECONDS
    ]
    for k in expired_keys:
        del CONTEXT_CACHE[k]


def cleanup_expired_group_messages():
    now = time.time()
    expired_gids = [
        gid for gid, data in GROUP_MESSAGE_CACHE.items()
        if now - data.get("last_active", 0) > GROUP_MESSAGE_EXPIRE_SECONDS
    ]
    for gid in expired_gids:
        del GROUP_MESSAGE_CACHE[gid]


def cleanup_expired_interjection_cooldowns():
    now = time.time()
    cooldown = get_interjection_cooldown_seconds()
    expired = [gid for gid, ts in LAST_INTERJECTION_AT.items() if now - ts > max(cooldown * 3, 3600)]
    for gid in expired:
        del LAST_INTERJECTION_AT[gid]


# ================================================================
# 群消息记录与过滤
# ================================================================
def get_sender_display_name(event: GroupMessageEvent) -> str:
    try:
        if event.sender.card:
            return event.sender.card
        if event.sender.nickname:
            return event.sender.nickname
    except Exception:
        pass
    return f"用户{event.user_id}"


def _is_all_punctuation(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return True
    return all((not ch.isalnum()) and (not ("\u4e00" <= ch <= "\u9fff")) for ch in raw)


def _is_pure_number(text: str) -> bool:
    return bool(re.fullmatch(r"\d+", text.strip()))


def _is_low_value_water_text(text: str) -> bool:
    t = text.strip().lower()
    low_value = {
        "哈", "哈哈", "哈哈哈", "哈哈哈哈",
        "草", "草草", "草草草",
        "6", "66", "666", "6666",
        "?", "？", "??", "？？", "???", "？？？",
        "嗯", "嗯嗯", "哦", "哦哦", "啊", "啊啊",
        "好", "好吧", "行", "行吧",
        "1", "11", "111",
    }
    if t in low_value:
        return True

    if len(t) <= 6 and len(set(t)) == 1:
        return True

    return False


def should_record_group_message(text: str, command_like_checker=None) -> bool:
    """群公共消息缓存的轻过滤。
    command_like_checker:
    - 由上层注入 _is_command_like_text
    - 避免 context_store 反向依赖 trigger 模块
    """
    raw = (text or "").strip()
    if not raw:
        return False

    if command_like_checker and command_like_checker(raw):
        return False

    if len(raw) < 2:
        return False

    if _is_all_punctuation(raw):
        return False

    if _is_pure_number(raw):
        return False

    if _is_low_value_water_text(raw):
        return False

    return True


def record_group_recent_message(
    event: GroupMessageEvent,
    text: str,
    command_like_checker=None,
):
    """记录群公共消息缓存。"""
    if not should_record_group_message(text, command_like_checker=command_like_checker):
        return

    gid = int(event.group_id)
    bucket = GROUP_MESSAGE_CACHE.setdefault(
        gid,
        {
            "messages": [],
            "last_active": time.time(),
        },
    )
    messages = bucket.get("messages", [])
    messages.append(
        {
            "uid": str(event.user_id),
            "name": get_sender_display_name(event),
            "text": text.strip(),
            "ts": time.time(),
            "source": "user",
        }
    )
    bucket["messages"] = messages[-GROUP_MESSAGE_MAX_LEN:]
    bucket["last_active"] = time.time()
    GROUP_MESSAGE_CACHE[gid] = bucket


def get_recent_group_messages(
    group_id: int,
    limit: int = 8,
    before_ts: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """获取群最近公共消息。
    before_ts:
    - 仅返回 ts < before_ts 的消息
    - 用于避免把“当前触发消息”也塞进上下文里
    """
    bucket = GROUP_MESSAGE_CACHE.get(int(group_id), {})
    messages = bucket.get("messages", [])

    if before_ts is not None:
        messages = [m for m in messages if m.get("ts", 0) < before_ts]

    return list(messages[-limit:])


def is_group_conversation_active(group_id: int) -> bool:
    """判断群当前是否处于有效对话状态。"""
    now = time.time()
    recent = get_recent_group_messages(group_id, limit=12)

    valid = [
        x for x in recent
        if x.get("source") == "user"
        and now - x.get("ts", 0) <= GROUP_MESSAGE_ACTIVE_WINDOW
        and len((x.get("text") or "").strip()) >= 6
    ]
    return len(valid) >= GROUP_MESSAGE_ACTIVE_MIN_COUNT


# ================================================================
# 插话冷却
# ================================================================
def get_interjection_cooldown_seconds() -> int:
    value = game_config.get("chat", "interjection_cooldown_seconds", default=None)
    if value is None:
        value = 600
    try:
        return max(60, int(value))
    except Exception:
        return 600


def is_interjection_on_cooldown(group_id: int) -> bool:
    now = time.time()
    last_ts = LAST_INTERJECTION_AT.get(int(group_id), 0)
    cooldown = get_interjection_cooldown_seconds()
    return (now - last_ts) < cooldown


def mark_interjection_sent(group_id: int):
    LAST_INTERJECTION_AT[int(group_id)] = time.time()