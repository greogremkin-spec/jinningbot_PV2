""" 晋宁会馆·秃贝五边形 5.0 妖灵药圃 · 灵植小院（正式版）

v5.0 正式版目标：
1. 药圃数据显式作用于当前群档
2. 私聊通过绑定群操作当前群档
3. 不再依赖旧式 DataManager 兼容桥
4. 保留全部原有机制：
   - 4 格药圃
   - 播种 / 灌溉 / 收获
   - 密语系统
   - 露水凝珠自动消耗
   - 成就检查
5. 为未来增加更多植物 / schema 扩展保留清晰结构
"""

from __future__ import annotations

import time
import random
from datetime import datetime
from collections import Counter

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.params import CommandArg
from nonebot.adapters import Message

from src.common.data_manager import data_manager
from src.common.response_manager import resp_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.mutex import check_mutex, MutexError
from src.plugins.tubei_system.recorder import recorder
from src.plugins.tubei_cultivation.achievement import achievement_engine


# ==================== 指令注册 ====================

garden_cmd = on_command("药圃", aliases={"妖灵药圃", "我的药圃", "灵植小院"}, priority=5, block=True)
sow_cmd = on_command("播种", priority=5, block=True)
water_cmd = on_command("灌溉", aliases={"浇水"}, priority=5, block=True)
harvest_cmd = on_command("收获", priority=5, block=True)


# ==================== 工具函数 ====================

def _get_empty_slot() -> dict:
    return {
        "status": "empty",
        "water_count": 0,
        "last_water": "",
    }


def _ensure_garden(data: dict) -> list:
    """确保药圃数据是固定长度 list。"""
    garden = data.get("garden", [])
    if not isinstance(garden, list):
        garden = []

    while len(garden) < game_config.garden_slot_count:
        garden.append(_get_empty_slot())

    normalized = []
    for slot in garden[:game_config.garden_slot_count]:
        if not isinstance(slot, dict):
            normalized.append(_get_empty_slot())
            continue

        fixed = dict(slot)
        fixed.setdefault("status", "empty")
        fixed.setdefault("water_count", 0)
        fixed.setdefault("last_water", "")
        normalized.append(fixed)

    return normalized


def _garden_footer(ctx: GroupContext, text: str) -> str:
    if ctx.is_private:
        return f"{text}\n 当前操作群：{ctx.group_name}"
    return text


# ==================== 查看药圃 ====================

@garden_cmd.handle()
async def handle_garden(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "妖灵药圃 · 灵植小院",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await garden_cmd.finish(perm.deny_message)

    member = await data_manager.get_member_info(uid)
    if not member:
        await garden_cmd.finish(ui.info("请先建立灵力档案。"))

    group_profile = await data_manager.get_member_group_profile(uid, ctx.group_id)
    owner_name = (
        (group_profile or {}).get("spirit_name")
        or member.get("spirit_name")
        or "路人"
    )

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    garden = _ensure_garden(data)

    today = datetime.now().strftime("%Y-%m-%d")
    icons = game_config.garden_icons

    items = data.get("items", {})
    has_dew = items.get("露水凝珠", 0) > 0

    grid_cells = []
    details = []
    active_plants = []
    growth_cfg = game_config.garden_growth

    for i, slot in enumerate(garden):
        st = slot.get("status", "empty")
        icon = icons.get(st, "❓")
        grid_cells.append(f"[{i + 1}] {icon}")

        if st == "empty":
            details.append(f" [{i + 1}] 待开垦")
            continue

        plant_name = slot.get("plant_name", "未知")
        wc = int(slot.get("water_count", 0))
        lw = slot.get("last_water", "")

        is_thirsty = (lw != today and st != "mature")
        if st != "mature":
            active_plants.append((plant_name, is_thirsty))

        water_mark = "💧" if is_thirsty else ""

        if st == "seed":
            need = growth_cfg.get("seed_to_sprout", 1)
            bar = ui.render_progress_bar(
                wc, need, length=5, filled_char="🟩", empty_char="⬜"
            )
            details.append(f" [{i + 1}] 种子{water_mark}\n {bar}")
        elif st == "sprout":
            need = growth_cfg.get("sprout_to_growing", 2)
            bar = ui.render_progress_bar(
                wc, need, length=5, filled_char="🟩", empty_char="⬜"
            )
            details.append(f" [{i + 1}] 嫩芽{water_mark}\n {bar}")
        elif st == "growing":
            need = growth_cfg.get("growing_to_mature", 5)
            bar = ui.render_progress_bar(
                wc, need, length=5, filled_char="🟩", empty_char="⬜"
            )
            details.append(f" [{i + 1}] {plant_name}{water_mark}\n {bar}")
        elif st == "mature":
            details.append(f" [{i + 1}] {plant_name} ✨可收获!")
        else:
            details.append(f" [{i + 1}] {plant_name}")

    grid = ui.render_mini_grid(grid_cells, columns=2)

    whisper = ""
    if active_plants:
        plant_name, is_thirsty = random.choice(active_plants)
        key = "garden_whispers_thirsty" if is_thirsty else "garden_whispers_happy"
        whisper_text = resp_manager.get_random_from(key, name=plant_name)
        if whisper_text and not whisper_text.startswith("["):
            whisper = f"\n{ui.THIN_DIVIDER}\n {whisper_text}"

    dew_hint = ""
    if has_dew:
        dew_hint = (
            f"\n 持有露水凝珠 ×{items.get('露水凝珠', 0)}"
            f"（灌溉时自动使用，效果翻倍）"
        )

    content = f"{grid}\n{ui.THIN_DIVIDER}\n" + "\n".join(details) + dew_hint + whisper

    card = ui.render_panel(
        f"{owner_name}的妖灵药圃",
        content,
        footer=_garden_footer(ctx, " 输入 播种 | 灌溉 | 收获"),
    )
    await garden_cmd.finish(card)


# ==================== 播种 ====================

@sow_cmd.handle()
async def handle_sow(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "妖灵药圃 · 播种",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await sow_cmd.finish(perm.deny_message)

    try:
        await check_mutex(uid, ctx.group_id, "garden")
    except MutexError as e:
        await sow_cmd.finish(e.message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    garden = _ensure_garden(data)
    items = dict(data.get("items", {}))

    if items.get("神秘种子", 0) < 1:
        await sow_cmd.finish(ui.error("缺少 [神秘种子]。可通过派遣获得~"))

    target_idx = -1
    for i, slot in enumerate(garden):
        if slot.get("status", "empty") == "empty":
            target_idx = i
            break

    if target_idx == -1:
        await sow_cmd.finish(ui.error("药圃已满，请先收获成熟的灵植。"))

    items["神秘种子"] -= 1
    if items["神秘种子"] <= 0:
        del items["神秘种子"]

    plants = game_config.garden_plants
    plant_name = random.choice(list(plants.keys()))

    garden[target_idx] = {
        "status": "seed",
        "plant_name": plant_name,
        "water_count": 0,
        "last_water": "",
        "sow_time": time.time(),
    }

    await data_manager.update_spirit_data(uid, ctx.group_id, {
        "garden": garden,
        "items": items,
    })

    await sow_cmd.finish(
        ui.render_result_card(
            "妖灵药圃 · 播种",
            f"在第 {target_idx + 1} 块灵田种下了一颗种子~",
            stats=[
                ("位置", f"第 {target_idx + 1} 格"),
                ("种子", "已消耗 1 颗"),
                ("灵植", plant_name),
            ],
            footer=_garden_footer(ctx, " 输入 灌溉 浇水促进生长"),
        )
    )


# ==================== 灌溉 ====================

@water_cmd.handle()
async def handle_water(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "妖灵药圃 · 灌溉",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await water_cmd.finish(perm.deny_message)

    try:
        await check_mutex(uid, ctx.group_id, "garden")
    except MutexError as e:
        await water_cmd.finish(e.message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    garden = _ensure_garden(data)
    items = dict(data.get("items", {}))
    today = datetime.now().strftime("%Y-%m-%d")
    growth_cfg = game_config.garden_growth

    has_dew = items.get("露水凝珠", 0) > 0
    water_amount = 1
    dew_used = False

    if has_dew:
        water_amount = 2
        items["露水凝珠"] -= 1
        if items["露水凝珠"] <= 0:
            del items["露水凝珠"]
        dew_used = True

    watered_count = 0
    grow_msg = []

    for i in range(len(garden)):
        slot = garden[i]
        st = slot.get("status", "empty")
        lw = slot.get("last_water", "")

        if st in ("empty", "mature") or lw == today:
            continue

        slot["water_count"] = int(slot.get("water_count", 0)) + water_amount
        slot["last_water"] = today
        watered_count += 1

        wc = slot["water_count"]

        if st == "seed" and wc >= growth_cfg.get("seed_to_sprout", 1):
            slot["status"] = "sprout"
            slot["water_count"] = wc - growth_cfg.get("seed_to_sprout", 1)
            grow_msg.append(f"[{i + 1}] 发芽了！🌱")
            st = "sprout"
            wc = slot["water_count"]

        if st == "sprout" and wc >= growth_cfg.get("sprout_to_growing", 2):
            slot["status"] = "growing"
            slot["water_count"] = wc - growth_cfg.get("sprout_to_growing", 2)
            grow_msg.append(f"[{i + 1}] 长高了！🌿")
            st = "growing"
            wc = slot["water_count"]

        if st == "growing" and wc >= growth_cfg.get("growing_to_mature", 5):
            slot["status"] = "mature"
            slot["water_count"] = 0
            grow_msg.append(f"[{i + 1}] 成熟了！✨")

    if watered_count == 0:
        if dew_used:
            items["露水凝珠"] = items.get("露水凝珠", 0) + 1
            await data_manager.update_spirit_data(uid, ctx.group_id, {"items": items})

        msg = await resp_manager.get_text("garden.water_none")
        await water_cmd.finish(msg)

    await data_manager.update_spirit_data(uid, ctx.group_id, {
        "garden": garden,
        "items": items,
    })

    await recorder.add_event("garden_water", int(uid), {
        "count": watered_count,
        "dew_used": dew_used,
        "group_id": ctx.group_id,
    })

    feedback = resp_manager.get_random_from(
        "garden_water_feedback",
        default="💧浇水成功！",
    )

    extra_lines = []
    if dew_used:
        extra_lines.append("✨露水凝珠生效！浇水效果翻倍！")
    if grow_msg:
        extra_lines.append("✨" + "，".join(grow_msg))

    extra_text = "\n".join(extra_lines) if extra_lines else None

    await water_cmd.finish(
        ui.render_result_card(
            "妖灵药圃 · 灌溉",
            feedback,
            stats=[
                ("浇灌", f"{watered_count} 棵植物 (每棵 +{water_amount} 水量)")
            ],
            extra=extra_text,
            footer=_garden_footer(ctx, " 输入 药圃 查看状态"),
        )
    )


# ==================== 收获 ====================

@harvest_cmd.handle()
async def handle_harvest(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "妖灵药圃 · 收获",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await harvest_cmd.finish(perm.deny_message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    garden = _ensure_garden(data)
    items = dict(data.get("items", {}))

    harvested = []
    for i in range(len(garden)):
        if garden[i].get("status") == "mature":
            name = garden[i].get("plant_name", "未知灵植")
            items[name] = items.get(name, 0) + 1
            harvested.append(name)
            garden[i] = _get_empty_slot()

    if not harvested:
        await harvest_cmd.finish(ui.info("没有成熟的果实可以收获~"))

    await data_manager.update_spirit_data(uid, ctx.group_id, {
        "garden": garden,
        "items": items,
    })

    await recorder.add_event("garden_harvest", int(uid), {
        "items": harvested,
        "group_id": ctx.group_id,
    })

    await data_manager.increment_group_stat(uid, ctx.group_id, "total_harvest_count", len(harvested))

    if len(harvested) >= 4:
        await achievement_engine.try_unlock(uid, "满园春色", bot, event, group_id=ctx.group_id)

    await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)

    c = Counter(harvested)
    harvest_str = "、".join(f"{k} x{v}" for k, v in c.items())

    plants_desc = game_config.garden_plants
    desc_lines = []
    for name in c.keys():
        desc = plants_desc.get(name, "未知效果")
        desc_lines.append(f"• {name}: {desc}")

    await harvest_cmd.finish(
        ui.render_result_card(
            "妖灵药圃 · 大丰收！",
            f"共收获 {len(harvested)} 株灵植",
            stats=[("获得", harvest_str)],
            extra="\n".join(desc_lines) if desc_lines else None,
            footer=_garden_footer(ctx, " 输入 背包 查看道具 | 播种 继续种植 | 图鉴 [道具名]"),
        )
    )