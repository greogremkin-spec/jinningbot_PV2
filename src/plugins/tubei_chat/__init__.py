""" 晋宁会馆·秃贝五边形 5.0 AI 核心（工程化拆分 + direct_mode 精修版）
本次版本目标：
1. 保持原有 AI 行为不减少
2. 将 __init__.py 作为 AI 子系统主装配入口
3. 主动聊天支持 direct_mode：
- mention：群内 @秃贝，优先直接回应用户
- call_name：“秃贝秃贝”，允许更自然贴一点群话题
4. 继续支持：
- 群聊 / 私聊上下文分离
- 私聊世界观跟随绑定群
- 主动聊天与随机插话分流
- 群公共消息缓存
- 插话每群冷却
- danger 群禁用 AI
"""
from __future__ import annotations

import logging
import time

from nonebot import on_message, get_driver
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.plugin import PluginMetadata

from .rag_engine import build_system_prompt
from .client import chat_with_deepseek
from .prompt_builder import (
    build_group_direct_prompt,
    build_interjection_prompt,
)
from .trigger import (
    is_command_like_text,
    is_sleeping_time,
    get_chat_trigger_type,
)
from .context_store import (
    get_context_key,
    get_interjection_context_key,
    cleanup_expired_group_messages,
    cleanup_expired_interjection_cooldowns,
    record_group_recent_message,
    get_recent_group_messages,
    mark_interjection_sent,
)

from src.common.group_context import GroupContext
from src.common.data_manager import data_manager
from src.plugins.tubei_system.config import system_config

logger = logging.getLogger("tubei.chat")

__plugin_meta__ = PluginMetadata(
    name="秃贝 AI 核心",
    description="DeepSeek-V3 驱动的 AI 对话（含群公共上下文插话）",
    usage="@秃贝 或 秃贝秃贝 + 任意内容",
)

driver = get_driver()


@driver.on_startup
async def _():
    print("✅[Tubei Chat] AI 核心已注入 (Priority=99)")
    print(" - 主动聊天 / 随机插话已分流")
    print(" - 群公共消息缓存已启用")
    print(" - 插话冷却 / 噪音过滤已启用")
    print(" - 模块已拆分：context_store / prompt_builder / trigger / client")
    print(" - direct_mode 已启用：mention / call_name")


# ==================== 宣传功能 ====================
async def _try_send_promotion(bot: Bot, event: GroupMessageEvent) -> bool:
    try:
        status = await data_manager.get_bot_status()
        promo = status.get("promotion", {})
        if not promo.get("enabled", False):
            return False

        import random
        chance = promo.get("chance", 0.20)
        if random.random() >= chance:
            return False

        content = promo.get("content", "")
        if not content:
            return False

        await bot.send(event, content)
        return True
    except Exception as e:
        logger.error(f"[Chat] 宣传发送失败: {e}")
        return False


def _resolve_direct_mode(event, text: str) -> str:
    """区分主动聊天的触发来源。

    - mention: @秃贝
    - call_name: 文本中出现“秃贝秃贝”
    - private: 私聊默认按 mention 语义处理（更偏直接回应）
    """
    if isinstance(event, GroupMessageEvent):
        if event.is_tome():
            return "mention"
        if "秃贝秃贝" in text:
            return "call_name"
        return "mention"

    return "mention"


# ==================== 主逻辑 ====================
ai_chat = on_message(priority=99, block=False)


@ai_chat.handle()
async def handle_chat(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    text = event.get_plaintext().strip()
    user_id = str(event.user_id)

    if not text:
        return

    # 命令优先避让
    if is_command_like_text(text):
        return

    cleanup_expired_group_messages()
    cleanup_expired_interjection_cooldowns()

    ctx = await GroupContext.from_event(event)

    # danger 群禁用 AI
    if isinstance(event, GroupMessageEvent) and ctx.group_tier == "danger":
        return

    now_ts = time.time()

    # 群公共消息缓存：记录群里的自然聊天内容
    if isinstance(event, GroupMessageEvent):
        record_group_recent_message(
            event,
            text,
            command_like_checker=is_command_like_text,
        )

    trigger_type = get_chat_trigger_type(event, ctx, text)
    if trigger_type == "none":
        return

    # 深夜主动聊天劝睡（主动触发才有意义）
    if trigger_type == "direct" and is_sleeping_time() and user_id not in system_config.superusers:
        nickname = getattr(event.sender, "nickname", "") or "小友"
        await ai_chat.finish(f"（揉眼睛）{nickname}小友，现在是深夜了... 快去睡觉！(OvO)")

    prompt_group_id = event.group_id if isinstance(event, GroupMessageEvent) else None

    # ===== 1. 主动聊天 =====
    if trigger_type == "direct":
        context_key = get_context_key(event)
        direct_mode = _resolve_direct_mode(event, text)

        # 群聊主动触发：同时注入群公共上下文
        if isinstance(event, GroupMessageEvent):
            recent_group_messages = get_recent_group_messages(
                event.group_id,
                limit=8,
                before_ts=now_ts,
            )
            user_prompt = build_group_direct_prompt(
                text,
                recent_group_messages,
                direct_mode=direct_mode,
            )
            sys_prompt = await build_system_prompt(
                user_id,
                group_id=prompt_group_id,
                scene="direct",
            )
            reply = await chat_with_deepseek(
                context_key,
                user_prompt,
                sys_prompt,
                use_history=True,
            )
            await ai_chat.finish(MessageSegment.at(user_id) + " " + reply)

        # 私聊 / 临时会话：只使用用户上下文
        else:
            sys_prompt = await build_system_prompt(
                user_id,
                group_id=prompt_group_id,
                scene="private",
            )
            reply = await chat_with_deepseek(
                context_key,
                text,
                sys_prompt,
                use_history=True,
            )
            await ai_chat.finish(reply)

    # ===== 2. 随机插话 =====
    if trigger_type == "interjection" and isinstance(event, GroupMessageEvent):
        # 先尝试宣传
        promoted = await _try_send_promotion(bot, event)
        if promoted:
            mark_interjection_sent(event.group_id)
            return

        recent_group_messages = get_recent_group_messages(
            event.group_id,
            limit=10,
            before_ts=now_ts,
        )
        interjection_prompt = build_interjection_prompt(recent_group_messages, ctx)
        context_key = get_interjection_context_key(event.group_id)
        sys_prompt = await build_system_prompt(
            user_id,
            group_id=prompt_group_id,
            scene="interjection",
        )

        # 插话默认不继承长期历史，避免逐渐漂成“连续答题模式”
        reply = await chat_with_deepseek(
            context_key,
            interjection_prompt,
            sys_prompt,
            use_history=False,
        )

        mark_interjection_sent(event.group_id)

        # 不 @ 任何人，直接发言
        await ai_chat.finish(reply)