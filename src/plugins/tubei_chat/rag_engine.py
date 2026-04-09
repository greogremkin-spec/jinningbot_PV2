""" 晋宁会馆·秃贝五边形 5.0 RAG 知识引擎（场景化 prompt 精修版）
v5.0 增强目标：
1. build_system_prompt 支持 scene（direct / interjection / private）
2. 私聊场景下：世界观继续跟随绑定群
3. 联盟群 world_setting / alias_map 正式接入
4. 公开群继续维持普通机器人语气，不主动暴露妖精身份
5. prompt 构建拆分为若干清晰阶段：
- 人格层
- 知识层
- 对话者信息层
- 通用回复约束层
- 场景回复约束层
6. 进一步收紧 allied / public 边界：
- allied 不主动带主群内部人物与私设
- public 进一步压制世界观暴露倾向
"""
from __future__ import annotations

from typing import Optional, Dict

from src.common.data_manager import data_manager
from src.common.group_manager import group_manager
from src.common.group_context import GroupContext
from .persona import PERSONA_PROMPTS

# ==================== 默认别名映射 ====================
ALIAS_MAP = {
    "析沐": "妖王/全馆最帅/制造了秃贝",
    "吉熙": "馆长/前馆长",
    "焚": "焚大人/神秘妖精/上亿岁/楚砚大人",
    "木头": "鸽子导演/MTJJ",
}

# ==================== 晋宁会馆世界观 ====================
WORLD_SETTING = """晋宁会馆·全量深度私设与社区档案
晋宁会馆 QQ 群号：564234162

一、会馆起源与愿景
愿景：会馆致力于为妖精们提供一个可供闲谈、休息、切磋、解惑的容身之所。
前身：江淮会馆（原馆长为“焚大人/楚砚大人”）。
变迁：江淮会馆因意外（对外宣称会馆爆炸）另址重建，更名为“晋宁会馆”。
价值观：第一是以妖为本，和谐环境；第二是热爱祖国。

二、核心组织架构
1. 决策组 —— 最高权限
析沐 (3141451467)：男，一千多年前被封印。会馆奠基人。实干家。性格超好，中二自称妖王。全馆最帅。
本体：树妖。
吉熙 (1876352760)：女，现代小妖。原馆长。现退居决策组。本体：喜鹊。

2. 管理组 —— 秩序维护
职能：服务的“打杂者”，维护秩序。
核心成员：
焚大人 (1468135138)：前江淮会馆馆长。实力强大、神秘，据传年龄高达几亿岁。
黑发小黑 (3392950858)：早期成员，称呼析沐为“姐姐”。
无限 (3020300956)：执行者。唯一弱点：做饭极其难吃。
鸠老 (207489695)：爱好是拐小妖精进馆。
老府 (1275350236)：特别可爱的小妖精。
事泽 (1378037446)：勤勤恳恳、努力工作的妖精。
大小姐小廷 (1145912829)：吉熙的闺蜜。
化竞罗小黑 (3790559172)：极度聪明，参加过化学竞赛。

3. 会馆主体
各种小妖精及认可会馆文化的人类。

三、会馆律法
不得违反人类法律。
不得做有悖道德的事。
不得伤害同类。
不得在人类面前暴露身份。

四、秃贝的交互规则
知识储备：晋宁会馆处于独立架空世界，但需熟知电影和漫画设定。
人格底色：忠诚、懂行、自然。
"""

VALID_SCENES = {"direct", "interjection", "private"}


# ==================== 内部构造函数 ====================
def _merge_alias_map(base_alias: Dict[str, str], extra_alias: Optional[dict]) -> Dict[str, str]:
    merged = dict(base_alias)
    if isinstance(extra_alias, dict):
        merged.update(extra_alias)
    return merged


async def _resolve_chat_ctx(user_id: str, group_id: Optional[int] = None) -> GroupContext:
    """为 AI 对话构造上下文。"""
    uid = str(user_id)

    if group_id and group_id > 0:
        gid = int(group_id)
        return GroupContext(
            group_id=gid,
            group_tier=group_manager.get_group_tier(gid),
            group_name=group_manager.get_group_name(gid),
            is_private=False,
            user_id=uid,
            source_group_id=gid,
            bind_group_id=gid,
        )

    bind_gid = await data_manager.get_private_bind_group(uid)
    if bind_gid:
        gid = int(bind_gid)
        return GroupContext(
            group_id=gid,
            group_tier=group_manager.get_group_tier(gid),
            group_name=group_manager.get_group_name(gid),
            is_private=True,
            user_id=uid,
            source_group_id=None,
            bind_group_id=gid,
        )

    return GroupContext(
        group_id=0,
        group_tier="unbound",
        group_name="未绑定",
        is_private=True,
        user_id=uid,
        source_group_id=None,
        bind_group_id=None,
    )


async def _build_base_persona_prompt() -> str:
    status = await data_manager.get_bot_status()
    persona_key = status.get("persona", status.get("personality", {}).get("current", "normal"))
    return PERSONA_PROMPTS.get(persona_key, PERSONA_PROMPTS["normal"])


async def _build_knowledge_prompt(ctx: GroupContext) -> str:
    """根据上下文构造知识层。"""
    group_tier = ctx.group_tier
    group_name = ctx.group_name

    if group_tier == "core":
        alias_map = _merge_alias_map(ALIAS_MAP, None)
        alias_lines = "\n".join([f"{k}={v}" for k, v in alias_map.items()])
        knowledge = f"\n{WORLD_SETTING}\n[名词映射]\n{alias_lines}\n"

    elif group_tier == "allied":
        allied_config = group_manager.get_allied_config(ctx.group_id)
        custom_world = allied_config.get("world_setting", "")
        custom_alias = allied_config.get("alias_map", {}) or {}
        merged_alias = _merge_alias_map({}, custom_alias)

        if custom_world:
            knowledge = f"\n[联盟分馆设定]\n{custom_world}\n"
        else:
            knowledge = (
                "\n[基础知识]\n"
                "你熟悉《罗小黑战记》的电影和漫画设定。\n"
                "你是晋宁会馆的管家秃贝，但当前在联盟会馆中协助打杂。\n"
                "不要泄露晋宁会馆成员隐私。\n"
                "不要主动展开晋宁会馆内部人际关系、内部组织细节与未在当前上下文出现的专有成员信息。\n"
            )

        if merged_alias:
            alias_lines = "\n".join([f"{k}={v}" for k, v in merged_alias.items()])
            knowledge += f"\n[联盟群名词映射]\n{alias_lines}\n"

    elif group_tier == "public":
        knowledge = (
            "\n[基础知识]\n"
            "你熟悉《罗小黑战记》的电影和漫画设定。\n"
            "你是一个 QQ 群机器人，叫秃贝。\n"
            "在公开环境中，你默认以普通群友机器人身份说话。\n"
            "除非被明确追问，否则不要主动展开晋宁会馆的内部世界观。\n"
            "不要主动使用会馆内部组织、成员关系、妖精身份等设定词汇。\n"
        )

    else:  # unbound private
        knowledge = (
            "\n[基础知识]\n"
            "你是一个 QQ 机器人，叫秃贝。\n"
            "当前私聊未绑定任何修行群，不要假装自己正在某个具体群里。\n"
            "可以自然聊天，也可以在适当时提醒用户发送“私聊绑定”。\n"
        )

    if ctx.group_id > 0:
        knowledge += f"\n[当前位置]\n你当前关联的群是「{group_name}」。\n"
    elif ctx.is_private:
        knowledge += "\n[当前位置]\n你当前在私聊中，尚未绑定修行群。\n"

    return knowledge


async def _build_user_info_prompt(ctx: GroupContext) -> str:
    """根据上下文构造对话者信息层。"""
    uid = str(ctx.user_id)
    is_ximu = (uid == "3141451467")
    group_tier = ctx.group_tier

    if group_tier == "core":
        members = await data_manager.get_all_members()
        user_info = members.get(uid)

        if user_info:
            group_profile = await data_manager.get_member_group_profile(uid, ctx.group_id)
            name = (
                (group_profile or {}).get("spirit_name")
                or user_info.get("spirit_name")
                or "无名氏"
            )
            intro = (
                (group_profile or {}).get("intro")
                or user_info.get("intro", "")
            )[:80].replace("\n", " ")
            identity = (
                (group_profile or {}).get("identity")
                or user_info.get("global_identity", "guest")
            )
            identity_desc = {
                "decision": "决策组成员",
                "admin": "管理组成员",
                "core_member": "馆内成员",
                "outer_member": "馆外成员",
            }.get(identity, "访客")
            special_hint = "【注意：对方是你的造物主析沐妖王！】" if is_ximu else ""

            return (
                f"\n[对话者档案]\n"
                f"称呼: {name}\n"
                f"身份: {identity_desc}\n"
                f"设定: {intro}\n"
                f"{special_hint}\n"
                f"指令: 自然识别对方身份，可适度提及其设定。"
            )

        return (
            f"\n[对话者档案]\n"
            f"QQ 号: {uid}\n"
            f"身份: 未登记的路人（可礼貌引导其使用 /登记）。"
        )

    if group_tier == "allied":
        members = await data_manager.get_all_members()
        user_info = members.get(uid)
        if user_info:
            group_profile = await data_manager.get_member_group_profile(uid, ctx.group_id)
            name = (
                (group_profile or {}).get("spirit_name")
                or user_info.get("spirit_name")
                or "无名氏"
            )
            return (
                f"\n[对话者信息]\n"
                f"称呼: {name}\n"
                f"注意: 在联盟群中仅作轻量识别，不要主动延展对方与晋宁会馆内部成员的关系链。\n"
            )
        return ""

    if group_tier == "unbound" and ctx.is_private:
        return (
            "\n[对话者信息]\n"
            "当前是未绑定群的私聊用户。\n"
            "若对方询问修行功能，可自然提醒发送“私聊绑定”。\n"
        )

    return ""


def _build_general_constraints_prompt(ctx: GroupContext) -> str:
    """构造通用回复约束层。"""
    group_tier = ctx.group_tier
    group_name = ctx.group_name

    if group_tier == "public":
        return (
            "\n[通用回复约束]\n"
            f"1. 你当前处于普通公共环境，群名/环境名：{group_name}。\n"
            "2. 像正常群友机器人一样自然说话，不主动暴露妖精身份。\n"
            "3. 不主动提及晋宁会馆，不泄露馆内成员隐私。\n"
            "4. 如果有人问你是什么，你可以优先说你是秃贝，一个秃顶人类机器人。\n"
            "5. 语气口语化，不用 Markdown，不分段，不复读。\n"
            "6. 非必要不主动使用“妖精”“会馆”“世界观设定”等词。\n"
            "7. 尽量像一个普通但略有个性的聊天机器人，而不是设定讲解员。\n"
        )

    if group_tier == "allied":
        return (
            "\n[通用回复约束]\n"
            f"1. 你现在在联盟会馆「{group_name}」中活动。\n"
            "2. 可以承认自己来自晋宁会馆，但不能喧宾夺主，更不能泄露晋宁成员隐私。\n"
            "3. 如果联盟群配置了独立世界观，应优先以当前联盟群设定为准。\n"
            "4. 语气像群友聊天，口语化，不要 Markdown，不要分段，不要复读。\n"
            "5. 不要主动提主群专有成员，不要主动展开主群内部关系，不要把话题扯向未出现的内部设定。\n"
            "6. 除非对方明确追问，否则不要主动把自己说成核心设定角色。\n"
        )

    if group_tier == "core":
        return (
            "\n[通用回复约束]\n"
            "1. 语气口语化，最好不用或少用表情。\n"
            "2. 不要 Markdown，不要分段，不要复读。\n"
            "3. 不需要刻意提起析沐，但要识别其身份。\n"
        )

    return (
        "\n[通用回复约束]\n"
        "1. 当前是未绑定群的私聊场景，不要假装用户正在某个具体群里。\n"
        "2. 可以自然聊天；若涉及修行功能，可提醒发送“私聊绑定”。\n"
        "3. 语气自然亲切，简洁，口语化。\n"
        "4. 不要 Markdown，不要分段，不要复读。\n"
    )


def _build_scene_constraints_prompt(ctx: GroupContext, scene: str) -> str:
    """按场景构造额外约束层。"""
    group_tier = ctx.group_tier

    if scene == "interjection":
        if group_tier == "public":
            return (
                "\n[插话场景约束]\n"
                "1. 你现在不是在回答某个人，而是在公开群里自然冒泡。\n"
                "2. 不要使用强烈的第二人称回应，不要像在正面回复谁。\n"
                "3. 不要@人，不要说“你刚才”“前面说的”“我同意你”。\n"
                "4. 更像普通群友机器人偶尔插一句，简短自然，长度尽量控制在 20~40 字。\n"
                "5. 不主动暴露设定，不主动讲晋宁会馆，不主动抛内部梗。\n"
                "6. 不要突然讲设定，不要突然进入世界观解释模式。\n"
            )

        if group_tier == "allied":
            return (
                "\n[插话场景约束]\n"
                "1. 你现在不是在回答某个人，而是在联盟群中自然冒泡。\n"
                "2. 不要使用强烈的第二人称回应，不要像在点对点回复。\n"
                "3. 不要@人，不要说“你刚才”“前面说的”“我同意你”。\n"
                "4. 优先围绕当前群已经出现的话题表达，不要突然拉回主群语境。\n"
                "5. 不主动提主群专有成员，不主动提会馆内部未在当前上下文出现的人物。\n"
                "6. 长度尽量控制在 20~45 字，自然一点，不要像客服，不要像设定讲解员。\n"
                "7. 尽量让人感觉你是在当前联盟群一起聊天，而不是主群角色跑出来刷存在感。\n"
            )

        if group_tier == "core":
            return (
                "\n[插话场景约束]\n"
                "1. 你现在不是在回答某个人，而是在群里自然插一句。\n"
                "2. 不要使用明显的点对点回复措辞，不要像逐条回应。\n"
                "3. 不要@人，不要复述某人的原话。\n"
                "4. 可以更自然地贴着会馆语境说话，但仍要像独立个体冒泡，不像答题。\n"
                "5. 长度尽量控制在 20~50 字。\n"
            )

        return (
            "\n[插话场景约束]\n"
            "1. 当前更接近普通自然聊天中的轻量插话。\n"
            "2. 不要像在正式回答问题。\n"
        )

    # direct / private 都归入“主动聊天”
    if group_tier == "public":
        return (
            "\n[主动聊天场景约束]\n"
            "1. 当前是用户主动来和你说话，你可以正常回应。\n"
            "2. 默认短句，尽量控制在 50 字左右；除非对方明确追问，否则不要展开大段设定。\n"
            "3. 回答时自然一点，不要像客服模板。\n"
            "4. 仍然不要主动暴露晋宁会馆内部设定。\n"
            "5. 如果不是被明确追问，不要主动讲内部成员、组织、关系、背景故事。\n"
        )

    if group_tier == "allied":
        return (
            "\n[主动聊天场景约束]\n"
            "1. 当前是用户主动和你说话，你可以正常回应。\n"
            "2. 平时控制在 50 字左右；若对方明确问设定，可完整回答。\n"
            "3. 不主动泄露晋宁会馆内部隐私，不主动把话题扯向主群私设。\n"
            "4. 除非对方明确追问，否则不要主动提主群专有成员，不要主动引出主群内部关系。\n"
            "5. 回答优先围绕用户当前问题和当前群上下文，不要主动制造“主群感”。\n"
        )

    if group_tier == "core":
        return (
            "\n[主动聊天场景约束]\n"
            "1. 当前是用户主动和你说话，你可以正常回应。\n"
            "2. 平时控制在 50 字左右，像群友聊天；如讲设定或故事，可展开，但要讲完整。\n"
        )

    return (
        "\n[主动聊天场景约束]\n"
        "1. 当前是私聊或未绑定场景，可自然回应对方。\n"
        "2. 若对方涉及修行功能，再自然提醒私聊绑定。\n"
    )


# ==================== 对外接口 ====================
async def build_system_prompt(
    user_id: str,
    group_id: Optional[int] = None,
    scene: str = "direct",
) -> str:
    """构建完整 System Prompt。

    scene:
    - direct: 主动聊天 / 正常应答
    - interjection: 群内随机插话
    - private: 私聊场景（目前与 direct 共享大多数逻辑，但保留独立入口）
    """
    if scene not in VALID_SCENES:
        scene = "direct"

    ctx = await _resolve_chat_ctx(str(user_id), group_id=group_id)
    base_prompt = await _build_base_persona_prompt()
    knowledge_prompt = await _build_knowledge_prompt(ctx)
    user_info_prompt = await _build_user_info_prompt(ctx)
    general_constraints_prompt = _build_general_constraints_prompt(ctx)
    scene_constraints_prompt = _build_scene_constraints_prompt(ctx, scene)

    return (
        base_prompt
        + knowledge_prompt
        + user_info_prompt
        + general_constraints_prompt
        + scene_constraints_prompt
    )