""" 晋宁会馆·秃贝五边形 5.0 行政管理系统

包含：
- registry       在馆人员登记（v5 群级档案入口）
- manager        名录管理（群级名册 / 数值调整 / 发放 / 除名）
- private_bind   私聊绑定
- data_sharing   多群数据共享

v5.0 说明：
行政系统已不再只是“登记和名单”，而是正式承担：
1. 新用户进入 v5 群级体系的入口
2. 私聊绑定与多群共享的管理入口
3. 管理组运维入口
"""

from nonebot import get_driver
from nonebot.plugin import PluginMetadata

from . import registry
from . import manager
from . import private_bind
from . import data_sharing

__plugin_meta__ = PluginMetadata(
    name="秃贝行政系统",
    description="档案登记 / 名录管理 / 私聊绑定 / 数据共享",
    usage="/登记, /档案, /查看名单, /私聊绑定, /数据共享",
)

driver = get_driver()


@driver.on_startup
async def _():
    print("✅[Tubei Admin] 行政系统已升级加载")
    print("   - 档案登记（v5 群级）")
    print("   - 名录管理")
    print("   - 私聊绑定")
    print("   - 数据共享")