""" 晋宁会馆·秃贝五边形 5.0 灵册大厅 —— 在馆人员登记（收尾定稿版）
v5.0 收尾定稿目标：
1. 登记正式写入 v5 member 结构：
- global_profile
- group_profiles
- registered_groups
- primary_group / private_bind_group
2. spirit 初始化正式写入当前群档
3. 若用户已存在，则只更新当前群资料，不破坏其他群档
4. 提示语义更明确：
- 私聊可获取模板
- 真正建档建议在目标群提交
5. 保留原有机制：
- 馆内 / 馆外身份
- 代登权限校验
- 身份分配
- 初始灵力 / 初始成就 / 初始称号历史
6. 冻结档案用户不可通过 /登记 自行恢复，必须管理员解冻
"""
from __future__ import annotations

from nonebot import on_command, on_regex
from nonebot.adapters.onebot.v11 import (
    Bot,
    MessageEvent,
    MessageSegment,
    GroupMessageEvent,
)

from src.common.data_manager import data_manager
from src.common.utils import parse_registry_form, check_sensitive_words, get_today_str
from src.common.response_manager import resp_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.common.identity import identity_manager
from src.plugins.tubei_system.config import system_config, game_config
from src.plugins.tubei_system.recorder import recorder


guide_cmd = on_command("登记", aliases={"在馆登记", "入册"}, priority=5, block=True)
submit_cmd = on_regex(r"^/在馆人员登记", priority=4, block=True)


# ==================== 引导登记 ====================

@guide_cmd.handle()
async def handle_guide(bot: Bot, event: MessageEvent):
    ctx = await GroupContext.from_event(event)
    perm = await check_permission(
        event,
        "灵册大厅 · 在馆人员登记",
        min_tier="allied",
        deny_promotion=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await guide_cmd.finish(perm.deny_message)

    tip_msg = await resp_manager.get_text("admin.register_guide")
    await guide_cmd.send(tip_msg)

    extra_tip = ""
    if ctx.is_private:
        if ctx.is_bound:
            extra_tip = (
                f"\n\n当前私聊绑定群：{ctx.group_name}\n"
                f"建议你到目标群提交正式登记表单，这样会直接建立该群档。"
            )
        else:
            extra_tip = (
                "\n\n当前私聊未绑定任何群。\n"
                "建议你先去目标群获取群身份，再在目标群提交正式登记。"
            )

    template = await resp_manager.get_text("admin.register_template")
    await guide_cmd.finish(template + extra_tip)


# ==================== 提交登记 ====================

@submit_cmd.handle()
async def handle_submit(bot: Bot, event: MessageEvent):
    ctx = await GroupContext.from_event(event)
    perm = await check_permission(
        event,
        "灵册大厅 · 档案提交",
        min_tier="allied",
        ctx=ctx,
    )
    if not perm.allowed:
        await submit_cmd.finish(perm.deny_message)

    raw_text = event.get_plaintext().strip()
    data = parse_registry_form(raw_text)
    if not data:
        await submit_cmd.finish(
            ui.error('解析失败！请确保保留了"QQ 号:"、"妖名:"和"简介:"等关键词。')
        )

    target_qq = data["qq"]
    spirit_name = data["spirit_name"]
    intro = data["intro"]
    nickname = data["nickname"] or spirit_name

    if check_sensitive_words(intro):
        await submit_cmd.finish(ui.error("内容包含敏感词。"))

    sender_qq = str(event.user_id)
    is_superuser = sender_qq in system_config.superusers
    is_admin = sender_qq in system_config.tubei_admins

    # 非本人代登需要管理员权限
    if target_qq != sender_qq and not (is_superuser or is_admin):
        msg = await resp_manager.get_text("system.permission_denied")
        await submit_cmd.finish(msg)

    # v5 正式策略：
    # - 允许私聊拿模板
    # - 正式提交登记必须明确落到一个群
    register_group = 0
    if isinstance(event, GroupMessageEvent):
        register_group = event.group_id

    if register_group <= 0:
        await submit_cmd.finish(
            ui.render_panel(
                "灵册大厅 · 档案提交",
                "正式登记需要在目标群中提交。\n\n"
                "原因：登记本质上是“建立某个群的修行档案”，\n"
                "必须明确归属群。\n\n"
                "请到目标群发送填写好的登记表。",
                footer="私聊可用于获取模板与咨询，但正式建档建议在目标群进行",
            )
        )

    identity = await identity_manager.on_new_registration(target_qq, register_group)

    # ===== 0. 冻结档案保护：冻结用户不能自行通过 /登记 恢复 =====
    existing_member = await data_manager.get_member_info(target_qq)
    if existing_member is not None:
        current_status = existing_member.get("global_profile", {}).get(
            "status",
            existing_member.get("status", "active"),
        )
        if current_status == "deleted":
            await submit_cmd.finish(
                ui.render_panel(
                    "灵册大厅 · 档案提交",
                    "你的档案当前已被冻结，不能自行重新登记恢复。\n\n"
                    "如需继续使用，请联系管理员执行：解冻档案",
                    footer="冻结期间历史数据仍会被保留",
                )
            )

    # ===== 1. 写 member：global + group profile =====
    if existing_member is None:
        member_global_patch = {
            "qq": target_qq,
            "spirit_name": spirit_name,
            "global_identity": identity,
            "registered_groups": [register_group],
            "primary_group": register_group,
            "private_bind_group": register_group,
            "sharing_config": None,
            "global_profile": {
                "register_time": int(event.time),
                "status": "active",
                "last_active": int(event.time),
                "public_visible": True,
                "oc_details": {},
                "web_synced": False,
                "web_profile_url": "",
            },
        }
        await data_manager.update_member_global(target_qq, member_global_patch)
    else:
        global_profile = existing_member.get("global_profile", {})
        member_global_patch = {
            "qq": target_qq,
            "spirit_name": spirit_name,
            "global_identity": existing_member.get("global_identity", identity),
            "registered_groups": existing_member.get("registered_groups", []),
            "primary_group": existing_member.get("primary_group", register_group),
            "private_bind_group": existing_member.get("private_bind_group", register_group),
            "sharing_config": existing_member.get("sharing_config"),
            "global_profile": {
                "register_time": global_profile.get("register_time", int(event.time)),
                "status": "active",
                "last_active": int(event.time),
                "public_visible": global_profile.get("public_visible", True),
                "oc_details": global_profile.get("oc_details", {}),
                "web_synced": global_profile.get("web_synced", False),
                "web_profile_url": global_profile.get("web_profile_url", ""),
            },
        }
        await data_manager.update_member_global(target_qq, member_global_patch)

    await data_manager.update_member_group_profile(
        target_qq,
        register_group,
        {
            "spirit_name": spirit_name,
            "nickname": nickname,
            "intro": intro,
            "identity": identity,
            "register_time": int(event.time),
        },
    )

    # ===== 2. 初始化当前群 spirit 档 =====
    spirit_data = await data_manager.get_spirit_data(target_qq, register_group)
    is_new_group_spirit = not bool(spirit_data)

    if is_new_group_spirit:
        initial_sp = game_config.initial_sp
        await data_manager.update_spirit_data(
            target_qq,
            register_group,
            {
                "sp": initial_sp,
                "level": 1,
                "items": {},
                "achievements": ["初探灵界"],
                "join_date": get_today_str(),
                "total_meditation_count": 0,
                "total_sp_earned": 0,
                "total_kitchen_count": 0,
                "total_expedition_count": 0,
                "heixiu_count": 0,
                "title_history": [
                    {
                        "level": 1,
                        "title": "灵识觉醒",
                        "date": get_today_str(),
                    }
                ],
            },
        )
        bonus_msg = await resp_manager.get_text("admin.bonus_msg", {"sp": initial_sp})
        await recorder.add_event(
            "registry_new",
            int(target_qq),
            {
                "name": spirit_name,
                "group_id": register_group,
            },
        )
    else:
        bonus_msg = await resp_manager.get_text("admin.update_msg")
        await recorder.add_event(
            "registry_update",
            int(target_qq),
            {
                "name": spirit_name,
                "group_id": register_group,
            },
        )

    # ===== 3. 身份提示 =====
    identity_tips = {
        "decision": "决策组",
        "admin": "管理组",
        "core_member": "馆内成员",
        "outer_member": "馆外成员",
    }
    identity_tip = identity_tips.get(identity, "")
    outer_tip = ""
    if identity == "outer_member":
        outer_tip = "\n" + await resp_manager.get_text("admin.register_outer")

    reply = await resp_manager.get_text(
        "admin.register_success",
        {
            "spirit_name": spirit_name,
            "bonus_msg": bonus_msg,
        },
    )

    stats = [
        ("妖名", spirit_name),
        ("身份", identity_tip),
        ("登记群", f"{ctx.group_name} ({register_group})"),
    ]

    card = ui.render_result_card(
        "灵册大厅 · 登记完成",
        reply,
        stats=stats,
        extra=outer_tip if outer_tip else None,
        footer="输入 档案 查看面板 | 菜单 查看功能",
    )
    await submit_cmd.finish(MessageSegment.at(event.user_id) + "\n" + card)