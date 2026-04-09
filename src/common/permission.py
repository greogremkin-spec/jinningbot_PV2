""" 晋宁会馆·秃贝五边形 5.0
统一权限检查系统
v5.0 核心升级：
1. 私聊不再默认视为 core
2. 私聊权限依赖绑定群上下文
3. 支持显式传入 GroupContext，减少重复构建
4. 保持对 v4.1 旧调用方式的兼容
权限维度：
- 群等级（core / allied / public / danger / unbound）
- 用户身份（decision / admin / core_member / outer_member / guest）
- 是否已在当前群登记
- 是否馆内专属
- 是否管理/决策专属
- 是否冻结档案
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
from nonebot.adapters.onebot.v11 import MessageEvent
from src.common.data_manager import data_manager
from src.common.group_context import GroupContext
from src.common.group_manager import (
    group_manager,
    TIER_CORE,
    TIER_ALLIED,
    TIER_PUBLIC,
    TIER_DANGER,
)
from src.common.ui_renderer import ui

logger = logging.getLogger("tubei.permission")


@dataclass
class PermissionResult:
    allowed: bool
    group_tier: str
    user_identity: str
    is_registered: bool
    deny_message: Optional[str]


TIER_PRIORITY = {
    TIER_CORE: 0,
    TIER_ALLIED: 1,
    TIER_PUBLIC: 2,
    TIER_DANGER: 3,
    "unbound": 98,
}

IDENTITY_PRIORITY = {
    "decision": 0,
    "admin": 1,
    "core_member": 2,
    "outer_member": 3,
    "guest": 4,
}


def _tier_meets(current_tier: str, required_tier: str) -> bool:
    return TIER_PRIORITY.get(current_tier, 99) <= TIER_PRIORITY.get(required_tier, 99)


def _identity_meets(current_identity: str, required_identity: str) -> bool:
    return IDENTITY_PRIORITY.get(current_identity, 99) <= IDENTITY_PRIORITY.get(required_identity, 99)


async def check_permission(
    event: MessageEvent,
    feature_name: str,
    min_tier: str = TIER_PUBLIC,
    min_identity: str = "guest",
    require_registered: bool = False,
    admin_only: bool = False,
    decision_only: bool = False,
    core_only: bool = False,
    deny_promotion: bool = False,
    ctx: Optional[GroupContext] = None,
) -> PermissionResult:
    """统一权限检查。

    v5.0 说明：
    - 群消息：直接根据当前群检查
    - 私聊：根据绑定群检查
    - 私聊未绑定：对于需要群级能力的功能统一拒绝，并提示先绑定
    - require_registered=True 时，表示“当前上下文对应群已登记”
    - 冻结档案用户会被统一拦截使用依赖档案/群档的能力
    """
    from src.plugins.tubei_system.config import system_config

    uid = str(event.user_id)
    if ctx is None:
        ctx = await GroupContext.from_event(event)

    group_tier = ctx.group_tier

    # ===== 1. 读取成员信息与冻结状态 =====
    member_info = await data_manager.get_member_info(uid)
    member_exists = member_info is not None

    is_frozen = False
    if member_exists:
        status = member_info.get(
            "global_profile", {}
        ).get("status", member_info.get("status", "active"))
        is_frozen = (status == "deleted")

    # ===== 2. 当前群登记判定 =====
    # 重要：v5 语义下，登记必须是“当前群已登记”，而不是“全局存在 member”
    is_registered = False
    if ctx.group_id > 0:
        is_registered = await data_manager.is_registered_in_group(uid, ctx.group_id)

    # ===== 3. 用户身份判定 =====
    # 决策组 / 管理组优先；其余再看当前群身份或全局身份
    if uid in system_config.superusers:
        user_identity = "decision"
    elif uid in system_config.tubei_admins:
        user_identity = "admin"
    elif member_exists and not is_frozen:
        group_profile = await data_manager.get_member_group_profile(uid, ctx.group_id) if ctx.group_id else None
        if group_profile and group_profile.get("identity"):
            user_identity = group_profile["identity"]
        else:
            user_identity = member_info.get(
                "global_identity", member_info.get("identity", "core_member")
            )
    else:
        user_identity = "guest"

    # ===== 4. 私聊未绑定判定 =====
    # 对任何需要群级语义的能力，未绑定私聊都不能直接放行
    if ctx.is_unbound_private:
        if any([
            require_registered,
            core_only,
            admin_only,
            decision_only,
            min_tier in (TIER_CORE, TIER_ALLIED, TIER_DANGER),
        ]):
            return PermissionResult(
                allowed=False,
                group_tier="unbound",
                user_identity=user_identity,
                is_registered=is_registered,
                deny_message=ui.render_panel(
                    feature_name,
                    "你当前在私聊中还没有绑定修行群档。\n\n"
                    "请先发送：私聊绑定\n"
                    "查看可绑定的群，再进行操作。",
                    footer="绑定后即可在私聊中使用对应群的数据",
                ),
            )

    # ===== 5. 冻结档案前置拦截 =====
    archive_dependent = any([
        require_registered,
        core_only,
        admin_only,
        decision_only,
    ])
    if is_frozen and archive_dependent:
        return PermissionResult(
            allowed=False,
            group_tier=group_tier,
            user_identity=user_identity,
            is_registered=False,
            deny_message=ui.render_panel(
                feature_name,
                "你的档案已被冻结，当前无法继续使用该功能。\n\n"
                "如需恢复，请联系管理员执行：解冻档案",
                footer="冻结期间历史数据仍会被保留",
            ),
        )

    # ===== 6. 决策组 / 管理组 =====
    if decision_only and user_identity != "decision":
        return PermissionResult(
            allowed=False,
            group_tier=group_tier,
            user_identity=user_identity,
            is_registered=is_registered,
            deny_message="此功能仅限决策组使用。",
        )

    if admin_only and user_identity not in ("decision", "admin"):
        return PermissionResult(
            allowed=False,
            group_tier=group_tier,
            user_identity=user_identity,
            is_registered=is_registered,
            deny_message="此功能仅限管理组使用。",
        )

    # ===== 7. 馆内专属 =====
    if core_only:
        is_core_user = user_identity in ("decision", "admin", "core_member")
        is_core_tier = group_tier == TIER_CORE

        if not is_core_user or not is_core_tier:
            if deny_promotion:
                locked_text = group_manager.get_feature_locked_text_by_tier(
                    feature_name,
                    group_tier,
                )
                footer = None if group_tier == "unbound" else group_manager.website
                msg = ui.render_panel(
                    feature_name,
                    locked_text,
                    footer=footer,
                )
            else:
                if group_tier == "unbound":
                    msg = f"{feature_name} 需要先绑定群档后才能使用。"
                elif group_tier == TIER_ALLIED:
                    msg = f"{feature_name} 在当前联盟群环境中不可用。"
                elif group_tier == TIER_PUBLIC:
                    msg = f"{feature_name} 在当前公开群不可用。"
                else:
                    msg = f"{feature_name} 为晋宁会馆馆内专属功能。"

            return PermissionResult(
                allowed=False,
                group_tier=group_tier,
                user_identity=user_identity,
                is_registered=is_registered,
                deny_message=msg,
            )

    # ===== 8. 群等级 =====
    if not _tier_meets(group_tier, min_tier):
        if deny_promotion:
            locked_text = group_manager.get_feature_locked_text_by_tier(
                feature_name,
                group_tier,
            )
            footer = None if group_tier == "unbound" else group_manager.website
            msg = ui.render_panel(
                feature_name,
                locked_text,
                footer=footer,
            )
        else:
            if ctx.is_private and not ctx.is_bound:
                msg = "当前私聊未绑定群档，无法使用此功能。"
            elif group_tier == TIER_ALLIED:
                msg = f"{feature_name} 在当前联盟群环境中不可用。"
            elif group_tier == TIER_PUBLIC:
                msg = f"{feature_name} 在当前公开群不可用。"
            else:
                msg = f"{feature_name} 在当前群不可用。"

        return PermissionResult(
            allowed=False,
            group_tier=group_tier,
            user_identity=user_identity,
            is_registered=is_registered,
            deny_message=msg,
        )

    # ===== 9. 身份等级 =====
    if not _identity_meets(user_identity, min_identity):
        return PermissionResult(
            allowed=False,
            group_tier=group_tier,
            user_identity=user_identity,
            is_registered=is_registered,
            deny_message=f"{feature_name} 需要更高的身份权限。",
        )

    # ===== 10. 当前群登记要求 =====
    if require_registered and not is_registered:
        if ctx.is_private and not ctx.is_bound:
            deny = (
                f"使用 {feature_name} 前需要先在私聊绑定一个群档。\n"
                f"发送 私聊绑定 查看可用群"
            )
        else:
            deny = (
                f"使用 {feature_name} 前需要先在当前群建立灵力档案~\n"
                f"发送 /登记 开始录入"
            )

        return PermissionResult(
            allowed=False,
            group_tier=group_tier,
            user_identity=user_identity,
            is_registered=is_registered,
            deny_message=deny,
        )

    return PermissionResult(
        allowed=True,
        group_tier=group_tier,
        user_identity=user_identity,
        is_registered=is_registered,
        deny_message=None,
    )