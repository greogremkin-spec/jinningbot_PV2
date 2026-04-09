"""
晋宁会馆·秃贝五边形 4.1
公共工具函数

提供各模块共用的通用功能：
  - 登记表单解析
  - 敏感词检查
  - 时间格式化
  - 日期工具
  - 每日计数器重置
"""

import re
import time
from typing import Optional, Dict
from datetime import datetime


# ================================================================
#  登记表单解析
# ================================================================

def parse_registry_form(text: str) -> Optional[Dict[str, str]]:
    """
    解析登记表单

    支持中英文冒号，支持简介换行
    返回 None 表示解析失败

    期望输入格式：
      /在馆人员登记
      QQ号: 123456
      馆内昵称: xxx
      简称: xxx
      妖名: xxx
      简介: xxx（可多行）

    :return: {"qq", "spirit_name", "intro", "nickname"} 或 None
    """
    # 预处理：统一冒号为英文冒号
    text = text.replace("：", ":")

    # QQ号
    qq_match = re.search(
        r"QQ\s*号\s*[:]\s*(\d+)", text, re.IGNORECASE
    )
    # 妖名
    name_match = re.search(
        r"妖名\s*[:]\s*(.+?)(?:\n|$)", text, re.IGNORECASE
    )
    # 简介（直到文本末尾，支持多行）
    intro_match = re.search(
        r"简介\s*[:]\s*([\s\S]+)", text, re.IGNORECASE
    )
    # 昵称/简称（可选字段）
    nick_match = re.search(
        r"(?:馆内昵称|简称)\s*[:]\s*(.+?)(?:\n|$)", text, re.IGNORECASE
    )

    if qq_match and name_match and intro_match:
        return {
            "qq": qq_match.group(1).strip(),
            "spirit_name": name_match.group(1).strip(),
            "intro": intro_match.group(1).strip(),
            "nickname": nick_match.group(1).strip() if nick_match else "",
        }
    return None


# ================================================================
#  敏感词检查
# ================================================================

def check_sensitive_words(text: str) -> bool:
    """
    简易敏感词过滤

    :return: True 表示包含敏感词
    """
    # TODO: 未来可改为从配置文件加载敏感词表
    BLACK_LIST = [
        "违规词1", "违规词2",
    ]
    text_lower = text.lower()
    for word in BLACK_LIST:
        if word in text_lower:
            return True
    return False


# ================================================================
#  时间工具
# ================================================================

def format_duration(seconds: int) -> str:
    """
    将秒数格式化为人类可读的时间文本

    示例：
      0     → "已完成"
      45    → "45秒"
      150   → "2分钟"
      3700  → "1小时1分"
      86400 → "24小时0分"
    """
    if seconds <= 0:
        return "已完成"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours > 0:
        return f"{hours}小时{minutes}分"
    elif minutes > 0:
        return f"{minutes}分钟"
    else:
        return f"{seconds}秒"


def format_timestamp(ts: int) -> str:
    """
    将时间戳格式化为日期字符串

    :param ts: Unix 时间戳
    :return: 如 "2026-03-21 14:30"
    """
    if ts <= 0:
        return "未知"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "未知"


# ================================================================
#  日期工具
# ================================================================

def get_today_str() -> str:
    """获取今日日期字符串，格式 YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")


def is_today(date_str: str) -> bool:
    """判断给定的日期字符串是否是今天"""
    return date_str == get_today_str()


def get_current_hour() -> int:
    """获取当前小时数 (0-23)"""
    return datetime.now().hour


def timestamp_now() -> float:
    """获取当前时间戳"""
    return time.time()


# ================================================================
#  每日计数器
# ================================================================

def ensure_daily_reset(
    data: dict,
    key: str = "daily_counts",
    extra_fields: Optional[Dict[str, int]] = None
) -> dict:
    """
    确保每日计数器已重置

    如果 data 中的日期不是今天，初始化新的计数器。
    各模块可以通过 extra_fields 定义自己的计数字段。

    :param data: 用户的 spirit_data
    :param key: 计数器在 data 中的键名
    :param extra_fields: 额外的计数字段及初始值，如 {"kitchen": 0, "bad_streak": 0}
    :return: 重置后的计数器字典（已是今天的则原样返回）

    用法示例：
      daily = ensure_daily_reset(data, extra_fields={"meditation": 0})
      if daily["meditation"] >= 1:
          await cmd.finish("今日已修行")
      daily["meditation"] += 1
    """
    daily = data.get(key, {})
    today = get_today_str()

    if daily.get("date") != today:
        daily = {"date": today}
        if extra_fields:
            daily.update(extra_fields)

    return daily


# ================================================================
#  数值工具
# ================================================================

def clamp(value: int, min_val: int = 0, max_val: int = 999999) -> int:
    """
    将数值限制在指定范围内

    :param value: 原始值
    :param min_val: 最小值
    :param max_val: 最大值
    :return: 限制后的值
    """
    return max(min_val, min(value, max_val))


# ================================================================
# 吉兆Buff检查（公共函数）
# ================================================================

def check_blessing(buffs: dict, system_key: str) -> bool:
    """
    检查吉兆buff是否对指定系统生效，生效则消耗该系统的吉兆。

    :param buffs: 用户的 buffs 字典（会被原地修改）
    :param system_key: 系统标识 ("kitchen" / "meditation" / "resonance" / "smelting")
    :return: True 表示吉兆生效（调用方应触发最佳结果）
    """
    import time
    blessing = buffs.get("blessing")
    if not blessing:
        return False
    if not isinstance(blessing, dict):
        return False
    if time.time() >= blessing.get("expire", 0):
        buffs.pop("blessing", None)
        return False
    if blessing.get(system_key, False):
        blessing[system_key] = False
        if not any(blessing.get(k) for k in ("kitchen", "meditation", "resonance", "smelting")):
            buffs.pop("blessing", None)
        return True
    return False