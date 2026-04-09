""" 晋宁会馆·秃贝五边形 5.0
文案管理器

职责：
1. 启动时一次性加载 responses.yaml 到内存
2. 提供统一的文案获取接口（支持 dot 路径、随机选择、模板填充）
3. 支持按群层级读取分层文案（core / allied / public / unbound）
4. 所有模块必须通过此管理器获取文案，禁止直接读 yaml

接口说明：
- get_text(key_path, args=None, default=...)                获取单条文案（列表则随机选一条）
- get_list(key_path, default=...)                          获取完整列表
- get_random_from(key_path, default=..., **kwargs)        从列表随机选一条并格式化
- get_value(key_path, default=None)                        获取原始值

- get_tiered_value(key_path, tier, default=None)           获取分层原始值
- get_tiered_list(key_path, tier, default=...)             获取分层列表
- get_tiered_text(key_path, tier, args=None, default=...)  获取分层单条文案
- get_tiered_random_from(key_path, tier, default=..., **kwargs)
                                                          获取分层随机文案

- reload()                                                热重载文案文件
"""
from __future__ import annotations

import yaml
import random
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("tubei.response")
RESPONSES_PATH = Path("config/responses.yaml")

# 哨兵值：区分“调用方没传 default”和“明确传了 default=''”
_MISSING = object()


class ResponseManager:
    """单例文案管理器。"""

    _instance: Optional["ResponseManager"] = None

    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._load()

    @classmethod
    def get_instance(cls) -> "ResponseManager":
        if cls._instance is None:
            cls._instance = ResponseManager()
        return cls._instance

    def _load(self):
        """加载 responses.yaml"""
        if not RESPONSES_PATH.exists():
            logger.warning(f"[ResponseManager] {RESPONSES_PATH} 不存在！")
            self._data = {}
            return

        try:
            with open(RESPONSES_PATH, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

            total = self._count_entries(self._data)
            logger.info(
                f"[ResponseManager] 文案加载完成 | "
                f"顶层键: {list(self._data.keys())} | "
                f"总条目: {total}"
            )
        except Exception as e:
            logger.error(f"[ResponseManager] 加载失败: {e}")
            self._data = {}

    def _count_entries(self, data: Any, depth: int = 0) -> int:
        """递归统计文案条目总数。"""
        if depth > 8:
            return 0
        if isinstance(data, dict):
            return sum(self._count_entries(v, depth + 1) for v in data.values())
        if isinstance(data, list):
            return len(data)
        if isinstance(data, str):
            return 1
        return 0

    def reload(self):
        """热重载文案文件（管理员可通过 /重载配置 触发）。"""
        self._load()
        logger.info("[ResponseManager] 文案已热重载")

    # ================================================================
    # 路径解析
    # ================================================================
    def _resolve_path(self, key_path: str) -> Any:
        """解析 dot 路径到对应数据。

        示例：
        "cultivation.meditate_success" -> self._data["cultivation"]["meditate_success"]
        "fortune_yi" -> self._data["fortune_yi"]
        """
        keys = key_path.split(".")
        data = self._data
        for k in keys:
            if isinstance(data, dict):
                data = data.get(k)
            else:
                return None
            if data is None:
                return None
        return data

    # ================================================================
    # 内部工具
    # ================================================================
    def _format_text(self, text: Any, args: Optional[Dict[str, Any]] = None) -> str:
        """将任意对象安全格式化为字符串。"""
        if args is None:
            args = {}

        if text is None:
            return ""

        if not isinstance(text, str):
            text = str(text)

        try:
            return text.format(**args)
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"[ResponseManager] 格式化失败 args={args}: {e}")
            return text

    def _warn_missing_key(self, key_path: str):
        logger.warning(f"[ResponseManager] 文案缺失: {key_path}")

    def _warn_empty_list(self, key_path: str):
        logger.warning(f"[ResponseManager] 列表为空或不存在: {key_path}")

    def _select_tier_block(self, block: Any, tier: str) -> Any:
        """从 tier 分层结构中取出当前层级内容。

        支持结构示例：
        fortune:
          yi:
            core: [...]
            allied: [...]
            public: [...]
            unbound: [...]
            default: [...]

        回退顺序：
        - core    -> core / default / public
        - allied  -> allied / default / public
        - public  -> public / default
        - unbound -> unbound / default / public

        兼容说明：
        - 若 block 不是 dict，则直接返回原值
        - 若 block 是 dict 但不包含 tier 键，则视为普通 dict（例如旧版 normal 结构）
        """
        if not isinstance(block, dict):
            return block

        tier = (tier or "public").strip().lower()

        fallback_order = {
            "core": ["core", "default", "public"],
            "allied": ["allied", "default", "public"],
            "public": ["public", "default"],
            "unbound": ["unbound", "default", "public"],
            "private": ["unbound", "default", "public"],
        }.get(tier, [tier, "default", "public"])

        for key in fallback_order:
            if key in block:
                return block[key]

        # 如果是 dict 但不含 tier 键，视为普通 dict（兼容旧结构）
        return block

    # ================================================================
    # 公共接口
    # ================================================================
    async def get_text(
        self,
        key_path: str,
        args: Optional[Dict[str, Any]] = None,
        default: Any = _MISSING,
    ) -> str:
        """获取文案文本。

        行为：
        - 字符串：直接返回
        - 列表：随机取一条
        - 字典：优先取 normal；否则返回 default/空字符串
        - 缺失：不再向用户暴露 [文案缺失: xxx]，改为日志 + 返回 default/空串
        """
        if args is None:
            args = {}

        text = self._resolve_path(key_path)

        if text is None:
            self._warn_missing_key(key_path)
            if default is not _MISSING:
                return self._format_text(default, args)
            return ""

        # 字典 -> 优先兼容旧版多人格/normal 结构
        if isinstance(text, dict):
            if "normal" in text:
                text = text.get("normal", "")
            else:
                logger.warning(f"[ResponseManager] 文案不是可直接渲染的字符串/列表: {key_path}")
                if default is not _MISSING:
                    return self._format_text(default, args)
                return ""

        # 列表 -> 随机取一条
        if isinstance(text, list):
            if not text:
                self._warn_empty_list(key_path)
                if default is not _MISSING:
                    return self._format_text(default, args)
                return ""
            text = random.choice(text)

        return self._format_text(text, args)

    def get_list(self, key_path: str, default: Any = _MISSING) -> List[str]:
        """获取列表型文案（不做随机选择，返回完整列表）。

        路径不存在或非列表时：
        - 若传了 default，返回 default
        - 否则返回 []
        """
        data = self._resolve_path(key_path)

        if isinstance(data, list):
            return list(data)

        if data is None:
            self._warn_missing_key(key_path)
        else:
            logger.warning(f"[ResponseManager] 目标不是列表: {key_path}")

        if default is not _MISSING:
            return list(default) if isinstance(default, list) else []
        return []

    def get_random_from(self, key_path: str, default: Any = _MISSING, **kwargs) -> str:
        """从列表中随机取一条并格式化。

        修复点：
        - default="" 时应真正返回空字符串
        - 不再返回 [列表为空: xxx] 给用户
        """
        pool = self.get_list(key_path)

        if not pool:
            if default is not _MISSING:
                return self._format_text(default, kwargs)
            return ""

        text = random.choice(pool)
        return self._format_text(text, kwargs)

    def get_value(self, key_path: str, default: Any = None) -> Any:
        """获取任意类型的值（不做格式化处理）。"""
        result = self._resolve_path(key_path)
        return result if result is not None else default

    # ================================================================
    # 分层文案接口（tier-aware）
    # ================================================================
    def get_tiered_value(self, key_path: str, tier: str, default: Any = None) -> Any:
        """获取分层文案原始值。"""
        raw = self._resolve_path(key_path)
        if raw is None:
            self._warn_missing_key(key_path)
            return default

        selected = self._select_tier_block(raw, tier)
        return selected if selected is not None else default

    def get_tiered_list(self, key_path: str, tier: str, default: Any = _MISSING) -> List[str]:
        """获取分层列表文案。"""
        selected = self.get_tiered_value(key_path, tier, default=None)

        if isinstance(selected, list):
            return list(selected)

        if selected is None:
            if default is not _MISSING:
                return list(default) if isinstance(default, list) else []
            return []

        logger.warning(f"[ResponseManager] 分层目标不是列表: {key_path} @tier={tier}")
        if default is not _MISSING:
            return list(default) if isinstance(default, list) else []
        return []

    async def get_tiered_text(
        self,
        key_path: str,
        tier: str,
        args: Optional[Dict[str, Any]] = None,
        default: Any = _MISSING,
    ) -> str:
        """获取分层单条文案。"""
        if args is None:
            args = {}

        selected = self.get_tiered_value(key_path, tier, default=None)

        if selected is None:
            if default is not _MISSING:
                return self._format_text(default, args)
            return ""

        if isinstance(selected, dict):
            if "normal" in selected:
                selected = selected.get("normal", "")
            else:
                logger.warning(f"[ResponseManager] 分层文案不是可直接渲染的字符串/列表: {key_path} @tier={tier}")
                if default is not _MISSING:
                    return self._format_text(default, args)
                return ""

        if isinstance(selected, list):
            if not selected:
                if default is not _MISSING:
                    return self._format_text(default, args)
                return ""
            selected = random.choice(selected)

        return self._format_text(selected, args)

    def get_tiered_random_from(
        self,
        key_path: str,
        tier: str,
        default: Any = _MISSING,
        **kwargs,
    ) -> str:
        """从分层列表中随机取一条并格式化。"""
        pool = self.get_tiered_list(key_path, tier)

        if not pool:
            if default is not _MISSING:
                return self._format_text(default, kwargs)
            return ""

        text = random.choice(pool)
        return self._format_text(text, kwargs)


# ==================== 全局单例 ====================
resp_manager = ResponseManager.get_instance()