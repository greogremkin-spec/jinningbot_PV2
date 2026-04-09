""" 晋宁会馆·秃贝五边形 5.0 排行榜系统（第三阶段增强版）

第三阶段增强：
1. 保留当前群排行
2. 保留私聊绑定群排行
3. 新增：
   - 顿悟排行榜
   - 毛球排行榜（按累计抚摸次数）
4. 继续使用 batch projection
"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message
from nonebot.params import CommandArg

from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_context import GroupContext


RANKING_TYPES = {
    "灵力": {
        "title": "灵力总榜",
        "field": "sp",
        "format": lambda v: f"{v} 灵力",
        "desc": "按当前灵力值排名",
    },
    "嘿咻": {
        "title": "嘿咻收集榜",
        "field": "heixiu_count",
        "format": lambda v: f"{v} 次",
        "desc": "按当前群档捕捉嘿咻次数排名",
    },
    "聚灵": {
        "title": "聚灵次数榜",
        "field": "total_meditation_count",
        "format": lambda v: f"{v} 次",
        "desc": "按累计聚灵次数排名",
    },
    "厨房": {
        "title": "厨房灾难榜",
        "field": "total_kitchen_bad",
        "format": lambda v: f"{v} 次黑暗料理",
        "desc": "按累计吃到黑暗料理次数排名",
    },
    "派遣": {
        "title": "派遣次数榜",
        "field": "total_expedition_count",
        "format": lambda v: f"{v} 次",
        "desc": "按累计派遣次数排名",
    },
    "顿悟": {
        "title": "顿悟榜",
        "field": "total_duel_enlighten",
        "format": lambda v: f"{v} 次顿悟",
        "desc": "按累计演武顿悟次数排名",
    },
    "毛球": {
        "title": "毛球抚摸榜",
        "field": "total_fur_pet_count",
        "format": lambda v: f"{v} 次",
        "desc": "按累计抚摸毛球次数排名",
    },
}

RANKING_ALIAS = {
    "": "灵力",
    "灵力": "灵力",
    "sp": "灵力",
    "嘿咻": "嘿咻",
    "聚灵": "聚灵",
    "修行": "聚灵",
    "厨房": "厨房",
    "派遣": "派遣",
    "探索": "派遣",
    "顿悟": "顿悟",
    "毛球": "毛球",
}


async def _render_ranking(bot: Bot, event: MessageEvent, ranking_key: str):
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "排行榜",
        min_tier="allied",
        ctx=ctx,
    )
    if not perm.allowed:
        await bot.send(event, perm.deny_message)
        return

    config = RANKING_TYPES.get(ranking_key)
    if not config:
        config = RANKING_TYPES["灵力"]
        ranking_key = "灵力"

    field = config["field"]
    formatter = config["format"]
    title = config["title"]

    members = await data_manager.get_group_members(ctx.group_id)
    if not members:
        await bot.send(
            event,
            ui.render_panel(
                title,
                "当前群还没有可参与排行的成员。",
                footer=f" 当前群：{ctx.group_name}",
            ),
        )
        return

    uids = list(members.keys())
    projections = await data_manager.batch_get_spirit_projection(
        uids,
        ctx.group_id,
        [field, "equipped_title"],
    )

    rank_data = []
    for qq, member in members.items():
        proj = projections.get(qq, {})
        value = proj.get(field, 0) or 0
        equipped_title = proj.get("equipped_title", "") or ""

        group_profile = await data_manager.get_member_group_profile(qq, ctx.group_id)
        spirit_name = (
            (group_profile or {}).get("spirit_name")
            or member.get("spirit_name")
            or f"妖灵{qq}"
        )

        display_name = f"[{equipped_title}] {spirit_name}" if equipped_title else spirit_name
        rank_data.append((qq, display_name, value))

    rank_data.sort(
        key=lambda x: x[2] if isinstance(x[2], (int, float)) else 0,
        reverse=True,
    )

    top_n = rank_data[:15]
    items = [(name, formatter(value)) for _, name, value in top_n]

    uid = str(event.user_id)
    my_rank = None
    my_value = None
    for idx, (qq, _, value) in enumerate(rank_data):
        if qq == uid:
            my_rank = idx + 1
            my_value = value
            break

    other_boards = [f"{key}榜" for key in RANKING_TYPES if key != ranking_key]
    other_str = " | ".join(other_boards)

    footer_parts = [f"当前群：{ctx.group_name}"]
    if my_rank:
        footer_parts.append(f"你的排名：第 {my_rank} 名 ({formatter(my_value)})")
    footer_parts.append(f"其他榜：{other_str}")
    if ctx.is_private:
        footer_parts.append("私聊显示的是绑定群排行")

    card = ui.render_ranking(
        title,
        items,
        footer="\n".join(footer_parts),
    )
    await bot.send(event, card)


ranking_cmd = on_command("排行榜", aliases={"排行", "榜单"}, priority=5, block=True)


@ranking_cmd.handle()
async def handle_ranking(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    sub_type = args.extract_plain_text().strip()
    ranking_key = RANKING_ALIAS.get(sub_type)

    if ranking_key is None:
        lines = ["可用排行榜：", ""]
        for key, info in RANKING_TYPES.items():
            lines.append(f"【{info['title']}】")
            lines.append(f" → {key}排行榜 | {key}榜")
            lines.append(f" → 排行榜 {key}")
            lines.append("")
        await ranking_cmd.finish(
            ui.render_panel(
                "排行榜系统",
                "\n".join(lines),
                footer=" 直接发送 灵力排行榜 即可查看",
            )
        )

    await _render_ranking(bot, event, ranking_key)
    await ranking_cmd.finish()


power_ranking_cmd = on_command("灵力排行榜", aliases={"灵力榜", "灵力排行"}, priority=4, block=True)
heixiu_ranking_cmd = on_command("嘿咻排行榜", aliases={"嘿咻榜", "嘿咻排行"}, priority=4, block=True)
meditation_ranking_cmd = on_command("聚灵排行榜", aliases={"聚灵榜", "聚灵排行"}, priority=4, block=True)
kitchen_ranking_cmd = on_command("厨房排行榜", aliases={"厨房榜", "厨房排行"}, priority=4, block=True)
expedition_ranking_cmd = on_command("派遣排行榜", aliases={"派遣榜", "派遣排行"}, priority=4, block=True)
insight_ranking_cmd = on_command("顿悟排行榜", aliases={"顿悟榜", "顿悟排行"}, priority=4, block=True)
fur_ranking_cmd = on_command("毛球排行榜", aliases={"毛球榜", "毛球排行"}, priority=4, block=True)


@power_ranking_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    await _render_ranking(bot, event, "灵力")


@heixiu_ranking_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    await _render_ranking(bot, event, "嘿咻")


@meditation_ranking_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    await _render_ranking(bot, event, "聚灵")


@kitchen_ranking_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    await _render_ranking(bot, event, "厨房")


@expedition_ranking_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    await _render_ranking(bot, event, "派遣")


@insight_ranking_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    await _render_ranking(bot, event, "顿悟")


@fur_ranking_cmd.handle()
async def _(bot: Bot, event: MessageEvent):
    await _render_ranking(bot, event, "毛球")