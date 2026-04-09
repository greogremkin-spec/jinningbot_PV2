""" 晋宁会馆·秃贝五边形 5.0 引导系统（结构收口版）

v5.0 目标：
1. guide 成为“上下文感知导航层”
2. 菜单 / 板块展示 / 指令清单 吃 command_registry 元数据
3. 私聊中根据绑定状态给出不同导航
4. 强化 v5 重点能力引导：
   - 私聊绑定
   - 数据共享
   - 群级档案 / 群级上下文
5. 保留原有全部能力：
   - 菜单
   - 查看指令
   - 板块菜单
   - 说明
   - 关于
   - 加入引导
   - 使用手册
   - 管理员指令

本版本收口目标：
- 不删减现有功能
- 保持原有引导语义
- 让内部结构更清晰、更可维护
"""
from __future__ import annotations

import logging
from pathlib import Path

from nonebot import on_command, on_keyword
from nonebot.adapters.onebot.v11 import (
    Bot,
    MessageEvent,
    PrivateMessageEvent,
    GroupMessageEvent,
)
from nonebot.params import CommandArg
from nonebot.adapters import Message
from nonebot.plugin import PluginMetadata

from src.plugins.tubei_system.config import TUBEI_FULL_NAME
from src.common.ui_renderer import ui
from src.common.group_manager import group_manager, TIER_CORE, TIER_ALLIED, TIER_PUBLIC
from src.common.group_context import GroupContext
from src.common.command_registry import (
    COMMANDS,
    MENU_SECTIONS,
    get_commands_by_section,
    get_help_detail,
    get_section_help_keywords,
)

__plugin_meta__ = PluginMetadata(
    name="秃贝指引系统",
    description="菜单/说明/关于/加入引导",
    usage="菜单, 说明, /关于",
)

logger = logging.getLogger("tubei.guide")

TIER_PRIORITY = {
    TIER_CORE: 0,
    TIER_ALLIED: 1,
    TIER_PUBLIC: 2,
}


# ================================================================
# 基础工具
# ================================================================
def _tier_meets(current_tier: str, required_tier: str) -> bool:
    return TIER_PRIORITY.get(current_tier, 99) <= TIER_PRIORITY.get(required_tier, 99)


def _get_cmd_trigger_display(cmd: dict) -> str:
    if cmd.get("text"):
        return cmd["text"][0]
    if cmd.get("slash"):
        return f"/{cmd['slash'][0]}"
    return ""


def _ctx_header(ctx: GroupContext) -> str:
    if ctx.is_private:
        if ctx.is_bound:
            return (
                f"当前模式：私聊\n"
                f"绑定群：{ctx.group_name} ({ctx.group_id})\n"
                f"说明：私聊中的修行 / 档案 / 背包等功能将作用于该群档\n"
            )
        return (
            "当前模式：私聊\n"
            "绑定群：未绑定\n"
            "说明：未绑定时，可先使用部分轻功能；群级修行能力请先绑定群档\n"
        )

    if ctx.group_tier == TIER_CORE:
        return f"当前群：{ctx.group_name} ({ctx.group_id})\n"

    if ctx.group_tier == TIER_ALLIED:
        return (
            f"当前群：{ctx.group_name} ({ctx.group_id})\n"
            "当前环境：联盟群\n"
        )

    if ctx.group_tier == TIER_PUBLIC:
        return (
            f"当前群：{ctx.group_name} ({ctx.group_id})\n"
            "当前环境：公开群\n"
        )

    return f"当前群：{ctx.group_name} ({ctx.group_id})\n"


def _ctx_current_tier(ctx: GroupContext) -> str:
    return ctx.group_tier if ctx.group_tier != "unbound" else "public"


def _build_footer_suffix_for_private(ctx: GroupContext) -> str:
    return f"\n 当前操作群：{ctx.group_name}" if ctx.is_private and ctx.is_bound else ""


def _get_admin_flags(user_id: str) -> tuple[bool, bool]:
    from src.plugins.tubei_system.config import system_config
    is_superuser = user_id in system_config.superusers
    is_admin = user_id in system_config.tubei_admins or is_superuser
    return is_superuser, is_admin


def _cmd_visible_in_ctx(cmd: dict, ctx: GroupContext, is_admin: bool, is_superuser: bool) -> bool:
    current_tier = _ctx_current_tier(ctx)

    if not _tier_meets(current_tier, cmd.get("min_tier", "public")):
        return False
    if ctx.is_private and not cmd.get("allow_private", False):
        return False
    if cmd.get("core_only") and ctx.group_tier != "core":
        return False
    if cmd.get("admin_only") and not is_admin:
        return False
    if cmd.get("decision_only") and not is_superuser:
        return False
    return True


# ================================================================
# 推荐与菜单构建
# ================================================================
def _build_recommendation_lines(ctx: GroupContext) -> list[str]:
    lines = []

    if ctx.is_private:
        if not ctx.is_bound:
            lines.append("下一步推荐：私聊绑定")
            lines.append("先绑定一个已登记群，私聊里才能操作对应群档")
            lines.append("如果你还没建档，请先去目标群发送 /登记")
        else:
            lines.append("下一步推荐：档案 / 聚灵 / 背包")
            lines.append("你当前私聊操作的是绑定群档，可发送 私聊绑定 切换")
            lines.append("如果你在多个群都有档案，可发送 数据共享 管理共享档")
        return lines

    if ctx.group_tier == TIER_CORE:
        lines.append("下一步推荐：档案 / 聚灵 / 派遣")
        lines.append("想在私聊中继续操作当前群档，可发送 私聊绑定")
        return lines

    if ctx.group_tier == TIER_ALLIED:
        lines.append("下一步推荐：档案 / 厨房 / 真心话")
        lines.append("当前联盟群可体验部分玩法；若已建档，也可继续推进修行")
        lines.append("想在私聊中操作当前群档，可发送 私聊绑定")
        return lines

    if ctx.group_tier == TIER_PUBLIC:
        lines.append("下一步推荐：厨房 / 真心话 / 大冒险")
        lines.append("当前公开群以轻聊天和轻娱乐玩法为主")
        lines.append("若想体验更完整的群级修行玩法，可先了解支持该体系的群环境")
        return lines

    lines.append("下一步推荐：菜单 / 说明")
    lines.append("先看看当前环境下有哪些功能可用吧")
    return lines


def _build_section_card(section_id: str, ctx: GroupContext, user_id: str = "") -> str:
    is_superuser, is_admin = _get_admin_flags(user_id)

    section = MENU_SECTIONS.get(section_id)
    if not section:
        return ""

    cmds = get_commands_by_section(section_id)
    if not cmds:
        return ""

    lines = []
    has_visible = False

    for cmd in cmds:
        if not _cmd_visible_in_ctx(cmd, ctx, is_admin, is_superuser):
            continue

        has_visible = True
        display_name = cmd.get("display_name", "")
        description = cmd.get("description", "")
        trigger = _get_cmd_trigger_display(cmd)

        if cmd.get("has_args") and trigger:
            if cmd["id"] == "duel":
                trigger = f"{trigger} @某人"
            elif cmd["id"] == "private_bind":
                trigger = f"{trigger} [群号可选]"
            elif cmd["id"] == "data_sharing":
                trigger = f"{trigger} [子命令]"
            elif cmd["id"] == "help":
                trigger = f"{trigger} [功能名]"

        lines.append(f"【{display_name}】")
        lines.append(f" {description}")
        lines.append(f" 指令：{trigger}")
        lines.append("")

    if not has_visible:
        return ""

    icon = section.get("icon", "")
    title = section.get("title", section.get("name", ""))
    subtitle = section.get("subtitle", "")

    prefix = _ctx_header(ctx)
    content = prefix + "\n" + subtitle + "\n\n" + "\n".join(lines)

    footer_lines = ["输入 说明 [功能名] 查看详细规则"]
    if ctx.is_private:
        if ctx.is_bound:
            footer_lines.append("输入 私聊绑定 可切换绑定群")
        footer_lines.append("输入 数据共享 可管理多群共享档")
    else:
        footer_lines.append("想在私聊中继续操作当前群档，可发送 私聊绑定")

    return ui.render_panel(
        f"{icon} {title}",
        content,
        footer="\n".join(footer_lines),
    )


def _build_main_menu(ctx: GroupContext, user_id: str = "") -> str:
    is_superuser, is_admin = _get_admin_flags(user_id)

    lines = []
    lines.append(_ctx_header(ctx).rstrip())
    lines.append("")
    lines.append("纯文字指令可直接触发秃贝功能 | @秃贝 可闲聊")
    lines.append("")

    current_tier = _ctx_current_tier(ctx)

    for section_id, section in MENU_SECTIONS.items():
        if current_tier == "public" and not section.get("display_in_public", False):
            continue
        if section_id == "console" and not is_admin:
            continue

        icon = section.get("icon", "")
        name = section.get("name", "")
        subtitle = section.get("subtitle", "")
        text_trigger = section.get("text_trigger", "")

        lines.append(f"【{icon} {name}】")
        lines.append(f" {subtitle}")
        lines.append(f" 指令：{text_trigger}")
        lines.append("")

    lines.append("【✨常用入口】")
    if ctx.is_private:
        if ctx.is_bound:
            lines.append(" 私聊绑定：切换当前私聊操作群")
            lines.append(" 数据共享：管理自己的多群共享档")
            lines.append(" 使用手册：获取完整玩法说明")
            lines.append(" 说明 私聊绑定 / 说明 数据共享：查看关键规则")
        else:
            lines.append(" 私聊绑定：先绑定一个可操作的群档")
            lines.append(" 使用手册：获取完整玩法说明")
            lines.append(" 说明 私聊绑定：查看如何绑定群档")
    else:
        lines.append(" 使用手册：获取完整玩法说明")
        lines.append(" 私聊绑定：在私聊中切换操作群")
        lines.append(" 数据共享：管理自己的多群档")
        lines.append(" 说明 真心话 / 说明 大冒险：查看题库层级说明")

    lines.append("")
    recommendation_lines = _build_recommendation_lines(ctx)
    if recommendation_lines:
        lines.append("【✨下一步推荐】")
        for line in recommendation_lines:
            lines.append(f" {line}")
        lines.append("")

    footer_lines = [
        "输入 查看指令 查看所有可用指令",
        "输入 [板块名] 查看详细菜单",
        "输入 说明 [功能名] 查看规则",
        "输入 使用手册 获取完整帮助",
    ]
    if ctx.is_private:
        footer_lines.append("输入 私聊绑定 | 数据共享")

    return ui.render_panel(
        TUBEI_FULL_NAME,
        "\n".join(lines),
        footer="\n".join(footer_lines),
    )


# ================================================================
# 指令列表 / 帮助
# ================================================================
def _build_view_commands_content(ctx: GroupContext, user_id: str) -> str:
    is_superuser, is_admin = _get_admin_flags(user_id)

    lines = []
    lines.append(_ctx_header(ctx).rstrip())
    lines.append("")

    current_tier = _ctx_current_tier(ctx)

    for sec_id, sec_info in MENU_SECTIONS.items():
        if sec_id == "_guide":
            continue
        if sec_id == "console" and not is_admin:
            continue
        if current_tier == "public" and not sec_info.get("display_in_public", False):
            continue

        cmd_lines = []
        for cmd in COMMANDS:
            if cmd.get("section") != sec_id:
                continue
            if cmd.get("hidden"):
                continue
            if not _cmd_visible_in_ctx(cmd, ctx, is_admin, is_superuser):
                continue

            display_name = cmd.get("display_name", "")
            slash_list = cmd.get("slash", [])
            text_list = cmd.get("text", [])

            text_triggers = []
            slash_triggers = []

            for t in text_list:
                if t not in text_triggers:
                    text_triggers.append(t)
            for s in slash_list:
                slash_display = f"/{s}"
                if slash_display not in slash_triggers:
                    slash_triggers.append(slash_display)

            if not text_triggers and not slash_triggers:
                continue

            cmd_lines.append(f"【{display_name}】")
            if text_triggers:
                for i in range(0, len(text_triggers), 3):
                    chunk = text_triggers[i:i + 3]
                    line = " | ".join(chunk)
                    if i == 0:
                        cmd_lines.append(f" 纯文字：{line}")
                    else:
                        cmd_lines.append(f" {line}")

            if slash_triggers:
                for i in range(0, len(slash_triggers), 3):
                    chunk = slash_triggers[i:i + 3]
                    line = " | ".join(chunk)
                    if i == 0:
                        cmd_lines.append(f" 斜杠：{line}")
                    else:
                        cmd_lines.append(f" {line}")

        if cmd_lines:
            icon = sec_info.get("icon", "▪")
            name = sec_info.get("name", "")
            lines.append(f"{'━' * 15}")
            lines.append(f"{icon}【{name}】")
            lines.append("")
            lines.extend(cmd_lines)
            lines.append("")

    if len(lines) <= 2:
        return ""

    lines.append("━" * 15)
    lines.append("纯文字直接发送即可触发")
    lines.append("斜杠指令需带 / 前缀")
    lines.append("说明 [功能名] 查看规则")
    lines.append("使用手册 获取完整帮助")
    if ctx.is_private:
        if ctx.is_bound:
            lines.append("私聊绑定 / 数据共享")
        else:
            lines.append("先发送 私聊绑定")

    return "\n".join(lines)


async def _handle_help(bot: Bot, event: MessageEvent, key: str = ""):
    if not key:
        ctx = await GroupContext.from_event(event)
        keywords = get_section_help_keywords()
        available = "、".join(keywords)

        extra_lines = ["你可以发送：说明 [功能名]", ""]

        if ctx.is_private and not ctx.is_bound:
            extra_lines.extend([
                "推荐优先查看：",
                "• 说明 私聊绑定",
                "• 说明 真心话",
                "• 说明 大冒险",
            ])
        elif ctx.group_tier == TIER_CORE:
            extra_lines.extend([
                "推荐优先查看：",
                "• 说明 聚灵",
                "• 说明 派遣",
                "• 说明 数据共享",
            ])
        elif ctx.group_tier == TIER_ALLIED:
            extra_lines.extend([
                "推荐优先查看：",
                "• 说明 私聊绑定",
                "• 说明 真心话",
                "• 说明 大冒险",
            ])
        else:
            extra_lines.extend([
                "推荐优先查看：",
                "• 说明 真心话",
                "• 说明 大冒险",
                "• 说明 私聊绑定",
            ])

        extra_lines.extend(["", f"可查询：{available}"])
        await bot.send(event, ui.render_panel("功能说明", "\n".join(extra_lines)))
        return

    content = get_help_detail(key)
    if not content:
        await bot.send(event, ui.info(f"未找到「{key}」的说明。"))
        return

    await bot.send(event, ui.render_panel(f"功能说明 · {key}", content))


# ================================================================
# 管理员指令页
# ================================================================
async def _handle_admin_commands(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    is_superuser, is_admin = _get_admin_flags(uid)

    if not is_admin:
        await bot.send(event, ui.info("此指令仅限管理组/决策组使用。"))
        return

    lines = []

    admin_cmds = []
    for cmd in COMMANDS:
        if not cmd.get("admin_only"):
            continue
        display_name = cmd.get("display_name", "")
        slash_list = cmd.get("slash", [])
        trigger_str = " | ".join([f"/{s}" for s in slash_list])
        desc = cmd.get("description", "")
        admin_cmds.append(f" {display_name}\n → {trigger_str}\n {desc}")

    if admin_cmds:
        lines.append("【行政管理指令】(管理组+)")
        lines.append("─" * 18)
        lines.extend(admin_cmds)
        lines.append("")

    console_cmds = []
    for cmd in COMMANDS:
        if cmd.get("section") != "console":
            continue
        if cmd.get("decision_only") and not is_superuser:
            continue

        display_name = cmd.get("display_name", "")
        slash_list = cmd.get("slash", [])
        desc = cmd.get("description", "")
        trigger_str = " | ".join([f"/{s}" for s in slash_list])
        console_cmds.append(f" {display_name}\n → {trigger_str}\n {desc}")

    if console_cmds:
        lines.append("⚙【控制台指令】(决策组专用)")
        lines.append("─" * 18)
        lines.extend(console_cmds)
        lines.append("")

    if not lines:
        await bot.send(event, ui.info("没有可用的管理指令。"))
        return

    content = "\n".join(lines)
    card = ui.render_panel(
        "⚙管理员指令清单",
        content,
        footer="所有管理指令仅支持 /斜杠 触发",
    )
    await bot.send(event, card)


# ================================================================
# 对外核心函数
# ================================================================
async def _handle_menu(bot: Bot, event: MessageEvent):
    ctx = await GroupContext.from_event(event)
    menu = _build_main_menu(ctx, user_id=str(event.user_id))
    await bot.send(event, menu)


async def _send_section_menu(bot: Bot, event: MessageEvent, section_id: str):
    ctx = await GroupContext.from_event(event)
    card = _build_section_card(section_id, ctx, user_id=str(event.user_id))
    if card:
        await bot.send(event, card)
    else:
        await bot.send(event, ui.info("该板块在当前上下文不可用~"))


async def _handle_view_commands(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)
    content = _build_view_commands_content(ctx, uid)

    if not content:
        await bot.send(event, ui.info("当前上下文没有可用的指令~"))
        return

    if len(content) > 1500:
        parts = content.split("━" * 15)
        for part in parts:
            part = part.strip()
            if part:
                await bot.send(event, part)
    else:
        await bot.send(event, f"✦ {TUBEI_FULL_NAME} · 全指令清单\n{content}")


# ================================================================
# about / join / manual
# ================================================================
async def _handle_about(bot: Bot, event: MessageEvent):
    ctx = await GroupContext.from_event(event)
    about_text = group_manager.get_about_text_by_tier(ctx.group_tier)

    if ctx.group_tier == TIER_CORE:
        footer = "想加入？私聊秃贝发送「加入会馆」"
    elif ctx.group_tier == TIER_ALLIED:
        footer = "想进一步了解秃贝的来源设定，可私聊秃贝继续问问"
    else:
        footer = "想了解更多？可私聊秃贝继续聊聊"

    await bot.send(
        event,
        ui.render_panel("关于秃贝 / 关于当前环境", about_text, footer=footer),
    )


async def _handle_join(bot: Bot, event: MessageEvent):
    ctx = await GroupContext.from_event(event)

    if isinstance(event, PrivateMessageEvent):
        join_text = group_manager.get_join_text_by_tier(
            ctx.group_tier if ctx.is_bound else "unbound"
        )
        await join_cmd.finish(
            ui.render_panel(
                "加入 / 进一步了解",
                join_text,
                footer="想体验完整功能时，记得先建档或绑定群档~",
            )
        )

    if ctx.group_tier == TIER_CORE:
        content = (
            "想了解晋宁会馆？\n\n"
            "私聊秃贝发送「加入会馆」\n"
            "即可获取详细信息~\n\n"
            "或者发送 /关于 了解更多"
        )
        title = "关于加入晋宁会馆"
        footer = None

    elif ctx.group_tier == TIER_ALLIED:
        content = (
            "你当前所在的是联盟群环境。\n\n"
            "如果你是想了解更完整的晋宁体系，"
            "可以私聊秃贝发送「加入会馆」进一步查看。\n\n"
            "如果你只是想体验当前群现有玩法，"
            "也可以直接先使用 菜单 / 说明。"
        )
        title = "关于进一步了解"
        footer = "先看看当前群可用功能也不错~"

    else:
        content = (
            "如果你想体验更完整的群级修行玩法，\n"
            "可以私聊秃贝发送「加入会馆」获取进一步说明。\n\n"
            "当前群更适合先体验聊天与轻娱乐功能。"
        )
        title = "关于更多玩法"
        footer = "发送 菜单 查看当前群可用功能"

    await join_cmd.finish(
        ui.render_panel(
            title,
            content,
            footer=footer,
        )
    )


async def _handle_manual(bot: Bot, event: MessageEvent):
    local_path = Path("data/使用手册.txt")
    container_path = "file:///app/napcat/使用手册.txt"

    if not local_path.exists():
        await manual_cmd.finish(ui.error("使用手册文件不存在，请联系管理员。"))

    try:
        if isinstance(event, GroupMessageEvent):
            await bot.call_api(
                "upload_group_file",
                group_id=event.group_id,
                file=container_path,
                name="晋宁会馆·秃贝使用手册.txt",
            )
        else:
            await bot.call_api(
                "upload_private_file",
                user_id=event.user_id,
                file=container_path,
                name="晋宁会馆·秃贝使用手册.txt",
            )
    except Exception as e:
        logger.error(f"[Manual] 文件发送失败: {e}")
        await manual_cmd.finish(
            ui.info(
                "文件发送失败。\n\n"
                "请联系析沐大人获取使用手册~"
            )
        )


# ================================================================
# 指令注册
# ================================================================
menu_cmd = on_command("菜单", priority=10, block=True)
view_commands_cmd = on_command("指令", aliases={"查看指令", "所有指令"}, priority=10, block=True)
manual_cmd = on_command("使用手册", aliases={"用户手册", "用户使用手册", "新手指南"}, priority=10, block=True)
admin_commands_cmd = on_command("管理员指令", aliases={"管理指令"}, priority=10, block=True)

section_cmds = {}
for sid, sinfo in MENU_SECTIONS.items():
    slash_trigger = sinfo.get("slash_trigger", "")
    if slash_trigger:
        aliases = {slash_trigger}
        if "板块" in slash_trigger:
            aliases.add(slash_trigger.replace("板块", "版块"))
        section_cmds[sid] = on_command(slash_trigger, aliases=aliases, priority=10, block=True)

help_cmd = on_command("说明", aliases={"规则", "怎么玩"}, priority=10, block=True)
about_cmd = on_command("关于", priority=10, block=True)
join_cmd = on_keyword({"加入会馆", "加入晋宁", "加入晋宁会馆", "怎么加入"}, priority=10, block=True)


# ================================================================
# Handler
# ================================================================
@menu_cmd.handle()
async def handle_menu(bot: Bot, event: MessageEvent):
    await _handle_menu(bot, event)
    await menu_cmd.finish()


@view_commands_cmd.handle()
async def handle_view_commands(bot: Bot, event: MessageEvent):
    await _handle_view_commands(bot, event)
    await view_commands_cmd.finish()


@admin_commands_cmd.handle()
async def handle_admin_commands(bot: Bot, event: MessageEvent):
    await _handle_admin_commands(bot, event)
    await admin_commands_cmd.finish()


for _sid, _cmd in section_cmds.items():
    def _make_handler(section_id):
        async def _handler(bot: Bot, event: MessageEvent):
            await _send_section_menu(bot, event, section_id)
        return _handler

    _cmd.handle()(_make_handler(_sid))


@help_cmd.handle()
async def handle_help(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    key = args.extract_plain_text().strip()
    await _handle_help(bot, event, key)
    await help_cmd.finish()


@about_cmd.handle()
async def handle_about(bot: Bot, event: MessageEvent):
    await _handle_about(bot, event)
    await about_cmd.finish()


@join_cmd.handle()
async def handle_join(bot: Bot, event: MessageEvent):
    await _handle_join(bot, event)


@manual_cmd.handle()
async def handle_manual(bot: Bot, event: MessageEvent):
    await _handle_manual(bot, event)