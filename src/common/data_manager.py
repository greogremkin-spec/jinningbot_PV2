""" 晋宁会馆·秃贝五边形 5.0 数据管理器 —— 全系统心脏（收口增强版）
设计目标：
1. 正式采用 v5.0 数据模型
2. 明确分层：
   - members_db: 用户全局资料 + 各群展示资料
   - spirit_db: 用户全局统计 + 各群修行档
   - bot_status: 全局唯一状态（祭坛 / 世界事件 / 人格 / 宣传等）
   - group_status/{gid}.json: 群级运行时状态
3. 提供正式异步 API：
   - member global / group profile
   - spirit global / group spirit
   - group status
   - bot status
   - sharing / private bind
   - projection / stat
4. 保持：
   - 启动全量加载
   - 内存态读写
   - 脏标记
   - 原子落盘
   - 定时持久化
5. 当前版本增强：
   - 继续强化可写 full 档 helper
   - 补充更稳的 projection / bot_status / 状态清理辅助
   - 保持对现有业务调用兼容
"""
from __future__ import annotations

import os
import ujson as json
import aiofiles
import asyncio
import logging
import shutil
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger("tubei.data")

# ================================================================
# 路径常量
# ================================================================
DATA_DIR = Path("data")
BACKUP_DIR = DATA_DIR / "backups"
LOG_DIR = DATA_DIR / "logs"
GROUP_STATUS_DIR = DATA_DIR / "group_status"

MEMBERS_DB_PATH = DATA_DIR / "members_db.json"
SPIRIT_DB_PATH = DATA_DIR / "spirit_db.json"
BOT_STATUS_PATH = DATA_DIR / "bot_status.json"

PERSIST_INTERVAL = 30
DEFAULT_SCHEMA_VERSION = "5.0"


class DataManager:
    """v5.0 正式版数据中心（收口增强版）"""

    _instance: Optional["DataManager"] = None

    def __init__(self):
        self._lock = asyncio.Lock()

        self._members: Dict[str, Any] = {}
        self._spirits: Dict[str, Any] = {}
        self._status: Dict[str, Any] = {}
        self._group_status: Dict[int, Dict[str, Any]] = {}

        self._dirty_members = False
        self._dirty_spirits = False
        self._dirty_status = False
        self._dirty_group_status: Dict[int, bool] = {}

        self._persist_task: Optional[asyncio.Task] = None
        self._ensure_infrastructure()

    @classmethod
    def get_instance(cls) -> "DataManager":
        if cls._instance is None:
            cls._instance = DataManager()
        return cls._instance

    # ================================================================
    # 默认结构
    # ================================================================
    def _default_member(self, qq: str) -> Dict[str, Any]:
        return {
            "qq": str(qq),
            "spirit_name": "",
            "global_identity": "guest",
            "registered_groups": [],
            "primary_group": 0,
            "private_bind_group": 0,
            "sharing_config": None,
            "global_profile": {
                "register_time": 0,
                "status": "active",
                "last_active": 0,
                "public_visible": True,
                "oc_details": {},
                "web_synced": False,
                "web_profile_url": "",
            },
            "group_profiles": {},
        }

    def _default_spirit_user(self) -> Dict[str, Any]:
        return {
            "global": {
                "altar_contributions": 0,
                "total_heixiu_count": 0,
            },
            "group_data": {},
        }

    def _default_full_group_spirit(self) -> Dict[str, Any]:
        return {
            "_type": "full",
            "sp": 0,
            "level": 1,
            "items": {},
            "buffs": {},
            "daily_counts": {},
            "expedition": {"status": "idle"},
            "achievements": [],
            "heixiu_count": 0,
        }

    def _default_group_status(self, group_id: int) -> Dict[str, Any]:
        return {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "group_id": int(group_id),
            "heixiu_state": {
                "active": False,
                "heixiu_type": "normal",
                "start_time": 0,
                "expire_time": 0,
            },
        }

    def _default_bot_status(self) -> Dict[str, Any]:
        return {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "altar": {
                "energy": 0,
                "last_buff_time": 0,
            },
            "personality": {
                "current": "normal",
            },
            "promotion": {
                "enabled": False,
                "chance": 0.20,
                "content": "",
            },
            "world_events": {
                "spirit_tide": {"active": False, "start_time": 0, "end_time": 0},
                "heixiu_frenzy": {"active": False, "start_time": 0, "end_time": 0},
                "kitchen_chaos": {"active": False, "start_time": 0, "end_time": 0},
            },
        }

    # ================================================================
    # 结构规范化
    # ================================================================
    def _normalize_member_record(self, qq: str, record: Any) -> Dict[str, Any]:
        if not isinstance(record, dict):
            return self._default_member(qq)

        fixed = self._default_member(qq)
        fixed.update(record)

        base_global = self._default_member(qq)["global_profile"]
        current_global = fixed.get("global_profile", {})
        if not isinstance(current_global, dict):
            current_global = {}
        base_global.update(current_global)
        fixed["global_profile"] = base_global

        group_profiles = fixed.get("group_profiles", {})
        if not isinstance(group_profiles, dict):
            group_profiles = {}
        fixed["group_profiles"] = group_profiles

        reg_groups = fixed.get("registered_groups", [])
        if not isinstance(reg_groups, list):
            reg_groups = []
        fixed["registered_groups"] = sorted({
            int(g) for g in reg_groups
            if isinstance(g, int) or str(g).isdigit()
        })

        if not fixed.get("primary_group") and fixed["registered_groups"]:
            fixed["primary_group"] = fixed["registered_groups"][0]

        # 避免绑定到未登记群
        bind_gid = int(fixed.get("private_bind_group", 0) or 0)
        if bind_gid and bind_gid not in fixed["registered_groups"]:
            fixed["private_bind_group"] = 0

        return fixed

    def _normalize_spirit_record(self, uid: str, record: Any) -> Dict[str, Any]:
        if not isinstance(record, dict):
            return self._default_spirit_user()

        fixed = self._default_spirit_user()
        fixed.update(record)

        base_global = self._default_spirit_user()["global"]
        current_global = fixed.get("global", {})
        if not isinstance(current_global, dict):
            current_global = {}
        base_global.update(current_global)
        fixed["global"] = base_global

        group_data = fixed.get("group_data", {})
        if not isinstance(group_data, dict):
            group_data = {}
        fixed["group_data"] = group_data

        normalized_group_data = {}
        for gid_str, profile in group_data.items():
            gid_key = str(gid_str)
            if not isinstance(profile, dict):
                continue

            if profile.get("_type") == "pointer":
                normalized_group_data[gid_key] = {
                    "_type": "pointer",
                    "_master_group": str(profile.get("_master_group", "")),
                }
            else:
                full_profile = self._default_full_group_spirit()
                full_profile.update(profile)
                full_profile["_type"] = "full"
                normalized_group_data[gid_key] = full_profile

        fixed["group_data"] = normalized_group_data
        return fixed

    def _normalize_group_status_record(self, gid: int, record: Any) -> Dict[str, Any]:
        if not isinstance(record, dict):
            return self._default_group_status(gid)

        fixed = self._default_group_status(gid)
        fixed.update(record)

        base_heixiu = self._default_group_status(gid)["heixiu_state"]
        current_heixiu = fixed.get("heixiu_state", {})
        if not isinstance(current_heixiu, dict):
            current_heixiu = {}
        base_heixiu.update(current_heixiu)
        fixed["heixiu_state"] = base_heixiu

        return fixed

    def _normalize_bot_status_record(self, record: Any) -> Dict[str, Any]:
        if not isinstance(record, dict):
            return self._default_bot_status()

        fixed = self._default_bot_status()
        fixed.update(record)

        for key in ("altar", "personality", "promotion", "world_events"):
            base = self._default_bot_status()[key]
            current = fixed.get(key, {})
            if not isinstance(current, dict):
                current = {}
            merged = dict(base)
            merged.update(current)
            fixed[key] = merged

        # 兼容字段同步
        fixed["persona"] = fixed.get("personality", {}).get("current", "normal")
        fixed["altar_energy"] = fixed.get("altar", {}).get("energy", 0)

        return fixed

    # ================================================================
    # 基础设施
    # ================================================================
    def _ensure_infrastructure(self):
        for d in [DATA_DIR, BACKUP_DIR, LOG_DIR, GROUP_STATUS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

        defaults = {
            MEMBERS_DB_PATH: {},
            SPIRIT_DB_PATH: {},
            BOT_STATUS_PATH: self._default_bot_status(),
        }

        for path, default_data in defaults.items():
            if not path.exists():
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(default_data, f, ensure_ascii=False, indent=2)
                logger.info(f"[DataManager] 创建默认文件: {path}")

    def _get_group_status_path(self, group_id: int) -> Path:
        return GROUP_STATUS_DIR / f"{int(group_id)}.json"

    # ================================================================
    # 同步读取与恢复
    # ================================================================
    def _load_json_sync(self, path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    logger.warning(f"[DataManager] {path.name} 为空文件，使用空字典")
                    return {}
                return json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"[DataManager] {path.name} 解析失败: {e}，尝试备份恢复...")
            return self._try_restore_from_backup(path)
        except FileNotFoundError:
            logger.warning(f"[DataManager] {path.name} 不存在，使用空字典")
            return {}
        except Exception as e:
            logger.error(f"[DataManager] {path.name} 读取异常: {e}")
            return self._try_restore_from_backup(path)

    def _try_restore_from_backup(self, path: Path) -> dict:
        bak_path = path.with_suffix(".json.bak")
        if bak_path.exists():
            try:
                with open(bak_path, "r", encoding="utf-8") as f:
                    data = json.loads(f.read())
                shutil.copy2(str(bak_path), str(path))
                logger.info(f"[DataManager] 从备份 {bak_path.name} 恢复成功")
                return data
            except Exception as e:
                logger.error(f"[DataManager] 备份也无法读取: {e}")

        logger.warning(f"[DataManager] {path.name} 无法恢复，使用空字典")
        return {}

    # ================================================================
    # 启动与关闭
    # ================================================================
    def load_all_sync(self):
        self._members = self._load_json_sync(MEMBERS_DB_PATH)
        self._spirits = self._load_json_sync(SPIRIT_DB_PATH)
        self._status = self._load_json_sync(BOT_STATUS_PATH)

        self._group_status = {}
        if GROUP_STATUS_DIR.exists():
            for f in GROUP_STATUS_DIR.iterdir():
                if f.suffix != ".json":
                    continue
                try:
                    gid = int(f.stem)
                except ValueError:
                    continue
                self._group_status[gid] = self._load_json_sync(f)

        self._ensure_runtime_defaults()

        logger.info(
            f"[DataManager] 数据加载完成 | "
            f"成员: {len(self._members)} | "
            f"灵力档案: {len(self._spirits)} | "
            f"群状态: {len(self._group_status)}"
        )

    def _ensure_runtime_defaults(self):
        self._status = self._normalize_bot_status_record(self._status)

        normalized_members = {}
        for uid, member in self._members.items():
            normalized_members[str(uid)] = self._normalize_member_record(str(uid), member)
        self._members = normalized_members

        normalized_spirits = {}
        for uid, spirit_user in self._spirits.items():
            normalized_spirits[str(uid)] = self._normalize_spirit_record(str(uid), spirit_user)
        self._spirits = normalized_spirits

        normalized_group_status = {}
        for gid, gs in self._group_status.items():
            normalized_group_status[int(gid)] = self._normalize_group_status_record(int(gid), gs)
        self._group_status = normalized_group_status

    def start_persist_loop(self):
        if self._persist_task is None or self._persist_task.done():
            self._persist_task = asyncio.create_task(self._persist_loop())
            logger.info(f"[DataManager] 持久化循环已启动 (间隔 {PERSIST_INTERVAL}s)")

    async def _persist_loop(self):
        while True:
            try:
                await asyncio.sleep(PERSIST_INTERVAL)
                await self.persist_all()
            except asyncio.CancelledError:
                await self.persist_all()
                break
            except Exception as e:
                logger.error(f"[DataManager] 持久化循环异常: {e}")

    async def shutdown(self):
        if self._persist_task and not self._persist_task.done():
            self._persist_task.cancel()
            try:
                await self._persist_task
            except asyncio.CancelledError:
                pass

        await self.persist_all()
        logger.info("[DataManager] 关闭完成，所有数据已安全落盘")

    # ================================================================
    # 原子写入
    # ================================================================
    async def _atomic_write(self, path: Path, data: dict):
        tmp_path = path.with_suffix(".json.tmp")
        bak_path = path.with_suffix(".json.bak")
        content = json.dumps(data, ensure_ascii=False, indent=2)

        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(content)
            await f.flush()

        with open(tmp_path, "r+", encoding="utf-8") as f_sync:
            f_sync.flush()
            os.fsync(f_sync.fileno())

        if path.exists():
            try:
                shutil.copy2(str(path), str(bak_path))
            except Exception as e:
                logger.warning(f"[DataManager] 备份 {path.name} 失败: {e}")

        os.replace(str(tmp_path), str(path))

    async def persist_all(self):
        async with self._lock:
            member_dirty = self._dirty_members
            spirit_dirty = self._dirty_spirits
            status_dirty = self._dirty_status
            group_dirty_ids = [gid for gid, dirty in self._dirty_group_status.items() if dirty]

            members_snapshot = deepcopy(self._members) if member_dirty else None
            spirits_snapshot = deepcopy(self._spirits) if spirit_dirty else None
            status_snapshot = deepcopy(self._status) if status_dirty else None
            group_snapshots = {gid: deepcopy(self._group_status[gid]) for gid in group_dirty_ids}

            self._dirty_members = False
            self._dirty_spirits = False
            self._dirty_status = False
            for gid in group_dirty_ids:
                self._dirty_group_status[gid] = False

        try:
            if member_dirty and members_snapshot is not None:
                await self._atomic_write(MEMBERS_DB_PATH, members_snapshot)
            if spirit_dirty and spirits_snapshot is not None:
                await self._atomic_write(SPIRIT_DB_PATH, spirits_snapshot)
            if status_dirty and status_snapshot is not None:
                await self._atomic_write(BOT_STATUS_PATH, status_snapshot)
            for gid, data in group_snapshots.items():
                await self._atomic_write(self._get_group_status_path(gid), data)
        except Exception as e:
            logger.error(f"[DataManager] 持久化失败: {e}")
            async with self._lock:
                if member_dirty:
                    self._dirty_members = True
                if spirit_dirty:
                    self._dirty_spirits = True
                if status_dirty:
                    self._dirty_status = True
                for gid in group_dirty_ids:
                    self._dirty_group_status[gid] = True

    # ================================================================
    # member global / group profile
    # ================================================================
    async def get_all_members(self) -> Dict[str, Any]:
        return deepcopy(self._members)

    async def get_member_info(self, qq: str) -> Optional[Dict[str, Any]]:
        data = self._members.get(str(qq))
        return deepcopy(data) if data else None

    async def get_member_global(self, qq: str) -> Optional[Dict[str, Any]]:
        member = self._members.get(str(qq))
        if not member:
            return None

        result = {
            "qq": member.get("qq", str(qq)),
            "spirit_name": member.get("spirit_name", ""),
            "global_identity": member.get("global_identity", "guest"),
            "registered_groups": member.get("registered_groups", []),
            "primary_group": member.get("primary_group", 0),
            "private_bind_group": member.get("private_bind_group", 0),
            "sharing_config": member.get("sharing_config"),
            "global_profile": member.get("global_profile", {}),
        }
        return deepcopy(result)

    async def update_member_global(self, qq: str, patch: Dict[str, Any]):
        uid = str(qq)
        async with self._lock:
            member = self._members.get(uid, self._default_member(uid))
            member.update({k: v for k, v in patch.items() if k != "group_profiles"})
            self._members[uid] = self._normalize_member_record(uid, member)
            self._dirty_members = True

    async def get_member_group_profile(self, qq: str, group_id: int) -> Optional[Dict[str, Any]]:
        member = self._members.get(str(qq))
        if not member:
            return None
        profile = member.get("group_profiles", {}).get(str(int(group_id)))
        return deepcopy(profile) if profile else None

    async def update_member_group_profile(self, qq: str, group_id: int, patch: Dict[str, Any]):
        uid = str(qq)
        gid = int(group_id)

        async with self._lock:
            member = self._members.get(uid, self._default_member(uid))
            group_profiles = member.setdefault("group_profiles", {})

            profile = group_profiles.get(str(gid), {})
            profile.update(patch)
            group_profiles[str(gid)] = profile

            registered = set(member.get("registered_groups", []))
            if gid > 0:
                registered.add(gid)
            member["registered_groups"] = sorted(registered)

            if not member.get("primary_group") and gid > 0:
                member["primary_group"] = gid
            if not member.get("private_bind_group") and gid > 0:
                member["private_bind_group"] = gid
            if patch.get("spirit_name"):
                member["spirit_name"] = patch["spirit_name"]

            self._members[uid] = self._normalize_member_record(uid, member)
            self._dirty_members = True

    async def get_registered_groups(self, qq: str) -> List[int]:
        member = self._members.get(str(qq), {})
        return list(member.get("registered_groups", []))

    async def is_registered_in_group(self, qq: str, group_id: int) -> bool:
        uid = str(qq)
        gid = int(group_id)

        member = self._members.get(uid)
        if not member:
            return False

        status = member.get("global_profile", {}).get("status", "active")
        if status == "deleted":
            return False

        if gid in member.get("registered_groups", []):
            return True
        if str(gid) in member.get("group_profiles", {}):
            return True
        return False

    async def update_member_identity(self, qq: str, new_identity: str, group_id: Optional[int] = None) -> bool:
        uid = str(qq)

        async with self._lock:
            member = self._members.get(uid)
            if member is None:
                return False

            changed = False

            if member.get("global_identity") != new_identity:
                member["global_identity"] = new_identity
                changed = True

            if group_id is not None:
                gid = str(int(group_id))
                gp = member.setdefault("group_profiles", {})
                profile = gp.get(gid, {})
                if profile.get("identity") != new_identity:
                    profile["identity"] = new_identity
                    gp[gid] = profile
                    changed = True

                registered = set(member.get("registered_groups", []))
                registered.add(int(group_id))
                member["registered_groups"] = sorted(registered)

            if changed:
                member["identity_updated_at"] = int(time.time())
                self._members[uid] = self._normalize_member_record(uid, member)
                self._dirty_members = True

            return changed

    async def update_member_last_active(self, qq: str):
        uid = str(qq)
        async with self._lock:
            member = self._members.get(uid)
            if not member:
                return
            member.setdefault("global_profile", {})
            member["global_profile"]["last_active"] = int(time.time())
            self._members[uid] = self._normalize_member_record(uid, member)
            self._dirty_members = True

    async def freeze_member_archive(self, qq: str) -> bool:
        """冻结用户整套档案（用户级全档案冻结）。"""
        uid = str(qq)

        async with self._lock:
            member = self._members.get(uid)
            if not member:
                return False

            member.setdefault("global_profile", {})
            member["global_profile"]["status"] = "deleted"
            member["private_bind_group"] = 0
            member["sharing_config"] = None

            self._members[uid] = self._normalize_member_record(uid, member)
            self._dirty_members = True

            user_spirit = self._spirits.get(uid)
            if user_spirit:
                group_data = user_spirit.setdefault("group_data", {})
                gid_keys = list(group_data.keys())

                for gid_key in gid_keys:
                    profile = group_data.get(gid_key, {})
                    if not isinstance(profile, dict):
                        continue
                    if profile.get("_type") != "pointer":
                        continue

                    master_gid = str(profile.get("_master_group", ""))
                    master_profile = group_data.get(master_gid, {})
                    if isinstance(master_profile, dict) and master_profile.get("_type") == "full":
                        group_data[gid_key] = self._extract_clean_full_profile_copy(master_profile)
                    else:
                        group_data[gid_key] = self._default_full_group_spirit()

                for gid_key, profile in list(group_data.items()):
                    if not isinstance(profile, dict):
                        continue
                    if profile.get("_type") != "full":
                        continue
                    exped = profile.get("expedition", {})
                    if isinstance(exped, dict) and exped.get("status") == "exploring":
                        profile["expedition"] = {"status": "idle"}
                    group_data[gid_key] = profile

                self._spirits[uid] = self._normalize_spirit_record(uid, user_spirit)
                self._dirty_spirits = True

            return True

    async def delete_member(self, qq: str):
        """兼容旧接口：等价于冻结整套档案。"""
        await self.freeze_member_archive(qq)

    async def unfreeze_member_archive(self, qq: str) -> bool:
        """解冻用户整套档案。"""
        uid = str(qq)

        async with self._lock:
            member = self._members.get(uid)
            if not member:
                return False

            member.setdefault("global_profile", {})
            status = member["global_profile"].get("status", "active")
            if status != "deleted":
                return False

            member["global_profile"]["status"] = "active"
            self._members[uid] = self._normalize_member_record(uid, member)
            self._dirty_members = True
            return True

    async def get_active_members(self) -> Dict[str, Any]:
        result = {}
        for qq, data in self._members.items():
            status = data.get("global_profile", {}).get("status", "active")
            if status != "deleted":
                result[qq] = deepcopy(data)
        return result

    async def get_core_members(self) -> Dict[str, Any]:
        result = {}
        core_identities = {"core_member", "admin", "decision"}
        for qq, data in self._members.items():
            status = data.get("global_profile", {}).get("status", "active")
            if status == "deleted":
                continue
            gid_identity = data.get("global_identity", "guest")
            if gid_identity in core_identities:
                result[qq] = deepcopy(data)
        return result

    async def get_group_members(self, group_id: int) -> Dict[str, Any]:
        result = {}
        gid = int(group_id)
        gid_str = str(gid)

        for qq, data in self._members.items():
            status = data.get("global_profile", {}).get("status", "active")
            if status == "deleted":
                continue

            if gid in data.get("registered_groups", []):
                result[qq] = deepcopy(data)
                continue
            if gid_str in data.get("group_profiles", {}):
                result[qq] = deepcopy(data)

        return result

    # ================================================================
    # private bind
    # ================================================================
    async def get_private_bind_group(self, qq: str) -> Optional[int]:
        member = self._members.get(str(qq))
        if not member:
            return None
        gid = member.get("private_bind_group", 0)
        return int(gid) if gid else None

    async def set_private_bind_group(self, qq: str, group_id: int):
        uid = str(qq)
        gid = int(group_id)

        async with self._lock:
            member = self._members.get(uid)
            if member is None:
                raise ValueError(f"用户 {uid} 不存在，无法设置私聊绑定")

            registered_groups = set(member.get("registered_groups", []))
            if gid not in registered_groups:
                raise ValueError(f"用户 {uid} 未登记群 {gid}，不可绑定")

            member["private_bind_group"] = gid
            if not member.get("primary_group"):
                member["primary_group"] = gid

            self._members[uid] = self._normalize_member_record(uid, member)
            self._dirty_members = True

    # ================================================================
    # sharing / pointer
    # ================================================================
    async def resolve_pointer(self, qq: str, group_id: int) -> Tuple[Dict[str, Any], int]:
        """解析指针，返回 (实际群档数据, 实际群号)。"""
        uid = str(qq)
        gid = int(group_id)

        user_data = self._spirits.get(uid)
        if not user_data:
            return {}, gid

        group_data = user_data.get("group_data", {})
        profile = group_data.get(str(gid), {})

        if isinstance(profile, dict) and profile.get("_type") == "pointer":
            master_gid = int(profile.get("_master_group", 0))
            if master_gid <= 0:
                return {}, gid

            master_profile = group_data.get(str(master_gid), {})
            if not isinstance(master_profile, dict) or master_profile.get("_type") != "full":
                logger.warning(f"[DataManager] 共享档损坏：{uid}@{gid} -> {master_gid}")
                return {}, gid

            clean = deepcopy(master_profile)
            clean.pop("_type", None)
            clean.pop("_master_group", None)
            return clean, master_gid

        if isinstance(profile, dict) and profile.get("_type") == "full":
            clean = deepcopy(profile)
            clean.pop("_type", None)
            clean.pop("_master_group", None)
            return clean, gid

        return {}, gid

    def _extract_clean_full_profile_copy(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """将一个 full 档清洗并复制为可独立保存的 full 档。"""
        if not isinstance(profile, dict):
            return self._default_full_group_spirit()

        copied = deepcopy(profile)
        copied.pop("_master_group", None)
        copied["_type"] = "full"

        normalized = self._default_full_group_spirit()
        normalized.update(copied)
        normalized["_type"] = "full"
        return normalized

    async def create_sharing(self, qq: str, master_group: int, slave_group: int) -> bool:
        uid = str(qq)
        master_gid = int(master_group)
        slave_gid = int(slave_group)

        if master_gid == slave_gid:
            raise ValueError("主档群和副档群不能相同")

        async with self._lock:
            user_spirit = self._spirits.get(uid, self._default_spirit_user())
            group_data = user_spirit.setdefault("group_data", {})

            master_profile = group_data.get(str(master_gid))
            if not master_profile or master_profile.get("_type") != "full":
                raise ValueError("主档必须存在且必须是 full 档")

            slave_profile = group_data.get(str(slave_gid))
            if slave_profile and slave_profile.get("_type") == "pointer":
                raise ValueError("副档当前已经是共享指针档")

            group_data[str(slave_gid)] = {
                "_type": "pointer",
                "_master_group": str(master_gid),
            }

            self._spirits[uid] = self._normalize_spirit_record(uid, user_spirit)
            self._dirty_spirits = True

            member = self._members.get(uid)
            if member:
                linked = set((member.get("sharing_config") or {}).get("linked_groups", []))
                linked.add(slave_gid)
                member["sharing_config"] = {
                    "enabled": True,
                    "master_group": master_gid,
                    "linked_groups": sorted(linked),
                    "created_at": int(time.time()),
                }
                self._members[uid] = self._normalize_member_record(uid, member)
                self._dirty_members = True

            return True

    async def remove_sharing(self, qq: str, group_id: int) -> bool:
        uid = str(qq)
        gid = int(group_id)

        async with self._lock:
            user_spirit = self._spirits.get(uid)
            if not user_spirit:
                return False

            group_data = user_spirit.setdefault("group_data", {})
            target = group_data.get(str(gid), {})
            if target.get("_type") != "pointer":
                return False

            master_gid = int(target.get("_master_group", 0))
            master_data = group_data.get(str(master_gid), {})
            if not master_data or master_data.get("_type") != "full":
                raise ValueError("共享主档不存在或非法")

            copied = deepcopy(master_data)
            copied["_type"] = "full"
            group_data[str(gid)] = copied

            self._spirits[uid] = self._normalize_spirit_record(uid, user_spirit)
            self._dirty_spirits = True

            member = self._members.get(uid)
            if member and member.get("sharing_config"):
                cfg = member["sharing_config"]
                linked = [x for x in cfg.get("linked_groups", []) if x != gid]
                if linked:
                    cfg["linked_groups"] = linked
                else:
                    member["sharing_config"] = None

                self._members[uid] = self._normalize_member_record(uid, member)
                self._dirty_members = True

            return True

    async def delete_group_archive(self, qq: str, group_id: int) -> Tuple[bool, str]:
        """删除用户在指定群的单个群档（仅允许删除独立 full 档）。"""
        uid = str(qq)
        gid = int(group_id)
        gid_str = str(gid)

        async with self._lock:
            member = self._members.get(uid)
            if not member:
                return False, "member_not_found"

            status = member.get("global_profile", {}).get("status", "active")
            if status == "deleted":
                return False, "frozen_member"

            registered_groups = set(member.get("registered_groups", []))
            group_profiles = member.get("group_profiles", {})

            if gid not in registered_groups and gid_str not in group_profiles:
                return False, "group_not_registered"

            user_spirit = self._spirits.get(uid)
            if not user_spirit:
                return False, "spirit_not_found"

            group_data = user_spirit.get("group_data", {})
            target_profile = group_data.get(gid_str)
            if not isinstance(target_profile, dict):
                return False, "spirit_not_found"
            if target_profile.get("_type") == "pointer":
                return False, "pointer_not_allowed"

            if gid_str in group_data:
                del group_data[gid_str]
            user_spirit["group_data"] = group_data
            self._spirits[uid] = self._normalize_spirit_record(uid, user_spirit)
            self._dirty_spirits = True

            if gid_str in group_profiles:
                del group_profiles[gid_str]
            member["group_profiles"] = group_profiles

            if gid in registered_groups:
                registered_groups.remove(gid)
            member["registered_groups"] = sorted(registered_groups)

            if member.get("private_bind_group", 0) == gid:
                member["private_bind_group"] = 0

            if member.get("primary_group", 0) == gid:
                remaining = sorted(registered_groups)
                member["primary_group"] = remaining[0] if remaining else 0

            if member.get("sharing_config"):
                cfg = dict(member.get("sharing_config") or {})
                linked = [x for x in cfg.get("linked_groups", []) if int(x) != gid]
                if linked:
                    cfg["linked_groups"] = linked
                    if int(cfg.get("master_group", 0) or 0) == gid:
                        member["sharing_config"] = None
                    else:
                        member["sharing_config"] = cfg
                else:
                    member["sharing_config"] = None

            self._members[uid] = self._normalize_member_record(uid, member)
            self._dirty_members = True
            return True, "ok"

    async def hard_delete_member(self, qq: str) -> bool:
        """彻底清档：物理删除整套用户档案（member + spirit）。"""
        uid = str(qq)

        async with self._lock:
            member_exists = uid in self._members
            spirit_exists = uid in self._spirits
            if not member_exists and not spirit_exists:
                return False

            if member_exists:
                del self._members[uid]
                self._dirty_members = True
            if spirit_exists:
                del self._spirits[uid]
                self._dirty_spirits = True

            return True

    # ================================================================
    # spirit 辅助：在锁内解析可写 full 档
    # ================================================================
    def _resolve_writable_group_profile_nolock(
        self,
        user_data: Dict[str, Any],
        group_id: int,
        create_if_missing: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
        """在已持锁前提下，解析到可写的 full 群档。"""
        gid = int(group_id)
        group_data = user_data.setdefault("group_data", {})

        profile = group_data.get(str(gid), {})
        actual_gid = gid

        if isinstance(profile, dict) and profile.get("_type") == "pointer":
            actual_gid = int(profile.get("_master_group", 0))
            if actual_gid <= 0:
                raise ValueError(f"共享档损坏：group {gid} 指向非法主档")
            profile = group_data.get(str(actual_gid), {})

        if not profile:
            if not create_if_missing:
                return group_data, {}, actual_gid
            profile = self._default_full_group_spirit()

        if not isinstance(profile, dict) or profile.get("_type") not in ("full", None):
            raise ValueError(f"{actual_gid} 不是可写 full 档")

        profile["_type"] = "full"
        group_data[str(actual_gid)] = profile
        return group_data, profile, actual_gid

    # ================================================================
    # spirit global / group spirit
    # ================================================================
    async def get_all_spirits(self) -> Dict[str, Any]:
        return deepcopy(self._spirits)

    async def get_spirit_global(self, qq: str) -> Dict[str, Any]:
        user_data = self._spirits.get(str(qq), self._default_spirit_user())
        return deepcopy(user_data.get("global", {}))

    async def update_spirit_global(self, qq: str, patch: Dict[str, Any]):
        uid = str(qq)

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            global_data = user_data.setdefault("global", {})
            global_data.update(patch)

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True

    async def increment_global_stat(self, qq: str, stat_key: str, amount: int = 1):
        uid = str(qq)

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            global_data = user_data.setdefault("global", {})
            global_data[stat_key] = global_data.get(stat_key, 0) + amount

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True

    async def get_global_stat(self, qq: str, stat_key: str, default: Any = 0) -> Any:
        global_data = await self.get_spirit_global(qq)
        return global_data.get(stat_key, default)

    async def set_global_stat(self, qq: str, stat_key: str, value: Any):
        await self.update_spirit_global(qq, {stat_key: value})

    async def get_spirit_data(self, qq: str, group_id: int) -> Dict[str, Any]:
        uid = str(qq)
        gid = int(group_id)

        try:
            resolved, _ = await self.resolve_pointer(uid, gid)
            return resolved if isinstance(resolved, dict) else {}
        except Exception as e:
            logger.warning(f"[DataManager] get_spirit_data 解析失败 uid={uid} gid={gid}: {e}")
            return {}

    async def update_spirit_data(self, qq: str, group_id: int, patch: Dict[str, Any]):
        uid = str(qq)
        gid = int(group_id)

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            group_data, profile, actual_gid = self._resolve_writable_group_profile_nolock(
                user_data, gid, create_if_missing=True
            )

            profile.update(patch)
            profile["_type"] = "full"
            group_data[str(actual_gid)] = profile

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True

    async def patch_spirit_data(
        self,
        qq: str,
        group_id: int,
        patch: Dict[str, Any],
        merge_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """原子更新群档数据。"""
        uid = str(qq)
        gid = int(group_id)
        merge_keys = merge_keys or []

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            group_data, profile, actual_gid = self._resolve_writable_group_profile_nolock(
                user_data, gid, create_if_missing=True
            )

            for key, value in patch.items():
                if key in merge_keys and isinstance(profile.get(key), dict) and isinstance(value, dict):
                    merged = dict(profile.get(key, {}))
                    merged.update(value)
                    profile[key] = merged
                else:
                    profile[key] = value

            profile["_type"] = "full"
            group_data[str(actual_gid)] = profile

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True
            return deepcopy(group_data[str(actual_gid)])

    async def update_spirit_items(
        self,
        qq: str,
        group_id: int,
        item_patch: Dict[str, int],
        remove_non_positive: bool = True,
    ) -> Dict[str, int]:
        """原子更新背包物品数量（按增量 patch）。"""
        uid = str(qq)
        gid = int(group_id)

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            group_data, profile, actual_gid = self._resolve_writable_group_profile_nolock(
                user_data, gid, create_if_missing=True
            )

            items = dict(profile.get("items", {}))
            for item_name, delta in item_patch.items():
                try:
                    delta = int(delta)
                except Exception:
                    continue
                items[item_name] = items.get(item_name, 0) + delta

            if remove_non_positive:
                items = {k: v for k, v in items.items() if isinstance(v, int) and v > 0}

            profile["items"] = items
            profile["_type"] = "full"
            group_data[str(actual_gid)] = profile

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True
            return deepcopy(items)

    async def add_spirit_item(self, qq: str, group_id: int, item_name: str, count: int = 1) -> Dict[str, int]:
        return await self.update_spirit_items(qq, group_id, {item_name: int(count)}, remove_non_positive=True)

    async def consume_spirit_item(self, qq: str, group_id: int, item_name: str, count: int = 1) -> Tuple[bool, Dict[str, int]]:
        """原子消耗某个物品。"""
        uid = str(qq)
        gid = int(group_id)
        need = max(1, int(count))

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            group_data, profile, actual_gid = self._resolve_writable_group_profile_nolock(
                user_data, gid, create_if_missing=True
            )

            items = dict(profile.get("items", {}))
            current = int(items.get(item_name, 0) or 0)
            if current < need:
                return False, deepcopy(items)

            remain = current - need
            if remain > 0:
                items[item_name] = remain
            else:
                items.pop(item_name, None)

            profile["items"] = items
            profile["_type"] = "full"
            group_data[str(actual_gid)] = profile

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True
            return True, deepcopy(items)

    async def update_spirit_buffs(
        self,
        qq: str,
        group_id: int,
        buff_patch: Dict[str, Any],
        remove_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """原子更新 buffs。"""
        uid = str(qq)
        gid = int(group_id)
        remove_keys = remove_keys or []

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            group_data, profile, actual_gid = self._resolve_writable_group_profile_nolock(
                user_data, gid, create_if_missing=True
            )

            buffs = dict(profile.get("buffs", {}))
            buffs.update(buff_patch)
            for key in remove_keys:
                buffs.pop(key, None)

            profile["buffs"] = buffs
            profile["_type"] = "full"
            group_data[str(actual_gid)] = profile

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True
            return deepcopy(buffs)

    async def update_spirit_daily_counts(
        self,
        qq: str,
        group_id: int,
        daily_patch: Dict[str, Any],
        merge: bool = True,
    ) -> Dict[str, Any]:
        """原子更新 daily_counts。"""
        uid = str(qq)
        gid = int(group_id)

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            group_data, profile, actual_gid = self._resolve_writable_group_profile_nolock(
                user_data, gid, create_if_missing=True
            )

            if merge:
                daily = dict(profile.get("daily_counts", {}))
                daily.update(daily_patch)
            else:
                daily = dict(daily_patch)

            profile["daily_counts"] = daily
            profile["_type"] = "full"
            group_data[str(actual_gid)] = profile

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True
            return deepcopy(daily)

    async def increment_group_stat(self, qq: str, group_id: int, stat_key: str, amount: int = 1):
        uid = str(qq)
        gid = int(group_id)

        async with self._lock:
            user_data = self._spirits.get(uid, self._default_spirit_user())
            group_data, profile, actual_gid = self._resolve_writable_group_profile_nolock(
                user_data, gid, create_if_missing=True
            )

            profile[stat_key] = profile.get(stat_key, 0) + amount
            profile["_type"] = "full"
            group_data[str(actual_gid)] = profile

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True

    async def get_group_stat(self, qq: str, group_id: int, stat_key: str, default: Any = 0) -> Any:
        spirit = await self.get_spirit_data(qq, group_id)
        return spirit.get(stat_key, default)

    async def set_group_stat(self, qq: str, group_id: int, stat_key: str, value: Any):
        await self.update_spirit_data(qq, group_id, {stat_key: value})

    async def cleanup_expired_taste_loss_for_group(self, qq: str, group_id: int) -> bool:
        """清理跨天未生效的味蕾丧失状态。"""
        uid = str(qq)
        gid = int(group_id)
        today = datetime.now().strftime("%Y-%m-%d")

        async with self._lock:
            user_data = self._spirits.get(uid)
            if not user_data:
                return False

            group_data, profile, actual_gid = self._resolve_writable_group_profile_nolock(
                user_data, gid, create_if_missing=False
            )
            if not profile:
                return False

            buffs = dict(profile.get("buffs", {}))
            if not buffs.get("taste_loss_active", False):
                return False

            loss_date = str(buffs.get("taste_loss_date", "") or "").strip()
            if not loss_date:
                return False
            if loss_date == today:
                return False

            buffs.pop("taste_loss_active", None)
            buffs.pop("taste_loss_date", None)

            profile["buffs"] = buffs
            profile["_type"] = "full"
            group_data[str(actual_gid)] = profile

            self._spirits[uid] = self._normalize_spirit_record(uid, user_data)
            self._dirty_spirits = True
            return True

    async def batch_get_spirit_projection(
        self,
        uids: List[str],
        group_id: int,
        fields: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        gid = int(group_id)
        result: Dict[str, Dict[str, Any]] = {}

        for uid in uids:
            user_data = self._spirits.get(str(uid), self._default_spirit_user())
            group_data = user_data.get("group_data", {})
            profile = group_data.get(str(gid), {})

            if isinstance(profile, dict) and profile.get("_type") == "pointer":
                master_gid = str(profile.get("_master_group", gid))
                profile = group_data.get(master_gid, {})

            if not isinstance(profile, dict):
                profile = {}

            result[str(uid)] = {f: profile.get(f) for f in fields}

        return result

    async def get_group_spirit_ranking(self, group_id: int, field: str) -> List[Tuple[str, Any]]:
        members = await self.get_group_members(group_id)
        uids = list(members.keys())
        proj = await self.batch_get_spirit_projection(uids, group_id, [field])

        rows = []
        for uid in uids:
            rows.append((uid, proj.get(uid, {}).get(field, 0)))

        rows.sort(key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)
        return rows

    # ================================================================
    # group_status
    # ================================================================
    async def get_group_status(self, group_id: int) -> Dict[str, Any]:
        gid = int(group_id)
        if gid not in self._group_status:
            async with self._lock:
                if gid not in self._group_status:
                    self._group_status[gid] = self._default_group_status(gid)
                    self._dirty_group_status[gid] = True
        return deepcopy(self._group_status[gid])

    async def update_group_status(self, group_id: int, patch: Dict[str, Any]):
        gid = int(group_id)

        async with self._lock:
            status = self._group_status.get(gid, self._default_group_status(gid))
            merged = dict(status)

            for key, value in patch.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    inner = dict(merged[key])
                    inner.update(value)
                    merged[key] = inner
                else:
                    merged[key] = value

            self._group_status[gid] = self._normalize_group_status_record(gid, merged)
            self._dirty_group_status[gid] = True

    # ================================================================
    # bot_status
    # ================================================================
    async def get_bot_status(self) -> Dict[str, Any]:
        status = deepcopy(self._status)
        if "persona" not in status:
            status["persona"] = status.get("personality", {}).get("current", "normal")
        if "altar_energy" not in status:
            status["altar_energy"] = status.get("altar", {}).get("energy", 0)
        return status

    async def update_bot_status(self, patch: Dict[str, Any]):
        """增量更新全局状态（支持结构化子对象合并）。"""
        async with self._lock:
            normalized = dict(patch)

            if "persona" in normalized:
                self._status.setdefault("personality", {})["current"] = normalized.pop("persona")
            if "altar_energy" in normalized:
                self._status.setdefault("altar", {})["energy"] = normalized.pop("altar_energy")

            merged = dict(self._status)
            for key, value in normalized.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    inner = dict(merged[key])
                    inner.update(value)
                    merged[key] = inner
                else:
                    merged[key] = value

            self._status = self._normalize_bot_status_record(merged)
            self._dirty_status = True

    async def update_altar_energy(self, delta: int):
        async with self._lock:
            altar = self._status.setdefault("altar", {})
            current = altar.get("energy", 0)
            altar["energy"] = max(0, current + delta)

            self._status["altar_energy"] = altar["energy"]
            self._status = self._normalize_bot_status_record(self._status)
            self._dirty_status = True

    async def get_altar_energy(self) -> int:
        return int(
            self._status.get("altar", {}).get(
                "energy",
                self._status.get("altar_energy", 0),
            )
        )

    async def get_world_event_status(self) -> Dict[str, Any]:
        return deepcopy(self._status.get("world_events", {}))

    async def is_daily_reset_active(self) -> bool:
        return bool(self._status.get("world_events", {}).get("daily_limits_reset", False))

    # ================================================================
    # 清洗 / 体检
    # ================================================================
    async def migrate_all_gardens(self):
        migrated_count = 0

        def _fix_garden_in_obj(obj: dict) -> bool:
            changed = False
            garden = obj.get("garden")
            if garden is None:
                return False
            if not isinstance(garden, list):
                return False

            while len(garden) < 4:
                garden.append({
                    "status": "empty",
                    "water_count": 0,
                    "last_water": "",
                })
                changed = True

            for slot in garden:
                if "last_water" not in slot:
                    slot["last_water"] = slot.pop("last_water_date", "")
                    changed = True
                slot.setdefault("water_count", 0)
                slot.setdefault("status", "empty")
                if slot.get("status") == "mature" and slot.get("water_count", 0) != 0:
                    slot["water_count"] = 0
                    changed = True

            return changed

        async with self._lock:
            for uid, data in self._spirits.items():
                changed = False
                for _, profile in data.get("group_data", {}).items():
                    if profile.get("_type") == "pointer":
                        continue
                    if _fix_garden_in_obj(profile):
                        changed = True

                if changed:
                    self._spirits[uid] = self._normalize_spirit_record(uid, data)
                    migrated_count += 1

            if migrated_count > 0:
                self._dirty_spirits = True

        logger.info(f"[DataManager] 药圃数据迁移/修正完成，共修正 {migrated_count} 位用户")

    async def migrate_member_identities(self, core_group_ids: set):
        updated_count = 0

        async with self._lock:
            for qq, data in self._members.items():
                if data.get("global_profile", {}).get("status", "active") == "deleted":
                    continue

                if "global_identity" not in data:
                    data["global_identity"] = data.get("identity", "core_member")
                    updated_count += 1

                if "registered_groups" not in data:
                    reg_group = data.get("register_group", 0)
                    data["registered_groups"] = [reg_group] if reg_group else []
                    updated_count += 1

                self._members[qq] = self._normalize_member_record(qq, data)

            if updated_count > 0:
                self._dirty_members = True

        logger.info(f"[DataManager] 成员身份迁移完成，补充/修正 {updated_count} 条")

    async def run_data_checkup(self) -> Dict[str, int]:
        result = {
            "orphan_spirit": 0,
            "empty_items_cleaned": 0,
            "empty_registered_groups_fixed": 0,
        }

        async with self._lock:
            for uid in list(self._spirits.keys()):
                if uid not in self._members:
                    result["orphan_spirit"] += 1

            for uid, data in self._spirits.items():
                changed = False
                for profile in data.get("group_data", {}).values():
                    if profile.get("_type") != "full":
                        continue

                    items = profile.get("items")
                    if isinstance(items, dict):
                        cleaned = {
                            k: v for k, v in items.items()
                            if isinstance(v, int) and v > 0
                        }
                        if cleaned != items:
                            profile["items"] = cleaned
                            result["empty_items_cleaned"] += 1
                            changed = True

                if changed:
                    self._spirits[uid] = self._normalize_spirit_record(uid, data)
                    self._dirty_spirits = True

            for uid, member in self._members.items():
                if "registered_groups" in member and not member["registered_groups"]:
                    primary = member.get("primary_group", 0)
                    if primary:
                        member["registered_groups"] = [primary]
                        self._members[uid] = self._normalize_member_record(uid, member)
                        result["empty_registered_groups_fixed"] += 1
                        self._dirty_members = True

        return result

    # ================================================================
    # 官网导出
    # ================================================================
    async def export_for_web(self, core_only: bool = True) -> Dict[str, Any]:
        members = await self.get_core_members() if core_only else await self.get_active_members()
        export_members = []

        for qq, member in members.items():
            global_profile = member.get("global_profile", {})
            if not global_profile.get("public_visible", True):
                continue

            primary_group = member.get("primary_group", 0)
            spirit = await self.get_spirit_data(qq, primary_group) if primary_group else {}
            group_profile = await self.get_member_group_profile(qq, primary_group) if primary_group else {}

            export_members.append({
                "qq": qq,
                "spirit_name": member.get("spirit_name", ""),
                "nickname": (group_profile or {}).get("nickname", ""),
                "intro": (group_profile or {}).get("intro", ""),
                "identity": member.get("global_identity", "guest"),
                "register_time": global_profile.get("register_time", 0),
                "oc_details": global_profile.get("oc_details", {}),
                "level": spirit.get("level", 1),
                "sp": spirit.get("sp", 0),
                "achievements": spirit.get("achievements", []),
                "total_meditation_count": spirit.get("total_meditation_count", 0),
                "total_sp_earned": spirit.get("total_sp_earned", 0),
                "join_date": spirit.get("join_date", ""),
                "title_history": spirit.get("title_history", []),
            })

        return {
            "version": DEFAULT_SCHEMA_VERSION,
            "exported_at": datetime.now().isoformat(),
            "member_count": len(export_members),
            "members": export_members,
            "altar_energy": await self.get_altar_energy(),
        }

    # ================================================================
    # 原始只读访问
    # ================================================================
    @property
    def members_raw(self) -> Dict[str, Any]:
        return self._members

    @property
    def spirits_raw(self) -> Dict[str, Any]:
        return self._spirits

    @property
    def status_raw(self) -> Dict[str, Any]:
        return self._status

    @property
    def group_status_raw(self) -> Dict[int, Dict[str, Any]]:
        return self._group_status


data_manager = DataManager.get_instance()