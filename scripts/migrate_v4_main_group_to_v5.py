#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""秃贝五边形 v4.1 主群旧数据 -> v5.0 正式格式迁移脚本

用途：
1. 将当前仍为 v4.1 结构的 members_db.json 转成 v5.0 结构
2. 将当前仍为 v4.1 结构的 spirit_db.json 转成 v5.0 结构
3. 将 bot_status.json 补齐到 v5.0 可用结构
4. 初始化 group_status/ 主群状态文件
5. 自动备份旧数据
6. 尽量保留原数据内容，不要求玩家重新登记

适用前提：
- 当前数据主要以“主群单档”存在
- 希望将旧主群数据整体迁入 v5 模型
- 暂不处理多群历史拆分，只默认归入主群档

使用方式：
1. 先停止 bot
2. 执行：
   python scripts/migrate_v4_main_group_to_v5.py
3. 检查 data/ 输出结果
4. 再启动 v5 代码
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


# ============================================================
# 路径与常量
# ============================================================

DATA_DIR = Path("data")
GROUP_STATUS_DIR = DATA_DIR / "group_status"

MEMBERS_DB_PATH = DATA_DIR / "members_db.json"
SPIRIT_DB_PATH = DATA_DIR / "spirit_db.json"
BOT_STATUS_PATH = DATA_DIR / "bot_status.json"

DEFAULT_MAIN_GROUP_ID = 564234162
DEFAULT_SCHEMA_VERSION = "5.0"


# ============================================================
# 基础 IO
# ============================================================

def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
        return json.loads(text) if text else {}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def backup():
    """迁移前自动备份。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = DATA_DIR / f"backup_v4_before_v5_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for src in [MEMBERS_DB_PATH, SPIRIT_DB_PATH, BOT_STATUS_PATH]:
        if src.exists():
            shutil.copy2(src, backup_dir / src.name)

    print(f"✅ 已备份旧数据 -> {backup_dir}")


# ============================================================
# 数据清洗工具
# ============================================================

def normalize_items(old_data: dict):
    """清理旧 items 中 <=0 的垃圾值。"""
    items = old_data.get("items")
    if not isinstance(items, dict):
        return
    cleaned = {k: v for k, v in items.items() if isinstance(v, int) and v > 0}
    old_data["items"] = cleaned


def normalize_achievements(old_data: dict):
    """把旧 achievements 字符串列表转成标准对象列表。"""
    achs = old_data.get("achievements")
    if not isinstance(achs, list) or not achs:
        return

    if isinstance(achs[0], dict):
        return

    migrated = []
    for item in achs:
        if isinstance(item, str):
            migrated.append({
                "id": item,
                "name": item,
                "desc": "",
                "rarity": "common",
                "date": "",
            })
    old_data["achievements"] = migrated


def normalize_garden(old_data: dict):
    """修正旧药圃格式。"""
    garden = old_data.get("garden")
    if garden is None:
        return

    if isinstance(garden, dict):
        # 极旧结构：dict -> list
        garden = list(garden.values())
        old_data["garden"] = garden

    if isinstance(garden, list):
        fixed = []
        for slot in garden:
            if not isinstance(slot, dict):
                continue
            s = dict(slot)
            if "last_water" not in s:
                s["last_water"] = s.pop("last_water_date", "")
            s.setdefault("status", "empty")
            s.setdefault("water_count", 0)
            if s.get("status") == "mature":
                s["water_count"] = 0
            fixed.append(s)

        while len(fixed) < 4:
            fixed.append({
                "status": "empty",
                "water_count": 0,
                "last_water": "",
            })

        old_data["garden"] = fixed


def normalize_buffs(old_data: dict):
    """兼容旧 buff 数据。

    注意：
    - 当前不强行删除旧 taste_loss_expire
    - 因为你已经有第三阶段新逻辑，但旧数据保留无妨
    """
    buffs = old_data.get("buffs")
    if not isinstance(buffs, dict):
        return
    old_data["buffs"] = dict(buffs)


# ============================================================
# members 迁移
# ============================================================

def migrate_members(old_members: dict) -> dict:
    """将 v4 旧 members 迁移成 v5 结构。"""
    new_members = {}

    for uid, old_member in old_members.items():
        if not isinstance(old_member, dict):
            continue

        uid = str(uid)
        old_member = dict(old_member)

        spirit_name = old_member.get("spirit_name", "")
        nickname = old_member.get("nickname", "") or spirit_name
        intro = old_member.get("intro", "")
        identity = old_member.get("identity", "core_member")
        register_time = old_member.get("register_time", 0)
        last_active = old_member.get("last_active", 0)
        status = old_member.get("status", "active")

        # 旧数据一律视为主群登记档
        reg_group = old_member.get("register_group") or DEFAULT_MAIN_GROUP_ID

        new_members[uid] = {
            "qq": uid,
            "spirit_name": spirit_name,
            "global_identity": identity,
            "registered_groups": [int(reg_group)],
            "primary_group": int(reg_group),
            "private_bind_group": int(reg_group),
            "sharing_config": None,
            "global_profile": {
                "register_time": register_time,
                "status": status,
                "last_active": last_active,
                "public_visible": old_member.get("public_visible", True),
                "oc_details": old_member.get("oc_details", {}),
                "web_synced": old_member.get("web_synced", False),
                "web_profile_url": old_member.get("web_profile_url", ""),
            },
            "group_profiles": {
                str(reg_group): {
                    "spirit_name": spirit_name,
                    "nickname": nickname,
                    "intro": intro,
                    "identity": identity,
                    "register_time": register_time,
                }
            },
        }

    return new_members


# ============================================================
# spirit 迁移
# ============================================================

def migrate_spirits(old_spirits: dict) -> dict:
    """将 v4 旧 spirit 扁平结构迁移成 v5 结构。"""
    new_spirits = {}

    for uid, old_data in old_spirits.items():
        if not isinstance(old_data, dict):
            continue

        uid = str(uid)
        old_data = dict(old_data)

        normalize_items(old_data)
        normalize_achievements(old_data)
        normalize_garden(old_data)
        normalize_buffs(old_data)

        # 迁出全局统计
        altar_contrib = int(old_data.pop("altar_contributions", 0) or 0)
        total_heixiu = int(old_data.pop("heixiu_count", 0) or 0)

        # 主群档里仍需保留当前群捕捉次数
        # 如果你历史上所有嘿咻记录都来自主群，那么群级次数就等于全局次数
        old_data["heixiu_count"] = total_heixiu

        old_data["_type"] = "full"

        new_spirits[uid] = {
            "global": {
                "altar_contributions": altar_contrib,
                "total_heixiu_count": total_heixiu,
            },
            "group_data": {
                str(DEFAULT_MAIN_GROUP_ID): old_data
            },
        }

    return new_spirits


# ============================================================
# bot_status 迁移
# ============================================================

def migrate_bot_status(old_status: dict) -> dict:
    """把旧 bot_status 补成 v5 可用结构。"""
    old_status = dict(old_status or {})

    persona = old_status.pop("persona", "normal")
    altar_energy = old_status.pop("altar_energy", 0)
    promotion = old_status.pop("promotion", {"enabled": False, "chance": 0.20, "content": ""})
    old_world = old_status.pop("world_events", {}) or {}

    spirit_tide = old_world.get("spirit_tide", {"active": False})
    heixiu_frenzy = old_world.get("heixiu_frenzy", {"active": False})
    kitchen_chaos = old_world.get("kitchen_chaos", {"active": False})

    new_status = {
        "schema_version": DEFAULT_SCHEMA_VERSION,
        "altar": {
            "energy": altar_energy,
            "last_buff_time": 0,
        },
        "altar_energy": altar_energy,  # 保留兼容字段
        "personality": {
            "current": persona,
        },
        "persona": persona,  # 保留兼容字段
        "world_events": {
            "spirit_tide": {
                "active": spirit_tide.get("active", False),
                "start_time": spirit_tide.get("start_time", 0),
                "end_time": spirit_tide.get("end_time", 0),
            },
            "heixiu_frenzy": {
                "active": heixiu_frenzy.get("active", False),
                "start_time": heixiu_frenzy.get("start_time", 0),
                "end_time": heixiu_frenzy.get("end_time", 0),
            },
            "kitchen_chaos": {
                "active": kitchen_chaos.get("active", False),
                "start_time": kitchen_chaos.get("start_time", 0),
                "end_time": kitchen_chaos.get("end_time", 0),
            },
        },
        "promotion": {
            "enabled": promotion.get("enabled", False),
            "chance": promotion.get("chance", 0.20),
            "content": promotion.get("content", ""),
        },
    }

    return new_status


# ============================================================
# group_status 初始化
# ============================================================

def init_group_status(group_ids: list[int]):
    GROUP_STATUS_DIR.mkdir(parents=True, exist_ok=True)

    for gid in sorted(set(group_ids)):
        path = GROUP_STATUS_DIR / f"{gid}.json"
        if path.exists():
            continue

        save_json(path, {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "group_id": gid,
            "heixiu_state": {
                "active": False,
                "heixiu_type": "normal",
                "start_time": 0,
                "expire_time": 0,
            },
        })


# ============================================================
# 主流程
# ============================================================

def main():
    print("=== 秃贝五边形 v4.1 主群旧数据 -> v5.0 正式数据迁移开始 ===")
    print(f"默认主群号：{DEFAULT_MAIN_GROUP_ID}")
    print("")

    backup()

    old_members = load_json(MEMBERS_DB_PATH)
    old_spirits = load_json(SPIRIT_DB_PATH)
    old_status = load_json(BOT_STATUS_PATH)

    new_members = migrate_members(old_members)
    new_spirits = migrate_spirits(old_spirits)
    new_status = migrate_bot_status(old_status)

    save_json(MEMBERS_DB_PATH, new_members)
    print(f"✅ members_db 迁移完成，共 {len(new_members)} 条")

    save_json(SPIRIT_DB_PATH, new_spirits)
    print(f"✅ spirit_db 迁移完成，共 {len(new_spirits)} 条")

    save_json(BOT_STATUS_PATH, new_status)
    print("✅ bot_status 迁移完成")

    group_ids = {DEFAULT_MAIN_GROUP_ID}
    for _, member in new_members.items():
        for gid in member.get("registered_groups", []):
            group_ids.add(int(gid))

    init_group_status(list(group_ids))
    print(f"✅ group_status 初始化完成，共 {len(group_ids)} 个群")

    print("")
    print("=== 迁移全部完成 ===")
    print("请重点检查：")
    print("1. data/members_db.json")
    print("2. data/spirit_db.json")
    print("3. data/bot_status.json")
    print("4. data/group_status/")
    print("")
    print("确认无误后，再启动 v5.0 代码。")


if __name__ == "__main__":
    main()