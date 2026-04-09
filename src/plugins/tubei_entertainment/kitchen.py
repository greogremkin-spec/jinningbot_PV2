""" 晋宁会馆·秃贝五边形 5.0 无限大人的厨房 · 生存挑战（状态收口增强版）
收口目标：
1. 味蕾丧失为“下一顿 normal 餐次的味觉失真状态”
2. 生效时仍先判定该顿原本成功/失败，再因味蕾丧失改为特殊结算
3. 若该顿原本成功：味蕾丧失解除
4. 若该顿原本失败：味蕾丧失续上
5. 若隔天仍未触发：味蕾丧失自动失效
6. 保持原有机制不删减：
   - 群级 daily_counts / kitchen_slots
   - 世界事件全服同步
   - 连败保底
   - 吉兆
   - 物品 Buff
   - 成就检查
7. 世界事件额外机会继续采用“额外机会”模式：
   - 不占 normal 次数
   - 不占本餐餐次
   - 但仍计入 total_kitchen_count
8. 饭点时间统一从 game_balance.yaml 读取，消除配置双源
"""
from __future__ import annotations

import random
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment

from src.common.data_manager import data_manager
from src.common.response_manager import resp_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.common.utils import ensure_daily_reset, get_current_hour, check_blessing, get_today_str
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.recorder import recorder
from src.plugins.tubei_system.mutex import check_mutex, MutexError
from src.plugins.tubei_cultivation.achievement import achievement_engine

kitchen_cmd = on_command("厨房生存", aliases={"厨房", "吃饭", "干饭"}, priority=5, block=True)

# ==================== 饭点工具函数 ====================

_DEFAULT_MEAL_SLOT_NAMES = [
    "breakfast",
    "lunch",
    "dinner",
    "midnight",
    "late_night",
]

_MEAL_DISPLAY_NAMES = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
    "midnight": "夜宵",
    "late_night": "深夜加餐",
}


def _normalize_meal_slots() -> list[tuple[int, int, str]]:
    """从配置读取饭点时间并转成带 slot_id 的结构。"""
    raw = game_config.kitchen_meal_times
    slots: list[tuple[int, int, str]] = []

    if isinstance(raw, list):
        for idx, item in enumerate(raw):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            try:
                start = int(item[0])
                end = int(item[1])
            except Exception:
                continue

            slot_id = (
                _DEFAULT_MEAL_SLOT_NAMES[idx]
                if idx < len(_DEFAULT_MEAL_SLOT_NAMES)
                else f"slot_{idx + 1}"
            )
            slots.append((start, end, slot_id))

    # 兜底，防止配置损坏
    if not slots:
        slots = [
            (6, 9, "breakfast"),
            (11, 14, "lunch"),
            (16, 21, "dinner"),
            (22, 24, "midnight"),
        ]

    return slots


def _hour_in_range(hour: int, start: int, end: int) -> bool:
    """支持跨天时间段判定。"""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def check_meal_time() -> bool:
    h = get_current_hour()
    for start, end, _ in _normalize_meal_slots():
        if _hour_in_range(h, start, end):
            return True
    return False


def get_current_meal_slot() -> str:
    h = get_current_hour()
    for start, end, slot_id in _normalize_meal_slots():
        if _hour_in_range(h, start, end):
            return slot_id
    return ""


def get_meal_display_name(slot_id: str) -> str:
    if not slot_id:
        return "未知餐次"

    for start, end, sid in _normalize_meal_slots():
        if sid == slot_id:
            base_name = _MEAL_DISPLAY_NAMES.get(slot_id, slot_id)
            return f"{base_name} ({start}-{end} 点)"

    return _MEAL_DISPLAY_NAMES.get(slot_id, slot_id)


def get_next_meal_hint() -> str:
    h = get_current_hour()
    slots = _normalize_meal_slots()

    future_candidates = []
    for start, end, slot_id in slots:
        if start > h:
            future_candidates.append((start, slot_id))

    if future_candidates:
        next_start, next_slot_id = sorted(future_candidates, key=lambda x: x[0])[0]
        return f"下一餐：{_MEAL_DISPLAY_NAMES.get(next_slot_id, next_slot_id)} {next_start}:00"

    # 没有未来时段，则找明天最早一餐
    tomorrow_start, tomorrow_slot_id = sorted(slots, key=lambda x: x[0])[0][:2]
    return f"下一餐：明天{_MEAL_DISPLAY_NAMES.get(tomorrow_slot_id, tomorrow_slot_id)} {tomorrow_start}:00"


# ==================== 味蕾丧失状态工具 ====================

def _cleanup_expired_taste_loss(buffs: dict) -> tuple[dict, bool]:
    """若味蕾丧失已跨天未触发，则自动清除。返回 (buffs, cleaned_flag)。"""
    buffs = dict(buffs)
    if not buffs.get("taste_loss_active", False):
        return buffs, False

    today = get_today_str()
    loss_date = str(buffs.get("taste_loss_date", "") or "").strip()

    if not loss_date:
        # 兼容旧数据：如果只有 active 没日期，保守视为当天状态，不在这里强清
        return buffs, False

    if loss_date != today:
        buffs.pop("taste_loss_active", None)
        buffs.pop("taste_loss_date", None)
        return buffs, True

    return buffs, False


def _mark_taste_loss_active(buffs: dict) -> dict:
    buffs = dict(buffs)
    buffs["taste_loss_active"] = True
    buffs["taste_loss_date"] = get_today_str()
    return buffs


def _clear_taste_loss(buffs: dict) -> dict:
    buffs = dict(buffs)
    buffs.pop("taste_loss_active", None)
    buffs.pop("taste_loss_date", None)
    return buffs


# ==================== 主逻辑 ====================
@kitchen_cmd.handle()
async def handle_kitchen(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "无限大人的厨房 · 生存挑战",
        min_tier="public",
        ctx=ctx,
    )
    if not perm.allowed:
        await kitchen_cmd.finish(perm.deny_message)

    try:
        await check_mutex(uid, ctx.group_id, "kitchen")
    except MutexError as e:
        await kitchen_cmd.finish(e.message)

    if not check_meal_time():
        msg = await resp_manager.get_text("entertainment.kitchen_not_time")
        next_hint = get_next_meal_hint()
        await kitchen_cmd.finish(
            ui.render_panel(
                "无限大人的厨房",
                f"{msg}\n\n{next_hint}",
            )
        )

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    daily = ensure_daily_reset(
        data,
        extra_fields={
            "kitchen": 0,
            "bad_streak": 0,
            "good_streak": 0,
            "kitchen_slots": {},
            "kitchen_chaos_bonus_used": False,
            "kitchen_chaos_bonus_date": "",
        },
    )

    from src.plugins.tubei_system.world_event import is_event_active
    kitchen_chaos_active = await is_event_active("kitchen_chaos")

    meal_slot = get_current_meal_slot()
    slots = daily.get("kitchen_slots", {}) if isinstance(daily.get("kitchen_slots", {}), dict) else {}

    normal_daily_allowed = daily.get("kitchen", 0) < game_config.kitchen_daily_limit
    normal_slot_allowed = bool(meal_slot) and (not slots.get(meal_slot, False))

    today = daily.get("date", "")
    kitchen_chaos_bonus_available = (
        kitchen_chaos_active
        and not (
            daily.get("kitchen_chaos_bonus_date", "") == today
            and daily.get("kitchen_chaos_bonus_used", False)
        )
    )

    normal_allowed = normal_daily_allowed and normal_slot_allowed

    # 若 normal 不允许，再看是否可以走事件额外机会
    if not normal_allowed and not kitchen_chaos_bonus_available:
        if not normal_daily_allowed:
            await kitchen_cmd.finish(
                ui.info(f"今天已经吃了 {game_config.kitchen_daily_limit} 顿，明天再来~")
            )
        if meal_slot and not normal_slot_allowed:
            slot_name = get_meal_display_name(meal_slot)
            await kitchen_cmd.finish(
                ui.info(f"{slot_name} 已经吃过啦~\n{get_next_meal_hint()}")
            )

    used_mode = "normal" if normal_allowed else "kitchen_chaos_bonus"

    buffs = dict(data.get("buffs", {}))
    buffs, taste_loss_expired = _cleanup_expired_taste_loss(buffs)
    is_taste_lost = bool(buffs.get("taste_loss_active", False))

    # ===== 基础成功率逻辑（bonus 模式只用于展示原始结果，不影响 bonus 必成功规则） =====
    base_prob = game_config.kitchen_success_rate
    bad_streak = daily.get("bad_streak", 0)

    if bad_streak >= 3:
        base_prob = game_config.kitchen_bad_streak_bonus_3
    elif bad_streak >= 2:
        base_prob += game_config.kitchen_bad_streak_bonus_2

    if buffs.pop("清心露", None):
        base_prob = min(1.0, base_prob + 0.20)

    blessing_active = check_blessing(buffs, "kitchen")
    if blessing_active:
        base_prob = 1.0

    # ===== 先算“原本结果” =====
    # bonus 事件额外机会仍保持原有“必成功”语义
    if used_mode == "kitchen_chaos_bonus":
        original_success = True
    else:
        original_success = random.random() < base_prob

    sp_change = 0
    result_title = ""
    result_desc = ""
    result_tags = []
    used_fulingdan = False

    current_sp = data.get("sp", 0)

    # ==================== 味蕾丧失特判 ====================
    # 只在 normal 餐次中覆盖结算；世界事件 bonus 保持 bonus 自己的语义
    if is_taste_lost and used_mode == "normal":
        taste_sp = game_config.kitchen_taste_loss_sp
        sp_change = taste_sp

        if original_success:
            menu = random.choice(game_config.kitchen_menu_good)
            result_title = "味蕾丧失中"
            result_desc = (
                f"原本端上来的是【{menu}】。\n"
                f"按理说，这一餐其实是成功的。\n"
                f"但你的味蕾还没恢复，只能木着脸把它咽下去。\n"
                f"灵力变化：+{taste_sp}"
            )
            result_tags.append("味蕾丧失")
            buffs = _clear_taste_loss(buffs)

            daily["bad_streak"] = 0
            daily["good_streak"] = daily.get("good_streak", 0) + 1
            daily["kitchen"] = daily.get("kitchen", 0) + 1
            if meal_slot:
                slots[meal_slot] = True
            daily["kitchen_slots"] = slots

            if daily["good_streak"] >= 3:
                await achievement_engine.try_unlock(uid, "美食品鉴家", bot, event, group_id=ctx.group_id)

        else:
            menu = random.choice(game_config.kitchen_menu_bad)
            result_title = "味蕾丧失中"
            result_desc = (
                f"原本端上来的是【{menu}】。\n"
                f"按理说，这一餐其实是失败的。\n"
                f"但你的味蕾早就麻了，只觉得“嗯，能吃”。\n"
                f"灵力变化：+{taste_sp}"
            )
            result_tags.append("味蕾丧失")
            result_tags.append("味蕾丧失（续上）")
            buffs = _mark_taste_loss_active(buffs)

            await data_manager.increment_group_stat(uid, ctx.group_id, "total_kitchen_bad", 1)
            await data_manager.increment_group_stat(uid, ctx.group_id, "total_taste_loss", 1)

            daily["good_streak"] = 0
            daily["bad_streak"] = daily.get("bad_streak", 0) + 1
            daily["kitchen"] = daily.get("kitchen", 0) + 1
            if meal_slot:
                slots[meal_slot] = True
            daily["kitchen_slots"] = slots

    # ==================== 正常成功分支 ====================
    elif original_success:
        reward = game_config.kitchen_reward_sp
        sp_change = reward
        menu = random.choice(game_config.kitchen_menu_good)
        result_title = "✨绝世珍馐"
        result_desc = await resp_manager.get_text(
            "entertainment.kitchen_good",
            {"menu": menu, "sp": reward},
        )

        if used_mode == "normal":
            daily["bad_streak"] = 0
            daily["good_streak"] = daily.get("good_streak", 0) + 1
            daily["kitchen"] = daily.get("kitchen", 0) + 1
            if meal_slot:
                slots[meal_slot] = True
            daily["kitchen_slots"] = slots

            if daily["good_streak"] >= 3:
                await achievement_engine.try_unlock(uid, "美食品鉴家", bot, event, group_id=ctx.group_id)
        else:
            daily["kitchen_chaos_bonus_used"] = True
            daily["kitchen_chaos_bonus_date"] = today
            result_tags.append("无限失控额外机会")

        if kitchen_chaos_active:
            result_tags.append("无限失控中")
        if blessing_active:
            result_tags.append("吉兆加持")

    # ==================== 正常失败分支 ====================
    else:
        penalty = game_config.kitchen_penalty_sp
        menu = random.choice(game_config.kitchen_menu_bad)

        if buffs.pop("涪灵丹", None):
            sp_change = 0
            used_fulingdan = True
            result_title = "涪灵丹护体"
            result_desc = (
                f"呃啊... 是【{menu}】！\n"
                f"但涪灵丹抵消了所有负面效果！\n"
                f"灵力变化：±0"
            )
        else:
            sp_change = -penalty
            result_title = "深渊料理"
            result_desc = await resp_manager.get_text(
                "entertainment.kitchen_bad",
                {"menu": menu, "sp": penalty},
            )
            buffs = _mark_taste_loss_active(buffs)
            result_tags.append("味蕾丧失（下顿生效）")

            await data_manager.increment_group_stat(uid, ctx.group_id, "total_taste_loss", 1)

        await data_manager.increment_group_stat(uid, ctx.group_id, "total_kitchen_bad", 1)

        daily["good_streak"] = 0
        daily["bad_streak"] = daily.get("bad_streak", 0) + 1
        daily["kitchen"] = daily.get("kitchen", 0) + 1
        if meal_slot:
            slots[meal_slot] = True
        daily["kitchen_slots"] = slots

    # ===== 写回 =====
    new_sp = max(0, current_sp + sp_change)

    await data_manager.update_spirit_data(uid, ctx.group_id, {"sp": new_sp})
    await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
    await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)

    # 不论 normal 还是 bonus，都会计入总吃饭次数
    await data_manager.increment_group_stat(uid, ctx.group_id, "total_kitchen_count", 1)

    await recorder.add_event(
        "kitchen",
        int(uid),
        {
            "sp_change": sp_change,
            "success": original_success,
            "taste_loss_before": is_taste_lost,
            "taste_loss_after": bool(buffs.get("taste_loss_active", False)),
            "taste_loss_expired": taste_loss_expired,
            "group_id": ctx.group_id,
            "mode": used_mode,
        },
    )

    await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)

    # ===== 构建反馈 =====
    sp_display = f"+{sp_change}" if sp_change >= 0 else str(sp_change)
    slot_name = get_meal_display_name(meal_slot)

    stats = [
        ("灵力变化", f"{sp_display} (当前: {new_sp})"),
        ("本餐", slot_name),
    ]

    if used_mode == "normal":
        stats.append(("今日已吃", f"{daily['kitchen']} / {game_config.kitchen_daily_limit} 顿"))
    else:
        stats.append((
            "今日已吃",
            f"{daily.get('kitchen', 0)} / {game_config.kitchen_daily_limit} 顿 (本次不占 normal 次数)"
        ))

    extra_lines = []

    if taste_loss_expired:
        extra_lines.append("昨天残留的味蕾丧失状态已经自然消散了。")

    if used_mode == "normal" and (not is_taste_lost) and (not original_success) and (not used_fulingdan):
        extra_lines.append(f"连败保底: {daily.get('bad_streak', 0)}/3")

    if used_mode == "kitchen_chaos_bonus":
        extra_lines.append("本次为世界事件额外机会，不占今日正常饭次，也不占本餐餐次。")

    # 只有当前仍带有味蕾丧失状态时，才展示状态文案
    if buffs.get("taste_loss_active", False):
        state_text = resp_manager.get_random_from("entertainment.kitchen_taste_loss_state", default="")
        if state_text:
            extra_lines.append(state_text)

    extra_text = "\n".join(extra_lines) if extra_lines else None

    footer = f"{get_next_meal_hint()}"
    if ctx.is_private:
        footer += f"\n 当前操作群：{ctx.group_name}"

    card = ui.render_result_card(
        f"无限大人的厨房 · {result_title}",
        result_desc,
        stats=stats,
        tags=result_tags if result_tags else None,
        extra=extra_text,
        footer=footer,
    )
    await kitchen_cmd.finish(MessageSegment.at(uid) + "\n" + card)