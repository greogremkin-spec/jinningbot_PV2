#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path
from copy import deepcopy
from datetime import datetime

SPIRIT_DB_PATH = Path("data/spirit_db.json")
BACKUP_PATH = Path(f"data/spirit_db.json.cleanup_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

def normalize_achievements(achs):
    if not isinstance(achs, list):
        return achs
    if not achs:
        return achs
    if isinstance(achs[0], dict):
        return achs

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
    return migrated

def main():
    if not SPIRIT_DB_PATH.exists():
        print("❌ spirit_db.json 不存在")
        return

    raw = json.loads(SPIRIT_DB_PATH.read_text(encoding="utf-8"))
    BACKUP_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已创建备份：{BACKUP_PATH}")

    changed_users = 0
    changed_profiles = 0
    fur_migrated = 0
    taste_fields_cleaned = 0
    achs_migrated = 0

    for uid, user_data in raw.items():
        if not isinstance(user_data, dict):
            continue

        group_data = user_data.get("group_data", {})
        if not isinstance(group_data, dict):
            continue

        user_changed = False

        for gid_str, profile in group_data.items():
            if not isinstance(profile, dict):
                continue
            if profile.get("_type") != "full":
                continue

            profile_changed = False

            # 1) 旧嘿咻毛球 -> 普通嘿咻毛球
            items = profile.get("items", {})
            if isinstance(items, dict):
                old_fur = items.pop("嘿咻毛球", 0)
                if isinstance(old_fur, int) and old_fur > 0:
                    items["普通嘿咻毛球"] = items.get("普通嘿咻毛球", 0) + old_fur
                    fur_migrated += old_fur
                    profile_changed = True
                profile["items"] = items

            # 2) 清理旧味蕾字段
            buffs = profile.get("buffs", {})
            if isinstance(buffs, dict):
                if "taste_loss_expire" in buffs:
                    # v5 已改为 taste_loss_active；旧时间型字段不再作为主逻辑
                    # 这里保守处理：直接删除旧字段，不自动推导 active
                    buffs.pop("taste_loss_expire", None)
                    taste_fields_cleaned += 1
                    profile_changed = True
                profile["buffs"] = buffs

            # 3) achievements 字符串列表 -> 对象列表
            achs = profile.get("achievements")
            new_achs = normalize_achievements(achs)
            if new_achs != achs:
                profile["achievements"] = new_achs
                achs_migrated += 1
                profile_changed = True

            if profile_changed:
                changed_profiles += 1
                user_changed = True

        if user_changed:
            changed_users += 1

    SPIRIT_DB_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    print("✅ 迁移完成")
    print(f"影响用户数: {changed_users}")
    print(f"影响群档数: {changed_profiles}")
    print(f"迁移旧嘿咻毛球数量: {fur_migrated}")
    print(f"清理旧味蕾字段次数: {taste_fields_cleaned}")
    print(f"成就列表对象化次数: {achs_migrated}")

if __name__ == "__main__":
    main()