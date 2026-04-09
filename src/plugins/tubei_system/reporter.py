""" 晋宁会馆·秃贝五边形 5.0 每日运行报告（结构化日志收口版）
每日 00:05 自动生成并私聊发送给决策组

说明：
1. 当前日报以 recorder JSONL 日志为主
2. 已优先支持 v5 结构化日志字段：
   - ts
   - type
   - uid
   - module
   - group_id
   - trace
   - data
3. 对旧日志保持兼容：
   - 若顶层缺 module/group_id/trace，则回退读取 data 中对应字段
4. 当前仍以全局视角统计为主，
   后续可继续扩展为按群统计 / debug 群过滤 / 模块细分统计
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter
from typing import Any, Dict

from nonebot import get_bot, require

try:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler
except ImportError:
    scheduler = None
    logging.warning("[Reporter] APScheduler 未安装，日报功能禁用")

from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from .config import system_config

logger = logging.getLogger("tubei.reporter")

LOG_DIR = Path("data/logs")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_report_entry(entry: dict) -> dict:
    """将 recorder 的日志记录整理为稳定结构。

    兼容两类输入：
    1. 新结构：
       {
         "ts": ...,
         "type": ...,
         "uid": ...,
         "module": ...,
         "group_id": ...,
         "trace": ...,
         "data": {...}
       }

    2. 旧结构：
       {
         "ts": ...,
         "type": ...,
         "uid": ...,
         "data": {
           "group_id": ...,
           "module": ...,
           "trace": ...
         }
       }
    """
    if not isinstance(entry, dict):
        return {
            "ts": 0,
            "type": "unknown",
            "uid": None,
            "group_id": None,
            "module": "unknown",
            "trace": "",
            "data": {},
        }

    evt_type = str(entry.get("type", "unknown"))
    ts = _safe_int(entry.get("ts", 0), 0)
    uid = entry.get("uid")

    data = entry.get("data", {})
    if not isinstance(data, dict):
        data = {}

    # 新结构优先；旧结构回退
    raw_group_id = entry.get("group_id", data.get("group_id"))
    try:
        group_id = int(raw_group_id) if raw_group_id is not None else None
    except Exception:
        group_id = None

    module = entry.get("module", data.get("module", "unknown"))
    if not isinstance(module, str) or not module.strip():
        module = "unknown"

    trace = entry.get("trace", data.get("trace", ""))
    if not isinstance(trace, str):
        trace = str(trace or "")

    return {
        "ts": ts,
        "type": evt_type,
        "uid": uid,
        "group_id": group_id,
        "module": module,
        "trace": trace,
        "data": data,
    }


async def generate_daily_report():
    """生成并发送昨日运行报告。"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{yesterday}.jsonl"

    # ==================== 统计 ====================
    stats = Counter()
    module_stats = Counter()
    group_stats = Counter()

    total_sp_generated = 0
    active_users = set()
    taste_loss_count = 0
    error_count = 0

    if log_file.exists():
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        raw_entry = json.loads(line)
                        entry = _normalize_report_entry(raw_entry)

                        evt_type = entry["type"]
                        uid = entry["uid"]
                        evt_data = entry["data"]
                        evt_module = entry["module"]
                        evt_group_id = entry["group_id"]

                        stats[evt_type] += 1
                        module_stats[evt_module] += 1

                        if evt_group_id is not None:
                            group_stats[evt_group_id] += 1

                        if uid:
                            active_users.add(uid)

                        if evt_type == "meditation":
                            total_sp_generated += _safe_int(evt_data.get("sp_gain", 0), 0)

                        if evt_type == "kitchen":
                            # 兼容旧字段 taste_loss；也保留未来可扩展字段
                            if bool(evt_data.get("taste_loss", False)):
                                taste_loss_count += 1
                            elif bool(evt_data.get("taste_loss_after", False)) and not bool(evt_data.get("taste_loss_before", False)):
                                # 新状态首次挂上时，也算一次味蕾丧失发生
                                taste_loss_count += 1

                        if evt_type == "error":
                            error_count += 1

                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        logger.warning(f"[Reporter] 单条日志解析失败: {e}")
                        continue
        except Exception as e:
            logger.error(f"[Reporter] 读取日志失败: {e}")

    # ==================== 全局状态 ====================
    bot_status = await data_manager.get_bot_status()

    altar_block = bot_status.get("altar", {}) if isinstance(bot_status.get("altar", {}), dict) else {}
    personality_block = bot_status.get("personality", {}) if isinstance(bot_status.get("personality", {}), dict) else {}

    altar_energy = altar_block.get("energy", bot_status.get("altar_energy", 0))
    current_persona = personality_block.get("current", bot_status.get("persona", "normal"))

    total_events = sum(stats.values())

    report = ui.render_data_card(
        f"每日灵力运行报告 [{yesterday}]",
        [
            ("活跃妖灵", f"{len(active_users)} 位"),
            ("处理事件", f"{total_events} 条"),
            ("", ""),

            ("聚灵修行", f"{stats.get('meditation', 0)} 次 (+{total_sp_generated} SP)"),
            ("厨房生存", f"{stats.get('kitchen', 0)} 次 (味蕾丧失 {taste_loss_count} 次)"),
            ("灵质鉴定", f"{stats.get('resonance', 0)} 次"),
            ("药圃操作", f"{stats.get('garden_water', 0) + stats.get('garden_harvest', 0)} 次"),
            ("灵力切磋", f"{stats.get('duel_win', 0)} 次"),
            ("嘿咻捕捉", f"{stats.get('heixiu_capture', 0)} 次"),
            ("", ""),

            ("系统事件", f"{module_stats.get('system', 0)} 条"),
            ("行政事件", f"{module_stats.get('admin', 0)} 条"),
            ("修行事件", f"{module_stats.get('cultivation', 0)} 条"),
            ("娱乐事件", f"{module_stats.get('entertainment', 0)} 条"),
            ("刷屏拦截", f"{stats.get('spam_block', 0)} 次"),
            ("系统错误", f"{error_count} 次"),
            ("祭坛能量", f"{altar_energy} / 1000"),
            ("当前人格", str(current_persona)),
        ],
        footer="今日也是为会馆努力工作的一天呢 (嘿咻)",
    )

    # ==================== 发送 ====================
    try:
        bot = get_bot()
        for superuser in system_config.superusers:
            try:
                await bot.send_private_msg(user_id=int(superuser), message=report)
                logger.info(f"[Reporter] 日报已发送给 {superuser}")
            except Exception as e:
                logger.error(f"[Reporter] 发送给 {superuser} 失败: {e}")
    except Exception as e:
        logger.error(f"[Reporter] 获取 Bot 实例失败: {e}")


async def cleanup_old_logs():
    """清理 30 天前的日志文件。"""
    if not LOG_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=30)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    cleaned = 0

    for f in LOG_DIR.iterdir():
        if f.suffix == ".jsonl" and f.stem < cutoff_str:
            try:
                f.unlink()
                cleaned += 1
                logger.info(f"[Reporter] 已清理旧日志: {f.name}")
            except Exception as e:
                logger.error(f"[Reporter] 清理日志失败 {f.name}: {e}")

    if cleaned > 0:
        logger.info(f"[Reporter] 共清理 {cleaned} 个过期日志文件")


if scheduler:
    scheduler.add_job(
        generate_daily_report,
        "cron",
        hour=0,
        minute=5,
        id="daily_report",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_old_logs,
        "cron",
        hour=0,
        minute=10,
        id="cleanup_old_logs",
        replace_existing=True,
    )