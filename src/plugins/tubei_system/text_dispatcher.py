""" 晋宁会馆·秃贝五边形 5.0 纯文字指令统一分发器（优雅收口版）
职责：
1. 监听群消息 / 私聊消息，检查是否匹配纯文字指令
2. 严格全文匹配（"聚灵"触发，"我要聚灵"不触发）
3. 支持带参数的纯文字指令（"派遣 晋宁老街"、"使用 天明珠"）
4. 根据 command_registry 元数据与 GroupContext 过滤不可用指令
5. 路由到对应模块 handler

本版本收口目标：
- 保持 registry 驱动
- 减少分发层中的业务特判感
- 保留全部现有功能，不删减
- 让排行榜等特殊入口处理更自然、更易维护
"""
from __future__ import annotations

import logging
import traceback
from typing import Callable, Awaitable, Dict, Optional

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    Bot, GroupMessageEvent, MessageEvent,
)
from nonebot.exception import FinishedException

from src.common.command_registry import (
    COMMANDS, MENU_SECTIONS, get_all_text_triggers, get_text_prefix_triggers,
)
from src.common.group_manager import TIER_CORE, TIER_ALLIED, TIER_PUBLIC, TIER_DANGER
from src.common.group_context import GroupContext

logger = logging.getLogger("tubei.text_dispatcher")

# ==================== 触发词表 ====================
EXACT_TRIGGERS = get_all_text_triggers()
PREFIX_TRIGGERS = get_text_prefix_triggers()

SECTION_TRIGGERS: Dict[str, str] = {}
for section_id, section_info in MENU_SECTIONS.items():
    text_trigger = section_info.get("text_trigger", "")
    if text_trigger:
        SECTION_TRIGGERS[text_trigger] = section_id
        if "板块" in text_trigger:
            SECTION_TRIGGERS[text_trigger.replace("板块", "版块")] = section_id

CMD_INDEX = {cmd["id"]: cmd for cmd in COMMANDS}

SKIP_IDS = {
    "heixiu_catch",
    "join_guide",
}

# ==================== 上下文等级检查 ====================
TIER_PRIORITY = {
    TIER_CORE: 0,
    TIER_ALLIED: 1,
    TIER_PUBLIC: 2,
    TIER_DANGER: 3,
    "unbound": 98,
}


def _tier_meets(current_tier: str, required_tier: str) -> bool:
    return TIER_PRIORITY.get(current_tier, 99) <= TIER_PRIORITY.get(required_tier, 99)


def _ctx_effective_tier(ctx: GroupContext) -> str:
    """未绑定私聊在纯文字菜单层按 public 视角对待。"""
    return ctx.group_tier if ctx.group_tier != "unbound" else "public"


def _cmd_available_in_ctx(cmd_def: dict, ctx: GroupContext) -> bool:
    """根据 registry 元数据与上下文判断命令能否被纯文字触发。"""
    current_tier = _ctx_effective_tier(ctx)
    min_tier = cmd_def.get("min_tier", "public")

    if not _tier_meets(current_tier, min_tier):
        return False
    if ctx.is_private and not cmd_def.get("allow_private", False):
        return False
    if cmd_def.get("core_only") and ctx.group_tier != "core":
        return False
    return True


# ==================== 特殊快捷解析 ====================
def _resolve_direct_ranking_key(text: str) -> Optional[str]:
    """解析“灵力排行榜 / 嘿咻榜 / 顿悟排行”这类整句快捷入口。"""
    mapping = {
        "灵力排行榜": "灵力",
        "灵力榜": "灵力",
        "灵力排行": "灵力",

        "嘿咻排行榜": "嘿咻",
        "嘿咻榜": "嘿咻",
        "嘿咻排行": "嘿咻",

        "聚灵排行榜": "聚灵",
        "聚灵榜": "聚灵",
        "聚灵排行": "聚灵",

        "厨房排行榜": "厨房",
        "厨房榜": "厨房",
        "厨房排行": "厨房",

        "派遣排行榜": "派遣",
        "派遣榜": "派遣",
        "派遣排行": "派遣",

        "顿悟排行榜": "顿悟",
        "顿悟榜": "顿悟",
        "顿悟排行": "顿悟",

        "毛球排行榜": "毛球",
        "毛球榜": "毛球",
        "毛球排行": "毛球",
    }
    return mapping.get(text)


# ==================== 路由表加载器 ====================
async def _route_register_guide(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_admin.registry import handle_guide
    await handle_guide(bot, event)


async def _route_view_commands(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_guide import _handle_view_commands
    await _handle_view_commands(bot, event)


async def _route_profile(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.meditation import handle_profile
    await handle_profile(bot, event)


async def _route_member_list(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_admin.manager import handle_list
    await handle_list(bot, event)


async def _route_meditate(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.meditation import handle_meditate
    await handle_meditate(bot, event)


async def _route_fortune(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.meditation import handle_fortune
    await handle_fortune(bot, event)


async def _route_expedition(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_cultivation.expedition import handle_expedition
    msg = Message(args_text) if args_text else Message()
    await handle_expedition(bot, event, msg)


async def _route_recall(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.expedition import handle_recall
    await handle_recall(bot, event)


async def _route_garden(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.garden import handle_garden
    await handle_garden(bot, event)


async def _route_sow(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_cultivation.garden import handle_sow
    msg = Message(args_text) if args_text else Message()
    await handle_sow(bot, event, msg)


async def _route_water(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.garden import handle_water
    await handle_water(bot, event)


async def _route_harvest(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.garden import handle_harvest
    await handle_harvest(bot, event)


async def _route_bag(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.items import handle_bag
    await handle_bag(bot, event)


async def _route_use_item(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_cultivation.items import handle_use
    msg = Message(args_text) if args_text else Message()
    await handle_use(bot, event, msg)


async def _route_smelt(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.items import handle_smelt
    await handle_smelt(bot, event)


async def _route_lore(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_cultivation.items import handle_lore
    msg = Message(args_text) if args_text else Message()
    await handle_lore(bot, event, msg)


async def _route_unlock(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_cultivation.items import handle_unlock
    msg = Message(args_text) if args_text else Message()
    await handle_unlock(bot, event, msg)


async def _route_altar(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.altar import handle_altar
    await handle_altar(bot, event)


async def _route_achievement(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_cultivation.achievement import handle_achievement
    await handle_achievement(bot, event)


async def _route_title(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_cultivation.achievement import handle_title
    msg = Message(args_text) if args_text else Message()
    await handle_title(bot, event, msg)


async def _route_ranking(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_cultivation.ranking import _render_ranking, handle_ranking

    text = event.get_plaintext().strip()
    ranking_key = _resolve_direct_ranking_key(text)

    if ranking_key:
        await _render_ranking(bot, event, ranking_key)
        return

    msg = Message(args_text) if args_text else Message()
    await handle_ranking(bot, event, msg)


async def _route_world_event(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_system.world_event import handle_event_status
    await handle_event_status(bot, event)


async def _route_kitchen(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_entertainment.kitchen import handle_kitchen
    await handle_kitchen(bot, event)


async def _route_appraise(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_entertainment.resonance import handle_appraise
    await handle_appraise(bot, event)


async def _route_duel(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_entertainment.duel import handle_duel
    msg = Message(args_text) if args_text else Message()
    await handle_duel(bot, event, msg)


async def _route_truth(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_entertainment.truth_dare import handle_truth
    await handle_truth(bot, event)


async def _route_dare(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_entertainment.truth_dare import handle_dare
    await handle_dare(bot, event)


async def _route_soulmate(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_entertainment.resonance import _handle_soulmate
    await _handle_soulmate(bot, event)


async def _route_waifu(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_entertainment.resonance import _handle_waifu
    await _handle_waifu(bot, event)


async def _route_menu(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_guide import _handle_menu
    await _handle_menu(bot, event)


async def _route_quit_easter_egg(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_entertainment.resonance import _handle_quit_easter_egg
    await _handle_quit_easter_egg(bot, event)


async def _route_help(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_guide import _handle_help
    await _handle_help(bot, event, args_text)


async def _route_manual(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_guide import handle_manual
    await handle_manual(bot, event)


async def _route_admin_commands(bot: Bot, event: MessageEvent, args_text: str):
    from src.plugins.tubei_guide import _handle_admin_commands
    await _handle_admin_commands(bot, event)


async def _route_private_bind(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_admin.private_bind import handle_private_bind
    msg = Message(args_text) if args_text else Message()
    await handle_private_bind(bot, event, msg)


async def _route_data_sharing(bot: Bot, event: MessageEvent, args_text: str):
    from nonebot.adapters.onebot.v11 import Message
    from src.plugins.tubei_admin.data_sharing import handle_data_sharing
    msg = Message(args_text) if args_text else Message()
    await handle_data_sharing(bot, event, msg)


ROUTE_TABLE: Dict[str, Callable[[Bot, MessageEvent, str], Awaitable[None]]] = {
    "register_guide": _route_register_guide,
    "view_commands": _route_view_commands,
    "profile": _route_profile,
    "member_list": _route_member_list,
    "meditate": _route_meditate,
    "fortune": _route_fortune,
    "expedition": _route_expedition,
    "recall": _route_recall,
    "garden": _route_garden,
    "sow": _route_sow,
    "water": _route_water,
    "harvest": _route_harvest,
    "bag": _route_bag,
    "use_item": _route_use_item,
    "smelt": _route_smelt,
    "lore": _route_lore,
    "unlock": _route_unlock,
    "altar": _route_altar,
    "achievement": _route_achievement,
    "title": _route_title,
    "ranking": _route_ranking,
    "world_event": _route_world_event,
    "kitchen": _route_kitchen,
    "appraise": _route_appraise,
    "duel": _route_duel,
    "truth": _route_truth,
    "dare": _route_dare,
    "soulmate": _route_soulmate,
    "waifu": _route_waifu,
    "menu": _route_menu,
    "quit_easter_egg": _route_quit_easter_egg,
    "help": _route_help,
    "manual": _route_manual,
    "admin_commands": _route_admin_commands,
    "private_bind": _route_private_bind,
    "data_sharing": _route_data_sharing,
}


# ==================== 分发辅助 ====================
async def _handle_danger_group_shortcuts(bot: Bot, event: MessageEvent, ctx: GroupContext, text: str) -> bool:
    """danger 群仅保留彩蛋能力。处理成功返回 True。"""
    if not isinstance(event, GroupMessageEvent):
        return False
    if ctx.group_tier != TIER_DANGER:
        return False

    if text == "今日老婆":
        await _route_to_handler(bot, event, "waifu", args_text="")
        raise FinishedException

    if text == "退出此群":
        await _route_to_handler(bot, event, "quit_easter_egg", args_text="")
        raise FinishedException

    return True


async def _handle_section_trigger(bot: Bot, event: MessageEvent, text: str) -> bool:
    """处理板块菜单触发。处理成功返回 True。"""
    if text not in SECTION_TRIGGERS:
        return False

    section_id = SECTION_TRIGGERS[text]
    from src.plugins.tubei_guide import _send_section_menu
    await _send_section_menu(bot, event, section_id)
    raise FinishedException


async def _handle_exact_trigger(bot: Bot, event: MessageEvent, ctx: GroupContext, text: str) -> bool:
    """处理精确匹配。处理成功返回 True。"""
    cmd_id = EXACT_TRIGGERS.get(text)
    if not cmd_id:
        return False
    if cmd_id in SKIP_IDS:
        return False

    cmd_def = CMD_INDEX.get(cmd_id)
    if not cmd_def:
        return False
    if not _cmd_available_in_ctx(cmd_def, ctx):
        return False

    await _route_to_handler(bot, event, cmd_id, args_text="")
    raise FinishedException


async def _handle_prefix_trigger(bot: Bot, event: MessageEvent, ctx: GroupContext, text: str) -> bool:
    """处理带参数前缀命令。处理成功返回 True。"""
    for prefix, cmd_id in PREFIX_TRIGGERS.items():
        cmd_def = CMD_INDEX.get(cmd_id)
        if not cmd_def:
            continue

        if text == prefix:
            if not _cmd_available_in_ctx(cmd_def, ctx):
                return False
            await _route_to_handler(bot, event, cmd_id, args_text="")
            raise FinishedException

        if text.startswith(prefix + " "):
            if cmd_id in SKIP_IDS:
                return False
            if not _cmd_available_in_ctx(cmd_def, ctx):
                return False

            args_text = text[len(prefix):].strip()
            await _route_to_handler(bot, event, cmd_id, args_text=args_text)
            raise FinishedException

    return False


# ==================== 分发器注册 ====================
text_dispatcher = on_message(priority=8, block=False)


@text_dispatcher.handle()
async def handle_text_dispatch(bot: Bot, event: MessageEvent):
    text = event.get_plaintext().strip()
    if not text:
        return
    if text.startswith("/") or text.startswith("／"):
        return

    ctx = await GroupContext.from_event(event)

    # 1. danger 群快捷彩蛋
    handled = await _handle_danger_group_shortcuts(bot, event, ctx, text)
    if handled:
        return

    # 2. 板块菜单
    handled = await _handle_section_trigger(bot, event, text)
    if handled:
        return

    # 3. 精确匹配
    handled = await _handle_exact_trigger(bot, event, ctx, text)
    if handled:
        return

    # 4. 前缀匹配
    handled = await _handle_prefix_trigger(bot, event, ctx, text)
    if handled:
        return

    # 没有匹配到，让 AI 等后续 matcher 处理


# ==================== 路由执行 ====================
async def _route_to_handler(bot: Bot, event: MessageEvent, cmd_id: str, args_text: str):
    try:
        route = ROUTE_TABLE.get(cmd_id)
        if not route:
            logger.debug(f"[TextDispatcher] 未实现的命令路由: {cmd_id}")
            return
        await route(bot, event, args_text)
    except Exception as e:
        if isinstance(e, FinishedException):
            return
        logger.error(f"[TextDispatcher] 路由 {cmd_id} 执行异常: {e}")
        traceback.print_exc()