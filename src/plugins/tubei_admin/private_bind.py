"""
晋宁会馆·秃贝五边形 5.0
私聊绑定系统

职责：
1. 支持用户在私聊中查看当前绑定群
2. 支持切换私聊绑定群
3. 私聊中的游戏功能通过绑定群确定数据归属
4. 群聊中也允许查看当前绑定状态，便于引导

指令：
- /私聊绑定
- /私聊绑定 [群号]
- 纯文字通过后续 text_dispatcher 适配
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, PrivateMessageEvent, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters import Message

from src.common.data_manager import data_manager
from src.common.group_context import GroupContext
from src.common.group_manager import group_manager
from src.common.ui_renderer import ui

private_bind_cmd = on_command(
    "私聊绑定",
    aliases={"绑定群档", "绑定群聊", "切换绑定群"},
    priority=5,
    block=True,
)


async def _build_bind_overview(uid: str) -> str:
    """构建当前用户可绑定群列表。"""
    member = await data_manager.get_member_info(uid)
    if not member:
        return ui.render_panel(
            "私聊绑定",
            "你当前还没有建立任何灵力档案。\n\n"
            "请先在目标群内发送 /登记 建立档案，\n"
            "之后即可在私聊中绑定并操作该群数据。",
            footer="建立档案后再来绑定吧",
        )

    registered_groups = await data_manager.get_registered_groups(uid)
    current_bind = await data_manager.get_private_bind_group(uid)

    # 兼容旧数据：registered_groups 为空时尝试回退
    if not registered_groups:
        maybe_gid = (
            member.get("primary_group")
            or member.get("register_group")
            or 0
        )
        if maybe_gid:
            registered_groups = [int(maybe_gid)]

    if not registered_groups:
        return ui.render_panel(
            "私聊绑定",
            "你的档案存在，但还没有可绑定的群数据。\n\n"
            "请先在一个群内完成登记或等待迁移修复。",
            footer="如有疑问请联系管理员",
        )

    lines = []

    if current_bind:
        lines.append(f"当前绑定：{group_manager.get_group_name(current_bind)} ({current_bind})")
    else:
        lines.append("当前绑定：未绑定")

    lines.append("")
    lines.append("你已登记的群：")
    lines.append("")

    for idx, gid in enumerate(registered_groups, start=1):
        marker = " ← 当前绑定" if gid == current_bind else ""
        lines.append(f"{idx}. {group_manager.get_group_name(gid)} ({gid}){marker}")

    lines.append("")
    lines.append("发送 /私聊绑定 [群号] 切换绑定")
    lines.append("例如：/私聊绑定 564234162")

    return ui.render_panel(
        "私聊绑定",
        "\n".join(lines),
        footer="绑定后，私聊中的修行/厨房/背包等功能将作用于该群档",
    )


@private_bind_cmd.handle()
async def handle_private_bind(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    uid = str(event.user_id)
    arg_text = args.extract_plain_text().strip()

    # 无参数：展示当前绑定状态与可绑定群列表
    if not arg_text:
        card = await _build_bind_overview(uid)
        await private_bind_cmd.finish(card)

    # 必须是纯数字群号
    if not arg_text.isdigit():
        await private_bind_cmd.finish(
            ui.error(
                "请输入正确的群号。\n"
                "用法：/私聊绑定 [群号]\n"
                "先发送 /私聊绑定 查看可绑定群列表"
            )
        )

    target_gid = int(arg_text)

    member = await data_manager.get_member_info(uid)
    if not member:
        await private_bind_cmd.finish(
            ui.info(
                "你当前还没有建立灵力档案。\n"
                "请先在目标群内发送 /登记"
            )
        )

    registered_groups = await data_manager.get_registered_groups(uid)
    if not registered_groups:
        maybe_gid = member.get("primary_group") or member.get("register_group") or 0
        if maybe_gid:
            registered_groups = [int(maybe_gid)]

    if target_gid not in registered_groups:
        await private_bind_cmd.finish(
            ui.render_panel(
                "私聊绑定",
                f"你尚未在群 {target_gid} 建立可绑定档案。\n\n"
                "只能绑定到自己已登记的群。",
                footer="发送 /私聊绑定 查看可绑定群列表",
            )
        )

    await data_manager.set_private_bind_group(uid, target_gid)

    card = ui.render_result_card(
        "私聊绑定",
        f"✅已将你的私聊绑定到【{group_manager.get_group_name(target_gid)}】",
        stats=[
            (" 绑定群", f"{group_manager.get_group_name(target_gid)}"),
            (" 群号", str(target_gid)),
            (" 群等级", group_manager.get_group_tier(target_gid)),
        ],
        footer="现在你可以在私聊中使用该群的修行功能",
    )
    await private_bind_cmd.finish(card)