""" 晋宁会馆·秃贝五边形 5.0 真心话大冒险（分层题库 + 短期去重版）

升级点：
1. 继续作为公开群可用的轻娱乐功能
2. 接入 GroupContext / Permission 统一风格
3. 题库从 config/questions.json 读取
4. 支持三类题库：
   - core_local：主群 / 会馆强绑定题
   - lxh：罗小黑联动题
   - general：通用题
5. 题库按群等级分层调度：
   - public -> general
   - allied -> lxh + general
   - core -> core_local + lxh + general
6. 兼容旧版扁平结构
7. 兼容未来扩展结构
8. 增加每群短期去重抽取，降低短时间重复题体验
9. 私聊场景说明更明确：
   - 已绑定私聊：按绑定群层级抽题
   - 未绑定私聊：使用通用题库
10. 本轮增强：
   - 当前模式说明更清晰
   - 增加题库来源提示
   - 记录最近一条题目消息，供 AI 触发层识别“这是在接题”
"""

from __future__ import annotations

import random
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext

logger = logging.getLogger("tubei.truth_dare")

QUESTIONS_FILE = Path("config/questions.json")

DEFAULT_QUESTIONS = {
    "truth": {
        "core_local": [
            "你第一次进入晋宁会馆时，对这里的第一印象是什么？",
        ],
        "lxh": [
            "如果你能拥有《罗小黑战记》中的一种能力，你最想选哪一种？",
        ],
        "general": [
            "你做过最社死的一件事是什么？",
            "你最近最想完成的一件事是什么？",
        ],
    },
    "dare": {
        "core_local": [
            "在群里发一句：今天也要认真修行。",
        ],
        "lxh": [
            "模仿《罗小黑战记》里你最喜欢的角色说一句台词。",
        ],
        "general": [
            "在下一条消息里夸一夸自己。",
            "接下来三句话都带上感叹号。",
        ],
    },
}

# ==================== 运行时最近题目缓存 ====================
# 说明：
# - 仅做体验优化，不持久化
# - 群维度隔离；私聊未绑定时使用 pseudo gid = 0
# - 每种模式独立维护
RECENT_QUESTIONS: Dict[int, Dict[str, List[str]]] = {}
RECENT_MAX_LEN = 10
RECENT_EXPIRE_SECONDS = 86400  # 1 天

# ==================== 题目消息运行时记录 ====================
# 用于避免“回复真心话/大冒险题目消息”时误触发 AI 闲聊
# 结构：{group_id: {"message_id": int, "mode": "truth"/"dare", "created_at": float}}
ACTIVE_TD_MESSAGES: Dict[int, Dict[str, Any]] = {}
TD_MESSAGE_EXPIRE_SECONDS = 600  # 10 分钟


def _cleanup_recent_questions():
    now = time.time()
    expired_gids = []

    for gid, payload in RECENT_QUESTIONS.items():
        last_active = payload.get("_last_active", 0)
        if now - last_active > RECENT_EXPIRE_SECONDS:
            expired_gids.append(gid)

    for gid in expired_gids:
        del RECENT_QUESTIONS[gid]


def cleanup_expired_td_messages():
    now = time.time()
    expired = []

    for gid, payload in ACTIVE_TD_MESSAGES.items():
        created_at = float(payload.get("created_at", 0) or 0)
        if now - created_at > TD_MESSAGE_EXPIRE_SECONDS:
            expired.append(gid)

    for gid in expired:
        ACTIVE_TD_MESSAGES.pop(gid, None)


def mark_truth_dare_message(group_id: int, message_id: int, mode: str):
    if group_id <= 0 or message_id <= 0:
        return
    ACTIVE_TD_MESSAGES[int(group_id)] = {
        "message_id": int(message_id),
        "mode": str(mode),
        "created_at": time.time(),
    }


def get_active_truth_dare_message(group_id: int) -> Dict[str, Any]:
    cleanup_expired_td_messages()
    return dict(ACTIVE_TD_MESSAGES.get(int(group_id), {}))


def load_questions() -> dict:
    """加载题库，兼容新旧结构。"""
    if not QUESTIONS_FILE.exists():
        return DEFAULT_QUESTIONS

    try:
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data or DEFAULT_QUESTIONS
    except Exception as e:
        logger.error(f"[TruthDare] 加载题库失败: {e}")
        return DEFAULT_QUESTIONS


def _extract_items_from_category(category_block: Any) -> List[str]:
    """从分类块中提取题目列表。

    支持两种结构：
    1. 旧结构：
       "general": ["题 1", "题 2"]
    2. 未来扩展结构：
       "general": {"enabled": true, "items": ["题 1", "题 2"]}
    """
    if isinstance(category_block, list):
        return [x for x in category_block if isinstance(x, str) and x.strip()]

    if isinstance(category_block, dict):
        enabled = category_block.get("enabled", True)
        if not enabled:
            return []

        items = category_block.get("items", [])
        if isinstance(items, list):
            return [x for x in items if isinstance(x, str) and x.strip()]

    return []


def _normalize_pool_block(block, mode: str) -> dict:
    """兼容旧结构并统一成三层分类。"""
    if isinstance(block, list):
        # 旧版扁平题库，保守视为 general
        return {
            "core_local": [],
            "lxh": [],
            "general": list(block),
        }

    if not isinstance(block, dict):
        return {
            "core_local": [],
            "lxh": [],
            "general": [],
        }

    return {
        "core_local": _extract_items_from_category(block.get("core_local", [])),
        "lxh": _extract_items_from_category(block.get("lxh", [])),
        "general": _extract_items_from_category(block.get("general", [])),
    }


def _get_question_pool(questions: dict, mode: str, group_tier: str) -> List[str]:
    """按群等级组合题池。"""
    block = _normalize_pool_block(questions.get(mode, {}), mode)

    if group_tier == "core":
        keys = ["core_local", "lxh", "general"]
    elif group_tier == "allied":
        keys = ["lxh", "general"]
    else:
        keys = ["general"]

    pool: List[str] = []
    for key in keys:
        pool.extend(block.get(key, []))

    # 去掉空项和重复项，保持顺序稳定
    seen = set()
    cleaned = []
    for item in pool:
        if not isinstance(item, str):
            continue
        q = item.strip()
        if not q or q in seen:
            continue
        seen.add(q)
        cleaned.append(q)

    return cleaned


def _get_recent_group_key(ctx: GroupContext) -> int:
    """最近题目缓存 key。

    - 群聊：真实 group_id
    - 私聊已绑定：绑定群 group_id
    - 私聊未绑定：0（通用私聊娱乐池）
    """
    return int(ctx.group_id or 0)


def _get_recent_questions(group_key: int, mode: str) -> List[str]:
    bucket = RECENT_QUESTIONS.get(group_key, {})
    return list(bucket.get(mode, []))


def _push_recent_question(group_key: int, mode: str, question: str):
    bucket = RECENT_QUESTIONS.setdefault(group_key, {"truth": [], "dare": [], "_last_active": 0})
    recent = list(bucket.get(mode, []))
    recent.append(question)
    bucket[mode] = recent[-RECENT_MAX_LEN:]
    bucket["_last_active"] = time.time()
    RECENT_QUESTIONS[group_key] = bucket


def _pick_question_with_dedup(pool: List[str], group_key: int, mode: str) -> str:
    """优先避开近期重复题；若题池过小则允许回退。"""
    if not pool:
        return ""

    recent = set(_get_recent_questions(group_key, mode))
    candidates = [q for q in pool if q not in recent]

    if candidates:
        question = random.choice(candidates)
    else:
        question = random.choice(pool)

    _push_recent_question(group_key, mode, question)
    return question


def _build_footer_for_truth(ctx: GroupContext) -> str:
    footer = "输入 真心话 再来一题 | 大冒险"
    if ctx.is_private:
        if ctx.is_bound:
            footer += f"\n 当前模式：私聊娱乐（按绑定群层级抽题：{ctx.group_name}）"
        else:
            footer += "\n 当前模式：私聊娱乐（未绑定，使用通用题库）"
    else:
        if ctx.group_tier == "core":
            footer += "\n 当前模式：核心群娱乐"
        elif ctx.group_tier == "allied":
            footer += "\n 当前模式：联盟群娱乐"
        else:
            footer += "\n 当前模式：公开群娱乐"
    return footer


def _build_footer_for_dare(ctx: GroupContext) -> str:
    footer = "输入 大冒险 再来一题 | 真心话"
    if ctx.is_private:
        if ctx.is_bound:
            footer += f"\n 当前模式：私聊娱乐（按绑定群层级抽题：{ctx.group_name}）"
        else:
            footer += "\n 当前模式：私聊娱乐（未绑定，使用通用题库）"
    else:
        if ctx.group_tier == "core":
            footer += "\n 当前模式：核心群娱乐"
        elif ctx.group_tier == "allied":
            footer += "\n 当前模式：联盟群娱乐"
        else:
            footer += "\n 当前模式：公开群娱乐"
    return footer


def _build_pool_source_hint(ctx: GroupContext, mode: str) -> str:
    """构建当前题库来源提示。"""
    mode_name = "真心话" if mode == "truth" else "大冒险"

    if ctx.is_private:
        if ctx.is_bound:
            if ctx.group_tier == "core":
                return f"{mode_name}题库来源：绑定群为核心群，已启用 core_local + lxh + general"
            if ctx.group_tier == "allied":
                return f"{mode_name}题库来源：绑定群为联盟群，已启用 lxh + general"
            return f"{mode_name}题库来源：绑定群为公开环境，已启用 general"
        return f"{mode_name}题库来源：当前私聊未绑定，使用 general 通用题库"

    if ctx.group_tier == "core":
        return f"{mode_name}题库来源：当前为核心群，已启用 core_local + lxh + general"
    if ctx.group_tier == "allied":
        return f"{mode_name}题库来源：当前为联盟群，已启用 lxh + general"
    return f"{mode_name}题库来源：当前为公开群，已启用 general"


# ==================== 指令注册 ====================
truth_cmd = on_command("真心话", priority=5, block=True)
dare_cmd = on_command("大冒险", priority=5, block=True)


# ==================== 真心话 ====================
@truth_cmd.handle()
async def handle_truth(bot: Bot, event: MessageEvent):
    _cleanup_recent_questions()
    cleanup_expired_td_messages()
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "真心话大冒险 · 灵力诚实探测",
        min_tier="public",
        ctx=ctx,
    )
    if not perm.allowed:
        await truth_cmd.finish(perm.deny_message)

    questions = load_questions()
    pool = _get_question_pool(questions, "truth", ctx.group_tier)
    if not pool:
        await truth_cmd.finish(ui.error("题库空了..."))

    group_key = _get_recent_group_key(ctx)
    question = _pick_question_with_dedup(pool, group_key, "truth")
    if not question:
        await truth_cmd.finish(ui.error("题库空了..."))

    footer = _build_footer_for_truth(ctx)
    pool_hint = _build_pool_source_hint(ctx, "truth")
    card = ui.render_result_card(
        "灵力诚实探测",
        "请听题：",
        stats=[("题目", "")],
        extra=f" {question}\n\n{pool_hint}",
        footer=footer,
    )

    # 群内发送时记录题目消息，供 AI 触发层识别“这是在接题，不是在找秃贝聊天”
    if getattr(ctx, "group_id", 0) > 0:
        try:
            send_ret = await bot.send(event, card)
            message_id = getattr(send_ret, "message_id", None)
            if message_id is None and isinstance(send_ret, dict):
                message_id = send_ret.get("message_id")
            if message_id:
                mark_truth_dare_message(ctx.group_id, int(message_id), "truth")
            await truth_cmd.finish()
        except Exception:
            await truth_cmd.finish(card)
    else:
        await truth_cmd.finish(card)


# ==================== 大冒险 ====================
@dare_cmd.handle()
async def handle_dare(bot: Bot, event: MessageEvent):
    _cleanup_recent_questions()
    cleanup_expired_td_messages()
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "真心话大冒险 · 灵压勇气挑战",
        min_tier="public",
        ctx=ctx,
    )
    if not perm.allowed:
        await dare_cmd.finish(perm.deny_message)

    questions = load_questions()
    pool = _get_question_pool(questions, "dare", ctx.group_tier)
    if not pool:
        await dare_cmd.finish(ui.error("题库空了..."))

    group_key = _get_recent_group_key(ctx)
    question = _pick_question_with_dedup(pool, group_key, "dare")
    if not question:
        await dare_cmd.finish(ui.error("题库空了..."))

    footer = _build_footer_for_dare(ctx)
    pool_hint = _build_pool_source_hint(ctx, "dare")
    card = ui.render_result_card(
        "灵压勇气挑战",
        "请接受挑战：",
        stats=[("任务", "")],
        extra=f" {question}\n\n{pool_hint}",
        footer=footer,
    )

    # 群内发送时记录题目消息，供 AI 触发层识别“这是在接题，不是在找秃贝聊天”
    if getattr(ctx, "group_id", 0) > 0:
        try:
            send_ret = await bot.send(event, card)
            message_id = getattr(send_ret, "message_id", None)
            if message_id is None and isinstance(send_ret, dict):
                message_id = send_ret.get("message_id")
            if message_id:
                mark_truth_dare_message(ctx.group_id, int(message_id), "dare")
            await dare_cmd.finish()
        except Exception:
            await dare_cmd.finish(card)
    else:
        await dare_cmd.finish(card)