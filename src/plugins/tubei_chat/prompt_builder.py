""" 晋宁会馆·秃贝五边形 5.0 AI Prompt 构造层（主动聊天强弱调节版）
职责：
1. 构造群聊主动聊天时的 user prompt
2. 构造随机插话时的 user prompt
3. 支持主动聊天 direct_mode：
- mention：更偏直接回应用户
- call_name：更偏自然接话，可稍微带一点群话题

说明：
- system prompt 仍由 rag_engine.build_system_prompt() 负责
- 本文件只负责场景化 user prompt / task prompt
"""
from __future__ import annotations

import random
from typing import List, Dict, Any

from src.common.group_context import GroupContext

VALID_DIRECT_MODES = {"mention", "call_name"}


def build_group_direct_prompt(
    user_text: str,
    recent_group_messages: List[Dict[str, Any]],
    direct_mode: str = "mention",
) -> str:
    """群聊主动触发时的用户 prompt。

    direct_mode:
    - mention: 来自 @秃贝，更偏直接回答用户当前这句话
    - call_name: 来自“秃贝秃贝”，可稍微更自然地贴一点群话题
    """
    if direct_mode not in VALID_DIRECT_MODES:
        direct_mode = "mention"

    lines = []

    # mention 模式：上下文更弱，只给较少群公共背景
    if direct_mode == "mention":
        if recent_group_messages:
            lines.append("以下是当前群里最近的少量聊天片段，仅供你辅助理解语境：")
            for item in recent_group_messages[-3:]:
                name = item.get("name", "某人")
                text = (item.get("text", "") or "").strip()
                if text:
                    lines.append(f"- {name}：{text}")
            lines.append("")

        lines.append("现在，有用户明确地在群里点名来和你说话。")
        lines.append(f"他的当前消息是：{user_text}")
        lines.append("")
        lines.append("请你优先直接回应这条消息本身。")
        lines.append("要求：")
        lines.append("1. 以当前用户这句话为第一优先")
        lines.append("2. 只有在确实自然时，才轻微参考上面的群聊片段")
        lines.append("3. 回复要像群里自然接话，不要太像私聊客服")
        lines.append("4. 不要复读原句")
        lines.append("5. 不要 Markdown，不要分段")

        return "\n".join(lines)

    # call_name 模式：允许稍微更自由地结合群话题
    if recent_group_messages:
        lines.append("以下是当前群里最近的聊天片段，仅供你理解语境：")
        for item in recent_group_messages[-6:]:
            name = item.get("name", "某人")
            text = (item.get("text", "") or "").strip()
            if text:
                lines.append(f"- {name}：{text}")
        lines.append("")

    lines.append("现在，有用户在群里喊你来接话了。")
    lines.append(f"他的当前消息是：{user_text}")
    lines.append("")
    lines.append("请你作为秃贝，在理解群聊语境的前提下自然回应。")
    lines.append("要求：")
    lines.append("1. 可以正常回应用户")
    lines.append("2. 可以比普通点名回复更自然地贴一点当前群聊话题")
    lines.append("3. 群聊口吻自然，不要太像私聊客服")
    lines.append("4. 不要复读原句")
    lines.append("5. 不要 Markdown，不要分段")

    return "\n".join(lines)


def build_interjection_prompt(
    recent_group_messages: List[Dict[str, Any]],
    ctx: GroupContext,
) -> str:
    """随机插话 prompt。

    核心要求：
    - 不是回复任何单独用户
    - 不是客服
    - 是独立个体在群里自然冒泡说一句
    """
    style_map = {
        "observe": "观察型",
        "opinion": "观点型",
        "tease": "轻吐槽型",
        "drift": "联想型",
    }
    style_key = random.choice(list(style_map.keys()))
    style_text = style_map[style_key]

    lines = []
    lines.append("你现在不是在回复某个用户，也不是在被@后回答问题。")
    lines.append("你是秃贝，现在正在群里潜水观察大家聊天。")
    lines.append("请根据最近的聊天内容，自然地插一句话。")
    lines.append("")
    lines.append(f"当前插话风格偏向：{style_text}")
    lines.append("")
    lines.append("要求：")
    lines.append("1. 不要@任何用户")
    lines.append("2. 不要直接回应某一句话，不要出现“你刚才说”“前面那个”“我同意你”之类措辞")
    lines.append("3. 不要复述最近某条消息原文")
    lines.append("4. 语气像群成员自然冒泡，不像客服，不像答题")
    lines.append("5. 可以表达感想、吐槽、联想、观察、补充，但要像独立个体发言")
    lines.append("6. 长度控制在 20~50 字左右")
    lines.append("7. 不要使用 Markdown，不要分段，不要编号")

    if ctx.group_tier == "core":
        lines.append("8. 当前是核心群，可以更自然结合会馆语境")
    elif ctx.group_tier == "allied":
        lines.append("8. 当前是联盟群，可以自然说话，但不要泄露核心群隐私，也不要主动带主群人物")
    else:
        lines.append("8. 当前是普通群，请保持普通群友机器人的自然口吻")

    lines.append("")
    lines.append("最近聊天片段：")

    if recent_group_messages:
        for item in recent_group_messages[-8:]:
            name = item.get("name", "某人")
            text = (item.get("text", "") or "").strip()
            if text:
                lines.append(f"- {name}：{text}")
    else:
        lines.append("- （暂无明确上下文，请尽量自然简短地冒泡）")

    lines.append("")
    lines.append("请只输出秃贝这次自然插话的内容。")

    return "\n".join(lines)