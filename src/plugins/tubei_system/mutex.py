"""
晋宁会馆·秃贝五边形 5.0
互斥锁系统

v5.0 升级：
1. 互斥检查正式增加 group_id 维度
2. A 群派遣默认不影响 B 群操作
3. 若该群数据是共享指针，则自动解析到主档检查
4. 保留 v4.1 调用兼容：
   - check_mutex(uid, action_type)
   - check_mutex(uid, group_id, action_type)

动作分类：
- meditation: 聚灵
- entertainment: 娱乐
- kitchen: 厨房
- resonance: 鉴定
- garden: 药圃
- registry: 登记
"""

from __future__ import annotations

import time
from typing import Optional

from src.common.data_manager import data_manager
from src.common.utils import format_duration


class MutexError(Exception):
    """互斥锁异常。"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def check_mutex(user_id: str, group_id_or_action: Optional[int | str], action_type: Optional[str] = None):
    """检查用户当前状态是否允许执行某动作。

    兼容两种调用方式：
    - v4: check_mutex(uid, "meditation")
    - v5: check_mutex(uid, group_id, "meditation")
    """
    uid = str(user_id)

    # v4 兼容：没有 group_id
    if action_type is None and isinstance(group_id_or_action, str):
        action = group_id_or_action
        member = await data_manager.get_member_info(uid)
        group_id = 0
        if member:
            group_id = (
                member.get("private_bind_group")
                or member.get("primary_group")
                or member.get("register_group")
                or 0
            )
        return await _check_mutex_impl(uid, int(group_id), action)

    # v5 正式调用
    group_id = int(group_id_or_action) if group_id_or_action else 0
    action = action_type or ""
    return await _check_mutex_impl(uid, group_id, action)


async def _check_mutex_impl(user_id: str, group_id: int, action_type: str):
    """实际互斥逻辑。"""
    # 药圃和登记不受派遣锁影响
    if action_type in ("garden", "registry"):
        return True

    # 没有群上下文时，尽量宽松处理；真正权限由上层控制
    if group_id <= 0:
        return True

    spirit_data, resolved_gid = await data_manager.resolve_pointer(user_id, group_id)
    if not spirit_data:
        spirit_data = await data_manager.get_spirit_data(user_id, group_id)

    expedition = spirit_data.get("expedition", {})
    if expedition.get("status") == "exploring":
        locked_actions = {"meditation", "entertainment", "kitchen", "resonance"}
        if action_type in locked_actions:
            loc = expedition.get("location", "未知之地")
            end_time = expedition.get("end_time", 0)
            remaining = int(end_time - time.time())

            if remaining > 0:
                time_str = format_duration(remaining)

                # 如果是共享档导致的锁，适当说明来源群
                shared_note = ""
                if resolved_gid != group_id:
                    shared_note = f"\n 当前群数据共享到群档：{resolved_gid}"

                raise MutexError(
                    f" 你的灵体正在【{loc}】探索中！\n"
                    f"⏳剩余时间：{time_str}"
                    f"{shared_note}\n"
                    f" 可使用 /召回 强制返回（消耗 5 灵力）"
                )

    return True