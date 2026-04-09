""" 晋宁会馆·秃贝五边形 5.0 名录管理（收尾定稿版）
管理组专属指令：
- 查看名单
- 修改数值
- 发放物品
- 冻结档案
- 解冻档案
- 删除档案（单群独立档案）
v5.0 收尾定稿目标：
1. 查看名单严格按当前群展示
2. 修改 / 发放默认作用于当前群档
3. 支持显式指定群号
4. 管理反馈更准确地表达“当前群档 / 指定群档”语义
5. 保留原有管理能力，不减少功能
6. 档案治理命令改为：
- 冻结档案（用户级全档案冻结）
- 解冻档案（用户级全档案解冻）
- 删除档案（删除单个独立群档，必须指定群号）
"""
from __future__ import annotations

import time
import ujson as json
from pathlib import Path
from typing import Any, Dict

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters import Message

from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.common.group_manager import group_manager
from src.plugins.tubei_system.recorder import recorder


list_cmd = on_command("查看名单", aliases={"名单", "在馆名单"}, priority=5, block=True)
modify_cmd = on_command("修改", aliases={"改数值"}, priority=5, block=True)
give_cmd = on_command("发放", aliases={"发东西"}, priority=5, block=True)

freeze_cmd = on_command("冻结档案", priority=5, block=True)
unfreeze_cmd = on_command("解冻档案", priority=5, block=True)
delete_archive_cmd = on_command("删除档案", priority=5, block=True)


# ==================== 备份工具 ====================

GROUP_ARCHIVE_BACKUP_DIR = Path("data/backups/group_archive_delete")
GROUP_ARCHIVE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)


async def _backup_group_archive_snapshot(uid: str, group_id: int) -> Path:
    """删除单群档前，为该群档生成审计快照。"""
    member = await data_manager.get_member_info(uid)
    spirit_raw = data_manager.spirits_raw.get(uid, {})

    gid = int(group_id)
    gid_str = str(gid)

    member_group_profile = {}
    registered_groups_before = []
    primary_group_before = 0
    private_bind_group_before = 0

    if isinstance(member, dict):
        member_group_profile = deepcopy_safe(
            member.get("group_profiles", {}).get(gid_str, {})
        )
        registered_groups_before = list(member.get("registered_groups", []))
        primary_group_before = int(member.get("primary_group", 0) or 0)
        private_bind_group_before = int(member.get("private_bind_group", 0) or 0)

    spirit_group_data = {}
    if isinstance(spirit_raw, dict):
        spirit_group_data = deepcopy_safe(
            spirit_raw.get("group_data", {}).get(gid_str, {})
        )

    payload = {
        "ts": int(time.time()),
        "target_uid": str(uid),
        "group_id": gid,
        "member_group_profile": member_group_profile,
        "registered_groups_before": registered_groups_before,
        "primary_group_before": primary_group_before,
        "private_bind_group_before": private_bind_group_before,
        "spirit_group_data": spirit_group_data,
    }

    file_name = f"group_delete_{time.strftime('%Y%m%d_%H%M%S')}_{uid}_{gid}.json"
    path = GROUP_ARCHIVE_BACKUP_DIR / file_name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return path


def deepcopy_safe(obj: Any) -> Any:
    """尽量轻量地复制结构化对象，避免直接引用原内存。"""
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False))
    except Exception:
        if isinstance(obj, dict):
            return dict(obj)
        if isinstance(obj, list):
            return list(obj)
        return obj


# ==================== 通用校验工具 ====================

async def _ensure_member_active_and_registered(uid: str, target_gid: int) -> tuple[bool, str]:
    """用于 /修改 与 /发放 的前置校验。"""
    member = await data_manager.get_member_info(uid)
    if not member:
        return False, "查无此人。"

    status = member.get("global_profile", {}).get("status", "active")
    if status == "deleted":
        return False, "该用户档案当前已被冻结，请先解冻档案。"

    registered = await data_manager.is_registered_in_group(uid, target_gid)
    if not registered:
        return False, f"该用户尚未在群 {target_gid} 建立档案，不能直接操作。"

    return True, ""


# ==================== 查看名单 ====================

@list_cmd.handle()
async def handle_list(bot: Bot, event: GroupMessageEvent):
    ctx = await GroupContext.from_event(event)
    perm = await check_permission(
        event,
        "灵册大厅 · 在馆名单",
        admin_only=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await list_cmd.finish(perm.deny_message)

    await list_cmd.send(ui.info("正在调取名单..."))

    members = await data_manager.get_group_members(ctx.group_id)
    if not members:
        await list_cmd.finish(ui.info("当前群名单为空。"))

    core_lines = []
    outer_lines = []
    idx = 0

    sorted_members = sorted(
        members.values(),
        key=lambda x: (
            x.get("group_profiles", {}).get(str(ctx.group_id), {}).get("register_time", 0),
            x.get("global_profile", {}).get("register_time", 0),
        ),
    )

    for m in sorted_members:
        status = m.get("global_profile", {}).get("status", "active")
        if status == "deleted":
            continue

        uid = m["qq"]
        spirit = await data_manager.get_spirit_data(uid, ctx.group_id)
        group_profile = await data_manager.get_member_group_profile(uid, ctx.group_id)

        idx += 1
        spirit_name = (
            (group_profile or {}).get("spirit_name") or m.get("spirit_name") or uid
        )
        identity = (
            (group_profile or {}).get("identity") or m.get("global_identity", "guest")
        )

        line = (
            f"{idx}. {spirit_name} ({uid}) | "
            f"Lv.{spirit.get('level', 1)} | {spirit.get('sp', 0)}灵力"
        )

        if identity in ("core_member", "admin", "decision"):
            core_lines.append(line)
        else:
            outer_lines.append(line)

    msg_parts = []
    if core_lines:
        msg_parts.append("馆内成员：\n" + "\n".join(core_lines))
    if outer_lines:
        msg_parts.append("馆外成员：\n" + "\n".join(outer_lines))

    full_msg = "\n\n".join(msg_parts) if msg_parts else "名单为空。"

    if len(full_msg) > 1500:
        parts = [full_msg[i:i + 1500] for i in range(0, len(full_msg), 1500)]
        for part in parts:
            await list_cmd.send(part)
        await list_cmd.finish()
    else:
        await list_cmd.finish(
            ui.render_panel(
                f"在馆人员名单 · {ctx.group_name}",
                full_msg,
            )
        )


# ==================== 修改数值 ====================

@modify_cmd.handle()
async def handle_modify(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    ctx = await GroupContext.from_event(event)
    perm = await check_permission(
        event,
        "管理指令 · 数值修改",
        admin_only=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await modify_cmd.finish(perm.deny_message)

    params = args.extract_plain_text().strip().split()
    if len(params) not in (3, 4):
        await modify_cmd.finish(ui.error("用法：/修改 [QQ] [灵力/等级] [数值] [群号可选]"))

    uid, key, val = params[0], params[1], params[2]
    target_gid = ctx.group_id

    if len(params) == 4:
        if not params[3].isdigit():
            await modify_cmd.finish(ui.error("群号必须是纯数字。"))
        target_gid = int(params[3])

    key_map = {
        "灵力": "sp",
        "等级": "level",
        "sp": "sp",
        "level": "level",
    }
    if key not in key_map:
        await modify_cmd.finish(ui.error("仅支持修改：灵力、等级。"))

    try:
        val = int(val)
    except ValueError:
        await modify_cmd.finish(ui.error("数值必须是整数。"))

    ok, deny = await _ensure_member_active_and_registered(uid, target_gid)
    if not ok:
        await modify_cmd.finish(ui.error(deny))

    real_key = key_map[key]
    await data_manager.update_spirit_data(uid, target_gid, {real_key: val})
    await recorder.add_event(
        "admin_action",
        int(event.user_id),
        {
            "action": "modify",
            "target": uid,
            "key": real_key,
            "value": val,
            "group_id": target_gid,
        },
    )

    target_group_name = group_manager.get_group_name(target_gid)
    await modify_cmd.finish(
        ui.success(f"{uid} 在【{target_group_name}】({target_gid}) 的 {key} 已变更为 {val}。")
    )


# ==================== 发放物品 ====================

@give_cmd.handle()
async def handle_give(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    ctx = await GroupContext.from_event(event)
    perm = await check_permission(
        event,
        "管理指令 · 物品发放",
        admin_only=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await give_cmd.finish(perm.deny_message)

    params = args.extract_plain_text().strip().split()
    if len(params) not in (3, 4):
        await give_cmd.finish(ui.error("用法：/发放 [QQ] [物品名] [数量] [群号可选]"))

    uid, item, count = params[0], params[1], params[2]
    target_gid = ctx.group_id

    if len(params) == 4:
        if not params[3].isdigit():
            await give_cmd.finish(ui.error("群号必须是纯数字。"))
        target_gid = int(params[3])

    try:
        count = int(count)
    except ValueError:
        await give_cmd.finish(ui.error("数量必须是整数。"))

    ok, deny = await _ensure_member_active_and_registered(uid, target_gid)
    if not ok:
        await give_cmd.finish(ui.error(deny))

    data = await data_manager.get_spirit_data(uid, target_gid)
    items = dict(data.get("items", {}))
    items[item] = items.get(item, 0) + count

    await data_manager.update_spirit_data(uid, target_gid, {"items": items})
    await recorder.add_event(
        "admin_action",
        int(event.user_id),
        {
            "action": "give",
            "target": uid,
            "item": item,
            "count": count,
            "group_id": target_gid,
        },
    )

    target_group_name = group_manager.get_group_name(target_gid)
    await give_cmd.finish(
        ui.success(f"{uid} 在【{target_group_name}】({target_gid}) 获得了 {item} x{count}。")
    )


# ==================== 冻结档案 ====================

@freeze_cmd.handle()
async def handle_freeze_archive(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    ctx = await GroupContext.from_event(event)
    perm = await check_permission(
        event,
        "管理指令 · 冻结档案",
        admin_only=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await freeze_cmd.finish(perm.deny_message)

    target = args.extract_plain_text().strip()
    if not target.isdigit():
        await freeze_cmd.finish(ui.error("请输入 QQ 号。"))

    member = await data_manager.get_member_info(target)
    if not member:
        await freeze_cmd.finish(ui.info("查无此人。"))

    status = member.get("global_profile", {}).get("status", "active")
    if status == "deleted":
        await freeze_cmd.finish(ui.info("该用户档案已经处于冻结状态。"))

    ok = await data_manager.freeze_member_archive(target)
    if not ok:
        await freeze_cmd.finish(ui.error("冻结档案失败，请稍后再试。"))

    await recorder.add_event(
        "admin_action",
        int(event.user_id),
        {
            "action": "freeze_archive",
            "target": target,
            "group_id": ctx.group_id,
        },
    )

    name = member.get("spirit_name", target)
    await freeze_cmd.finish(
        ui.success(f"【{name}】({target}) 的整套档案已被冻结。")
    )


# ==================== 解冻档案 ====================

@unfreeze_cmd.handle()
async def handle_unfreeze_archive(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    ctx = await GroupContext.from_event(event)
    perm = await check_permission(
        event,
        "管理指令 · 解冻档案",
        admin_only=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await unfreeze_cmd.finish(perm.deny_message)

    target = args.extract_plain_text().strip()
    if not target.isdigit():
        await unfreeze_cmd.finish(ui.error("请输入 QQ 号。"))

    member = await data_manager.get_member_info(target)
    if not member:
        await unfreeze_cmd.finish(ui.info("查无此人。"))

    status = member.get("global_profile", {}).get("status", "active")
    if status != "deleted":
        await unfreeze_cmd.finish(ui.info("该用户档案当前不处于冻结状态。"))

    ok = await data_manager.unfreeze_member_archive(target)
    if not ok:
        await unfreeze_cmd.finish(ui.error("解冻档案失败，请稍后再试。"))

    await recorder.add_event(
        "admin_action",
        int(event.user_id),
        {
            "action": "unfreeze_archive",
            "target": target,
            "group_id": ctx.group_id,
        },
    )

    name = member.get("spirit_name", target)
    await unfreeze_cmd.finish(
        ui.success(f"【{name}】({target}) 的整套档案已解冻。")
    )


# ==================== 删除档案（单群独立档案） ====================

@delete_archive_cmd.handle()
async def handle_delete_archive(bot: Bot, event: GroupMessageEvent, args: Message = CommandArg()):
    ctx = await GroupContext.from_event(event)
    perm = await check_permission(
        event,
        "管理指令 · 删除档案",
        admin_only=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await delete_archive_cmd.finish(perm.deny_message)

    params = args.extract_plain_text().strip().split()
    if len(params) != 2:
        await delete_archive_cmd.finish(
            ui.error("用法：/删除档案 [QQ] [群号]")
        )

    uid, gid_str = params[0], params[1]
    if not uid.isdigit():
        await delete_archive_cmd.finish(ui.error("QQ 号必须是纯数字。"))
    if not gid_str.isdigit():
        await delete_archive_cmd.finish(ui.error("群号必须是纯数字。"))

    target_gid = int(gid_str)

    member = await data_manager.get_member_info(uid)
    if not member:
        await delete_archive_cmd.finish(ui.info("查无此人。"))

    status = member.get("global_profile", {}).get("status", "active")
    if status == "deleted":
        await delete_archive_cmd.finish(ui.error("该用户档案当前已被冻结，请先解冻后再操作。"))

    registered = await data_manager.is_registered_in_group(uid, target_gid)
    if not registered:
        await delete_archive_cmd.finish(
            ui.error(f"该用户尚未在群 {target_gid} 建立档案。")
        )

    spirit_raw = data_manager.spirits_raw.get(uid, {})
    group_data = spirit_raw.get("group_data", {}) if isinstance(spirit_raw, dict) else {}
    raw_profile = group_data.get(str(target_gid), {})

    if not isinstance(raw_profile, dict):
        await delete_archive_cmd.finish(ui.error("目标群档不存在或已损坏。"))

    if raw_profile.get("_type") == "pointer":
        await delete_archive_cmd.finish(
            ui.render_panel(
                "删除档案",
                "该群档当前是共享指针档，不能直接删除。\n\n"
                "请先取消共享后再删除，或使用彻底清档处理整套档案。",
                footer="共享档删除前必须先拆除共享关系",
            )
        )

    # 删除前做单群档快照
    backup_path = await _backup_group_archive_snapshot(uid, target_gid)

    ok, reason = await data_manager.delete_group_archive(uid, target_gid)
    if not ok:
        reason_map = {
            "member_not_found": "查无此人。",
            "frozen_member": "该用户档案当前已被冻结，请先解冻后再操作。",
            "group_not_registered": f"该用户尚未在群 {target_gid} 建立档案。",
            "spirit_not_found": "目标群档不存在或已损坏。",
            "pointer_not_allowed": "共享指针档不能直接删除，请先取消共享。",
        }
        await delete_archive_cmd.finish(ui.error(reason_map.get(reason, "删除档案失败，请稍后再试。")))

    await recorder.add_event(
        "admin_action",
        int(event.user_id),
        {
            "action": "delete_group_archive",
            "target": uid,
            "target_group_id": target_gid,
            "group_id": ctx.group_id,
            "backup_file": str(backup_path),
        },
    )

    target_group_name = group_manager.get_group_name(target_gid)
    await delete_archive_cmd.finish(
        ui.render_result_card(
            "删除档案",
            f"已删除该用户在【{target_group_name}】({target_gid}) 的单个独立群档。",
            stats=[
                ("目标用户", uid),
                ("目标群", f"{target_group_name} ({target_gid})"),
                ("备份", backup_path.name),
            ],
            footer="该操作仅删除单群独立档案，不影响其他群档",
        )
    )