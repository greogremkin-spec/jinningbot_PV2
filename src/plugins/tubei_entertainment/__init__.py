""" 晋宁会馆·秃贝五边形 5.0 趣味娱乐系统

包含：
- kitchen          无限大人的厨房 · 生存挑战
- resonance        灵力宿命（灵伴）+ 灵质鉴定 + 今日老婆
- duel             灵质空间 · 斗帅宫
- heixiu_catcher   嘿咻捕获计划
- truth_dare       真心话大冒险

v5.0 说明：
1. 娱乐系统中的重状态玩法已接入群级 spirit / group_status
2. 嘿咻系统已升级为群级多实例
3. 灵伴 / 鉴定 / 切磋均已接入当前群上下文
4. 轻娱乐功能继续保持公开可玩
"""

from nonebot import get_driver
from nonebot.plugin import PluginMetadata

from . import kitchen
from . import resonance
from . import duel
from . import heixiu_catcher
from . import truth_dare

__plugin_meta__ = PluginMetadata(
    name="秃贝娱乐系统",
    description="厨房/灵伴/鉴定/切磋/嘿咻/真心话",
    usage="/厨房, /灵伴, /鉴定, /切磋, /真心话, /大冒险",
)

driver = get_driver()


@driver.on_startup
async def _():
    print("✅[Tubei Entertainment] 娱乐场所已开放")
    print("   - 群级厨房")
    print("   - 群级灵伴 / 鉴定")
    print("   - 群级切磋")
    print("   - 群级嘿咻")
    print("   - 公开群轻娱乐")