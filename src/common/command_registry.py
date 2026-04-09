""" 晋宁会馆·秃贝五边形 5.0 统一指令注册中心（结构收口版）

定位：
1. 所有指令元数据的唯一声明中心
2. guide / text_dispatcher / 说明系统 从这里读取
3. 持续强化“注册表驱动”思路
4. 当前版本目标：
   - 命令元数据足够完整
   - allow_private / 权限语义清晰
   - v5 新能力（私聊绑定 / 数据共享）纳入正式导航体系
   - 排行榜 / 轻娱乐等纯文字能力在注册表中体现完整

设计原则：
- slash 第一个 = 菜单展示主斜杠指令
- text 第一个 = 菜单展示主纯文字指令
- text 为空 = 不支持纯文字触发
- has_args = 支持带参数形式
- hidden = 不在菜单中显示
- allow_private = 是否允许在私聊自然成立
- 本文件只声明元数据，不承载执行业务逻辑
"""
from __future__ import annotations
from typing import List, Optional, Dict, Any

# ================================================================
# 板块定义
# ================================================================
MENU_SECTIONS = {
    "admin": {
        "name": "行政板块",
        "icon": " ",
        "title": "灵册大厅 · 在馆人员登记与档案管理",
        "subtitle": "建立你的灵力档案，成为在册妖灵。",
        "slash_trigger": "行政板块",
        "text_trigger": "行政板块",
        "display_in_public": False,
    },
    "cultivation": {
        "name": "修行板块",
        "icon": " ",
        "title": "灵质修行 · 聚灵派遣药圃道具祭坛",
        "subtitle": "聚集天地灵气，探索九大灵域，培育灵植，熔炼法宝。",
        "slash_trigger": "修行板块",
        "text_trigger": "修行板块",
        "display_in_public": False,
    },
    "entertainment": {
        "name": "娱乐板块",
        "icon": " ",
        "title": "趣味玩法 · 厨房鉴定切磋嘿咻灵伴",
        "subtitle": "无限厨房、鉴定、切磋、捕捉嘿咻、寻找今日灵伴！",
        "slash_trigger": "娱乐板块",
        "text_trigger": "娱乐板块",
        "display_in_public": True,
    },
    "console": {
        "name": "管理板块",
        "icon": "⚙",
        "title": "管理控制台 · 决策组/管理组专用",
        "subtitle": "人格切换、广播、封印、福利发放、配置管理。",
        "slash_trigger": "管理板块",
        "text_trigger": "管理板块",
        "display_in_public": False,
    },
}

# ================================================================
# 指令定义
# ================================================================
COMMANDS: List[Dict[str, Any]] = [
    # ==================== 行政 ====================
    {
        "id": "register_guide",
        "slash": ["登记", "在馆登记"],
        "text": ["登记", "在馆登记"],
        "help_keywords": ["登记", "在馆登记", "灵册大厅"],
        "section": "admin",
        "display_name": "在馆登记",
        "description": "录入灵力档案，成为在册妖灵",
        "min_tier": "allied",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【灵册大厅 · 在馆人员登记】\n"
            "• 发送 登记 获取登记模板\n"
            "• 建议私聊获取模板，正式提交建议在目标群内\n"
            "• 登记后解锁该群的修行能力\n"
            "─────────────────\n"
            "登记"
        ),
    },
    {
        "id": "register_submit",
        "slash": ["在馆人员登记"],
        "text": [],
        "section": "admin",
        "display_name": "提交登记",
        "description": "提交填写好的登记表单",
        "min_tier": "allied",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "profile",
        "slash": ["档案", "我的档案", "个人信息", "妖灵档案", "个人档案"],
        "text": ["我的档案", "档案", "妖灵档案", "个人档案"],
        "help_keywords": ["档案", "我的档案", "个人档案", "妖灵档案"],
        "section": "admin",
        "display_name": "妖灵档案",
        "description": "查看个人修行面板",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【灵册大厅 · 妖灵档案】\n"
            "• 发送 档案 查看个人修行面板\n"
            "• 群内显示当前群档\n"
            "• 私聊显示绑定群档\n"
            "• 含当前群修行信息与全局统计信息\n"
            "─────────────────\n"
            "档案"
        ),
    },
    {
        "id": "member_list",
        "slash": ["查看名单", "名单"],
        "text": ["查看名单"],
        "section": "admin",
        "display_name": "查看名单",
        "description": "查看当前群在册人员",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": True,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": False,
        "help_detail": None,
    },
    {
        "id": "modify",
        "slash": ["修改", "改数值"],
        "text": [],
        "section": "admin",
        "display_name": "修改数值",
        "description": "修改指定成员当前群档属性",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": True,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "give",
        "slash": ["发放", "发东西"],
        "text": [],
        "section": "admin",
        "display_name": "发放物品",
        "description": "给指定成员发放道具",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": True,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "freeze_archive",
        "slash": ["冻结档案"],
        "text": [],
        "section": "admin",
        "display_name": "冻结档案",
        "description": "冻结指定用户的整套档案",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": True,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【管理指令 · 冻结档案】\n"
            "• /冻结档案 [QQ]\n"
            "• 冻结该用户的整套档案（所有群档）\n"
            "• 冻结后用户无法继续使用修行功能\n"
            "• 不删除历史数据\n"
            "• 必须管理员 /解冻档案 恢复\n"
            "─────────────────\n"
            "/冻结档案 123456"
        ),
        "help_keywords": ["冻结档案", "冻结"],
    },
    {
        "id": "unfreeze_archive",
        "slash": ["解冻档案"],
        "text": [],
        "section": "admin",
        "display_name": "解冻档案",
        "description": "解冻指定用户的整套档案",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": True,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【管理指令 · 解冻档案】\n"
            "• /解冻档案 [QQ]\n"
            "• 解除冻结，恢复档案可用\n"
            "• 不会自动恢复共享和私聊绑定\n"
            "─────────────────\n"
            "/解冻档案 123456"
        ),
        "help_keywords": ["解冻档案", "解冻"],
    },
    {
        "id": "delete_archive",
        "slash": ["删除档案"],
        "text": [],
        "section": "admin",
        "display_name": "删除档案",
        "description": "删除指定用户在某群的单个独立档案",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": True,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【管理指令 · 删除档案】\n"
            "• /删除档案 [QQ] [群号]\n"
            "• 删除该用户在指定群的单个独立群档\n"
            "• 不影响其他群档\n"
            "• 共享指针档不能直接删除\n"
            "• 删除前会自动生成备份\n"
            "─────────────────\n"
            "/删除档案 123456 564234162"
        ),
        "help_keywords": ["删除档案"],
    },
    {
        "id": "private_bind",
        "slash": ["私聊绑定", "绑定群档", "绑定群聊", "切换绑定群"],
        "text": ["私聊绑定"],
        "help_keywords": ["私聊绑定", "绑定群档", "绑定群聊"],
        "section": "admin",
        "display_name": "私聊绑定",
        "description": "设置私聊中操作的群档",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【私聊绑定】\n"
            "• 私聊绑定：查看当前已绑定群与可绑定群列表\n"
            "• 私聊绑定 [群号]：切换私聊当前操作群\n"
            "• 绑定的含义是“私聊里现在操作哪一个群档”\n"
            "• 绑定后，私聊中的聚灵 / 档案 / 背包 / 药圃 / 熔炼等功能都作用于该群档\n"
            "• 你只能绑定到自己已经登记过的群\n"
            "─────────────────\n"
            "私聊绑定"
        ),
    },
    {
        "id": "data_sharing",
        "slash": ["数据共享", "共享档案", "共享存档"],
        "text": ["数据共享"],
        "help_keywords": ["数据共享", "共享档案", "共享存档"],
        "section": "admin",
        "display_name": "数据共享",
        "description": "管理自己的多群共享档",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【数据共享】\n"
            "• 数据共享：查看你当前拥有的各群档概况\n"
            "• 数据共享 设置 [主档群号] [副档群号]：让副档跟随主档数据\n"
            "• 数据共享 取消 [副档群号]：取消共享，把当前主档复制回该群，恢复独立档\n"
            "• 共享的含义是“多个群共用同一份修行数据”\n"
            "• 与“私聊绑定”不同：私聊绑定只决定当前操作哪个群，数据共享则是让多个群真的共用一份档\n"
            "• 设置共享后，副档原有数据会被主档覆盖，请谨慎操作\n"
            "─────────────────\n"
            "数据共享"
        ),
    },

    # ==================== 修行 ====================
    {
        "id": "meditate",
        "slash": ["聚灵", "聚灵修行"],
        "text": ["聚灵", "聚灵修行"],
        "help_keywords": ["聚灵", "聚灵修行", "灵质修行", "聚灵台"],
        "section": "cultivation",
        "display_name": "聚灵台 · 灵质修行",
        "description": "汲取天地灵气，每日修行",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【聚灵台 · 灵质修行】\n"
            "• 每日可执行 1 次\n"
            "• 群内作用于当前群档\n"
            "• 私聊作用于绑定群档\n"
            "• 收益受等级、运势、道具、世界事件影响\n"
            "─────────────────\n"
            "聚灵"
        ),
    },
    {
        "id": "fortune",
        "slash": ["求签", "每日灵签"],
        "text": ["求签", "每日灵签", "灵签"],
        "help_keywords": ["求签", "灵签", "每日灵签"],
        "section": "cultivation",
        "display_name": "每日灵签",
        "description": "今日运势宜忌",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【聚灵台 · 每日灵签】\n"
            "• 每日一次，测测今日运势\n"
            "• 运势影响聚灵收益\n"
            "• 私聊可用\n"
            "─────────────────\n"
            "求签"
        ),
    },
    {
        "id": "expedition",
        "slash": ["派遣", "妖灵派遣", "灵风传送"],
        "text": ["派遣", "妖灵派遣", "灵风传送"],
        "help_keywords": ["派遣", "妖灵派遣", "灵风传送", "探索", "灵域"],
        "section": "cultivation",
        "display_name": "灵风传送 · 妖灵派遣",
        "description": "探索九大灵域",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【灵风传送 · 妖灵派遣】\n"
            "• 派遣 查看九大灵域\n"
            "• 派遣 [地点名] 出发\n"
            "• 私聊中作用于绑定群档\n"
            "• 派遣期间无法聚灵\n"
            "─────────────────\n"
            "派遣"
        ),
    },
    {
        "id": "recall",
        "slash": ["召回", "强制召回"],
        "text": ["召回", "强制召回"],
        "section": "cultivation",
        "display_name": "强制召回",
        "description": "中止探索，召回灵体",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": None,
    },
    {
        "id": "garden",
        "slash": ["药圃", "我的药圃", "妖灵药圃", "灵植小院"],
        "text": ["药圃", "我的药圃", "妖灵药圃", "灵植小院"],
        "help_keywords": ["药圃", "我的药圃", "妖灵药圃", "灵植小院"],
        "section": "cultivation",
        "display_name": "妖灵药圃 · 灵植小院",
        "description": "四块灵田，播种灌溉收获",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【妖灵药圃 · 灵植小院】\n"
            "• 4 块灵田，独立种植\n"
            "• 群内作用于当前群档\n"
            "• 私聊作用于绑定群档\n"
            "• 流程：播种 → 灌溉 → 收获\n"
            "─────────────────\n"
            "药圃"
        ),
    },
    {
        "id": "sow",
        "slash": ["播种"],
        "text": ["播种"],
        "section": "cultivation",
        "display_name": "播种",
        "description": "消耗种子种下灵植",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "water",
        "slash": ["灌溉", "浇水"],
        "text": ["灌溉", "浇水"],
        "section": "cultivation",
        "display_name": "灌溉",
        "description": "为灵植浇灌灵泉",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "harvest",
        "slash": ["收获"],
        "text": ["收获"],
        "section": "cultivation",
        "display_name": "收获",
        "description": "采摘成熟灵植",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "bag",
        "slash": ["储物袋", "背包", "我的背包"],
        "text": ["储物袋", "背包", "我的背包"],
        "section": "cultivation",
        "display_name": "灵质空间 · 储物袋",
        "description": "查看道具一览",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": None,
    },
    {
        "id": "use_item",
        "slash": ["使用"],
        "text": ["使用"],
        "section": "cultivation",
        "display_name": "使用道具",
        "description": "使用背包中的道具",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "has_args": True,
        "help_detail": None,
    },
    {
        "id": "smelt",
        "slash": ["熔炼", "法宝熔炼"],
        "text": ["熔炼", "法宝熔炼"],
        "help_keywords": ["熔炼", "法宝熔炼", "君阁工坊"],
        "section": "cultivation",
        "display_name": "君阁工坊 · 法宝熔炼",
        "description": "法宝碎片重铸",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【君阁工坊 · 法宝熔炼】\n"
            "• 消耗法宝碎片 x10\n"
            "• 群内作用于当前群档\n"
            "• 私聊作用于绑定群档\n"
            "• 虚空结晶 / 吉兆可提升品质\n"
            "─────────────────\n"
            "熔炼"
        ),
    },
    {
        "id": "lore",
        "slash": ["图鉴", "道具图鉴"],
        "text": ["图鉴", "道具图鉴"],
        "help_keywords": ["图鉴", "道具图鉴", "道具说明"],
        "section": "cultivation",
        "display_name": "道具图鉴",
        "description": "查看道具碎碎念描述",
        "min_tier": "allied",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【道具图鉴 · 碎碎念】\n"
            "• 图鉴 查看所有道具分类\n"
            "• 图鉴 [道具名] 查看碎碎念描述\n"
            "─────────────────\n"
            "图鉴 灵心草"
        ),
    },
    {
        "id": "unlock",
        "slash": ["解锁", "解锁灵域"],
        "text": ["解锁"],
        "section": "cultivation",
        "display_name": "灵域解锁",
        "description": "使用析沐的钥匙解锁灵域",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "has_args": True,
        "help_detail": None,
    },
    {
        "id": "altar",
        "slash": ["祭坛", "催更祭坛"],
        "text": ["催更祭坛", "祭坛"],
        "help_keywords": ["祭坛", "催更祭坛", "催更", "木头的催更祭坛"],
        "section": "cultivation",
        "display_name": "木头的催更祭坛",
        "description": "汇集全服怨气的祭坛",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": True,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【木头的催更祭坛】\n"
            "• 每次聚灵自动上缴 1% 灵力\n"
            "• 祭坛是全服唯一共享系统\n"
            "• 能量满阈值时触发全服加成\n"
            "─────────────────\n"
            "祭坛"
        ),
    },
    {
        "id": "achievement",
        "slash": ["成就", "我的成就"],
        "text": ["我的成就", "成就系统"],
        "help_keywords": ["成就", "我的成就", "成就系统"],
        "section": "cultivation",
        "display_name": "会馆成就系统",
        "description": "查看当前群档已解锁成就",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【成就系统】\n"
            "• 当前查看的是当前群档成就\n"
            "• 私聊中查看绑定群档成就\n"
            "• 通过修行/探索/战斗解锁成就\n"
            "─────────────────\n"
            "我的成就"
        ),
    },
    {
        "id": "title",
        "slash": ["称号", "我的称号"],
        "text": ["我的称号", "称号系统"],
        "help_keywords": ["称号", "我的称号", "称号系统"],
        "section": "cultivation",
        "display_name": "称号系统",
        "description": "佩戴当前群档称号",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "has_args": True,
        "help_detail": None,
    },
    {
        "id": "ranking",
        "slash": [
            "排行榜", "排行", "榜单",
            "灵力排行榜", "灵力榜", "灵力排行",
            "嘿咻排行榜", "嘿咻榜", "嘿咻排行",
            "聚灵排行榜", "聚灵榜", "聚灵排行",
            "厨房排行榜", "厨房榜", "厨房排行",
            "派遣排行榜", "派遣榜", "派遣排行",
            "顿悟排行榜", "顿悟榜", "顿悟排行",
            "毛球排行榜", "毛球榜", "毛球排行",
        ],
        "text": [
            "排行榜",
            "灵力排行榜", "灵力榜", "灵力排行",
            "嘿咻排行榜", "嘿咻榜", "嘿咻排行",
            "聚灵排行榜", "聚灵榜", "聚灵排行",
            "厨房排行榜", "厨房榜", "厨房排行",
            "派遣排行榜", "派遣榜", "派遣排行",
            "顿悟排行榜", "顿悟榜", "顿悟排行",
            "毛球排行榜", "毛球榜", "毛球排行",
        ],
        "section": "cultivation",
        "display_name": "会馆排行榜",
        "description": "查看当前群多榜排行",
        "min_tier": "allied",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "has_args": True,
        "help_keywords": [
            "排行榜", "排行", "榜单",
            "灵力排行榜", "嘿咻排行榜", "聚灵排行榜",
            "厨房排行榜", "派遣排行榜",
            "顿悟排行榜", "毛球排行榜",
        ],
        "help_detail": (
            "【会馆排行榜系统】\n"
            "• 群内查看当前群排行\n"
            "• 私聊查看绑定群排行\n"
            "• 可直接发送 灵力排行榜 / 嘿咻排行榜 / 顿悟排行榜 / 毛球排行榜 等\n"
            "─────────────────\n"
            "灵力排行榜"
        ),
    },
    {
        "id": "world_event",
        "slash": ["世界事件", "事件", "灵潮"],
        "text": ["世界事件"],
        "section": "cultivation",
        "display_name": "世界事件",
        "description": "查看当前全服事件状态",
        "min_tier": "allied",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【世界事件系统】\n"
            "• 世界事件为全服同步事件\n"
            "• 所有游戏群统一经历同一事件\n"
            "─────────────────\n"
            "世界事件"
        ),
    },

    # ==================== 娱乐 ====================
    {
        "id": "kitchen",
        "slash": ["厨房", "厨房挑战", "厨房生存", "厨房生存战"],
        "text": ["厨房", "厨房挑战", "厨房生存", "厨房生存战"],
        "help_keywords": ["厨房", "厨房挑战", "厨房生存", "无限大人的厨房"],
        "section": "entertainment",
        "display_name": "无限大人的厨房生存战",
        "description": "赌上味蕾的一餐",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【无限大人的厨房生存战】\n"
            "• 公开群可玩\n"
            "• 已登记玩家在当前群档结算灵力\n"
            "• 私聊中作用于绑定群档\n"
            "─────────────────\n"
            "厨房"
        ),
    },
    {
        "id": "appraise",
        "slash": ["鉴定", "灵质鉴定"],
        "text": ["鉴定", "灵质鉴定"],
        "help_keywords": ["鉴定", "灵质鉴定", "灵力鉴定", "灵力检测"],
        "section": "entertainment",
        "display_name": "灵质鉴定",
        "description": "检测灵力纯度与隐藏属性",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【灵质鉴定 · 隐藏属性】\n"
            "• 群内作用于当前群档\n"
            "• 私聊作用于绑定群档\n"
            "• 持有鸾草或吉兆可出稀有\n"
            "─────────────────\n"
            "鉴定"
        ),
    },
    {
        "id": "duel",
        "slash": ["切磋", "灵力切磋", "PK", "领域较量"],
        "text": ["切磋"],
        "help_keywords": ["切磋", "PK", "灵力切磋", "演武场", "领域较量", "斗帅宫"],
        "section": "entertainment",
        "display_name": "灵质空间 · 演武场",
        "description": "与其他妖灵进行群级切磋",
        "min_tier": "allied",
        "require_registered": True,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【灵质空间 · 演武场】\n"
            "• 切磋 @某人 进行灵力比拼\n"
            "• 只在当前群档内结算\n"
            "• 私聊不可用\n"
            "─────────────────\n"
            "切磋 @某人"
        ),
    },
    {
        "id": "heixiu_catch",
        "slash": ["捕捉", "捕捉嘿咻"],
        "text": ["捕捉", "捕捉嘿咻"],
        "section": "entertainment",
        "display_name": "嘿咻捕获计划",
        "description": "野生嘿咻出没时发送捕捉",
        "min_tier": "allied",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": False,
        "help_detail": (
            "【嘿咻捕获计划】\n"
            "• 每个游戏群可独立刷新嘿咻\n"
            "• 捕捉结果记入当前群档\n"
            "• 全局嘿咻总数也会累加\n"
            "• 私聊不可用\n"
            "─────────────────\n"
            "嘿咻出现时发送 捕捉"
        ),
    },
    {
        "id": "truth",
        "slash": ["真心话"],
        "text": ["真心话"],
        "section": "entertainment",
        "display_name": "真心话",
        "description": "灵力诚实探测",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【真心话大冒险 · 真心话】\n"
            "• 公开群可用的轻娱乐玩法\n"
            "• 题库按群层级分层抽取：\n"
            " - public：general 通用题\n"
            " - allied：lxh 联动题 + general 通用题\n"
            " - core：core_local 会馆题 + lxh 联动题 + general 通用题\n"
            "• 私聊已绑定时：按绑定群层级抽题\n"
            "• 私聊未绑定时：使用通用题库\n"
            "• 系统会尽量避开短期重复题\n"
            "─────────────────\n"
            "真心话"
        ),
        "help_keywords": ["真心话", "真心话大冒险"],
    },
    {
        "id": "dare",
        "slash": ["大冒险"],
        "text": ["大冒险"],
        "section": "entertainment",
        "display_name": "大冒险",
        "description": "灵压勇气挑战",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【真心话大冒险 · 大冒险】\n"
            "• 公开群可用的轻娱乐玩法\n"
            "• 题库按群层级分层抽取：\n"
            " - public：general 通用挑战\n"
            " - allied：lxh 联动挑战 + general 通用挑战\n"
            " - core：core_local 会馆挑战 + lxh 联动挑战 + general 通用挑战\n"
            "• 私聊已绑定时：按绑定群层级抽题\n"
            "• 私聊未绑定时：使用通用题库\n"
            "• 系统会尽量避开短期重复题\n"
            "─────────────────\n"
            "大冒险"
        ),
        "help_keywords": ["大冒险", "真心话大冒险"],
    },
    {
        "id": "soulmate",
        "slash": ["灵伴", "今日灵伴"],
        "text": ["今日灵伴"],
        "section": "entertainment",
        "display_name": "今日灵伴",
        "description": "当前群每日灵力共鸣匹配",
        "min_tier": "allied",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": False,
        "help_detail": (
            "【灵力宿命 · 今日灵伴】\n"
            "• 从当前群全体成员中匹配\n"
            "• 奖励记入当前群档\n"
            "• 私聊不可用\n"
            "─────────────────\n"
            "今日灵伴"
        ),
    },
    {
        "id": "waifu",
        "slash": ["今日老婆"],
        "text": ["今日老婆"],
        "section": "entertainment",
        "display_name": "今日老婆",
        "description": "致敬萝卜前辈",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "quit_easter_egg",
        "slash": [],
        "text": ["退出此群"],
        "section": "entertainment",
        "display_name": "退出彩蛋",
        "description": "致敬萝卜",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": False,
        "hidden": True,
        "help_detail": None,
    },

    # ==================== 引导类 ====================
    {
        "id": "menu",
        "slash": ["菜单"],
        "text": ["菜单"],
        "section": "_guide",
        "display_name": "功能菜单",
        "description": "查看所有功能",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "view_commands",
        "slash": ["指令", "查看指令", "所有指令"],
        "text": ["查看指令", "所有指令"],
        "section": "_guide",
        "display_name": "查看指令",
        "description": "查看所有可用指令",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "admin_commands",
        "slash": ["管理员指令", "管理指令"],
        "text": ["管理员指令", "管理指令"],
        "section": "_guide",
        "display_name": "管理员指令",
        "description": "查看管理组/决策组专属指令",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
        "help_keywords": ["管理员指令", "管理指令"],
    },
    {
        "id": "help",
        "slash": ["说明", "规则"],
        "text": ["说明"],
        "section": "_guide",
        "display_name": "功能说明",
        "description": "查看详细规则",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "has_args": True,
        "help_detail": None,
    },
    {
        "id": "manual",
        "slash": ["使用手册", "用户手册", "用户使用手册", "新手指南"],
        "text": ["使用手册", "用户手册", "用户使用手册", "新手指南"],
        "section": "_guide",
        "display_name": "使用手册",
        "description": "获取完整使用手册文件",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
        "help_keywords": ["使用手册", "手册", "帮助", "新手"],
    },
    {
        "id": "about",
        "slash": ["关于"],
        "text": [],
        "section": "_guide",
        "display_name": "关于会馆",
        "description": "会馆缘起与愿景",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
    },
    {
        "id": "join_guide",
        "slash": [],
        "text": ["加入会馆", "加入晋宁", "加入晋宁会馆"],
        "section": "_guide",
        "display_name": "加入引导",
        "description": "如何加入晋宁会馆",
        "min_tier": "public",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": False,
        "allow_private": True,
        "hidden": True,
        "help_detail": None,
    },

    # ==================== 管理控制台 ====================
    {
        "id": "persona",
        "slash": ["切换人格", "变身", "切换模式"],
        "text": [],
        "section": "console",
        "display_name": "人格切换",
        "description": "切换秃贝的性格模式",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【人格切换】\n"
            "• /切换人格 查看可用模式\n"
            "• /切换人格 [代码] 切换\n"
            "─────────────────\n"
            "/切换人格"
        ),
        "help_keywords": ["人格", "切换人格", "变身", "模式"],
    },
    {
        "id": "system_status",
        "slash": ["系统状态", "查看状态"],
        "text": [],
        "section": "console",
        "display_name": "系统状态",
        "description": "查看系统运行数据",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "help_detail": None,
        "help_keywords": ["系统状态", "状态"],
    },
    {
        "id": "broadcast",
        "slash": ["全员广播", "广播", "公告"],
        "text": [],
        "section": "console",
        "display_name": "全员广播",
        "description": "向所有核心群发送公告",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "help_detail": None,
        "help_keywords": ["广播", "公告"],
    },
    {
        "id": "ban",
        "slash": ["封印", "关小黑屋"],
        "text": [],
        "section": "console",
        "display_name": "封印",
        "description": "封禁指定用户的灵力回路",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "help_detail": None,
        "help_keywords": ["封印", "封禁", "小黑屋"],
    },
    {
        "id": "gift_all",
        "slash": ["全员福利", "发红包"],
        "text": [],
        "section": "console",
        "display_name": "全员福利",
        "description": "向全体成员发放灵力或道具",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "help_detail": (
            "【全员福利】\n"
            "• /全员福利 sp 100\n"
            "• /全员福利 item 神秘种子 3\n"
            "─────────────────\n"
            "/全员福利 sp [数量]"
        ),
        "help_keywords": ["福利", "发红包", "全员福利"],
    },
    {
        "id": "reload_config",
        "slash": ["重载配置", "刷新配置", "reload"],
        "text": [],
        "section": "console",
        "display_name": "重载配置",
        "description": "热重载文案和数值配置",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "help_detail": None,
        "help_keywords": ["重载", "刷新配置", "reload"],
    },
    {
        "id": "force_save",
        "slash": ["强制保存", "保存数据", "save"],
        "text": [],
        "section": "console",
        "display_name": "强制保存",
        "description": "立即将内存数据写入磁盘",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "help_detail": None,
        "help_keywords": ["保存", "save"],
    },
    {
        "id": "promo_toggle",
        "slash": ["宣传开关"],
        "text": [],
        "section": "console",
        "display_name": "宣传开关",
        "description": "开启或关闭宣传功能",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "help_detail": None,
        "help_keywords": ["宣传"],
    },
    {
        "id": "purge_archive",
        "slash": ["彻底清档"],
        "text": [],
        "section": "console",
        "display_name": "彻底清档",
        "description": "彻底清除指定用户的整套档案（不可逆）",
        "min_tier": "core",
        "require_registered": False,
        "admin_only": False,
        "core_only": False,
        "decision_only": True,
        "allow_private": True,
        "hidden": False,
        "has_args": True,
        "help_detail": (
            "【控制台 · 彻底清档】\n"
            "• /彻底清档 [QQ]\n"
            "• 物理删除该用户的整套 member + spirit\n"
            "• 删除前自动备份\n"
            "• 需要二次确认\n"
            "• 删除后用户可自行重新登记\n"
            "─────────────────\n"
            "/彻底清档 123456"
        ),
        "help_keywords": ["彻底清档", "清档"],
    },
]


# ================================================================
# 工具函数
# ================================================================
def get_commands_by_section(section: str) -> List[Dict[str, Any]]:
    return [c for c in COMMANDS if c["section"] == section and not c.get("hidden", False)]


def get_all_text_triggers() -> Dict[str, str]:
    mapping = {}
    for cmd in COMMANDS:
        for t in cmd.get("text", []):
            mapping[t] = cmd["id"]
    return mapping


def get_text_prefix_triggers() -> Dict[str, str]:
    result = {}
    for cmd in COMMANDS:
        if cmd.get("has_args") and cmd.get("text"):
            for t in cmd["text"]:
                result[t] = cmd["id"]
    return result


def get_command_by_id(cmd_id: str) -> Optional[Dict[str, Any]]:
    for cmd in COMMANDS:
        if cmd["id"] == cmd_id:
            return cmd
    return None


def get_help_detail(keyword: str) -> Optional[str]:
    keyword = keyword.strip()
    for cmd in COMMANDS:
        if cmd.get("help_detail") is None:
            continue

        if keyword == cmd["id"]:
            return cmd["help_detail"]
        if keyword == cmd.get("display_name", ""):
            return cmd["help_detail"]

        dn = cmd.get("display_name", "")
        if dn and keyword in dn:
            return cmd["help_detail"]

        if keyword in cmd.get("slash", []):
            return cmd["help_detail"]
        if keyword in cmd.get("text", []):
            return cmd["help_detail"]
        if keyword in cmd.get("help_keywords", []):
            return cmd["help_detail"]

    return None


def get_section_help_keywords() -> List[str]:
    keywords = []
    for cmd in COMMANDS:
        if cmd.get("help_detail"):
            dn = cmd.get("display_name", "")
            if dn:
                keywords.append(dn)
            elif cmd.get("text"):
                keywords.append(cmd["text"][0])
            elif cmd.get("slash"):
                keywords.append(cmd["slash"][0])
    return keywords