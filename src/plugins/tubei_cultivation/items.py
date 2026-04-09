""" 晋宁会馆·秃贝五边形 5.0 灵质空间 —— 储物袋 + 道具使用 + 法宝熔炼 + 灵域解锁（结构收口版）
收口目标：
1. 保留全部现有功能，不删减玩法
2. 将“使用道具”的超长条件分支拆为更清晰的内部 helper
3. 毛球玩法继续保持类型化与配置化
4. 继续优先使用 DataManager 原子 helper
5. 保持现有文案与用户体验，不做无意义文案改写
"""
from __future__ import annotations

import random
import time
import asyncio
from typing import Optional, Tuple

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.adapters import Message

from src.common.utils import check_blessing, ensure_daily_reset
from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext
from src.plugins.tubei_system.config import game_config
from src.plugins.tubei_system.recorder import recorder
from src.plugins.tubei_cultivation.achievement import achievement_engine

ARTIFACTS = {
    "灵心草": {
        "desc": "下次聚灵总收益×1.5",
        "type": "buff",
        "lore": (
            "据说是会馆后山最常见的杂草。"
            "但不知道为什么，嚼一片再去聚灵，"
            "灵气就像不要钱似的往身体里灌。"
            "析沐大人曾经试图拔光它们来美化环境，"
            "结果第二天又长满了。生命力真强。"
        ),
    },
    "蓝玉果": {
        "desc": "下次聚灵基础值锁定最大值",
        "type": "buff",
        "lore": (
            "蓝得不太正常的果子，咬一口满嘴灵气。"
            "传说是从灵溪上游漂下来的，"
            "没人知道上游到底有什么。"
            "吉熙馆长说她小时候拿这个当弹珠玩，"
            "浪费了多少修行资源啊这位。"
        ),
    },
    "鸾草": {
        "desc": "下次灵质鉴定必出稀有词条",
        "type": "buff",
        "lore": (
            "叶片上天然带着奇怪的纹路，"
            "像是谁在上面写了字又擦掉了。"
            "鉴定师说这种草能和灵质产生共振，"
            "所以拿着它做鉴定特别准。"
            "秃贝曾经偷吃了一片，"
            "结果打嗝打了三天，每个嗝都带火花。"
        ),
    },
    "凤羽花": {
        "desc": "下次派遣必掉落法宝碎片",
        "type": "buff",
        "lore": (
            "花瓣是橙红色的，逆光看像在燃烧。"
            "鸠老说这花只在有宝物的地方绽放，"
            "所以带着它出去探索，"
            "总能找到好东西。"
            "唯一的缺点是太好看了，"
            "经常被采回来插花瓶，浪费了。"
        ),
    },
    "忘忧草": {
        "desc": "立即消除[味蕾丧失]状态",
        "type": "active",
        "lore": (
            "闻一下就觉得世界美好了。"
            "发明这个的人一定吃过无限大人做的饭。"
            "事实上，整个忘忧草的培育项目"
            "就是管理组专门为'无限大人的厨房'"
            "配套开发的应急预案。"
            "无限本人对此表示：'我做的饭明明很好吃。'"
        ),
    },
    "聚灵花": {
        "desc": "使用后立即获得 15 灵力",
        "type": "active",
        "lore": (
            "把花瓣碾碎就能释放出纯净的灵气。"
            "很多小妖嫌聚灵太慢就嚼这个，"
            "相当于灵界的功能饮料。"
            "但老一辈的妖精觉得这样不踏实，"
            "'修行哪有走捷径的？'"
            "然后他们自己偷偷也嚼。"
        ),
    },
    "涪灵丹": {
        "desc": "抵消下次厨房失败惩罚",
        "type": "buff",
        "lore": (
            "专门给要去无限大人厨房吃饭的勇士准备的。"
            "提前服用，可在胃壁形成灵力保护膜。"
            "发明者是焚大人，"
            "因为她是第一个因为'给面子'"
            "而吃完无限的料理的妖精。"
            "她活了几亿年，那是她最接近死亡的一次。"
        ),
    },
    "玄清丹": {
        "desc": "重置今日聚灵次数",
        "type": "active",
        "lore": (
            "吃了之后灵脉里堵住的灵气一下子通了。"
            "感觉就像被人拍了一下后背。"
            "制作工艺据说失传了，"
            "但不知道为什么派遣的时候偶尔能捡到。"
            "也许古人也有'今天还想再练一次'的烦恼。"
        ),
    },
    "清心露": {
        "desc": "今日厨房成功率+20%",
        "type": "buff",
        "lore": (
            "一小瓶透明的液体，喝了心特别静。"
            "面对无限大人端出来的不明物体时，"
            "你能用更平和的心态去品尝。"
            "当然，平和不代表好吃。"
            "只是你不那么害怕了而已。"
            "生产商：云隐茶楼 · 监制：管理组。"
        ),
    },
    "空间简片": {
        "desc": "下次派遣耗时减半",
        "type": "buff",
        "lore": (
            "一片薄如蝉翼的透明碎片，"
            "据说是上古空间法宝破碎后的残余。"
            "贴在身上可以短暂折叠空间，"
            "赶路速度翻倍。"
            "副作用是会晕车。"
            "嗯，晕空间。"
        ),
    },
    "引灵香": {
        "desc": "立即在群内召唤一只野生嘿咻",
        "type": "active_group",
        "lore": (
            "点燃后会散发出嘿咻们无法抗拒的香气。"
            "成分是个谜，据说包含了三种嘿咻喜欢的味道："
            "阳光的味道、树叶的味道、"
            "以及析沐大人洗完头的味道。"
            "析沐：'最后一个是谁加的？？？'"
        ),
    },
    "万宝如意": {
        "desc": "下次熔炼品质至少为稀有",
        "type": "buff",
        "lore": (
            "如意造型的小法宝，放在熔炉旁边"
            "就能让炉火变得温顺听话。"
            "它不保证你能炼出什么，"
            "但保证炼出来的东西不会太差。"
            "'至少是个稀有。'——这是它的底线。"
            "'但也可能只是个稀有。'——这也是它的底线。"
        ),
    },
    "五行灵核": {
        "desc": "药圃任意一株瞬间成熟",
        "type": "active",
        "lore": (
            "五种颜色交替闪烁的小球，"
            "拿在手里微微发烫。"
            "埋进土里可以瞬间催熟一株灵植。"
            "代价是周围半径三米的草全秃了。"
            "所以请不要在析沐大人头上使用。"
            "不是，他头上的是树枝不是草——算了。"
        ),
    },
    "护身符": {
        "desc": "下次派遣灵力收益+20%",
        "type": "buff",
        "lore": (
            "管理组统一制作的黄色符纸，"
            "上面画着看不懂的符文。"
            "据事泽大人说，这些符文的意思是"
            "'出门在外注意安全早点回来'。"
            "很朴实，但确实有用。"
            "有种被老妈塞红包的感觉。"
        ),
    },
    "完整天明珠": {
        "desc": "使用后永久聚灵收益+5",
        "type": "permanent",
        "lore": (
            "龙脉深处凝结的灵气结晶，"
            "发出温暖的白光。"
            "融入灵脉后，你的身体会永远记住"
            "这种'被灵气包围'的感觉，"
            "从此聚灵效率永久提升。"
            "持有者感言：'我觉得我开挂了。'"
            "管理组回应：'你没有，这是合法的。'"
        ),
    },
    "上古秘卷": {
        "desc": "使用后永久派遣收益+3",
        "type": "permanent",
        "lore": (
            "泛黄的卷轴上记载着古代妖灵的探索经验。"
            "读完之后你会发现，"
            "原来那些灵域的好东西都藏在你想不到的地方。"
            "'原来要翻开第三块石板啊...'"
            "从此每次派遣都能多带点好东西回来。"
            "知识就是力量，诚不欺我。"
        ),
    },
    "法宝碎片": {
        "desc": "熔炼主材料（10 个熔炼一次）",
        "type": "material",
        "lore": (
            "到处都能捡到的法宝残骸。"
            "单独一片没什么用，"
            "但攒够十片扔进熔炉，"
            "说不定能炼出比原来更好的东西。"
            "'垃圾是放错位置的资源'"
            "——某位不愿透露姓名的炼器师。"
        ),
    },
    "神秘种子": {
        "desc": "药圃播种消耗品",
        "type": "seed",
        "lore": (
            "不知道是什么植物的种子，"
            "但种下去一定会长出有用的东西。"
            "有人怀疑这些种子是析沐大人"
            "从头上撇下来的树枝变的。"
            "析沐：'别什么都往我头上安。'"
            "种子：（沉默但发芽了）"
        ),
    },
    "虚空结晶": {
        "desc": "熔炼时自动消耗，产物品质提升一档",
        "type": "material",
        "lore": (
            "从镜中世界带回来的透明结晶，"
            "里面好像封着一小块扭曲的空间。"
            "扔进熔炉里可以提升产物品质。"
            "原理是什么？没人知道。"
            "'也许是因为虚空中什么都有可能发生吧。'"
            "——秃贝如是说（其实它也不懂）。"
        ),
    },
    "露水凝珠": {
        "desc": "灌溉时自动消耗，浇水效果翻倍",
        "type": "material",
        "lore": (
            "清晨从灵溪浅滩收集的灵露，"
            "凝结成珍珠大小的水滴。"
            "用它浇灌植物，一次顶两次。"
            "植物们特别喜欢这个，"
            "大概就像人类觉得"
            "矿泉水比自来水高级一样吧。"
        ),
    },
    "普通嘿咻毛球": {
        "desc": "可反复抚摸，大概率获得少量灵力，小概率掉落基础资源；摸太多会掉毛、揉散",
        "type": "heixiu_fur",
        "lore": (
            "从普通嘿咻身上蹭下来的柔软绒毛，"
            "没有生命，只是一小团残留着空间灵气的毛。"
            "摸起来很舒服，摸久了会慢慢掉毛。"
        ),
    },
    "彩虹嘿咻毛球": {
        "desc": "可反复抚摸，大概率获得少量灵力，小概率掉落稀有灵植或法宝；摸太多会掉毛、揉散",
        "type": "heixiu_fur",
        "lore": (
            "带着淡淡虹光的柔软绒毛，"
            "像从彩色的梦里落下来的一小团光。"
            "看起来很脆弱，摸多了会慢慢散掉。"
        ),
    },
    "黄金嘿咻毛球": {
        "desc": "可反复抚摸，大概率获得少量灵力，小概率掉落更稀有的法宝或灵植；摸太多会掉毛、揉散",
        "type": "heixiu_fur",
        "lore": (
            "隐隐泛着金光的绒毛团，"
            "摸上去比普通毛球更细密、更暖。"
            "只是再好的毛，也经不起没完没了地揉。"
        ),
    },
    "暗影嘿咻毛球": {
        "desc": "可反复抚摸，大概率获得少量灵力，小概率掉落诡异副产物；摸太多会掉毛、揉散",
        "type": "heixiu_fur",
        "lore": (
            "颜色偏深的绒毛团，"
            "摸起来凉凉的，有点像夜色本身。"
            "它没有生命，但总让人觉得它好像知道些什么。"
        ),
    },
    "吉熙的信羽": {
        "desc": "获得「吉兆」Buff(24h)，每个系统各一次最佳结果",
        "type": "blessing_feather",
        "lore": (
            "前馆长吉熙的喜鹊之羽，"
            "洁白的羽毛上流转着淡淡的金光。"
            "据说拿着它做任何事都会特别顺利。"
            "'喜鹊报喜嘛，这是种族天赋。'"
            "吉熙本人如是说，然后得意地拍了拍翅膀。"
            "持此羽毛任何项目均可获最佳结果！"
            "24 小时后效果自动消失。"
        ),
    },
    "焚的残火": {
        "desc": "立即获得当前灵力×25%",
        "type": "ancient_flame",
        "lore": (
            "焚大人指尖偶然落下的一缕残火。"
            "几亿年的岁月都没能将它熄灭，"
            "可见其中蕴含的力量有多深厚。"
            "古老的火焰会燃烧掉灵力中的杂质，"
            "纯化后的灵力反而更加充沛。"
            "焚大人：'不过是指缝间漏出的余烬罢了。'"
            "小妖们：（看着暴涨 25%的灵力感动哭了）"
        ),
    },
    "破碎星核": {
        "desc": "使用后永久聚灵收益+3",
        "type": "permanent",
        "lore": (
            "熔炉爆炸时偶尔产生的奇异结晶。"
            "理论上不应该存在，"
            "但它就是出现了。"
            "吸收后会感觉灵脉里多了一个小太阳，"
            "暖暖的，每次聚灵都比以前多一点点。"
            "'失败是成功之母'的最佳代言。"
        ),
    },
    "混沌残片": {
        "desc": "下次熔炼必出传说品质",
        "type": "buff",
        "lore": (
            "熔炉彩蛋中的彩蛋，"
            "一块不断变换颜色的碎片。"
            "拿着它靠近熔炉时，"
            "炉火会变成七彩色。"
            "此时熔炼出来的东西..."
            "必定是传说级别的。"
            "'运气这种东西，偶尔也会站在你这边。'"
        ),
    },
}

bag_cmd = on_command("我的背包", aliases={"背包", "储物袋"}, priority=5, block=True)
use_cmd = on_command("使用", priority=5, block=True)
smelt_cmd = on_command("法宝熔炼", aliases={"熔炼"}, priority=5, block=True)
lore_cmd = on_command("图鉴", aliases={"道具图鉴", "碎碎念"}, priority=5, block=True)
unlock_cmd = on_command("解锁", aliases={"解锁灵域"}, priority=5, block=True)


def _footer_with_ctx(ctx: GroupContext, text: str) -> str:
    if ctx.is_private:
        return f"{text}\n 当前操作群：{ctx.group_name}"
    return text


def _fur_daily_count_key(item_name: str) -> str:
    return f"{item_name}_pet_count"


def _fur_daily_warning_key(item_name: str) -> str:
    return f"{item_name}_warning"


def _get_fur_warning_threshold() -> int:
    return int(game_config.heixiu_fur_warning_threshold)


def _get_fur_disappear_rate_map() -> dict:
    raw = game_config.heixiu_fur_disappear_rates or {}
    if not isinstance(raw, dict):
        return {
            "11": 0.12,
            "12": 0.18,
            "13": 0.25,
            "14": 0.35,
            "default_after": 0.50,
        }
    return raw


def _get_fur_roll_weights() -> dict:
    raw = game_config.heixiu_fur_roll_weights or {}
    if not isinstance(raw, dict):
        return {
            "sp_gain": 0.60,
            "cleanse_taste_loss": 0.03,
            "special_drop": 0.08,
            "comfort_only": 0.29,
        }
    return raw


def _get_fur_drop_pools() -> dict:
    raw = game_config.heixiu_fur_drop_pools or {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _fur_disappear_rate(pet_count: int) -> float:
    threshold = _get_fur_warning_threshold()
    if pet_count <= threshold:
        return 0.0
    rate_map = _get_fur_disappear_rate_map()
    return float(rate_map.get(str(pet_count), rate_map.get("default_after", 0.50)))


def _fur_comfort_text() -> str:
    from src.common.response_manager import resp_manager
    return resp_manager.get_random_from(
        "heixiu_fur_comfort",
        default="你揉了揉毛球，心情好像也跟着软了一点。"
    )


def _fur_warning_text() -> str:
    from src.common.response_manager import resp_manager
    return resp_manager.get_random_from(
        "heixiu_fur_warning",
        default="再这样揉下去，这团毛怕是要散了。"
    )


def _fur_disappear_text() -> str:
    from src.common.response_manager import resp_manager
    return resp_manager.get_random_from(
        "heixiu_fur_disappear",
        default="你一个没收住力，这团毛就被揉散了。"
    )


def _fur_sp_text(sp: int) -> str:
    from src.common.response_manager import resp_manager
    return resp_manager.get_random_from(
        "heixiu_fur_sp_gain",
        default=f"你从毛球里蹭出了一点灵气。✨灵力 +{sp}",
        sp=sp,
    )


def _fur_cleanse_text() -> str:
    from src.common.response_manager import resp_manager
    return resp_manager.get_random_from(
        "heixiu_fur_cleanse",
        default="你感觉那股难受的味觉后劲终于退去了。"
    )


def _fur_drop_text(item_name: str, count: int) -> str:
    from src.common.response_manager import resp_manager
    return resp_manager.get_random_from(
        "heixiu_fur_drop",
        default=f"你从毛球里摸出了【{item_name}】x{count}！",
        item=item_name,
        count=count,
    )


def _empty_fur_daily_fields() -> dict:
    return {
        _fur_daily_count_key("普通嘿咻毛球"): 0,
        _fur_daily_warning_key("普通嘿咻毛球"): False,
        _fur_daily_count_key("彩虹嘿咻毛球"): 0,
        _fur_daily_warning_key("彩虹嘿咻毛球"): False,
        _fur_daily_count_key("黄金嘿咻毛球"): 0,
        _fur_daily_warning_key("黄金嘿咻毛球"): False,
        _fur_daily_count_key("暗影嘿咻毛球"): 0,
        _fur_daily_warning_key("暗影嘿咻毛球"): False,
    }


async def _load_item_use_context(uid: str, ctx: GroupContext) -> tuple[dict, dict, dict]:
    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    buffs = dict(data.get("buffs", {}))
    daily = ensure_daily_reset(data, extra_fields=_empty_fur_daily_fields())
    return data, buffs, daily


async def _finish_use_result(use_matcher, ctx: GroupContext, title: str, result_msg: str, footer_text: str):
    await use_matcher.finish(
        ui.render_result_card(
            title,
            result_msg,
            footer=_footer_with_ctx(ctx, footer_text),
        )
    )


# ==================== 背包 ====================
@bag_cmd.handle()
async def handle_bag(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "灵质空间 · 储物袋",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await bag_cmd.finish(perm.deny_message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    items = data.get("items", {})
    valid_items = {k: v for k, v in items.items() if isinstance(v, int) and v > 0}

    if not valid_items:
        await bag_cmd.finish(
            ui.render_panel(
                "灵质空间 · 储物袋",
                " 背包空空如也~\n\n 通过派遣、药圃、熔炼可以获得道具",
                footer=_footer_with_ctx(ctx, " 输入 派遣 | 药圃 | 熔炼"),
            )
        )

    if len(valid_items) != len(items):
        await data_manager.update_spirit_data(uid, ctx.group_id, {"items": valid_items})

    lines = []
    for name, count in valid_items.items():
        desc = ARTIFACTS.get(name, {}).get("desc", "未知物品")
        lines.append(ui.render_bag_item(name, count, desc))

    card = ui.render_panel(
        f"灵质空间 · 储物袋 ({sum(valid_items.values())}件)",
        "\n".join(lines),
        footer=_footer_with_ctx(ctx, " 输入 使用 [物品名] | 图鉴 [物品名] | 熔炼"),
    )
    await bag_cmd.finish(card)


# ==================== 图鉴 ====================
@lore_cmd.handle()
async def handle_lore(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    ctx = await GroupContext.from_event(event)
    item_name = args.extract_plain_text().strip()

    if not item_name:
        categories = {
            " 灵植": ["灵心草", "蓝玉果", "鸾草", "凤羽花", "忘忧草", "聚灵花"],
            " 丹药": ["涪灵丹", "玄清丹", "清心露"],
            "⚡法宝": ["空间简片", "引灵香", "万宝如意", "五行灵核", "护身符"],
            " 秘宝": ["完整天明珠", "上古秘卷", "破碎星核"],
            " 材料": ["法宝碎片", "神秘种子", "虚空结晶", "露水凝珠"],
            " 毛球": ["普通嘿咻毛球", "彩虹嘿咻毛球", "黄金嘿咻毛球", "暗影嘿咻毛球", "混沌残片"],
            " 决策组信物": ["析沐的钥匙", "吉熙的信羽", "焚的残火"],
        }

        lines = []
        for cat, names in categories.items():
            lines.append(f"\n{cat}")
            for n in names:
                lines.append(f" · {n}")

        await lore_cmd.finish(
            ui.render_panel(
                "道具图鉴",
                "\n".join(lines),
                footer=_footer_with_ctx(ctx, " 输入 图鉴 [道具名] 查看碎碎念"),
            )
        )

    info = ARTIFACTS.get(item_name)
    if not info:
        await lore_cmd.finish(ui.error(f"未找到「{item_name}」的图鉴。"))

    lore_text = info.get("lore", "这个道具很神秘，连秃贝也不了解它。")
    desc = info.get("desc", "未知效果")

    card = ui.render_panel(
        item_name,
        f"✨效果：{desc}\n\n {lore_text}",
        footer=_footer_with_ctx(ctx, " 输入 背包 | 使用 [道具名]"),
    )
    await lore_cmd.finish(card)


# ==================== 使用道具：毛球 ====================
async def _handle_use_heixiu_fur(
    bot: Bot,
    event: MessageEvent,
    ctx: GroupContext,
    uid: str,
    item_name: str,
    data: dict,
    buffs: dict,
    daily: dict,
):
    pet_count_key = _fur_daily_count_key(item_name)
    warning_key = _fur_daily_warning_key(item_name)
    warning_threshold = _get_fur_warning_threshold()

    fur_drop_pools = _get_fur_drop_pools()
    roll_weights = _get_fur_roll_weights()

    sp_gain_rate = float(roll_weights.get("sp_gain", 0.60))
    cleanse_rate = float(roll_weights.get("cleanse_taste_loss", 0.03))
    special_drop_rate = float(roll_weights.get("special_drop", 0.08))

    cleanse_upper = sp_gain_rate + cleanse_rate
    special_drop_upper = cleanse_upper + special_drop_rate

    pet_count = int(daily.get(pet_count_key, 0)) + 1
    daily[pet_count_key] = pet_count

    await data_manager.increment_group_stat(uid, ctx.group_id, "total_fur_pet_count", 1)

    disappear_rate = _fur_disappear_rate(pet_count)
    if pet_count > warning_threshold and random.random() < disappear_rate:
        await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
        await data_manager.consume_spirit_item(uid, ctx.group_id, item_name, 1)

        await recorder.add_event(
            "use_item",
            int(uid),
            {
                "item": item_name,
                "group_id": ctx.group_id,
                "fur_pet_count": pet_count,
                "fur_disappeared": True,
            },
        )
        await achievement_engine.try_unlock(uid, "手下留毛", bot, event, group_id=ctx.group_id)

        await use_cmd.finish(
            ui.render_result_card(
                item_name,
                _fur_disappear_text(),
                stats=[
                    ("今日抚摸次数", str(pet_count)),
                    ("状态", "这团毛被你揉散了"),
                ],
                footer=_footer_with_ctx(ctx, " 明天记得克制一点，不然毛球可经不起一直揉"),
            )
        )

    if pet_count == warning_threshold and not daily.get(warning_key, False):
        daily[warning_key] = True
        await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)

        await recorder.add_event(
            "use_item",
            int(uid),
            {
                "item": item_name,
                "group_id": ctx.group_id,
                "fur_pet_count": pet_count,
                "fur_warning": True,
            },
        )

        await use_cmd.finish(
            ui.render_result_card(
                item_name,
                _fur_warning_text(),
                stats=[
                    ("今日抚摸次数", str(pet_count)),
                    ("危险阶段", "已进入"),
                ],
                footer=_footer_with_ctx(ctx, " 再继续揉下去，这团毛随时可能被你揉散"),
            )
        )

    roll = random.random()
    result_msg = ""

    if roll < sp_gain_rate:
        sp_gain = random.randint(1, 3)
        new_sp = data.get("sp", 0) + sp_gain
        await data_manager.update_spirit_data(uid, ctx.group_id, {"sp": new_sp})
        await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
        result_msg = _fur_sp_text(sp_gain)

    elif roll < cleanse_upper:
        had_taste_loss = bool(buffs.get("taste_loss_active"))
        if had_taste_loss:
            buffs.pop("taste_loss_active", None)
            buffs.pop("taste_loss_date", None)

        await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)
        await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
        result_msg = _fur_cleanse_text() if had_taste_loss else _fur_comfort_text()

    elif roll < special_drop_upper:
        pool_cfg = fur_drop_pools.get(item_name, {})
        if random.random() < pool_cfg.get("drop_chance", 0):
            drops = pool_cfg.get("drops", [("神秘种子", 1)])
            drop_item, drop_count = random.choice(drops)
            await data_manager.add_spirit_item(uid, ctx.group_id, drop_item, drop_count)
            await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
            result_msg = _fur_drop_text(drop_item, drop_count)
        else:
            await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
            result_msg = _fur_comfort_text()

    else:
        await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
        result_msg = _fur_comfort_text()

    await recorder.add_event(
        "use_item",
        int(uid),
        {
            "item": item_name,
            "group_id": ctx.group_id,
            "fur_pet_count": pet_count,
        },
    )

    danger_note = ""
    if pet_count > warning_threshold:
        danger_note = f"\n⚠已进入高风险阶段，继续抚摸有 {int(disappear_rate * 100)}% 概率把毛球揉散"

    await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)

    await use_cmd.finish(
        ui.render_result_card(
            item_name,
            result_msg,
            stats=[
                ("今日抚摸次数", str(pet_count)),
                ("状态", "正常" if pet_count < warning_threshold else "危险"),
            ],
            extra=danger_note.strip() if danger_note else None,
            footer=_footer_with_ctx(ctx, " 毛球没有生命，但摸太狠的话，毛会掉、会散"),
        )
    )


# ==================== 使用道具：钥匙 ====================
async def _handle_use_special_key(ctx: GroupContext, data: dict):
    user_level = data.get("level", 1)
    unlocked = data.get("unlocked_locations", [])
    all_locations = game_config.expedition_locations

    all_levels = sorted(set(loc_cfg.get("level", 1) for loc_cfg in all_locations.values()))
    next_level = None
    for lv in all_levels:
        if lv > user_level:
            next_level = lv
            break

    lockable = []
    if next_level is not None:
        for loc_name, loc_cfg in all_locations.items():
            req_lv = loc_cfg.get("level", 1)
            if req_lv == next_level and loc_name not in unlocked:
                lockable.append((loc_name, req_lv, loc_cfg.get("desc", "")))

    if not lockable:
        await use_cmd.finish(
            ui.info(
                "你已经可以进入所有区域了，钥匙暂时无处可用~\n"
                "等级提升后所有区域自动解锁，无需钥匙。"
            )
        )

    lines = ["这把古老的钥匙在你手中微微发光...\n"]
    lines.append("请发送 /解锁 [区域名] 来选择要解锁的灵域：\n")

    groups = {}
    for loc_name, req_lv, desc in lockable:
        groups.setdefault(req_lv, []).append((loc_name, desc))

    for lv in sorted(groups.keys()):
        lines.append(f" Lv.{lv} 区域：")
        for loc_name, desc in groups[lv]:
            lines.append(f" · {loc_name}")
            lines.append(f" {desc[:30]}...")
        lines.append("")

    card = ui.render_panel(
        "析沐的钥匙 · 灵域解锁",
        "\n".join(lines),
        footer=_footer_with_ctx(ctx, " 输入 解锁 [区域名] | 发送其他内容取消"),
    )
    await use_cmd.finish(card)


# ==================== 使用道具：吉熙的信羽 ====================
async def _handle_use_blessing_feather(bot: Bot, event: MessageEvent, ctx: GroupContext, uid: str, item_name: str, buffs: dict):
    existing = buffs.get("blessing")
    if existing and isinstance(existing, dict) and time.time() < existing.get("expire", 0):
        await use_cmd.finish(ui.info("「吉兆」Buff 尚未消散，请先享用当前的好运~"))

    ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, item_name, 1)
    if not ok:
        await use_cmd.finish(ui.error(f"没有【{item_name}】。"))

    buffs["blessing"] = {
        "expire": time.time() + 86400,
        "kitchen": True,
        "meditation": True,
        "resonance": True,
        "smelting": True,
    }
    await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)

    await recorder.add_event("use_item", int(uid), {"item": item_name, "group_id": ctx.group_id})
    await achievement_engine.try_unlock(uid, "吉祥之人", bot, event, group_id=ctx.group_id)

    result_msg = (
        " 信羽化为金光融入了你的灵脉...\n\n"
        "✨获得「吉兆」Buff！(24 小时)\n\n"
        "接下来的每个系统各享一次最佳结果：\n"
        " 厨房 → 必定美味\n"
        " 聚灵 → 必定大吉\n"
        " 鉴定 → 必出稀有\n"
        " 熔炼 → 品质升档\n\n"
        "每个系统触发一次后该系统的吉兆消失"
    )
    await use_cmd.finish(
        ui.render_result_card(
            "吉熙的信羽 · 喜鹊报喜",
            result_msg,
            footer=_footer_with_ctx(ctx, " 好运已就位，去闯荡吧！"),
        )
    )


# ==================== 使用道具：焚的残火 ====================
async def _handle_use_ancient_flame(bot: Bot, event: MessageEvent, ctx: GroupContext, uid: str, item_name: str, data: dict):
    current_sp = data.get("sp", 0)
    gain = int(current_sp * 0.25)
    if gain <= 0:
        await use_cmd.finish(
            ui.info(
                "你当前灵力太低了，残火找不到足够的杂质来燃烧...\n"
                "先去聚灵攒点灵力再来吧！"
            )
        )

    ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, item_name, 1)
    if not ok:
        await use_cmd.finish(ui.error(f"没有【{item_name}】。"))

    new_sp = current_sp + gain
    await data_manager.update_spirit_data(uid, ctx.group_id, {"sp": new_sp})

    await recorder.add_event(
        "use_item",
        int(uid),
        {
            "item": item_name,
            "gain": gain,
            "before": current_sp,
            "after": new_sp,
            "group_id": ctx.group_id,
        },
    )
    await achievement_engine.try_unlock(uid, "焚之眷顾", bot, event, group_id=ctx.group_id)

    result_msg = (
        " 残火在掌心燃起，古老的力量灼烧着灵脉中的杂质...\n\n"
        "灵力杂质被净化，纯度大幅提升！\n"
    )
    await use_cmd.finish(
        ui.render_result_card(
            "焚的残火 · 灵力纯化",
            result_msg,
            stats=[
                ("纯化前", f"{current_sp} 灵力"),
                ("纯化后", f"{new_sp} 灵力"),
                ("净增", f"+{gain} 灵力 (+25%)"),
            ],
            footer=_footer_with_ctx(ctx, "焚大人：'不过是余烬罢了。'"),
        )
    )


# ==================== 使用道具：普通 active ====================
async def _handle_use_active_item(
    bot: Bot,
    event: MessageEvent,
    ctx: GroupContext,
    uid: str,
    item_name: str,
    data: dict,
    buffs: dict,
    daily: dict,
):
    ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, item_name, 1)
    if not ok:
        await use_cmd.finish(ui.error(f"没有【{item_name}】。"))

    if item_name == "玄清丹":
        daily["meditation"] = 0
        await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
        await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)

        await recorder.add_event("use_item", int(uid), {"item": item_name, "group_id": ctx.group_id})
        await _finish_use_result(use_cmd, ctx, "灵质空间 · 道具使用", "✨玄清丹生效！今日聚灵次数已重置。", " 输入 背包 查看剩余道具")

    elif item_name == "忘忧草":
        if buffs.get("taste_loss_active"):
            buffs.pop("taste_loss_active", None)
            buffs.pop("taste_loss_date", None)
            await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)
            await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
            await recorder.add_event("use_item", int(uid), {"item": item_name, "group_id": ctx.group_id})
            await _finish_use_result(use_cmd, ctx, "灵质空间 · 道具使用", " 忘忧草生效！味蕾已恢复~", " 输入 背包 查看剩余道具")
        else:
            await data_manager.add_spirit_item(uid, ctx.group_id, item_name, 1)
            await use_cmd.finish(ui.info("你当前没有[味蕾丧失]状态。"))

    elif item_name == "聚灵花":
        sp_gain = 15
        new_sp = data.get("sp", 0) + sp_gain
        await data_manager.update_spirit_data(uid, ctx.group_id, {"sp": new_sp})
        await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)
        await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)

        await recorder.add_event("use_item", int(uid), {"item": item_name, "group_id": ctx.group_id})
        await use_cmd.finish(
            ui.render_result_card(
                "灵质空间 · 道具使用",
                f" 聚灵花绽放！花瓣中的灵气融入体内。\n✨灵力 +{sp_gain} (当前: {new_sp})",
                footer=_footer_with_ctx(ctx, " 输入 背包 查看剩余道具"),
            )
        )

    elif item_name == "五行灵核":
        garden = data.get("garden", [])
        matured = False

        if isinstance(garden, list):
            for slot in garden:
                if isinstance(slot, dict) and slot.get("status") in ("sprout", "growing", "seed"):
                    slot["status"] = "mature"
                    slot["water_count"] = 0
                    matured = True
                    break

        if matured:
            await data_manager.update_spirit_data(uid, ctx.group_id, {"garden": garden})
            await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)
            await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
            await recorder.add_event("use_item", int(uid), {"item": item_name, "group_id": ctx.group_id})

            await use_cmd.finish(
                ui.render_result_card(
                    "灵质空间 · 道具使用",
                    "✨五行灵核生效！一株灵植瞬间成熟！",
                    footer=_footer_with_ctx(ctx, " 输入 药圃 查看状态 | 收获"),
                )
            )
        else:
            await data_manager.add_spirit_item(uid, ctx.group_id, item_name, 1)
            await use_cmd.finish(ui.info("药圃中没有需要催熟的植物。"))

    else:
        await data_manager.add_spirit_item(uid, ctx.group_id, item_name, 1)
        await use_cmd.finish(ui.info("该物品无法直接使用。"))


# ==================== 使用道具：群限定 active ====================
async def _handle_use_active_group_item(
    bot: Bot,
    event: MessageEvent,
    ctx: GroupContext,
    uid: str,
    item_name: str,
):
    ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, item_name, 1)
    if not ok:
        await use_cmd.finish(ui.error(f"没有【{item_name}】。"))

    if item_name == "引灵香":
        if not isinstance(event, GroupMessageEvent):
            await data_manager.add_spirit_item(uid, ctx.group_id, item_name, 1)
            await use_cmd.finish(ui.info("引灵香只能在群内使用~"))

        from src.plugins.tubei_entertainment.heixiu_catcher import spawn_heixiu_in_group
        asyncio.create_task(spawn_heixiu_in_group(event.group_id))

        await recorder.add_event("use_item", int(uid), {"item": item_name, "group_id": ctx.group_id})
        await _finish_use_result(use_cmd, ctx, "灵质空间 · 道具使用", " 引灵香点燃！一股奇异的香气弥漫开来...", " 输入 嘿咻出现时发送 捕捉")

    else:
        await data_manager.add_spirit_item(uid, ctx.group_id, item_name, 1)
        await use_cmd.finish(ui.info("该群限定道具无法直接使用。"))


# ==================== 使用道具：permanent ====================
async def _handle_use_permanent_item(
    bot: Bot,
    event: MessageEvent,
    ctx: GroupContext,
    uid: str,
    item_name: str,
    data: dict,
    buffs: dict,
    daily: dict,
):
    ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, item_name, 1)
    if not ok:
        await use_cmd.finish(ui.error(f"没有【{item_name}】。"))

    result_msg = ""

    if item_name == "完整天明珠":
        perm_bonus = data.get("permanent_meditation_bonus", 0) + 5
        await data_manager.update_spirit_data(uid, ctx.group_id, {"permanent_meditation_bonus": perm_bonus})
        result_msg = f" 天明珠光芒绽放！\n 永久聚灵收益 +5 (当前加成: +{perm_bonus})"

    elif item_name == "上古秘卷":
        perm_bonus = data.get("permanent_expedition_bonus", 0) + 3
        await data_manager.update_spirit_data(uid, ctx.group_id, {"permanent_expedition_bonus": perm_bonus})
        result_msg = f" 秘卷化为灵光融入灵识！\n 永久派遣收益 +3 (当前加成: +{perm_bonus})"

    elif item_name == "破碎星核":
        perm_bonus = data.get("permanent_meditation_bonus", 0) + 3
        await data_manager.update_spirit_data(uid, ctx.group_id, {"permanent_meditation_bonus": perm_bonus})
        result_msg = f" 破碎的星光融入了灵脉！\n 永久聚灵收益 +3 (当前加成: +{perm_bonus})"

    else:
        await data_manager.add_spirit_item(uid, ctx.group_id, item_name, 1)
        await use_cmd.finish(ui.info("该物品无法直接使用。"))

    await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)
    await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)
    await recorder.add_event("use_item", int(uid), {"item": item_name, "group_id": ctx.group_id})

    await use_cmd.finish(
        ui.render_result_card(
            "灵质空间 · 道具使用",
            result_msg,
            footer=_footer_with_ctx(ctx, " 输入 背包 查看剩余道具"),
        )
    )


# ==================== 使用道具：普通 buff ====================
async def _handle_use_buff_item(
    bot: Bot,
    event: MessageEvent,
    ctx: GroupContext,
    uid: str,
    item_name: str,
    buffs: dict,
    daily: dict,
):
    ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, item_name, 1)
    if not ok:
        await use_cmd.finish(ui.error(f"没有【{item_name}】。"))

    buffs[item_name] = True
    await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)
    await data_manager.update_spirit_daily_counts(uid, ctx.group_id, daily, merge=False)

    await recorder.add_event("use_item", int(uid), {"item": item_name, "group_id": ctx.group_id})

    await use_cmd.finish(
        ui.render_result_card(
            "灵质空间 · 道具使用",
            f"✨【{item_name}】效果已激活！\n {ARTIFACTS[item_name]['desc']}",
            footer=_footer_with_ctx(ctx, " 输入 背包 查看剩余道具"),
        )
    )


# ==================== 使用主入口 ====================
@use_cmd.handle()
async def handle_use(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)
    item_name = args.extract_plain_text().strip()

    if not item_name:
        await use_cmd.finish(ui.info("请指定道具名称。\n 用法：/使用 [道具名]"))

    perm = await check_permission(
        event,
        "道具使用",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await use_cmd.finish(perm.deny_message)

    data, buffs, daily = await _load_item_use_context(uid, ctx)
    items = dict(data.get("items", {}))

    if items.get(item_name, 0) < 1:
        await use_cmd.finish(ui.error(f"没有【{item_name}】。"))

    info = ARTIFACTS.get(item_name)
    if not info:
        await use_cmd.finish(ui.error("未知物品。"))

    item_type = info.get("type")

    if item_type in ("material", "seed"):
        await use_cmd.finish(ui.info(f"【{item_name}】无法直接使用。\n {info['desc']}"))

    if item_type == "heixiu_fur":
        await _handle_use_heixiu_fur(bot, event, ctx, uid, item_name, data, buffs, daily)

    if item_type == "special_key":
        await _handle_use_special_key(ctx, data)

    if item_type == "blessing_feather":
        await _handle_use_blessing_feather(bot, event, ctx, uid, item_name, buffs)

    if item_type == "ancient_flame":
        await _handle_use_ancient_flame(bot, event, ctx, uid, item_name, data)

    if item_type == "buff":
        await _handle_use_buff_item(bot, event, ctx, uid, item_name, buffs, daily)

    if item_type == "active":
        await _handle_use_active_item(bot, event, ctx, uid, item_name, data, buffs, daily)

    if item_type == "active_group":
        await _handle_use_active_group_item(bot, event, ctx, uid, item_name)

    if item_type == "permanent":
        await _handle_use_permanent_item(bot, event, ctx, uid, item_name, data, buffs, daily)

    await use_cmd.finish(ui.info("该物品当前无法使用。"))


# ==================== 解锁灵域 ====================
@unlock_cmd.handle()
async def handle_unlock(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)
    target_loc = args.extract_plain_text().strip()

    if not target_loc:
        await unlock_cmd.finish(
            ui.info(
                "请指定要解锁的区域名称。\n"
                "用法：/解锁 [区域名]\n"
                "先使用 /使用 析沐的钥匙 查看可解锁的区域"
            )
        )

    perm = await check_permission(
        event,
        "灵域解锁",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await unlock_cmd.finish(perm.deny_message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    items = dict(data.get("items", {}))
    user_level = data.get("level", 1)
    unlocked = list(data.get("unlocked_locations", []))
    all_locations = game_config.expedition_locations

    if items.get("析沐的钥匙", 0) < 1:
        await unlock_cmd.finish(ui.error("你没有【析沐的钥匙】。\n 通过派遣探索有几率获得。"))

    if target_loc not in all_locations:
        await unlock_cmd.finish(ui.error(f"未知区域「{target_loc}」。\n 请使用 /使用 析沐的钥匙 查看可解锁区域。"))

    loc_cfg = all_locations[target_loc]
    req_level = loc_cfg.get("level", 1)

    if user_level >= req_level:
        await unlock_cmd.finish(ui.info(f"你的等级已经足够进入【{target_loc}】了，不需要钥匙~"))

    all_levels = sorted(set(cfg.get("level", 1) for cfg in all_locations.values()))
    next_level = None
    for lv in all_levels:
        if lv > user_level:
            next_level = lv
            break

    if next_level is not None and req_level > next_level:
        await unlock_cmd.finish(
            ui.error(
                f"【{target_loc}】需要 Lv.{req_level}，但你只能解锁 Lv.{next_level} 的区域。\n"
                f"先提升等级或解锁 Lv.{next_level} 区域吧~"
            )
        )

    if target_loc in unlocked:
        await unlock_cmd.finish(ui.info(f"【{target_loc}】已经被钥匙解锁过了~"))

    ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, "析沐的钥匙", 1)
    if not ok:
        await unlock_cmd.finish(ui.error("你没有【析沐的钥匙】。\n 通过派遣探索有几率获得。"))

    unlocked.append(target_loc)
    await data_manager.update_spirit_data(uid, ctx.group_id, {"unlocked_locations": unlocked})

    await recorder.add_event("unlock_location", int(uid), {"location": target_loc, "group_id": ctx.group_id})
    await achievement_engine.try_unlock(uid, "钥匙守护者", bot, event, group_id=ctx.group_id)

    desc = loc_cfg.get("desc", "")
    card = ui.render_result_card(
        "析沐的钥匙 · 灵域解锁",
        f"✨钥匙化为光芒融入了【{target_loc}】的封印...\n\n"
        f" {target_loc} 已永久解锁！\n"
        f" {desc}\n\n"
        f"即使等级不足也可以前往探索~",
        stats=[
            ("消耗", "析沐的钥匙 ×1"),
            ("解锁", target_loc),
            ("需要等级", f"Lv.{req_level} (你当前 Lv.{user_level})"),
        ],
        footer=_footer_with_ctx(ctx, f" 输入 派遣 {target_loc}"),
    )
    await unlock_cmd.finish(card)


# ==================== 法宝熔炼 ====================
@smelt_cmd.handle()
async def handle_smelt(bot: Bot, event: MessageEvent):
    uid = str(event.user_id)
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "君阁工坊 · 法宝熔炼",
        min_tier="allied",
        require_registered=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await smelt_cmd.finish(perm.deny_message)

    data = await data_manager.get_spirit_data(uid, ctx.group_id)
    items = dict(data.get("items", {}))
    buffs = dict(data.get("buffs", {}))
    cost = game_config.smelt_cost

    if items.get("法宝碎片", 0) < cost:
        await smelt_cmd.finish(
            ui.render_data_card(
                "君阁工坊 · 法宝熔炼",
                [
                    ("需要", f"法宝碎片 x{cost}"),
                    ("持有", f"法宝碎片 x{items.get('法宝碎片', 0)}"),
                    ("", ""),
                    ("概率", "45%普通 | 35%稀有 | 15%传说 | 5%彩蛋"),
                    ("加持", "虚空结晶可提升一档品质"),
                ],
                footer=_footer_with_ctx(ctx, " 输入 通过派遣获取法宝碎片"),
            )
        )

    ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, "法宝碎片", cost)
    if not ok:
        await smelt_cmd.finish(
            ui.render_data_card(
                "君阁工坊 · 法宝熔炼",
                [
                    ("需要", f"法宝碎片 x{cost}"),
                    ("持有", f"法宝碎片 x{items.get('法宝碎片', 0)}"),
                ],
                footer=_footer_with_ctx(ctx, " 输入 通过派遣获取法宝碎片"),
            )
        )

    await data_manager.increment_group_stat(uid, ctx.group_id, "total_smelt_count", 1)

    tiers = game_config.get("smelting", "tiers", default={})
    forced_tier = None

    if buffs.pop("混沌残片", None):
        forced_tier = "legendary"
    elif buffs.pop("万宝如意", None):
        forced_tier = random.choices(
            ["rare", "legendary", "easter_egg"],
            weights=[60, 30, 10],
            k=1,
        )[0]

    blessing_upgrade = False
    if check_blessing(buffs, "smelting"):
        blessing_upgrade = True

    if forced_tier:
        selected_tier = forced_tier
    else:
        tier_names = list(tiers.keys())
        tier_rates = [tiers[t].get("rate", 0) for t in tier_names]
        selected_tier = random.choices(tier_names, weights=tier_rates, k=1)[0]

    crystal_used = False
    if items.get("虚空结晶", 0) > 0 and not forced_tier:
        ok, _ = await data_manager.consume_spirit_item(uid, ctx.group_id, "虚空结晶", 1)
        if ok:
            crystal_used = True

    upgrade_count = 0
    if crystal_used:
        upgrade_count += 1
    if blessing_upgrade:
        upgrade_count += 1

    tier_order = ["normal", "rare", "legendary", "easter_egg"]
    for _ in range(upgrade_count):
        idx = tier_order.index(selected_tier) if selected_tier in tier_order else 0
        if idx < len(tier_order) - 1:
            selected_tier = tier_order[idx + 1]

    tier_config = tiers.get(selected_tier, {})
    pool = tier_config.get("pool", []) or ["涪灵丹"]
    prize = random.choice(pool)

    await data_manager.add_spirit_item(uid, ctx.group_id, prize, 1)
    await data_manager.update_spirit_buffs(uid, ctx.group_id, buffs)

    tier_display = {
        "normal": ("✨", "普通"),
        "rare": (" ", "稀有"),
        "legendary": (" ", "传说"),
        "easter_egg": (" ", "命运彩蛋"),
    }
    icon, tier_name = tier_display.get(selected_tier, ("✨", "普通"))

    extra_notes = []
    if crystal_used:
        extra_notes.append(" 虚空结晶：品质提升一档！")
    if blessing_upgrade:
        extra_notes.append(" 吉兆加持：品质提升一档！")

    if selected_tier == "easter_egg":
        description = (
            "炉火猛然熄灭... 碎片化为了灰烬。\n"
            "但灰烬中，有什么在微微发光...\n\n"
            f"✨获得了【{prize}】！\n"
            f" {ARTIFACTS.get(prize, {}).get('desc', '')}\n\n"
            "...这或许才是最珍贵的馈赠。"
        )
        await achievement_engine.try_unlock(uid, "否极泰来", bot, event, group_id=ctx.group_id)
    elif selected_tier == "legendary":
        description = f" 奇迹降临！熔炼出了传说中的【{prize}】！"
        await achievement_engine.try_unlock(uid, "命运眷顾", bot, event, group_id=ctx.group_id)
    elif selected_tier == "rare":
        description = f" 炉火闪烁，凝结出了稀有法宝【{prize}】！"
    else:
        description = f"✨熔炼完成，获得了【{prize}】。"

    await achievement_engine.try_unlock(uid, "炼器学徒", bot, event, group_id=ctx.group_id)
    await achievement_engine.check_stat_achievements(uid, bot, event, group_id=ctx.group_id)

    card = ui.render_result_card(
        f"君阁工坊 · 熔炼结果 [{tier_name}]",
        description,
        stats=[
            ("消耗", f"法宝碎片 x{cost}"),
            ("品质", f"{icon} {tier_name}"),
            ("产物", prize),
        ],
        extra="\n".join(extra_notes) if extra_notes else None,
        footer=_footer_with_ctx(ctx, " 输入 背包 查看道具 | 熔炼 再来一次"),
    )
    await smelt_cmd.finish(card)