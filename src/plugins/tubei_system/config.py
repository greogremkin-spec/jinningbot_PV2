""" 晋宁会馆·秃贝五边形
系统配置中心

职责：
1. 从 NoneBot 的 .env 加载系统配置（SystemConfig）
2. 从 game_balance.yaml 加载游戏数值（GameConfig）
3. 所有模块通过 system_config / game_config 获取参数
4. 支持 /重载配置 热生效
"""

from __future__ import annotations

import yaml
import logging
from pathlib import Path
from typing import Set, Dict, Any, List, Optional
from pydantic import BaseModel
from nonebot import get_driver

logger = logging.getLogger("tubei.config")

# ================================================================
# 版本号（全局唯一定义点）
# ================================================================
TUBEI_VERSION = "5.0"
TUBEI_FULL_NAME = f"秃贝五边形 v{TUBEI_VERSION}"


# ================================================================
# 系统配置（来自 .env）
# ================================================================
class SystemConfig(BaseModel):
    """系统级配置：从 NoneBot 的 .env / .env.prod 文件读取。"""

    # 防刷屏阈值（1 分钟内最大操作次数）
    tubei_spam_threshold: int = 10

    # 封禁时长（秒）
    tubei_ban_duration: int = 600

    # 决策组（超级管理员 QQ 号）
    superusers: Set[str] = {"3141451467", "1876352760"}

    # 管理组（管理员 QQ 号）
    tubei_admins: Set[str] = {
        "1468135138", "3392950858", "3020300956", "207489695",
        "1275350236", "1378037446", "1145912829", "3790559172",
    }

    class Config:
        extra = "ignore"  # 忽略多余配置项（HOST, PORT 等）


driver = get_driver()

try:
    system_config = SystemConfig.parse_obj(driver.config)
except Exception:
    try:
        system_config = SystemConfig(**driver.config.dict())
    except Exception:
        system_config = SystemConfig()
        logger.warning("[Config] 系统配置加载失败，使用默认值")

logger.info(
    f"[Config] 系统配置加载完成 | "
    f"决策组: {len(system_config.superusers)}人 | "
    f"管理组: {len(system_config.tubei_admins)}人"
)


# ================================================================
# 游戏数值配置（来自 game_balance.yaml）
# ================================================================
GAME_BALANCE_PATH = Path("config/game_balance.yaml")


class GameConfig:
    """游戏数值配置（单例）

    从 config/game_balance.yaml 读取所有游戏参数
    支持热重载
    """

    _instance: Optional["GameConfig"] = None

    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._load()

    @classmethod
    def get_instance(cls) -> "GameConfig":
        if cls._instance is None:
            cls._instance = GameConfig()
        return cls._instance

    def _load(self):
        """加载配置文件"""
        if not GAME_BALANCE_PATH.exists():
            logger.warning(f"[GameConfig] {GAME_BALANCE_PATH} 不存在，使用默认值")
            self._data = {}
            return

        try:
            with open(GAME_BALANCE_PATH, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
            logger.info(f"[GameConfig] 数值配置加载完成: {list(self._data.keys())}")
        except Exception as e:
            logger.error(f"[GameConfig] 加载失败: {e}")
            self._data = {}

    def reload(self):
        """热重载"""
        self._load()
        logger.info("[GameConfig] 数值配置已热重载")

    # ================================================================
    # 通用取值
    # ================================================================
    def get(self, *keys, default=None):
        """链式取值

        用法:
            game_config.get("meditation", "base_min", default=10)
        """
        data = self._data
        for k in keys:
            if isinstance(data, dict):
                data = data.get(k)
            else:
                return default

            if data is None:
                return default
        return data

    # ================================================================
    # 基础设置
    # ================================================================
    @property
    def initial_sp(self) -> int:
        return self.get("initial_sp", default=60)

    @property
    def unregistered_sp_cap(self) -> int:
        return self.get("unregistered_sp_cap", default=99)

    # ================================================================
    # 等级系统
    # ================================================================
    @property
    def level_map(self) -> Dict[int, int]:
        """等级 -> 所需灵力"""
        raw = self.get("levels", "thresholds", default=None)
        if isinstance(raw, dict):
            return {int(k): int(v) for k, v in raw.items()}
        return {
            1: 0,
            2: 100,
            3: 800,
            4: 2000,
            5: 5000,
            6: 15000,
            7: 40000,
        }

    @property
    def level_titles(self) -> Dict[int, str]:
        """等级 -> 境界名称"""
        raw = self.get("levels", "titles", default=None)
        if isinstance(raw, dict):
            return {int(k): v for k, v in raw.items()}
        return {
            1: "灵识觉醒",
            2: "聚灵化息",
            3: "引灵归宗",
            4: "固灵成相",
            5: "御灵镇域",
            6: "化灵通神",
            7: "万灵归一",
        }

    # ================================================================
    # 聚灵修行
    # ================================================================
    @property
    def meditation_base_min(self) -> int:
        return self.get("meditation", "base_min", default=10)

    @property
    def meditation_base_max(self) -> int:
        return self.get("meditation", "base_max", default=30)

    @property
    def meditation_cooldown(self) -> int:
        return self.get("meditation", "cooldown", default=60)

    @property
    def meditation_daily_limit(self) -> int:
        return self.get("meditation", "daily_limit", default=1)

    @property
    def meditation_level_bonus(self) -> List[int]:
        """等级加成列表 [0, lv1, lv2, ..., lv7]"""
        raw = self.get("meditation", "level_bonus", default={})
        if isinstance(raw, dict):
            return [0] + [raw.get(f"lv{i}", 0) for i in range(1, 8)]
        return [0, 0, 2, 5, 8, 10, 15, 20]

    # ================================================================
    # 灵签系统
    # ================================================================
    @property
    def fortune_names(self) -> List[str]:
        return self.get("fortune", "names", default=["大吉", "中吉", "小吉", "平", "末凶"])

    @property
    def fortune_weights(self) -> List[float]:
        return self.get("fortune", "weights", default=[0.10, 0.15, 0.30, 0.40, 0.05])

    @property
    def fortune_mults(self) -> Dict[str, float]:
        return self.get(
            "fortune",
            "mults",
            default={
                "大吉": 0.5,
                "中吉": 0.2,
                "小吉": 0.1,
                "平": 0.0,
                "末凶": -0.1,
            },
        )

    # ================================================================
    # 厨房系统
    # ================================================================
    @property
    def kitchen_reward_sp(self) -> int:
        return self.get("kitchen", "reward_sp", default=50)

    @property
    def kitchen_penalty_sp(self) -> int:
        return self.get("kitchen", "penalty_sp", default=10)

    @property
    def kitchen_success_rate(self) -> float:
        return self.get("kitchen", "success_rate", default=0.30)

    @property
    def kitchen_daily_limit(self) -> int:
        return self.get("kitchen", "daily_limit", default=4)

    @property
    def kitchen_taste_loss_duration(self) -> int:
        # [兼容保留字段] v5 主逻辑已改为餐次型状态，不再作为主逻辑判断依据
        return self.get("kitchen", "taste_loss_duration", default=7200)

    @property
    def kitchen_taste_loss_sp(self) -> int:
        return self.get("kitchen", "taste_loss_sp", default=2)

    @property
    def kitchen_bad_streak_bonus_2(self) -> float:
        return self.get("kitchen", "bad_streak_bonus_2", default=0.3)

    @property
    def kitchen_bad_streak_bonus_3(self) -> float:
        return self.get("kitchen", "bad_streak_bonus_3", default=1.0)

    @property
    def kitchen_meal_times(self) -> List[List[int]]:
        return self.get("kitchen", "meal_times", default=[[6, 9], [11, 14], [16, 21], [22, 24], [0, 1]])

    @property
    def kitchen_menu_good(self) -> List[str]:
        return self.get("kitchen", "menu_good", default=["清蒸灵溪鱼", "发光蛋炒饭"])

    @property
    def kitchen_menu_bad(self) -> List[str]:
        return self.get("kitchen", "menu_bad", default=["虚空拉面", "仰望星空派"])

    # ================================================================
    # 祭坛系统
    # ================================================================
    @property
    def altar_tax_rate(self) -> float:
        return self.get("altar", "tax_rate", default=0.01)

    @property
    def altar_threshold(self) -> int:
        return self.get("altar", "trigger_threshold", default=1000)

    @property
    def altar_buff_duration(self) -> int:
        return self.get("altar", "buff_duration", default=86400)

    @property
    def altar_buff_bonus(self) -> int:
        return self.get("altar", "buff_bonus", default=5)

    # ================================================================
    # 派遣系统
    # ================================================================
    @property
    def expedition_recall_penalty(self) -> int:
        return self.get("expedition", "recall_penalty", default=5)

    @property
    def expedition_locations(self) -> Dict[str, Any]:
        return self.get(
            "expedition",
            "locations",
            default={
                "灵溪周边": {
                    "level": 2,
                    "time": 3600,
                    "sp_min": 5,
                    "sp_max": 5,
                    "drops": {"神秘种子": 0.3},
                },
            },
        )

    # ================================================================
    # 药圃系统
    # ================================================================
    @property
    def garden_slot_count(self) -> int:
        return self.get("garden", "slot_count", default=4)

    @property
    def garden_plants(self) -> Dict[str, str]:
        return self.get(
            "garden",
            "plants",
            default={
                "灵心草": "下一次聚灵收益+50%",
                "鸾草": "下一次鉴定必出华丽词条",
                "蓝玉果": "下一次聚灵必出最大值",
                "凤羽花": "下一次派遣必带回法宝碎片",
            },
        )

    @property
    def garden_growth(self) -> Dict[str, int]:
        return self.get(
            "garden",
            "growth",
            default={
                "seed_to_sprout": 1,
                "sprout_to_growing": 2,
                "growing_to_mature": 5,
            },
        )

    @property
    def garden_icons(self) -> Dict[str, str]:
        return self.get(
            "garden",
            "icons",
            default={
                "empty": "⬜",
                "seed": "🌱",
                "sprout": "🌿",
                "growing": "🍀",
                "mature": "✨",
            },
        )

    # ================================================================
    # 鉴定系统
    # ================================================================
    @property
    def appraise_cost(self) -> int:
        return self.get("resonance", "appraise_cost", default=2)

    @property
    def rare_chance(self) -> float:
        return self.get("resonance", "rare_chance", default=0.05)

    @property
    def keywords_normal(self) -> List[str]:
        return self.get("resonance", "keywords_normal", default=["混沌", "清澄"])

    @property
    def keywords_rare(self) -> List[str]:
        return self.get("resonance", "keywords_rare", default=["虚空之主", "天选之子"])

    @property
    def buff_pool(self) -> List[Dict[str, str]]:
        return self.get(
            "resonance",
            "buff_pool",
            default=[
                {"name": "风行 Lv1", "desc": "派遣-10%"},
                {"name": "无", "desc": "无"},
            ],
        )

    @property
    def buff_pool_rare(self) -> List[Dict[str, str]]:
        return self.get(
            "resonance",
            "buff_pool_rare",
            default=[
                {"name": "风行 MAX", "desc": "派遣-30%"},
            ],
        )

    # ================================================================
    # 切磋系统
    # ================================================================
    @property
    def duel_fluctuation(self) -> float:
        return self.get("duel", "power_fluctuation", default=0.2)

    @property
    def duel_steal_rate(self) -> float:
        return self.get("duel", "steal_rate", default=0.01)

    @property
    def duel_steal_cap(self) -> int:
        return self.get("duel", "steal_cap", default=20)

    @property
    def duel_protection_threshold(self) -> int:
        return self.get("duel", "protection_threshold", default=50)

    # ================================================================
    # 嘿咻系统
    # ================================================================
    @property
    def heixiu_spawn_interval(self) -> int:
        return self.get("heixiu", "spawn_interval_hours", default=4)

    @property
    def heixiu_spawn_jitter(self) -> int:
        return self.get("heixiu", "spawn_jitter", default=1800)

    @property
    def heixiu_catch_base_prob(self) -> float:
        return self.get("heixiu", "catch_base_prob", default=0.7)

    @property
    def heixiu_catch_herb_prob(self) -> float:
        return self.get("heixiu", "catch_herb_prob", default=1.0)

    @property
    def heixiu_escape_timeout(self) -> int:
        return self.get("heixiu", "escape_timeout", default=60)

    @property
    def heixiu_fur_drop(self) -> Dict[str, Any]:
        return self.get(
            "heixiu",
            "fur_drop",
            default={
                "normal": {"item": "普通嘿咻毛球", "chance": 0.15},
                "rainbow": {"item": "彩虹嘿咻毛球", "chance": 0.25},
                "golden": {"item": "黄金嘿咻毛球", "chance": 0.45},
                "shadow": {"item": "暗影嘿咻毛球", "chance": 0.10},
            },
        )

    # ================================================================
    # 毛球系统
    # ================================================================
    @property
    def heixiu_fur_warning_threshold(self) -> int:
        return self.get("heixiu_fur", "warning_threshold", default=10)

    @property
    def heixiu_fur_disappear_rates(self) -> Dict[str, float]:
        return self.get(
            "heixiu_fur",
            "disappear_rates",
            default={
                "11": 0.12,
                "12": 0.18,
                "13": 0.25,
                "14": 0.35,
                "default_after": 0.50,
            },
        )

    @property
    def heixiu_fur_roll_weights(self) -> Dict[str, float]:
        return self.get(
            "heixiu_fur",
            "roll_weights",
            default={
                "sp_gain": 0.60,
                "cleanse_taste_loss": 0.03,
                "special_drop": 0.08,
                "comfort_only": 0.29,
            },
        )

    @property
    def heixiu_fur_drop_pools(self) -> Dict[str, Any]:
        return self.get(
            "heixiu_fur",
            "drop_pools",
            default={
                "普通嘿咻毛球": {
                    "drop_chance": 0.08,
                    "drops": [["神秘种子", 1], ["法宝碎片", 1], ["灵心草", 1]],
                },
                "彩虹嘿咻毛球": {
                    "drop_chance": 0.10,
                    "drops": [["蓝玉果", 1], ["鸾草", 1], ["空间简片", 1]],
                },
                "黄金嘿咻毛球": {
                    "drop_chance": 0.12,
                    "drops": [["凤羽花", 1], ["万宝如意", 1], ["玄清丹", 1]],
                },
                "暗影嘿咻毛球": {
                    "drop_chance": 0.09,
                    "drops": [["忘忧草", 1], ["清心露", 1], ["法宝碎片", 2]],
                },
            },
        )

    # ================================================================
    # 法宝熔炼
    # ================================================================
    @property
    def smelt_cost(self) -> int:
        return self.get("smelting", "cost", default=10)

    @property
    def smelt_fail_rate(self) -> float:
        return self.get("smelting", "results", "fail_rate", default=0.2)

    @property
    def smelt_normal_rate(self) -> float:
        return self.get("smelting", "results", "normal_rate", default=0.4)

    @property
    def smelt_rare_rate(self) -> float:
        return self.get("smelting", "results", "rare_rate", default=0.3)

    @property
    def smelt_legend_rate(self) -> float:
        return self.get("smelting", "results", "legend_rate", default=0.1)

    @property
    def smelt_rare_pool(self) -> List[str]:
        return self.get("smelting", "rare_pool", default=["空间简片", "玄清丹", "灵心草"])

    # ================================================================
    # 系统风控
    # ================================================================
    @property
    def sleep_start(self) -> int:
        return self.get("security", "sleep_start", default=1)

    @property
    def sleep_end(self) -> int:
        return self.get("security", "sleep_end", default=5)

    @property
    def random_chat_rate(self) -> float:
        return self.get("security", "random_chat_rate", default=0.03)

    @property
    def random_chat_min_length(self) -> int:
        return self.get("security", "random_chat_min_length", default=12)


# 全局单例
game_config = GameConfig.get_instance()