""" 晋宁会馆·秃贝五边形 5.0 系统门神模块

v5.0 启动流程：
1. 加载 members / spirits / bot_status / group_status 到内存
2. 执行兼容迁移与基础清洗
3. 启动持久化循环
4. 输出系统运行信息

关闭流程：
1. 停止持久化循环
2. 强制安全落盘

包含子模块：
- config          配置中心
- interceptor     消息拦截器
- mutex           互斥锁
- recorder        事件记录
- reporter        日报
- console         控制台
- world_event     世界事件
- text_dispatcher 纯文字分发
"""

from nonebot import get_driver
from nonebot.plugin import PluginMetadata

from .config import TUBEI_VERSION, TUBEI_FULL_NAME
from . import config
from . import interceptor
from . import recorder
from . import reporter
from . import console
from . import world_event
from . import text_dispatcher

from src.common.data_manager import data_manager
from src.common.group_manager import group_manager

__plugin_meta__ = PluginMetadata(
    name="秃贝系统门神",
    description="配置中心 / 拦截器 / 事件记录 / 管理控制台 / 世界事件 / 纯文字分发",
    usage="全局生效",
    config=config.SystemConfig,
)

driver = get_driver()


@driver.on_startup
async def startup():
    """系统启动初始化。"""
    # 1. 加载数据
    data_manager.load_all_sync()

    # 2. 启动时兼容修复
    await data_manager.migrate_all_gardens()
    await data_manager.migrate_member_identities(core_group_ids=group_manager.core_group_ids)

    # 3. 轻量数据体检
    checkup = await data_manager.run_data_checkup()

    # 4. 启动持久化循环
    data_manager.start_persist_loop()

    # 5. 输出启动信息
    member_count = len(data_manager.members_raw)
    spirit_count = len(data_manager.spirits_raw)

    active_members = [
        m for m in data_manager.members_raw.values()
        if m.get("global_profile", {}).get("status", m.get("status", "active")) != "deleted"
    ]
    active_count = len(active_members)

    core_count = 0
    outer_count = 0
    for m in active_members:
        identity = m.get("global_identity", m.get("identity", "guest"))
        if identity in ("core_member", "admin", "decision"):
            core_count += 1
        else:
            outer_count += 1

    core_groups = len(group_manager.core_group_ids)
    allied_groups = len(group_manager.allied_group_ids)
    game_groups = len(group_manager.get_all_game_groups())
    group_status_count = len(data_manager.group_status_raw)

    from src.common.command_registry import COMMANDS
    text_cmd_count = sum(1 for c in COMMANDS if c.get("text"))

    bot_status = await data_manager.get_bot_status()
    altar_energy = bot_status.get("altar", {}).get("energy", bot_status.get("altar_energy", 0))
    current_persona = bot_status.get("personality", {}).get("current", bot_status.get("persona", "normal"))

    print("=" * 64)
    print(f" [Tubei System] {TUBEI_FULL_NAME} · 联盟化底座已启动")
    print("=" * 64)
    print(f" 版本: v{TUBEI_VERSION}")
    print(f" 成员档案: {member_count} 条 (活跃{active_count} / 馆内{core_count} / 馆外{outer_count})")
    print(f" 灵力档案: {spirit_count} 条")
    print(f" 群状态文件: {group_status_count} 条")
    print(f" 核心群: {core_groups} 个")
    print(f" 联盟群: {allied_groups} 个")
    print(f" 游戏群总计: {game_groups} 个")
    print(f" 纯文字指令: {text_cmd_count} 个")
    print(f" 当前人格: {current_persona}")
    print(f" ⛩祭坛能量: {altar_energy}")
    print(
        f" 数据体检: 孤儿 spirit={checkup['orphan_spirit']} | "
        f"清理空物品={checkup['empty_items_cleaned']} | "
        f"修复空注册群={checkup['empty_registered_groups_fixed']}"
    )
    print(" ⏱持久化间隔: 30s (原子写入)")
    print("=" * 64)


@driver.on_shutdown
async def shutdown():
    """系统关闭：安全保存所有数据。"""
    await data_manager.shutdown()
    print("=" * 64)
    print(" [Tubei System] 数据已安全落盘，联盟化底座关闭")
    print("=" * 64)