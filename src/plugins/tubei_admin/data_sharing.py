"""
晋宁会馆·秃贝五边形 5.0
多群数据共享系统

职责：
1. 查看当前用户的群档概况
2. 将一个群档设为主档，另一个群档改为指针共享档
3. 取消共享时，把当前主档复制为独立档

设计说明：
- 共享是“用户自己的多群数据合并”
- 当前实现采用二段确认，使用内存确认缓存
- 确认口令：
  - 确认共享
  - 确认取消共享
- 为减少误操作，只有本人可触发自己的共享行为
"""

from __future__ import annotations

import time
from typing import Dict, Any

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.params import CommandArg
from nonebot.adapters import Message

from src.common.data_manager import data_manager
from src.common.group_manager import group_manager
from src.common.ui_renderer import ui

sharing_cmd = on_command(
    "数据共享",
    aliases={"共享档案", "共享存档"},
    priority=5,
    block=True,
)

sharing_confirm_listener = on_message(priority=6, block=False)

# 简易确认缓存：{uid: {...}}
# 说明：
# - 当前先用进程内缓存做确认流程，简单稳妥
# - 后续如需跨重启确认，可迁移到 bot_status 或 group_status
PENDING_SHARING_ACTIONS: Dict[str, Dict[str, Any]] = {}
PENDING_EXPIRE_SECONDS = 300


def _cleanup_pending():
    now = time.time()
    expired = [
        uid for uid, data in PENDING_SHARING_ACTIONS.items()
        if now - data.get("created_at", 0) > PENDING_EXPIRE_SECONDS
    ]
    for uid in expired:
        del PENDING_SHARING_ACTIONS[uid]


async def _collect_user_group_profiles(uid: str) -> list[dict]:
    """收集用户各群档信息。"""
    member = await data_manager.get_member_info(uid)
    if not member:
        return []

    groups = await data_manager.get_registered_groups(uid)
    result = []

    for gid in groups:
        spirit = await data_manager.get_spirit_data(uid, gid)
        raw_spirit = data_manager.spirits_raw.get(uid, {})
        group_data = raw_spirit.get("group_data", {}) if isinstance(raw_spirit, dict) else {}
        raw_profile = group_data.get(str(gid), {})

        profile_type = raw_profile.get("_type", "full")
        master_group = raw_profile.get("_master_group") if profile_type == "pointer" else None

        result.append({
            "group_id": gid,
            "group_name": group_manager.get_group_name(gid),
            "tier": group_manager.get_group_tier(gid),
            "sp": spirit.get("sp", 0),
            "level": spirit.get("level", 1),
            "type": profile_type,
            "master_group": int(master_group) if master_group else None,
        })

    result.sort(key=lambda x: x["group_id"])
    return result


async def _build_sharing_overview(uid: str) -> str:
    profiles = await _collect_user_group_profiles(uid)
    if not profiles:
        return ui.render_panel(
            "数据共享",
            "你当前还没有可共享的群档。\n\n"
            "请先在至少一个群中建立档案。",
            footer="建立档案后再回来吧",
        )

    lines = []
    lines.append("你当前拥有以下群档：")
    lines.append("")

    for idx, p in enumerate(profiles, start=1):
        share_note = ""
        if p["type"] == "pointer":
            share_note = f" [共享档 → {p['master_group']}]"
        else:
            share_note = " [独立档]"

        lines.append(
            f"{idx}. {p['group_name']} ({p['group_id']})\n"
            f"   Lv.{p['level']} | {p['sp']} 灵力 | {p['tier']}{share_note}"
        )

    lines.append("")
    lines.append("设置共享：/数据共享 设置 [主档群号] [副档群号]")
    lines.append("取消共享：/数据共享 取消 [副档群号]")
    lines.append("")
    lines.append("⚠副档共享后，其原有数据将被主档覆盖。")

    return ui.render_panel(
        "数据共享",
        "\n".join(lines),
        footer="共享后，多个群将共用同一份修行数据",
    )


@sharing_cmd.handle()
async def handle_data_sharing(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    _cleanup_pending()

    uid = str(event.user_id)
    arg_text = args.extract_plain_text().strip()
    parts = arg_text.split()

    # 无参数：展示概况
    if not parts:
        card = await _build_sharing_overview(uid)
        await sharing_cmd.finish(card)

    sub = parts[0]

    # ========== 设置共享 ==========
    if sub == "设置":
        if len(parts) != 3:
            await sharing_cmd.finish(
                ui.error(
                    "用法错误。\n"
                    "格式：/数据共享 设置 [主档群号] [副档群号]"
                )
            )

        master_str, slave_str = parts[1], parts[2]
        if not (master_str.isdigit() and slave_str.isdigit()):
            await sharing_cmd.finish(ui.error("群号必须是纯数字。"))

        master_gid = int(master_str)
        slave_gid = int(slave_str)

        if master_gid == slave_gid:
            await sharing_cmd.finish(ui.error("主档群和副档群不能相同。"))

        profiles = await _collect_user_group_profiles(uid)
        available_groups = {p["group_id"] for p in profiles}

        if master_gid not in available_groups or slave_gid not in available_groups:
            await sharing_cmd.finish(
                ui.error("你只能对自己已登记的群档进行共享操作。")
            )

        # 主档必须是 full，不能拿 pointer 当主档
        spirit_raw = data_manager.spirits_raw.get(uid, {})
        group_data = spirit_raw.get("group_data", {}) if isinstance(spirit_raw, dict) else {}

        master_raw = group_data.get(str(master_gid), {})
        slave_raw = group_data.get(str(slave_gid), {})

        if master_raw.get("_type") == "pointer":
            await sharing_cmd.finish(
                ui.error("主档群当前本身就是共享指针档，不能继续作为主档。")
            )

        slave_spirit = await data_manager.get_spirit_data(uid, slave_gid)
        master_spirit = await data_manager.get_spirit_data(uid, master_gid)

        PENDING_SHARING_ACTIONS[uid] = {
            "type": "create",
            "master_group": master_gid,
            "slave_group": slave_gid,
            "created_at": time.time(),
        }

        card = ui.render_panel(
            "数据共享 · 二次确认",
            f"⚠确认操作：\n\n"
            f"主档：{group_manager.get_group_name(master_gid)} ({master_gid})\n"
            f"Lv.{master_spirit.get('level', 1)} | {master_spirit.get('sp', 0)} 灵力\n\n"
            f"副档：{group_manager.get_group_name(slave_gid)} ({slave_gid})\n"
            f"Lv.{slave_spirit.get('level', 1)} | {slave_spirit.get('sp', 0)} 灵力\n\n"
            f"副档中的现有数据将被主档覆盖！\n"
            f"此操作不可逆！",
            footer="发送「确认共享」继续，5 分钟内有效",
        )
        await sharing_cmd.finish(card)

    # ========== 取消共享 ==========
    if sub == "取消":
        if len(parts) != 2:
            await sharing_cmd.finish(
                ui.error(
                    "用法错误。\n"
                    "格式：/数据共享 取消 [副档群号]"
                )
            )

        gid_str = parts[1]
        if not gid_str.isdigit():
            await sharing_cmd.finish(ui.error("群号必须是纯数字。"))

        target_gid = int(gid_str)

        spirit_raw = data_manager.spirits_raw.get(uid, {})
        group_data = spirit_raw.get("group_data", {}) if isinstance(spirit_raw, dict) else {}
        target_raw = group_data.get(str(target_gid), {})

        if target_raw.get("_type") != "pointer":
            await sharing_cmd.finish(
                ui.info("该群档当前不是共享指针档，无需取消共享。")
            )

        master_gid = int(target_raw.get("_master_group", 0))
        master_spirit = await data_manager.get_spirit_data(uid, master_gid)

        PENDING_SHARING_ACTIONS[uid] = {
            "type": "remove",
            "target_group": target_gid,
            "master_group": master_gid,
            "created_at": time.time(),
        }

        card = ui.render_panel(
            "数据共享取消 · 二次确认",
            f"你即将取消群档共享：\n\n"
            f"当前副档：{group_manager.get_group_name(target_gid)} ({target_gid})\n"
            f"当前主档：{group_manager.get_group_name(master_gid)} ({master_gid})\n\n"
            f"取消后，将从主档复制一份当前数据，\n"
            f"使【{target_gid}】重新变为独立档。\n\n"
            f"复制基准：Lv.{master_spirit.get('level', 1)} | {master_spirit.get('sp', 0)} 灵力",
            footer="发送「确认取消共享」继续，5 分钟内有效",
        )
        await sharing_cmd.finish(card)

    await sharing_cmd.finish(
        ui.info(
            "未知子命令。\n\n"
            "查看概况：/数据共享\n"
            "设置共享：/数据共享 设置 [主档群号] [副档群号]\n"
            "取消共享：/数据共享 取消 [副档群号]"
        )
    )


@sharing_confirm_listener.handle()
async def handle_sharing_confirm(bot: Bot, event: MessageEvent):
    _cleanup_pending()

    uid = str(event.user_id)
    text = event.get_plaintext().strip()

    pending = PENDING_SHARING_ACTIONS.get(uid)
    if not pending:
        return

    # 避免与斜杠命令冲突
    if text.startswith("/") or text.startswith("／"):
        return

    # 创建共享确认
    if pending["type"] == "create" and text == "确认共享":
        ok = await data_manager.create_sharing(
            uid,
            master_group=int(pending["master_group"]),
            slave_group=int(pending["slave_group"]),
        )
        del PENDING_SHARING_ACTIONS[uid]

        if not ok:
            await bot.send(event, ui.error("创建共享失败，请检查主档是否有效。"))
            return

        await bot.send(
            event,
            ui.render_result_card(
                "数据共享",
                "✅共享创建成功！",
                stats=[
                    (" 主档", f"{group_manager.get_group_name(int(pending['master_group']))} ({pending['master_group']})"),
                    (" 副档", f"{group_manager.get_group_name(int(pending['slave_group']))} ({pending['slave_group']})"),
                ],
                footer="现在两个群将共享同一份修行数据",
            )
        )
        return

    # 取消共享确认
    if pending["type"] == "remove" and text == "确认取消共享":
        ok = await data_manager.remove_sharing(
            uid,
            int(pending["target_group"]),
        )
        del PENDING_SHARING_ACTIONS[uid]

        if not ok:
            await bot.send(event, ui.error("取消共享失败，请稍后再试。"))
            return

        await bot.send(
            event,
            ui.render_result_card(
                "数据共享",
                "✅共享已取消！",
                stats=[
                    (" 独立恢复群", f"{group_manager.get_group_name(int(pending['target_group']))} ({pending['target_group']})"),
                    (" 数据来源", f"{group_manager.get_group_name(int(pending['master_group']))} ({pending['master_group']})"),
                ],
                footer="该群档现在重新拥有独立数据",
            )
        )
        return