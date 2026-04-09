""" 晋宁会馆·秃贝五边形 5.0
灵质纪事记录器（结构化收口版）

职责：
1. 按日切割 JSONL 日志文件
2. 为全项目提供统一事件记录入口
3. 对旧调用形式做兼容规范化
4. 为 reporter / 审计 / 排障 提供更稳定的事件 schema

当前统一事件结构：
{
  "ts": 1710000000,
  "type": "meditation",
  "uid": 123456,
  "module": "cultivation",
  "group_id": 564234162,
  "trace": "",
  "data": {
    ...
  }
}

兼容说明：
- 业务层仍可继续调用：
  await recorder.add_event("kitchen", 123456, {"group_id": 1, "sp_change": 2})
- recorder 会自动补：
  - module
  - 顶层 group_id
  - trace
  - data dict 规范化
"""
from __future__ import annotations

import time
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger("tubei.recorder")

LOG_DIR = Path("data/logs")
if not LOG_DIR.exists():
    LOG_DIR.mkdir(parents=True)


# ==================== 默认模块映射 ====================
EVENT_MODULE_MAP: Dict[str, str] = {
    # cultivation
    "meditation": "cultivation",
    "expedition_start": "cultivation",
    "expedition_finish": "cultivation",
    "garden_water": "cultivation",
    "garden_harvest": "cultivation",
    "unlock_location": "cultivation",
    "achievement_unlock": "cultivation",
    "use_item": "cultivation",

    # entertainment
    "kitchen": "entertainment",
    "resonance": "entertainment",
    "soulmate_resonance": "entertainment",
    "duel_win": "entertainment",
    "heixiu_capture": "entertainment",

    # admin
    "registry_new": "admin",
    "registry_update": "admin",
    "admin_action": "admin",
    "identity_upgrade": "admin",

    # system
    "spam_block": "system",
    "error": "system",
    "persona_change": "system",
}


class EventRecorder:
    """事件记录器（单例）"""

    _instance: Optional["EventRecorder"] = None

    def __init__(self):
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "EventRecorder":
        if cls._instance is None:
            cls._instance = EventRecorder()
        return cls._instance

    def _get_log_file(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return LOG_DIR / f"{today}.jsonl"

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _guess_module(self, event_type: str, data: Dict[str, Any]) -> str:
        explicit_module = data.get("module")
        if isinstance(explicit_module, str) and explicit_module.strip():
            return explicit_module.strip()
        return EVENT_MODULE_MAP.get(str(event_type), "unknown")

    def _extract_group_id(self, data: Dict[str, Any]) -> Optional[int]:
        raw_gid = data.get("group_id")
        if raw_gid is None:
            return None
        try:
            return int(raw_gid)
        except Exception:
            return None

    def _normalize_details(self, details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(details, dict):
            return {}
        return dict(details)

    def _build_record(
        self,
        event_type: str,
        user_id: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """将旧式调用规范化为稳定日志结构。"""
        payload = self._normalize_details(details)

        # 允许旧业务把 trace/module/group_id 塞在 details 里，这里统一提升
        module = self._guess_module(event_type, payload)
        group_id = self._extract_group_id(payload)
        trace = str(payload.get("trace", "") or "")

        record = {
            "ts": int(time.time()),
            "type": str(event_type),
            "uid": self._safe_int(user_id, 0),
            "module": module,
            "group_id": group_id,
            "trace": trace,
            "data": payload,
        }
        return record

    async def add_event(
        self,
        event_type: str,
        user_id: int,
        details: Optional[Dict[str, Any]] = None,
    ):
        """记录一条事件"""
        record = self._build_record(event_type, user_id, details)

        async with self._lock:
            try:
                log_file = self._get_log_file()
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.error(f"[Recorder] 写入失败: {e}")

    async def add_error(
        self,
        user_id: int = 0,
        err: str = "",
        *,
        group_id: Optional[int] = None,
        module: str = "system",
        trace: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ):
        """错误事件快捷入口。"""
        payload: Dict[str, Any] = dict(extra or {})
        if group_id is not None:
            payload["group_id"] = int(group_id)
        payload["module"] = module
        payload["trace"] = trace
        payload["err"] = str(err)

        await self.add_event("error", int(user_id or 0), payload)


recorder = EventRecorder.get_instance()