"""
晋宁会馆·秃贝五边形 5.0
群级上下文模型

职责：
1. 为所有业务逻辑提供统一的运行时上下文
2. 统一处理 群聊 / 私聊 / 临时会话 的数据归属问题
3. 私聊场景下自动解析绑定群
4. 为 v5.0 联盟化架构提供显式上下文传递能力

设计原则：
- 业务层尽量不直接从 event 上零散读取 group_id / tier / bind 信息
- 所有“当前操作到底作用于哪一个群的数据”问题，都应收敛到 GroupContext
- 聊天上下文与游戏数据上下文是两回事：
  GroupContext 只解决“游戏/业务数据归属”
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from nonebot.adapters.onebot.v11 import (
    MessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
)

from src.common.group_manager import group_manager


@dataclass(slots=True)
class GroupContext:
    """统一业务上下文。

    字段说明：
    - group_id:
        当前业务操作实际作用的群号。
        群消息时 = event.group_id
        私聊时 = 用户绑定群号；未绑定则为 0
    - group_tier:
        当前业务上下文对应的群等级。
        未绑定私聊时为 "unbound"
    - group_name:
        当前业务上下文对应的群名称。
        未绑定私聊时为 "未绑定"
    - is_private:
        当前消息是否来自私聊（包括好友私聊与群临时会话）
    - user_id:
        当前用户 QQ 号（字符串）
    - source_group_id:
        消息来源群号。
        群消息时 = event.group_id
        私聊时如果是群临时会话，可尝试读取 sender.group_id，否则为 None
    - bind_group_id:
        私聊绑定的群号。
        群消息时通常等于当前 group_id；
        私聊未绑定时为 None
    """

    group_id: int
    group_tier: str
    group_name: str
    is_private: bool
    user_id: str
    source_group_id: Optional[int] = None
    bind_group_id: Optional[int] = None

    @property
    def is_bound(self) -> bool:
        """私聊是否已绑定群数据。群消息场景天然视为已绑定。"""
        return self.group_id > 0

    @property
    def is_group(self) -> bool:
        """是否为群消息上下文。"""
        return not self.is_private

    @property
    def is_unbound_private(self) -> bool:
        """是否为未绑定的私聊上下文。"""
        return self.is_private and not self.is_bound

    @staticmethod
    async def from_event(event: MessageEvent) -> "GroupContext":
        """从 NoneBot 事件构建统一上下文。

        规则：
        1. 群消息：直接使用当前群作为业务上下文
        2. 私聊：读取用户 private_bind_group 作为业务上下文
        3. 未绑定私聊：返回 unbound 上下文
        """
        from src.common.data_manager import data_manager

        user_id = str(event.user_id)

        if isinstance(event, GroupMessageEvent):
            gid = int(event.group_id)
            return GroupContext(
                group_id=gid,
                group_tier=group_manager.get_group_tier(gid),
                group_name=group_manager.get_group_name(gid),
                is_private=False,
                user_id=user_id,
                source_group_id=gid,
                bind_group_id=gid,
            )

        if isinstance(event, PrivateMessageEvent):
            source_group_id: Optional[int] = None

            # 群临时会话下，OneBot sender 里可能带 group_id；好友私聊通常没有。
            try:
                sender = getattr(event, "sender", None)
                if sender is not None:
                    maybe_gid = getattr(sender, "group_id", None)
                    if maybe_gid:
                        source_group_id = int(maybe_gid)
            except Exception:
                source_group_id = None

            bind_gid = await data_manager.get_private_bind_group(user_id)
            if bind_gid:
                return GroupContext(
                    group_id=bind_gid,
                    group_tier=group_manager.get_group_tier(bind_gid),
                    group_name=group_manager.get_group_name(bind_gid),
                    is_private=True,
                    user_id=user_id,
                    source_group_id=source_group_id,
                    bind_group_id=bind_gid,
                )

            return GroupContext(
                group_id=0,
                group_tier="unbound",
                group_name="未绑定",
                is_private=True,
                user_id=user_id,
                source_group_id=source_group_id,
                bind_group_id=None,
            )

        # 理论兜底：未知事件类型按未绑定私聊处理
        return GroupContext(
            group_id=0,
            group_tier="unbound",
            group_name="未绑定",
            is_private=True,
            user_id=user_id,
            source_group_id=None,
            bind_group_id=None,
        )