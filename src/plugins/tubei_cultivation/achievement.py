""" 晋宁会馆·秃贝五边形 5.0 成就系统 3.5 + 称号系统

第三阶段增强：
1. 成就继续以当前群档为主
2. 继续保持显式 group_id 调用
3. 补第三阶段新增玩法的成就承载能力
4. 继续保留群级称号逻辑
5. 保持旧 achievements 字符串列表的一次性迁移兼容
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.params import CommandArg
from nonebot.adapters import Message

from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.common.utils import get_today_str
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.recorder import recorder

logger = logging.getLogger("tubei.achievement")


class AchievementEngine:
    """成就检查引擎（单例）。"""

    _instance: Optional["AchievementEngine"] = None

    @classmethod
    def get_instance(cls) -> "AchievementEngine":
        if cls._instance is None:
            cls._instance = AchievementEngine()
        return cls._instance

    def _get_definitions(self) -> Dict[str, Any]:
        return game_config.get("achievements", default={})

    async def _normalize_achievements(
        self,
        uid: str,
        group_id: int,
        achievements: List[Any],
    ) -> List[Dict[str, Any]]:
        defs = self._get_definitions()

        if not achievements:
            return []

        if isinstance(achievements[0], dict):
            return achievements

        migrated = []
        for item in achievements:
            if isinstance(item, str):
                ach_def = defs.get(item, {})
                migrated.append({
                    "id": item,
                    "name": item,
                    "desc": ach_def.get("desc", ""),
                    "rarity": ach_def.get("rarity", "common"),
                    "date": "",
                })

        await data_manager.update_spirit_data(uid, group_id, {"achievements": migrated})
        return migrated

    async def try_unlock(
        self,
        uid: str,
        achievement_id: str,
        notify_bot: Optional[Bot] = None,
        notify_event: Optional[MessageEvent] = None,
        group_id: Optional[int] = None,
    ) -> Optional[str]:
        if group_id is None or group_id <= 0:
            raise ValueError("AchievementEngine.try_unlock 必须显式传入有效 group_id")

        defs = self._get_definitions()
        ach_def = defs.get(achievement_id)
        if not ach_def:
            return None

        spirit = await data_manager.get_spirit_data(uid, group_id)
        current_achs = await self._normalize_achievements(
            uid,
            group_id,
            spirit.get("achievements", []),
        )

        unlocked_ids = {a.get("id", "") for a in current_achs if isinstance(a, dict)}
        if achievement_id in unlocked_ids:
            return None

        new_ach = {
            "id": achievement_id,
            "name": achievement_id,
            "desc": ach_def.get("desc", ""),
            "rarity": ach_def.get("rarity", "common"),
            "date": get_today_str(),
        }

        current_achs.append(new_ach)
        await data_manager.update_spirit_data(uid, group_id, {"achievements": current_achs})

        await recorder.add_event("achievement_unlock", int(uid), {
            "achievement": achievement_id,
            "rarity": ach_def.get("rarity", "common"),
            "group_id": group_id,
        })

        logger.info(f"[Achievement] {uid} 解锁成就: {achievement_id} @group={group_id}")

        if notify_bot and notify_event:
            rarity_icons = {
                "common": "⭐",
                "rare": "🌟",
                "epic": "💠",
                "legendary": "👑",
            }
            icon = rarity_icons.get(ach_def.get("rarity", "common"), "⭐")

            title_text = ""
            title = ach_def.get("title")
            if title:
                title_text = f"\n 解锁称号：【{title}】"

            msg = (
                f"\n{icon} 成就解锁！\n"
                f"【{achievement_id}】\n"
                f"{ach_def.get('desc', '')}"
                f"{title_text}"
            )
            try:
                await notify_bot.send(notify_event, MessageSegment.at(uid) + msg)
            except Exception:
                pass

        return achievement_id

    async def check_stat_achievements(
        self,
        uid: str,
        notify_bot: Optional[Bot] = None,
        notify_event: Optional[MessageEvent] = None,
        group_id: Optional[int] = None,
    ) -> List[str]:
        if group_id is None or group_id <= 0:
            raise ValueError("AchievementEngine.check_stat_achievements 必须显式传入有效 group_id")

        defs = self._get_definitions()
        spirit = await data_manager.get_spirit_data(uid, group_id)

        unlocked = []
        for ach_id, ach_def in defs.items():
            if not isinstance(ach_def, dict):
                continue
            if ach_def.get("check_type") != "stat_gte":
                continue

            field = ach_def.get("check_field", "")
            value = ach_def.get("check_value", 0)
            current_val = spirit.get(field, 0)

            if current_val >= value:
                result = await self.try_unlock(
                    uid,
                    ach_id,
                    notify_bot=notify_bot,
                    notify_event=notify_event,
                    group_id=group_id,
                )
                if result:
                    unlocked.append(result)

        return unlocked

    async def get_user_achievements(self, uid: str, group_id: int) -> List[Dict[str, Any]]:
        spirit = await data_manager.get_spirit_data(uid, group_id)
        achs = await self._normalize_achievements(uid, group_id, spirit.get("achievements", []))
        return achs

    async def get_available_titles(self, uid: str, group_id: int) -> List[str]:
        achs = await self.get_user_achievements(uid, group_id)
        defs = self._get_definitions()

        titles = []
        for a in achs:
            ach_id = a.get("id", "")
            ach_def = defs.get(ach_id, {})
            title = ach_def.get("title")
            if title:
                titles.append(title)

        return titles

    async def get_equipped_title(self, uid: str, group_id: int) -> str:
        spirit = await data_manager.get_spirit_data(uid, group_id)
        return spirit.get("equipped_title", "")


achievement_engine = AchievementEngine.get_instance()


# ==================== 指令注册 ====================

achievement_cmd = on_command("成就", aliases={"我的成就"}, priority=5, block=True)
title_cmd = on_command("称号", aliases={"我的称号"}, priority=5, block=True)


# ==================== 成就查看 ====================

@achievement_cmd.handle()
async def handle_achievement(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "成就系统",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await achievement_cmd.finish(perm.deny_message)

    await achievement_engine.check_stat_achievements(
        uid,
        bot,
        event,
        group_id=ctx.group_id,
    )

    achs = await achievement_engine.get_user_achievements(uid, ctx.group_id)
    if not achs:
        footer = " 输入 聚灵 | 派遣 | 厨房"
        if ctx.is_private:
            footer += f"\n 当前操作群：{ctx.group_name}"

        await achievement_cmd.finish(
            ui.render_panel(
                "会馆成就系统",
                "还没有解锁任何成就~\n\n通过修行、探索、战斗等活动解锁成就",
                footer=footer,
            )
        )

    rarity_icons = {
        "common": "⭐",
        "rare": "🌟",
        "epic": "💠",
        "legendary": "👑",
    }
    rarity_order = {"legendary": 0, "epic": 1, "rare": 2, "common": 3}

    achs_sorted = sorted(
        achs,
        key=lambda x: rarity_order.get(x.get("rarity", "common"), 99),
    )

    lines = []
    for a in achs_sorted:
        icon = rarity_icons.get(a.get("rarity", "common"), "⭐")
        name = a.get("name", a.get("id", "未知"))
        desc = a.get("desc", "")
        date = a.get("date", "")
        date_str = f" ({date})" if date else ""
        lines.append(f"{icon}【{name}】{date_str}\n {desc}")

    equipped = await achievement_engine.get_equipped_title(uid, ctx.group_id)
    equipped_str = f"当前称号：【{equipped}】" if equipped else "未佩戴称号"

    footer = " 输入 我的称号 查看可用称号"
    if ctx.is_private:
        footer += f"\n 当前操作群：{ctx.group_name}"

    card = ui.render_panel(
        f"会馆成就系统 ({len(achs)} 个)",
        f"{equipped_str}\n\n" + "\n".join(lines),
        footer=footer,
    )
    await achievement_cmd.finish(card)


# ==================== 称号系统 ====================

@title_cmd.handle()
async def handle_title(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "称号系统",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await title_cmd.finish(perm.deny_message)

    target_title = args.extract_plain_text().strip()
    available_titles = await achievement_engine.get_available_titles(uid, ctx.group_id)
    current_title = await achievement_engine.get_equipped_title(uid, ctx.group_id)

    footer_suffix = f"\n 当前操作群：{ctx.group_name}" if ctx.is_private else ""

    if not target_title:
        if not available_titles:
            await title_cmd.finish(
                ui.render_panel(
                    "称号系统",
                    "还没有解锁任何称号~\n\n解锁成就可获得对应称号",
                    footer=" 输入 成就 查看成就进度" + footer_suffix,
                )
            )

        lines = []
        for t in available_titles:
            marker = " ← 当前" if t == current_title else ""
            lines.append(f"【{t}】{marker}")

        card = ui.render_panel(
            "称号系统",
            f"当前称号：{f'【{current_title}】' if current_title else '未佩戴'}\n\n"
            f"可用称号：\n" + "\n".join(lines) + "\n\n"
            f"发送 /称号 [名称] 佩戴\n"
            f"发送 /称号 无 取消佩戴",
            footer=footer_suffix.strip() if footer_suffix else None,
        )
        await title_cmd.finish(card)

    if target_title in ("无", "取消", "卸下"):
        await data_manager.update_spirit_data(uid, ctx.group_id, {"equipped_title": ""})
        await title_cmd.finish(ui.success("已取消佩戴称号。"))

    if target_title not in available_titles:
        await title_cmd.finish(
            ui.error(
                f"你还没有解锁【{target_title}】这个称号。\n"
                f" /成就 查看成就进度"
            )
        )

    await data_manager.update_spirit_data(uid, ctx.group_id, {"equipped_title": target_title})
    await title_cmd.finish(ui.success(f"已佩戴称号：【{target_title}】"))