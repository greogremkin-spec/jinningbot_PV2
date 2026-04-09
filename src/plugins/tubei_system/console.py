""" 晋宁会馆·秃贝五边形 5.0 管理员控制台（v5 收口版）
收口目标：
1. bot_status 按 v5 结构优先读取：
   - personality.current
   - altar.energy
   - promotion
2. 宣传控制语义与当前 AI 插话链路对齐
3. 保留原有所有管理能力：
   - 人格切换
   - 系统状态
   - 全员广播
   - 封印
   - 全员福利
   - 重载配置
   - 强制保存
   - 宣传开关 / 内容 / 概率
   - 彻底清档（二次确认 + 自动备份）
"""
from __future__ import annotations

import asyncio
import time
import ujson as json
from pathlib import Path
from typing import Dict, Any

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.adapters import Message

from src.common.data_manager import data_manager
from src.common.response_manager import resp_manager
from src.common.group_manager import group_manager
from src.common.ui_renderer import ui
from .config import system_config, game_config
from .interceptor import BAN_LIST
from .recorder import recorder

# ==================== 指令注册 ====================
persona_cmd = on_command(
    "切换人格",
    aliases={"变身", "切换模式"},
    permission=SUPERUSER,
    priority=1,
    block=True,
)
status_cmd = on_command(
    "系统状态",
    aliases={"查看状态"},
    permission=SUPERUSER,
    priority=1,
    block=True,
)
broadcast_cmd = on_command(
    "全员广播",
    aliases={"广播", "公告"},
    permission=SUPERUSER,
    priority=1,
    block=True,
)
ban_cmd = on_command(
    "封印",
    aliases={"关小黑屋"},
    permission=SUPERUSER,
    priority=1,
    block=True,
)
gift_cmd = on_command(
    "全员福利",
    aliases={"发红包"},
    permission=SUPERUSER,
    priority=1,
    block=True,
)
reload_cmd = on_command(
    "重载配置",
    aliases={"刷新配置", "reload"},
    permission=SUPERUSER,
    priority=1,
    block=True,
)
force_save_cmd = on_command(
    "强制保存",
    aliases={"保存数据", "save"},
    permission=SUPERUSER,
    priority=1,
    block=True,
)
promo_toggle_cmd = on_command(
    "宣传开关",
    permission=SUPERUSER,
    priority=1,
    block=True,
)
promo_content_cmd = on_command(
    "宣传内容",
    permission=SUPERUSER,
    priority=1,
    block=True,
)
promo_chance_cmd = on_command(
    "宣传概率",
    permission=SUPERUSER,
    priority=1,
    block=True,
)

# 新增：彻底清档
purge_archive_cmd = on_command(
    "彻底清档",
    permission=SUPERUSER,
    priority=1,
    block=True,
)
purge_confirm_listener = on_message(priority=2, block=False)

# ==================== 危险操作确认缓存 ====================
PENDING_PURGE_ACTIONS: Dict[str, Dict[str, Any]] = {}
PENDING_PURGE_EXPIRE_SECONDS = 300
PURGE_BACKUP_DIR = Path("data/backups/purge")
PURGE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_pending_purge():
    now = time.time()
    expired = [
        uid
        for uid, data in PENDING_PURGE_ACTIONS.items()
        if now - data.get("created_at", 0) > PENDING_PURGE_EXPIRE_SECONDS
    ]
    for uid in expired:
        del PENDING_PURGE_ACTIONS[uid]


async def _backup_full_archive_snapshot(target_uid: str) -> Path:
    """彻底清档前，备份整套用户档案。"""
    member = await data_manager.get_member_info(target_uid)
    spirit = data_manager.spirits_raw.get(str(target_uid))
    payload = {
        "ts": int(time.time()),
        "target_uid": str(target_uid),
        "member": _deepcopy_safe(member),
        "spirit": _deepcopy_safe(spirit),
    }
    file_name = f"purge_{time.strftime('%Y%m%d_%H%M%S')}_{target_uid}.json"
    path = PURGE_BACKUP_DIR / file_name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _deepcopy_safe(obj):
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False))
    except Exception:
        if isinstance(obj, dict):
            return dict(obj)
        if isinstance(obj, list):
            return list(obj)
        return obj


# ==================== 人格系统 ====================
VALID_PERSONAS = {
    "normal": "✨普通模式 (治愈管家)",
    "middle_school": "🔥中二模式 (漆黑烈焰)",
    "cold": "❄高冷模式 (绝对零度)",
    "secretary": "📋秘书模式 (高效冷漠)",
    "overload": "⚡过载模式 (电波话痨)",
}


@persona_cmd.handle()
async def handle_persona(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    mode = args.extract_plain_text().strip()

    if not mode:
        status = await data_manager.get_bot_status()
        current = status.get("personality", {}).get(
            "current",
            status.get("persona", "normal"),
        )

        rows = [("当前人格", VALID_PERSONAS.get(current, current)), ("", "")]
        for k, v in VALID_PERSONAS.items():
            marker = " ← 当前" if k == current else ""
            rows.append((k, f"{v}{marker}"))

        msg = ui.render_data_card("人格切换面板", rows, footer="/切换人格 模式代码")
        await persona_cmd.finish(msg)

    if mode not in VALID_PERSONAS:
        await persona_cmd.finish(ui.error("无效的模式代码。请使用 /切换人格 查看可选项。"))

    await data_manager.update_bot_status({"persona": mode})
    await recorder.add_event("persona_change", int(event.user_id), {"new_persona": mode})
    await persona_cmd.finish(
        f"系统重构完成！\n当前人格已切换为：【{VALID_PERSONAS[mode]}】"
    )


# ==================== 系统状态 ====================
@status_cmd.handle()
async def handle_status(bot: Bot, event: MessageEvent):
    status = await data_manager.get_bot_status()

    personality_block = status.get("personality", {}) if isinstance(status.get("personality", {}), dict) else {}
    altar_block = status.get("altar", {}) if isinstance(status.get("altar", {}), dict) else {}
    promo = status.get("promotion", {}) if isinstance(status.get("promotion", {}), dict) else {}

    persona = personality_block.get("current", status.get("persona", "normal"))
    energy = altar_block.get("energy", status.get("altar_energy", 0))

    members = await data_manager.get_all_members()
    spirits = await data_manager.get_all_spirits()

    # v5 正确统计：成员状态看 global_profile.status，身份看 global_identity
    active_members = {
        qq: m
        for qq, m in members.items()
        if m.get("global_profile", {}).get("status", "active") != "deleted"
    }
    active_count = len(active_members)
    core_count = len(
        [
            m
            for m in active_members.values()
            if m.get("global_identity", "guest") in ("core_member", "admin", "decision")
        ]
    )
    outer_count = active_count - core_count

    # v5 正确统计灵力：统计所有 full 群档，pointer 不重复算
    total_sp = 0
    for uid, spirit_user in spirits.items():
        if not isinstance(spirit_user, dict):
            continue
        group_data = spirit_user.get("group_data", {})
        if not isinstance(group_data, dict):
            continue
        for gid_str, profile in group_data.items():
            if not isinstance(profile, dict):
                continue
            if profile.get("_type") != "full":
                continue
            total_sp += profile.get("sp", 0)

    promo_enabled = "✅开启" if promo.get("enabled", False) else "❌关闭"
    promo_chance = promo.get("chance", 0.20)

    msg = ui.render_data_card(
        "系统控制台",
        [
            ("当前人格", VALID_PERSONAS.get(persona, persona)),
            ("", ""),
            ("总人数", f"{active_count} 位"),
            ("馆内", f"{core_count} 位"),
            ("馆外", f"{outer_count} 位"),
            ("全馆灵力", f"{total_sp}"),
            ("祭坛能量", f"{energy} / 1000"),
            ("", ""),
            ("核心群", f"{len(group_manager.core_group_ids)} 个"),
            ("当前封禁", f"{len(BAN_LIST)} 人"),
            ("", ""),
            ("宣传功能", promo_enabled),
            ("宣传概率", f"{int(promo_chance * 100)}%"),
            ("宣传语义", "随机插话触发时，优先尝试转为宣传"),
        ],
        footer="/切换人格 | /全员广播 | /强制保存 | /宣传开关 | /彻底清档",
    )
    await status_cmd.finish(msg)


# ==================== 全员广播 ====================
@broadcast_cmd.handle()
async def handle_broadcast(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    msg_text = args.extract_plain_text().strip()
    if not msg_text:
        await broadcast_cmd.finish(ui.error("请输入广播内容。\n用法：/全员广播 [内容]"))

    count = 0
    for gid in group_manager.core_group_ids:
        if group_manager.is_debug_group(gid):
            continue
        try:
            await bot.send_group_msg(
                group_id=gid,
                message=f"【会馆公告】\n{msg_text}",
            )
            count += 1
            await asyncio.sleep(0.5)
        except Exception:
            pass

    await broadcast_cmd.finish(ui.success(f"广播已发送至 {count} 个群。"))


# ==================== 封印 ====================
@ban_cmd.handle()
async def handle_ban(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    params = args.extract_plain_text().strip().split()
    if len(params) != 2:
        await ban_cmd.finish(ui.error("用法：/封印 [QQ 号] [分钟数]"))

    target_qq, mins_str = params
    if not target_qq.isdigit():
        await ban_cmd.finish(ui.error("QQ 号格式错误。"))

    try:
        mins = int(mins_str)
    except ValueError:
        await ban_cmd.finish(ui.error("分钟数必须是整数。"))

    BAN_LIST[int(target_qq)] = time.time() + mins * 60
    await recorder.add_event(
        "admin_action",
        int(event.user_id),
        {
            "action": "ban",
            "target": target_qq,
            "duration": mins,
        },
    )
    await ban_cmd.finish(ui.success(f"已封印 {target_qq} 的灵力回路 {mins} 分钟。"))


# ==================== 全员福利 ====================
@gift_cmd.handle()
async def handle_gift(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    params = args.extract_plain_text().strip().split()
    if len(params) < 2:
        await gift_cmd.finish(
            ui.error(
                "格式错误！\n"
                "用法 1: /全员福利 sp 100\n"
                "用法 2: /全员福利 item [物品名] [数量]"
            )
        )

    gift_type = params[0].lower()
    members = await data_manager.get_all_members()

    # 只处理活跃成员
    active_uids = [
        qq for qq, m in members.items()
        if m.get("global_profile", {}).get("status", "active") != "deleted"
    ]

    touched_profiles = 0
    touched_users = 0

    if gift_type == "sp":
        try:
            amount = int(params[1])
        except ValueError:
            await gift_cmd.finish(ui.error("数值必须是整数。"))

        for uid in active_uids:
            spirit_user = data_manager.spirits_raw.get(uid, {})
            group_data = spirit_user.get("group_data", {})
            if not isinstance(group_data, dict):
                continue

            user_touched = False

            # 规则：
            # - 独立存档（full）每个都加
            # - 共享存档（pointer）跳过，因为主档 full 会被加一次
            for gid_str, profile in group_data.items():
                if not isinstance(profile, dict):
                    continue
                if profile.get("_type") != "full":
                    continue

                gid = int(gid_str)
                data = await data_manager.get_spirit_data(uid, gid)
                await data_manager.update_spirit_data(
                    uid,
                    gid,
                    {"sp": data.get("sp", 0) + amount},
                )
                touched_profiles += 1
                user_touched = True

            if user_touched:
                touched_users += 1

        await recorder.add_event(
            "admin_action",
            int(event.user_id),
            {
                "action": "gift_sp",
                "amount": amount,
                "users": touched_users,
                "profiles": touched_profiles,
            },
        )
        await gift_cmd.finish(
            ui.success(
                f"全员福利发放完毕！\n"
                f"每个独立群档 +{amount} 灵力\n"
                f"影响用户：{touched_users} 人\n"
                f"影响群档：{touched_profiles} 个"
            )
        )

    elif gift_type == "item":
        if len(params) != 3:
            await gift_cmd.finish(ui.error("请指定物品名和数量。"))

        item_name = params[1]
        try:
            amount = int(params[2])
        except ValueError:
            await gift_cmd.finish(ui.error("数量必须是整数。"))

        for uid in active_uids:
            spirit_user = data_manager.spirits_raw.get(uid, {})
            group_data = spirit_user.get("group_data", {})
            if not isinstance(group_data, dict):
                continue

            user_touched = False

            # 规则：
            # - 独立存档（full）每个都加
            # - 共享存档（pointer）跳过，因为主档 full 会被加一次
            for gid_str, profile in group_data.items():
                if not isinstance(profile, dict):
                    continue
                if profile.get("_type") != "full":
                    continue

                gid = int(gid_str)
                data = await data_manager.get_spirit_data(uid, gid)
                items = dict(data.get("items", {}))
                items[item_name] = items.get(item_name, 0) + amount
                await data_manager.update_spirit_data(uid, gid, {"items": items})
                touched_profiles += 1
                user_touched = True

            if user_touched:
                touched_users += 1

        await recorder.add_event(
            "admin_action",
            int(event.user_id),
            {
                "action": "gift_item",
                "item": item_name,
                "amount": amount,
                "users": touched_users,
                "profiles": touched_profiles,
            },
        )
        await gift_cmd.finish(
            ui.success(
                f"全员福利发放完毕！\n"
                f"每个独立群档获得 {item_name} x{amount}\n"
                f"影响用户：{touched_users} 人\n"
                f"影响群档：{touched_profiles} 个"
            )
        )

    else:
        await gift_cmd.finish(ui.error("未知类型，仅支持 sp 或 item。"))


# ==================== 配置热重载 ====================
@reload_cmd.handle()
async def handle_reload(bot: Bot, event: MessageEvent):
    resp_manager.reload()
    game_config.reload()
    group_manager.reload()
    await reload_cmd.finish(
        ui.success(
            "配置重载完成！\n"
            "✅responses.yaml\n"
            "✅game_balance.yaml\n"
            "✅groups.yaml"
        )
    )


# ==================== 强制保存 ====================
@force_save_cmd.handle()
async def handle_force_save(bot: Bot, event: MessageEvent):
    await data_manager.persist_all()
    await force_save_cmd.finish(ui.success("所有数据已强制保存到磁盘。"))


# ==================== 宣传开关 ====================
@promo_toggle_cmd.handle()
async def handle_promo_toggle(bot: Bot, event: MessageEvent):
    status = await data_manager.get_bot_status()
    promo = status.get("promotion", {}) if isinstance(status.get("promotion", {}), dict) else {}

    current = promo.get("enabled", False)
    new_state = not current
    promo["enabled"] = new_state

    # 确保默认值
    if "chance" not in promo:
        promo["chance"] = 0.20
    if "content" not in promo:
        promo["content"] = ""

    await data_manager.update_bot_status({"promotion": promo})

    state_text = "✅已开启" if new_state else "❌已关闭"
    content_preview = promo.get("content", "(空)")
    if len(content_preview) > 50:
        content_preview = content_preview[:50] + "..."

    card = ui.render_data_card(
        "宣传功能",
        [
            ("状态", state_text),
            ("触发概率", f"{int(promo.get('chance', 0.20) * 100)}%"),
            ("触发方式", "随机插话命中后，优先改为发送宣传"),
            ("当前内容", content_preview if content_preview else "(空)"),
        ],
        footer="/宣传内容 [文本] | /宣传概率 [0~100]",
    )
    await promo_toggle_cmd.finish(card)


# ==================== 宣传内容 ====================
@promo_content_cmd.handle()
async def handle_promo_content(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    new_content = args.extract_plain_text().strip()

    if not new_content:
        status = await data_manager.get_bot_status()
        promo = status.get("promotion", {}) if isinstance(status.get("promotion", {}), dict) else {}
        current_content = promo.get("content", "(空)")
        await promo_content_cmd.finish(
            ui.render_panel(
                "当前宣传内容",
                current_content if current_content else "(空)",
                footer="/宣传内容 [新文本] 来修改",
            )
        )
        return

    status = await data_manager.get_bot_status()
    promo = status.get("promotion", {}) if isinstance(status.get("promotion", {}), dict) else {}
    promo["content"] = new_content
    if "enabled" not in promo:
        promo["enabled"] = False
    if "chance" not in promo:
        promo["chance"] = 0.20

    await data_manager.update_bot_status({"promotion": promo})
    await promo_content_cmd.finish(
        ui.success(
            f"宣传内容已更新！\n\n新内容：\n{new_content}"
        )
    )


# ==================== 宣传概率 ====================
@promo_chance_cmd.handle()
async def handle_promo_chance(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    val_str = args.extract_plain_text().strip()

    if not val_str:
        status = await data_manager.get_bot_status()
        promo = status.get("promotion", {}) if isinstance(status.get("promotion", {}), dict) else {}
        current_chance = promo.get("chance", 0.20)
        await promo_chance_cmd.finish(
            ui.info(
                f"当前宣传概率：{int(current_chance * 100)}%\n"
                f"用法：/宣传概率 [0~100]\n"
                f"表示在随机插话命中后，有多少概率改为发宣传"
            )
        )
        return

    try:
        val = int(val_str)
    except ValueError:
        await promo_chance_cmd.finish(ui.error("请输入 0~100 的整数。"))
        return

    if val < 0 or val > 100:
        await promo_chance_cmd.finish(ui.error("范围 0~100。"))
        return

    status = await data_manager.get_bot_status()
    promo = status.get("promotion", {}) if isinstance(status.get("promotion", {}), dict) else {}
    promo["chance"] = val / 100.0
    if "enabled" not in promo:
        promo["enabled"] = False
    if "content" not in promo:
        promo["content"] = ""

    await data_manager.update_bot_status({"promotion": promo})
    await promo_chance_cmd.finish(ui.success(f"宣传概率已设为 {val}%"))


# ==================== 彻底清档（危险操作） ====================
@purge_archive_cmd.handle()
async def handle_purge_archive(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    _cleanup_pending_purge()

    target_uid = args.extract_plain_text().strip()
    if not target_uid or not target_uid.isdigit():
        await purge_archive_cmd.finish(ui.error("用法：/彻底清档 [QQ]"))

    member = await data_manager.get_member_info(target_uid)
    spirit_exists = str(target_uid) in data_manager.spirits_raw
    if not member and not spirit_exists:
        await purge_archive_cmd.finish(ui.info("查无此档案。"))

    operator_uid = str(event.user_id)
    PENDING_PURGE_ACTIONS[operator_uid] = {
        "target_uid": target_uid,
        "created_at": time.time(),
    }

    member_name = target_uid
    if isinstance(member, dict):
        member_name = member.get("spirit_name", target_uid)

    card = ui.render_panel(
        "彻底清档 · 二次确认",
        f"⚠你即将彻底清除该用户的整套档案：\n\n"
        f"目标：{member_name} ({target_uid})\n\n"
        f"将被删除：\n"
        f"• member 全局资料\n"
        f"• spirit 全部群档与全局统计\n\n"
        f"系统会在执行前自动生成备份快照。\n"
        f"此操作不可逆，请谨慎确认。",
        footer=f"请在 5 分钟内发送：确认彻底清档 {target_uid}",
    )
    await purge_archive_cmd.finish(card)


@purge_confirm_listener.handle()
async def handle_purge_confirm(bot: Bot, event: MessageEvent):
    _cleanup_pending_purge()

    text = event.get_plaintext().strip()
    if text.startswith("/") or text.startswith("／"):
        return

    operator_uid = str(event.user_id)
    pending = PENDING_PURGE_ACTIONS.get(operator_uid)
    if not pending:
        return

    prefix = "确认彻底清档 "
    if not text.startswith(prefix):
        return

    target_uid = text[len(prefix):].strip()
    if target_uid != pending.get("target_uid", ""):
        return

    member = await data_manager.get_member_info(target_uid)
    spirit_exists = str(target_uid) in data_manager.spirits_raw
    if not member and not spirit_exists:
        del PENDING_PURGE_ACTIONS[operator_uid]
        await bot.send(event, ui.info("目标档案已不存在，无需重复清理。"))
        return

    # 1. 先做整套快照备份
    backup_path = await _backup_full_archive_snapshot(target_uid)

    # 2. 再执行物理删除
    ok = await data_manager.hard_delete_member(target_uid)
    del PENDING_PURGE_ACTIONS[operator_uid]

    if not ok:
        await bot.send(event, ui.error("彻底清档失败，请稍后再试。"))
        return

    await recorder.add_event(
        "admin_action",
        int(event.user_id),
        {
            "action": "purge_archive",
            "target": target_uid,
            "backup_file": str(backup_path),
        },
    )

    await bot.send(
        event,
        ui.render_result_card(
            "彻底清档",
            "已彻底清除该用户的整套档案。\n\n备份已生成，可供后续人工审计或手工恢复。",
            stats=[
                ("目标用户", target_uid),
                ("备份文件", backup_path.name),
            ],
            footer="该用户之后可自行重新登记，从零开始建立新档案",
        ),
    )