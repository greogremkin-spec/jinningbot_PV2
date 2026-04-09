""" 晋宁会馆·秃贝五边形 5.0 AI 触发判定层

职责：
1. 判断文本是否像命令，应避让给命令系统
2. 判断是否处于睡眠时段
3. 根据事件、上下文、文本判断 AI 触发类型：
   - direct
   - interjection
   - none
4. 本轮增强：
   - 若当前消息是在回复“真心话/大冒险题目消息”，则不触发 AI 闲聊

说明：
- 本文件不负责 matcher 注册
- 不负责 API 调用
- 不负责 prompt 生成
- 只负责“该不该触发、以什么方式触发”
"""

from __future__ import annotations

from datetime import datetime
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from src.common.group_context import GroupContext
from src.plugins.tubei_system.config import game_config
from .context_store import (
    is_group_conversation_active,
    is_interjection_on_cooldown,
)


def is_command_like_text(text: str) -> bool:
    """避让 slash 命令与纯文字命令。"""
    if text.startswith("/") or text.startswith("／"):
        return True

    from src.common.command_registry import (
        get_all_text_triggers, get_text_prefix_triggers, MENU_SECTIONS,
    )

    text_triggers = get_all_text_triggers()
    prefix_triggers = get_text_prefix_triggers()
    section_triggers = {
        s.get("text_trigger", ""): True
        for s in MENU_SECTIONS.values()
        if s.get("text_trigger")
    }

    if text in text_triggers or text in section_triggers:
        return True

    for prefix in prefix_triggers:
        if text == prefix or text.startswith(prefix + " "):
            return True

    return False


def is_sleeping_time() -> bool:
    """判断是否处于睡眠时段。"""
    h = datetime.now().hour
    start = game_config.get("security", "sleep_start", default=1)
    end = game_config.get("security", "sleep_end", default=5)

    if start <= end:
        return start <= h < end
    return h >= start or h < end


def _extract_reply_message_id(event) -> int:
    """尝试从消息中提取 reply 段对应的 message_id。"""
    try:
        for seg in event.message:
            if seg.type == "reply":
                raw_id = seg.data.get("id")
                if raw_id is None:
                    continue
                return int(raw_id)
    except Exception:
        return 0
    return 0


def is_replying_truth_dare_message(event) -> bool:
    """是否正在回复当前群最近一条真心话/大冒险题目消息。"""
    if not isinstance(event, GroupMessageEvent):
        return False

    reply_id = _extract_reply_message_id(event)
    if reply_id <= 0:
        return False

    try:
        from src.plugins.tubei_entertainment.truth_dare import get_active_truth_dare_message
        payload = get_active_truth_dare_message(event.group_id)
    except Exception:
        return False

    target_message_id = int(payload.get("message_id", 0) or 0)
    if target_message_id <= 0:
        return False

    return reply_id == target_message_id


def get_chat_trigger_type(event, ctx: GroupContext, text: str) -> str:
    """返回：
    - direct: 主动聊天
    - interjection: 随机插话
    - none: 不触发
    """
    if isinstance(event, PrivateMessageEvent):
        return "direct"

    if isinstance(event, GroupMessageEvent):
        # 若用户是在回复“真心话/大冒险”题目消息，则视为继续参与游戏，不触发 AI 闲聊
        if is_replying_truth_dare_message(event):
            return "none"

        if event.is_tome():
            return "direct"
        if "秃贝秃贝" in text:
            return "direct"

        # 群随机插话：当前继续支持 core / allied / public
        if ctx.group_tier in ("core", "allied", "public"):
            if is_sleeping_time():
                return "none"

            min_len = game_config.get("security", "random_chat_min_length", default=12)
            rate = game_config.get("security", "random_chat_rate", default=0.03)

            if len(text) < min_len:
                return "none"
            if not is_group_conversation_active(event.group_id):
                return "none"
            if is_interjection_on_cooldown(event.group_id):
                return "none"

            import random
            if random.random() < rate:
                return "interjection"

    return "none"