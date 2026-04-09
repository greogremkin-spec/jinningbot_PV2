"""
晋宁会馆·秃贝五边形 5.0
群分级管理器

v5.0 升级目标：
1. 保留 v4.1 的 core / allied / public / danger 分层能力
2. 扩展联盟群配置，支持独立世界观和别名映射
3. 明确区分：
   - 全部已知群
   - 支持游戏玩法的群（core + allied）
   - danger 群（特殊受限）
4. 为主群特权、联盟群世界观、全服广播提供统一查询入口

注意：
- 本文件仍保持配置驱动
- 所有群号、群名称、世界观配置都来自 groups.yaml
"""

from __future__ import annotations

import yaml
import logging
from pathlib import Path
from typing import Optional, Set, Dict, Any

logger = logging.getLogger("tubei.group")

GROUPS_CONFIG_PATH = Path("config/groups.yaml")

# 群等级常量
TIER_CORE = "core"
TIER_ALLIED = "allied"
TIER_PUBLIC = "public"
TIER_DANGER = "danger"

# 核心群子类型常量
TYPE_MAIN = "main"
TYPE_ADMIN = "admin"
TYPE_DEBUG = "debug"


class GroupManager:
    """群配置与分级管理中心。"""

    _instance: Optional["GroupManager"] = None

    def __init__(self):
        self._core_groups: Dict[int, Dict[str, Any]] = {}
        self._allied_groups: Dict[int, Dict[str, Any]] = {}
        self._danger_groups: Dict[int, Dict[str, Any]] = {}

        self._promotion: Dict[str, Any] = {}
        self._cross_group_rules: Dict[str, Any] = {}

        self._core_group_ids: Set[int] = set()
        self._allied_group_ids: Set[int] = set()
        self._danger_group_ids: Set[int] = set()
        self._main_group_ids: Set[int] = set()

        self._load()

    @classmethod
    def get_instance(cls) -> "GroupManager":
        if cls._instance is None:
            cls._instance = GroupManager()
        return cls._instance

    # ================================================================
    # 加载配置
    # ================================================================
    def _load(self):
        """从 groups.yaml 加载配置。"""
        if not GROUPS_CONFIG_PATH.exists():
            logger.warning(f"[GroupManager] {GROUPS_CONFIG_PATH} 不存在，使用默认配置")
            self._load_defaults()
            return

        try:
            with open(GROUPS_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"[GroupManager] 加载配置失败: {e}，使用默认配置")
            self._load_defaults()
            return

        # 核心群
        for gid_str, info in (data.get("core_groups") or {}).items():
            gid = int(gid_str)
            group_info = {
                "name": info.get("name", f"核心群{gid}"),
                "type": info.get("type", TYPE_MAIN),
            }
            self._core_groups[gid] = group_info
            self._core_group_ids.add(gid)
            if group_info["type"] == TYPE_MAIN:
                self._main_group_ids.add(gid)

        # 联盟群
        for gid_str, info in (data.get("allied_groups") or {}).items():
            gid = int(gid_str)
            self._allied_groups[gid] = {
                "name": info.get("name", f"联盟群{gid}"),
                "world_setting": info.get("world_setting", ""),
                "alias_map": info.get("alias_map", {}) or {},
            }
            self._allied_group_ids.add(gid)

        # 危险群
        for gid_str, info in (data.get("danger_groups") or {}).items():
            gid = int(gid_str)
            self._danger_groups[gid] = {
                "name": info.get("name", f"危险群{gid}"),
            }
            self._danger_group_ids.add(gid)

        # 宣传配置
        self._promotion = data.get("promotion", {}) or {}

        # 跨群规则（v5.0 预留）
        self._cross_group_rules = data.get("cross_group_rules", {}) or {}

        logger.info(
            f"[GroupManager] 群配置加载完成 | "
            f"核心群: {len(self._core_groups)} | "
            f"联盟群: {len(self._allied_groups)} | "
            f"危险群: {len(self._danger_groups)}"
        )

    def _load_defaults(self):
        """默认配置兜底。"""
        default_cores = {
            564234162: {"name": "晋宁会馆主群", "type": TYPE_MAIN},
            210383914: {"name": "管理组官群", "type": TYPE_ADMIN},
            805930992: {"name": "功能调试群", "type": TYPE_DEBUG},
        }

        for gid, info in default_cores.items():
            self._core_groups[gid] = dict(info)
            self._core_group_ids.add(gid)
            if info["type"] == TYPE_MAIN:
                self._main_group_ids.add(gid)

        self._promotion = {
            "main_group_id": 564234162,
            "main_group_name": "晋宁会馆",
            "slogan": "基于《罗小黑战记》的温馨同人社群",
            "website": " ",
        }
        self._cross_group_rules = {
            "share_daily_limit": False,
        }

    def reload(self):
        """热重载群配置。"""
        self._core_groups.clear()
        self._allied_groups.clear()
        self._danger_groups.clear()

        self._core_group_ids.clear()
        self._allied_group_ids.clear()
        self._danger_group_ids.clear()
        self._main_group_ids.clear()

        self._promotion.clear()
        self._cross_group_rules.clear()

        self._load()

    # ================================================================
    # 基础查询
    # ================================================================
    def get_group_tier(self, group_id: int) -> str:
        """获取群等级。"""
        if group_id in self._core_group_ids:
            return TIER_CORE
        if group_id in self._allied_group_ids:
            return TIER_ALLIED
        if group_id in self._danger_group_ids:
            return TIER_DANGER
        return TIER_PUBLIC

    def get_group_type(self, group_id: int) -> Optional[str]:
        """获取核心群子类型。非核心群返回 None。"""
        info = self._core_groups.get(group_id)
        return info.get("type") if info else None

    def get_group_name(self, group_id: int) -> str:
        """获取群名称。"""
        if group_id in self._core_groups:
            return self._core_groups[group_id]["name"]
        if group_id in self._allied_groups:
            return self._allied_groups[group_id]["name"]
        if group_id in self._danger_groups:
            return self._danger_groups[group_id]["name"]
        if group_id <= 0:
            return "未绑定"
        return f"外部群({group_id})"

    def get_allied_config(self, group_id: int) -> Dict[str, Any]:
        """获取联盟群完整配置。非联盟群返回空字典。"""
        return dict(self._allied_groups.get(group_id, {}))

    def is_core_group(self, group_id: int) -> bool:
        return group_id in self._core_group_ids

    def is_allied_group(self, group_id: int) -> bool:
        return group_id in self._allied_group_ids

    def is_danger_group(self, group_id: int) -> bool:
        return group_id in self._danger_group_ids

    def is_main_group(self, group_id: int) -> bool:
        return group_id in self._main_group_ids

    def is_debug_group(self, group_id: int) -> bool:
        return self.get_group_type(group_id) == TYPE_DEBUG

    def is_admin_group(self, group_id: int) -> bool:
        return self.get_group_type(group_id) == TYPE_ADMIN

    # ================================================================
    # v5.0 新增查询
    # ================================================================
    def get_all_game_groups(self) -> Set[int]:
        """返回所有支持游戏玩法的群：核心群 + 联盟群。"""
        return self._core_group_ids | self._allied_group_ids

    @property
    def core_group_ids(self) -> Set[int]:
        return self._core_group_ids.copy()

    @property
    def allied_group_ids(self) -> Set[int]:
        return self._allied_group_ids.copy()

    @property
    def main_group_ids(self) -> Set[int]:
        return self._main_group_ids.copy()

    @property
    def all_known_group_ids(self) -> Set[int]:
        return self._core_group_ids | self._allied_group_ids | self._danger_group_ids

    # ================================================================
    # 宣传与文案
    # ================================================================
    @property
    def main_group_id(self) -> int:
        return int(self._promotion.get("main_group_id", 564234162))

    @property
    def website(self) -> str:
        return self._promotion.get("website", "jinninghuiguan.cn")

    @property
    def slogan(self) -> str:
        return self._promotion.get("slogan", "基于《罗小黑战记》的温馨同人社群")

    @property
    def share_daily_limit(self) -> bool:
        """跨群是否共享每日限次。v5.0 默认 False。"""
        return bool(self._cross_group_rules.get("share_daily_limit", False))

    # ==================== 上下文感知文案 ====================
    def get_about_text_by_tier(self, group_tier: str) -> str:
        """按群层级返回关于介绍文案。"""
        from src.plugins.tubei_system.config import TUBEI_FULL_NAME

        tier = (group_tier or TIER_PUBLIC).strip().lower()

        if tier == TIER_CORE:
            return (
                "晋宁会馆是一个基于《罗小黑战记》\n"
                "的同人架空社群。\n"
                "\n"
                "这里的妖灵们以会馆为家，\n"
                "修行、种植、探索、切磋...\n"
                "在温馨和谐的氛围中共同成长。\n"
                "\n"
                " 决策组：析沐、吉熙\n"
                " 核心：温馨、和谐、治愈\n"
                f" 管家：{TUBEI_FULL_NAME}"
            )

        if tier == TIER_ALLIED:
            return (
                "秃贝来自晋宁会馆体系，\n"
                "会在联盟会馆中协助提供聊天、轻娱乐与部分修行玩法。\n"
                "\n"
                "不同群会保留各自的氛围与设定，\n"
                "秃贝会尽量自然地融入当前环境。\n"
                "\n"
                "如果你对晋宁会馆本体感兴趣，\n"
                "可在合适场景下进一步了解。"
            )

        return (
            "秃贝是一只会聊天、会整活、\n"
            "也会提供部分轻玩法的群机器人。\n"
            "\n"
            "在不同群里，秃贝会根据环境\n"
            "使用不同语气与功能范围。\n"
            "\n"
            "如果你想进一步了解其来源设定，\n"
            "也可以私聊继续问问它。"
        )

    def get_join_text_by_tier(self, group_tier: str) -> str:
        """按群层级返回加入/引导文案。"""
        tier = (group_tier or TIER_PUBLIC).strip().lower()

        if tier == TIER_CORE:
            return (
                f"很高兴你对会馆感兴趣~ (嘿咻)\n"
                f"\n"
                f" 主群号：{self.main_group_id}\n"
                f"\n"
                f"加入后发送 /登记 即可\n"
                f"建立你的灵力档案，解锁全部功能！"
            )

        if tier == TIER_ALLIED:
            return (
                "你当前所在的是联盟群环境。\n"
                "\n"
                "如果你想体验更完整的群级修行体系，\n"
                f"可进一步了解晋宁会馆主群：{self.main_group_id}\n"
                "\n"
                "但如果你只是想在当前群自然聊天和游玩，\n"
                "也完全可以先留在这里体验秃贝的现有能力。"
            )

        return (
            "如果你想体验更完整的修行功能，\n"
            "通常需要在支持该体系的群中建立档案。\n"
            "\n"
            f"如需进一步了解，可参考晋宁会馆主群：{self.main_group_id}\n"
            "也可以先私聊秃贝了解规则与玩法。"
        )

    def get_feature_locked_text_by_tier(self, feature_name: str, group_tier: str) -> str:
        """按群层级返回功能锁定提示。"""
        tier = (group_tier or TIER_PUBLIC).strip().lower()

        if tier == TIER_ALLIED:
            return (
                f"{feature_name} 在当前联盟群环境中暂不可用。\n"
                "\n"
                "秃贝会根据不同群的定位开放不同能力，\n"
                "当前群已开放的玩法仍可正常体验。"
            )

        if tier == TIER_PUBLIC:
            return (
                f"{feature_name} 不在当前公开群开放范围内。\n"
                "\n"
                "公开群以轻聊天和轻娱乐为主，\n"
                "更完整的群级修行玩法需要在对应游戏群中体验。"
            )

        if tier == "unbound":
            return (
                f"{feature_name} 需要明确的群档上下文才能使用。\n"
                "\n"
                "你当前私聊还没有绑定群档，\n"
                "可先发送：私聊绑定"
            )

        return (
            f"{feature_name} 是秃贝在当前体系中\n"
            f"为对应环境准备的专属玩法~\n"
            f"\n"
            f"发送 /关于 可以了解更多背景"
        )

    # ==================== 兼容旧接口 ====================
    def get_about_text(self) -> str:
        """关于会馆介绍（兼容旧接口，默认返回 core 版本）。"""
        return self.get_about_text_by_tier(TIER_CORE)

    def get_join_text(self) -> str:
        """加入会馆引导（兼容旧接口，默认返回 core 版本）。"""
        return self.get_join_text_by_tier(TIER_CORE)

    def get_feature_locked_text(self, feature_name: str) -> str:
        """功能锁定提示（兼容旧接口，默认返回 public 通用版）。"""
        return self.get_feature_locked_text_by_tier(feature_name, TIER_PUBLIC)

# 全局单例
group_manager = GroupManager.get_instance()