"""
晋宁会馆·秃贝五边形 
身份感知与自动更新系统

职责：
  1. 监听用户在不同群的活动，自动检测身份是否需要更新
  2. 馆外成员出现在核心群 → 自动升级为馆内成员
  3. 身份只升不降（不会因为去了公开群而被降级）
  4. 使用检查缓存，避免对同一用户频繁查库

触发时机：
  - interceptor.py 中每条消息经过时调用 check_and_update()
  - 不阻塞消息处理流程（仅在后台更新）
"""

import time
import logging
from typing import Optional, Dict

from .data_manager import data_manager
from .group_manager import group_manager

logger = logging.getLogger("tubei.identity")

# 同一用户的检查间隔（秒）—— 10分钟内不重复检查
CHECK_INTERVAL = 600


class IdentityManager:
    """
    身份感知管理器（单例）

    身份等级（只升不降）：
      guest → outer_member → core_member
      admin / decision 由配置文件决定，不受自动感知影响
    """
    _instance: Optional["IdentityManager"] = None

    def __init__(self):
        # 检查缓存：{uid: last_check_timestamp}
        self._check_cache: Dict[str, float] = {}

    @classmethod
    def get_instance(cls) -> "IdentityManager":
        if cls._instance is None:
            cls._instance = IdentityManager()
        return cls._instance

    async def check_and_update(
        self,
        user_id: str,
        group_id: int
    ) -> Optional[str]:
        """
        检查用户身份是否需要更新

        调用时机：每条群消息经过 interceptor 时
        使用缓存控制频率，不会造成性能问题

        :param user_id: 用户QQ号
        :param group_id: 当前群号
        :return: 如果身份发生变更，返回通知消息；否则返回 None
        """
        now = time.time()

        # 频率控制：同一用户 10 分钟内不重复检查
        cache_key = f"{user_id}_{group_id}"
        last_check = self._check_cache.get(cache_key, 0)
        if now - last_check < CHECK_INTERVAL:
            return None
        self._check_cache[cache_key] = now

        # 获取用户当前信息
        member = await data_manager.get_member_info(user_id)
        if member is None:
            # 未登记用户，不处理
            return None

        status = member.get("global_profile", {}).get("status", "active")
        if status == "deleted":
            return None

        current_identity = member.get("global_identity", member.get("identity", "guest"))
        group_tier = group_manager.get_group_tier(group_id)

        # ===== 升级规则 =====

        # 规则1：馆外成员出现在核心群 → 升级为馆内成员
        if current_identity == "outer_member" and group_tier == "core":
            success = await data_manager.update_member_identity(
                user_id, "core_member", group_id=group_id
            )
            if success:
                spirit_name = member.get("spirit_name", "小友")
                logger.info(
                    f"[Identity] {spirit_name}({user_id}) "
                    f"自动升级: outer_member → core_member "
                    f"(出现在核心群 {group_id})"
                )
                return (
                    f"✨ 欢迎回到晋宁会馆，{spirit_name}！\n"
                    f"你的档案已自动更新为馆内成员~\n"
                    f"所有馆内功能已解锁！(嘿咻)"
                )

        # 规则2：guest 状态的不自动处理（需要手动 /登记）

        # 规则3：admin / decision 不受自动感知影响（由 config 决定）

        # 更新最后活跃时间
        await data_manager.update_member_last_active(user_id)

        return None

    async def on_new_registration(
        self,
        user_id: str,
        group_id: int
    ) -> str:
        """
        新用户登记时调用，确定初始身份

        :param user_id: 用户QQ号
        :param group_id: 登记时所在的群号
        :return: 分配的身份标识
        """
        # 先检查是否是管理组/决策组
        from src.plugins.tubei_system.config import system_config

        if user_id in system_config.superusers:
            return "decision"
        if user_id in system_config.tubei_admins:
            return "admin"

        # 根据登记群的等级决定身份
        group_tier = group_manager.get_group_tier(group_id)
        if group_tier == "core":
            return "core_member"
        else:
            return "outer_member"

    def clear_cache(self):
        """清除检查缓存（调试用）"""
        self._check_cache.clear()

    def cleanup_expired_cache(self):
        """清理过期的缓存条目（节省内存）"""
        now = time.time()
        expired_keys = [
            k for k, v in self._check_cache.items()
            if now - v > CHECK_INTERVAL * 10
        ]
        for k in expired_keys:
            del self._check_cache[k]


# ==================== 全局单例 ====================
identity_manager = IdentityManager.get_instance()