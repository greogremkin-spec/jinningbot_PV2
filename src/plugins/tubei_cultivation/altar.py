""" 晋宁会馆·秃贝五边形 5.0 木头的催更祭坛

v5.0 定位：
1. 祭坛是全服唯一共享系统
2. 所有游戏群（core + allied）的聚灵税收汇入同一能量池
3. 祭坛 Buff 对所有游戏群生效
4. 馆内专属查看与触发入口保留（core_only）
5. 保留原有机制：
   - 能量阈值触发
   - Buff 持续时间
   - 实时状态查看
"""

from __future__ import annotations

import time

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

from src.common.data_manager import data_manager
from src.common.ui_renderer import ui
from src.common.permission import check_permission
from src.common.group_manager import group_manager
from src.common.group_context import GroupContext
from src.plugins.tubei_system.config import game_config


altar_cmd = on_command("祭坛", aliases={"催更祭坛"}, priority=5, block=True)


@altar_cmd.handle()
async def handle_altar(bot: Bot, event: MessageEvent):
    ctx = await GroupContext.from_event(event)

    perm = await check_permission(
        event,
        "木头的催更祭坛",
        core_only=True,
        deny_promotion=True,
        ctx=ctx,
    )
    if not perm.allowed:
        await altar_cmd.finish(perm.deny_message)

    status = await data_manager.get_bot_status()

    # v5 优先读 altar.energy，兼容旧 altar_energy
    altar_block = status.get("altar", {})
    energy = altar_block.get("energy", status.get("altar_energy", 0))
    threshold = game_config.altar_threshold

    buff_active = status.get("ritual_buff_active", False)
    ritual_start_time = status.get("ritual_start_time", 0)

    # ===== 达阈值且尚未开启 Buff：立即触发 =====
    if energy >= threshold and not buff_active:
        await data_manager.update_bot_status({
            "altar": {
                "energy": 0,
                "last_buff_time": int(time.time()),
            },
            "altar_energy": 0,  # 兼容旧字段
            "ritual_buff_active": True,
            "ritual_start_time": time.time(),
        })

        # 广播到所有游戏群（core + allied）
        for gid in group_manager.get_all_game_groups():
            if group_manager.is_debug_group(gid):
                continue
            try:
                await bot.send_group_msg(
                    group_id=gid,
                    message=(
                        "【全服公告】催更祭坛仪式开启！\n"
                        "全员聚灵收益加成生效中！"
                    ),
                )
            except Exception:
                pass

        await altar_cmd.finish(
            ui.render_result_card(
                "木头的催更祭坛",
                "⛩怨念汇聚，仪式已开启！",
                stats=[
                    ("能量", f"0 / {threshold} (已重置)"),
                    ("全服 Buff", "生效中！"),
                ],
                footer="全员聚灵收益加成 24 小时",
            )
        )

    # ===== Buff 过期检查 =====
    if buff_active:
        elapsed = time.time() - ritual_start_time
        buff_duration = game_config.altar_buff_duration
        if elapsed >= buff_duration:
            await data_manager.update_bot_status({
                "ritual_buff_active": False,
                "ritual_start_time": 0,
            })
            buff_active = False

    # ===== 实时状态展示 =====
    bar = ui.render_progress_bar(energy, threshold)
    buff_str = "✨生效中" if buff_active else "未激活"

    footer = " 输入 集满怨念，催木头更新！"
    if ctx.is_private:
        footer += f"\n 当前操作群：{ctx.group_name}"

    card = ui.render_data_card(
        "木头的催更祭坛 · 实时监控",
        [
            ("当前怨念", f"{energy} / {threshold}"),
            ("进度", bar),
            ("全服 Buff", buff_str),
            ("", ""),
            ("机制", "每次聚灵自动上缴 1% 灵力"),
        ],
        footer=footer,
    )
    await altar_cmd.finish(card)