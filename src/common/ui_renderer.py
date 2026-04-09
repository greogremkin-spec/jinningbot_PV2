"""
晋宁会馆·秃贝五边形 4.1
UI 渲染器 —— 卡片式反馈系统

提供统一的文本卡片组件，确保所有模块的输出风格一致。
所有组件都是纯文本，适配手机 QQ 的显示宽度。

组件列表：
  render_panel()         标准卡片面板（标题 + 内容 + 底栏）
  render_data_card()     数据卡片（结构化 key-value 展示）
  render_progress_bar()  进度条
  render_status_tags()   状态标签行
  render_mini_grid()     小型网格（如药圃 2x2）
  render_bag_item()      背包物品行
  render_ranking()       排行榜
  render_result_card()   操作结果卡片（聚灵、厨房等反馈用）
"""

from typing import Optional, List, Tuple


class UIRenderer:
    """
    现代卡片式 UI 渲染器
    纯文本实现，不依赖图片，适配手机 QQ
    """

    # 粗分隔线（用于标题下方和主要分隔）
    DIVIDER = "━━━━━━━━━━━━━━━"
    # 细分隔线（用于底栏上方和次要分隔）
    THIN_DIVIDER = "─────────────────"

    # ================================================================
    #  标准卡片面板
    # ================================================================

    @staticmethod
    def render_panel(
        title: str,
        content: str,
        footer: Optional[str] = None
    ) -> str:
        """
        标准卡片面板

        格式：
          ✦ 标题
          ━━━━━━━━━━━━━━━
          内容...
          ─────────────────
          底栏提示

        :param title: 标题文本（会自动加装饰符 ✦）
        :param content: 正文内容（保持原排版）
        :param footer: 底部提示（可选）
        """
        lines = [
            f"✦ {title}",
            UIRenderer.DIVIDER,
        ]

        # 保持内容原排版
        for line in content.strip().split("\n"):
            lines.append(line)

        if footer:
            lines.append(UIRenderer.THIN_DIVIDER)
            lines.append(footer)

        return "\n".join(lines)

    # ================================================================
    #  数据卡片
    # ================================================================

    @staticmethod
    def render_data_card(
        title: str,
        rows: List[Tuple[str, str]],
        footer: Optional[str] = None
    ) -> str:
        """
        数据卡片（用于结构化信息展示）

        格式：
          ✦ 标题
          ━━━━━━━━━━━━━━━
            🔮 运势：大吉
            ⚡ 基础：25
            💎 获得：+30
          ─────────────────
            底栏提示

        :param title: 卡片标题
        :param rows: [(图标+标签, 值), ...] 的列表
                     如果标签为空字符串，渲染为空行（用于分隔）
        :param footer: 底部提示
        """
        lines = [
            f"✦ {title}",
            UIRenderer.DIVIDER,
        ]

        for label, value in rows:
            if not label and not value:
                # 空行分隔
                lines.append("")
            elif not label:
                # 只有值，不缩进
                lines.append(value)
            else:
                lines.append(f"  {label}：{value}")

        if footer:
            lines.append(UIRenderer.THIN_DIVIDER)
            lines.append(f"  {footer}")

        return "\n".join(lines)

    # ================================================================
    #  操作结果卡片
    # ================================================================

    @staticmethod
    def render_result_card(
        title: str,
        description: str,
        stats: Optional[List[Tuple[str, str]]] = None,
        tags: Optional[List[str]] = None,
        extra: Optional[str] = None,
        footer: Optional[str] = None
    ) -> str:
        """
        操作结果卡片（聚灵、厨房、鉴定等操作反馈用）

        格式：
          ✦ 聚灵台 · 修行报告
          ━━━━━━━━━━━━━━━
          你在聚灵台盘膝而坐，感受着灵气流动...

            🔮 运势：大吉
            ⚡ 基础：25
            💎 灵力：+30 (当前: 508)

          📌 [灵心草] [运势:大吉]

          ✨ 灵力激荡！晋升为【Lv.3 引灵归宗】！
          ─────────────────
            👉 /求签 | /聚灵 | /档案

        :param title: 卡片标题
        :param description: 描述文本（场景描写等）
        :param stats: 数据行列表 [(label, value), ...]
        :param tags: 状态标签列表
        :param extra: 额外信息（如升级提示）
        :param footer: 底部提示
        """
        lines = [
            f"✦ {title}",
            UIRenderer.DIVIDER,
        ]

        # 描述
        if description:
            lines.append(description)
            lines.append("")

        # 数据行
        if stats:
            for label, value in stats:
                if not label and not value:
                    lines.append("")
                else:
                    lines.append(f"  {label}：{value}")
            lines.append("")

        # 状态标签
        if tags:
            tag_str = " ".join(f"[{t}]" for t in tags)
            lines.append(f"  📌 {tag_str}")

        # 额外信息
        if extra:
            lines.append("")
            lines.append(f"  {extra}")

        # 底栏
        if footer:
            lines.append(UIRenderer.THIN_DIVIDER)
            lines.append(f"  {footer}")

        return "\n".join(lines)

    # ================================================================
    #  进度条
    # ================================================================

    @staticmethod
    def render_progress_bar(
        current: int,
        total: int,
        length: int = 10,
        filled_char: str = "▓",
        empty_char: str = "░"
    ) -> str:
        """
        进度条渲染

        :return: 如 "▓▓▓▓░░░░░░ 40%"
        """
        if total <= 0:
            return empty_char * length + " 0%"
        ratio = min(current / total, 1.0)
        filled = int(ratio * length)
        bar = filled_char * filled + empty_char * (length - filled)
        percent = int(ratio * 100)
        return f"{bar} {percent}%"

    # ================================================================
    #  状态标签
    # ================================================================

    @staticmethod
    def render_status_tags(tags: List[str]) -> str:
        """
        状态标签渲染

        :param tags: 标签列表，如 ["🌿 灵心草", "⭐ 大吉"]
        :return: 用空格分隔的标签行，空列表返回 "💚 状态正常"
        """
        if not tags:
            return "💚 状态正常"
        return " ".join(f"[{t}]" for t in tags)

    # ================================================================
    #  小型网格
    # ================================================================

    @staticmethod
    def render_mini_grid(cells: List[str], columns: int = 2) -> str:
        """
        小型网格渲染（用于药圃 2x2 布局等）

        :param cells: 格子内容列表
        :param columns: 每行列数
        :return: 网格文本
        """
        lines = []
        for i in range(0, len(cells), columns):
            row = cells[i:i + columns]
            lines.append("　".join(row))  # 全角空格做列间距
        return "\n".join(lines)

    # ================================================================
    #  背包物品
    # ================================================================

    @staticmethod
    def render_bag_item(name: str, count: int, desc: str) -> str:
        """
        背包物品行渲染

        :return: "🔹 灵心草 x2\n   └ 下一次聚灵收益+50%"
        """
        return f"🔹 {name} x{count}\n   └ {desc}"

    # ================================================================
    #  排行榜
    # ================================================================

    @staticmethod
    def render_ranking(
        title: str,
        items: List[Tuple[str, str]],
        footer: Optional[str] = None
    ) -> str:
        """
        排行榜渲染

        :param items: [(名字, 数值描述), ...]
        :return: 带序号和奖牌的排行榜
        """
        lines = [
            f"✦ {title}",
            UIRenderer.DIVIDER,
        ]

        medals = ["🥇", "🥈", "🥉"]
        for idx, (name, value) in enumerate(items):
            prefix = medals[idx] if idx < 3 else f"  {idx + 1}."
            lines.append(f"  {prefix} {name}　{value}")

        if footer:
            lines.append(UIRenderer.THIN_DIVIDER)
            lines.append(f"  {footer}")

        return "\n".join(lines)

    # ================================================================
    #  简易消息（带图标前缀）
    # ================================================================

    @staticmethod
    def success(text: str) -> str:
        """成功消息"""
        return f"✅ {text}"

    @staticmethod
    def error(text: str) -> str:
        """错误消息"""
        return f"❌ {text}"

    @staticmethod
    def warning(text: str) -> str:
        """警告消息"""
        return f"⚠ {text}"

    @staticmethod
    def info(text: str) -> str:
        """信息消息"""
        return f"💡 {text}"


# ==================== 全局实例 ====================
ui = UIRenderer()