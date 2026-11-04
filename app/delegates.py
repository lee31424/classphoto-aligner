"""照片网格和名单行的绘制委托。"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from models import PHOTO_ROLE, ROSTER_NO_ROLE, ROSTER_NAME_ROLE, PhotoModel, RosterModel


class PhotoDelegate(QStyledItemDelegate):
    CELL_SIZE = QSize(190, 220)

    def __init__(self, photo_model: PhotoModel, thumbs, parent=None):
        super().__init__(parent)
        self.photo_model = photo_model
        self.thumbs = thumbs
        self.theme_mode = "light"
        self.dark = False
        self.hover_row = -1

    def set_hover_row(self, row: int):
        self.hover_row = row

    @staticmethod
    def overlay_rects(rect: QRect) -> tuple[QRect, QRect]:
        outer = rect.adjusted(3, 3, -3, -3)
        size = 28
        top = outer.top() + 6
        delete_rect = QRect(
            outer.right() - 6 - size, top, size, size
        )
        zoom_rect = QRect(
            delete_rect.left() - 6 - size, top, size, size
        )
        return zoom_rect, delete_rect

    def sizeHint(self, option, index: QModelIndex) -> QSize:  # noqa: N802
        return self.CELL_SIZE

    def set_thumbs(self, thumbs):
        self.thumbs = thumbs

    def set_theme(self, mode: str):
        if mode not in ("light", "dark", "black"):
            mode = "light"
        self.theme_mode = mode
        self.dark = mode != "light"

    def set_dark(self, dark: bool):
        self.set_theme("dark" if dark else "light")

    def paint(self, painter: QPainter, option, index: QModelIndex):
        photo = index.data(PHOTO_ROLE)
        if photo is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        outer = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(
            option.state & QStyle.StateFlag.State_MouseOver
        ) or index.row() == self.hover_row
        if self.theme_mode == "black":
            if selected:
                background = QColor("#0a2540")
                border = QColor("#3b82f6")
            elif hovered:
                background = QColor("#141414")
                border = QColor("#333333")
            else:
                background = QColor("#000000")
                border = QColor("#202020")
        elif self.dark:
            if selected:
                background = QColor("#17395f")
                border = QColor("#3b82f6")
            elif hovered:
                background = QColor("#223244")
                border = QColor("#3a4f66")
            else:
                background = QColor("#1b2633")
                border = QColor("#2b3948")
        elif selected:
            background = QColor("#e3f0ff")
            border = QColor("#2f80ed")
        elif hovered:
            background = QColor("#f3f7fd")
            border = QColor("#c7d8ee")
        else:
            background = QColor("#ffffff")
            border = QColor("#e1e5ec")

        painter.setBrush(background)
        painter.setPen(QPen(border, 2 if selected else 1))
        painter.drawRoundedRect(QRectF(outer), 8, 8)

        group_text = " / ".join(
            value
            for value in (photo.department, photo.major, photo.class_no)
            if value
        )
        bottom_reserved = 56 if group_text else 40
        thumb_rect = QRect(
            outer.left() + 7,
            outer.top() + 7,
            outer.width() - 14,
            outer.height() - bottom_reserved,
        )
        pixmap = self.thumbs.request(photo.path) if self.thumbs is not None else None
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                thumb_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = thumb_rect.left() + (thumb_rect.width() - scaled.width()) // 2
            y = thumb_rect.top() + (thumb_rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            if self.theme_mode == "black":
                placeholder_bg = QColor("#0d0d0d")
                placeholder_fg = QColor("#777777")
            elif self.dark:
                placeholder_bg = QColor("#24313f")
                placeholder_fg = QColor("#71849a")
            else:
                placeholder_bg = QColor("#eef1f5")
                placeholder_fg = QColor("#9aa4b2")
            painter.setBrush(placeholder_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(thumb_rect), 5, 5)
            painter.setPen(placeholder_fg)
            placeholder_font = QFont(option.font)
            placeholder_font.setPointSizeF(8.5)
            painter.setFont(placeholder_font)
            painter.drawText(
                thumb_rect,
                Qt.AlignmentFlag.AlignCenter,
                "加载中…" if self.thumbs is not None else "无预览",
            )

        badge = QRect(outer.left() + 8, outer.top() + 8, 40, 22)
        display_seq = index.row() + 1
        is_extra = display_seq > self.photo_model.counterpart_count
        if is_extra:
            badge_color = QColor("#c0392b")
        elif self.theme_mode == "black":
            badge_color = QColor("#111111")
        else:
            badge_color = QColor("#34495e")
        painter.setBrush(badge_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(badge), 5, 5)
        painter.setPen(Qt.GlobalColor.white)
        badge_font = QFont(option.font)
        badge_font.setPointSizeF(8.0)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(display_seq))

        if group_text:
            group_rect = QRect(
                outer.left() + 8,
                outer.bottom() - 43,
                outer.width() - 16,
                16,
            )
            if self.theme_mode == "black":
                group_color = QColor("#999999")
            elif self.dark:
                group_color = QColor("#8fa1b5")
            else:
                group_color = QColor("#7a8798")
            painter.setPen(group_color)
            group_font = QFont(option.font)
            group_font.setPointSizeF(7.4)
            painter.setFont(group_font)
            group_metrics = QFontMetrics(group_font)
            group_elided = group_metrics.elidedText(
                group_text, Qt.TextElideMode.ElideRight, group_rect.width()
            )
            painter.drawText(
                group_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                group_elided,
            )

        name_rect = QRect(
            outer.left() + 8,
            outer.bottom() - 28,
            outer.width() - 16,
            22,
        )
        if self.theme_mode == "black":
            name_color = QColor("#f2f2f2")
        elif self.dark:
            name_color = QColor("#dce6f0")
        else:
            name_color = QColor("#2f3b4a")
        painter.setPen(name_color)
        name_font = QFont(option.font)
        name_font.setPointSizeF(8.5)
        painter.setFont(name_font)
        metrics = QFontMetrics(name_font)
        elided = metrics.elidedText(
            photo.name, Qt.TextElideMode.ElideMiddle, name_rect.width()
        )
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            elided,
        )

        if hovered:
            zoom_rect, delete_rect = self.overlay_rects(option.rect)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(25, 31, 39, 165))
            painter.drawRoundedRect(QRectF(zoom_rect), 7, 7)
            painter.setBrush(QColor(190, 45, 45, 180))
            painter.drawRoundedRect(QRectF(delete_rect), 7, 7)

            # 放大镜
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 235), 2))
            center = zoom_rect.center()
            painter.drawEllipse(
                QRectF(center.x() - 7, center.y() - 7, 12, 12)
            )
            painter.drawLine(
                center.x() + 4,
                center.y() + 4,
                center.x() + 10,
                center.y() + 10,
            )

            # 删除图标
            c = delete_rect.center()
            painter.drawLine(c.x() - 7, c.y() - 7, c.x() + 7, c.y() - 7)
            painter.drawLine(c.x() - 5, c.y() - 4, c.x() - 5, c.y() + 8)
            painter.drawLine(c.x() + 5, c.y() - 4, c.x() + 5, c.y() + 8)
            painter.drawLine(c.x() - 5, c.y() + 8, c.x() + 5, c.y() + 8)
            painter.drawLine(c.x() - 2, c.y() - 4, c.x() - 2, c.y() + 5)
            painter.drawLine(c.x() + 2, c.y() - 4, c.x() + 2, c.y() + 5)

        painter.restore()


class RosterDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 48

    def __init__(self, roster_model: RosterModel, parent=None):
        super().__init__(parent)
        self.roster_model = roster_model
        self.cell_width = 100
        self.theme_mode = "light"
        self.dark = False

    def set_theme(self, mode: str):
        if mode not in ("light", "dark", "black"):
            mode = "light"
        self.theme_mode = mode
        self.dark = mode != "light"

    def set_dark(self, dark: bool):
        self.set_theme("dark" if dark else "light")

    def set_cell_width(self, width: int):
        self.cell_width = max(80, int(width))

    def sizeHint(self, option, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(self.cell_width, self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index: QModelIndex):
        entry = self.roster_model.entry_at(index.row())
        if entry is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if self.theme_mode == "black":
            if selected:
                painter.setBrush(QColor("#0a2540"))
                painter.setPen(QPen(QColor("#3b82f6"), 2))
            elif hovered:
                painter.setBrush(QColor("#141414"))
                painter.setPen(QPen(QColor("#333333"), 1))
            else:
                painter.setBrush(QColor("#000000"))
                painter.setPen(QPen(QColor("#202020"), 1))
        elif self.dark:
            if selected:
                painter.setBrush(QColor("#17395f"))
                painter.setPen(QPen(QColor("#3b82f6"), 2))
            elif hovered:
                painter.setBrush(QColor("#223244"))
                painter.setPen(QPen(QColor("#3a4f66"), 1))
            else:
                painter.setBrush(QColor("#1b2633"))
                painter.setPen(QPen(QColor("#2b3948"), 1))
        elif selected:
            painter.setBrush(QColor("#e3f0ff"))
            painter.setPen(QPen(QColor("#2f80ed"), 2))
        elif hovered:
            painter.setBrush(QColor("#f4f8fd"))
            painter.setPen(QPen(QColor("#d7e3f2"), 1))
        else:
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(QPen(QColor("#e5e9ef"), 1))
        painter.drawRoundedRect(QRectF(rect), 6, 6)

        is_extra = index.row() + 1 > self.roster_model.counterpart_count
        is_duplicate = entry.student_no in self.roster_model.duplicate_ids
        if self.theme_mode == "black":
            normal_number = "#999999"
        elif self.dark:
            normal_number = "#8fa1b5"
        else:
            normal_number = "#5b6b7f"
        number_color = (
            QColor("#c0392b")
            if (is_extra or is_duplicate)
            else QColor(normal_number)
        )
        number_rect = QRect(rect.left() + 8, rect.top() + 9, 34, 28)
        painter.setBrush(number_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(number_rect), 5, 5)
        painter.setPen(Qt.GlobalColor.white)
        number_font = QFont(option.font)
        number_font.setPointSizeF(8.0)
        number_font.setBold(True)
        painter.setFont(number_font)
        painter.drawText(number_rect, Qt.AlignmentFlag.AlignCenter, str(index.row() + 1))

        gender = entry.gender if entry.gender in ("男", "女") else ""
        text_left = rect.left() + 50
        text_width = rect.width() - (110 if gender else 78)
        # 第一行姓名，第二行学号（附班级/院系）。
        name_rect = QRect(text_left, rect.top() + 5, text_width, 21)
        id_rect = QRect(text_left, rect.top() + 24, text_width, 18)

        name_font = QFont(option.font)
        name_font.setPointSizeF(9.5)
        name_font.setBold(True)
        painter.setFont(name_font)
        if self.theme_mode == "black":
            name_color = QColor("#f2f2f2")
        elif self.dark:
            name_color = QColor("#e6edf5")
        else:
            name_color = QColor("#223044")
        painter.setPen(name_color)
        metrics = QFontMetrics(name_font)
        name_text = metrics.elidedText(
            entry.name or "（无姓名）",
            Qt.TextElideMode.ElideRight,
            name_rect.width(),
        )
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            name_text,
        )

        id_font = QFont(option.font)
        id_font.setPointSizeF(8.3)
        painter.setFont(id_font)
        if is_duplicate:
            id_color = QColor("#c0392b")
        elif self.theme_mode == "black":
            id_color = QColor("#999999")
        elif self.dark:
            id_color = QColor("#9fb0c3")
        else:
            id_color = QColor("#6b7788")
        painter.setPen(id_color)
        metrics = QFontMetrics(id_font)
        id_text_value = entry.student_no or "（空学号）"
        group_text = " / ".join(
            value for value in (entry.class_no, entry.department) if value
        )
        if group_text:
            id_text_value += f"  ·  {group_text}"
        id_text = metrics.elidedText(
            id_text_value, Qt.TextElideMode.ElideRight, id_rect.width()
        )
        painter.drawText(
            id_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            id_text,
        )

        if gender:
            gender_rect = QRect(rect.right() - 58, rect.top() + 7, 28, 18)
            if self.theme_mode == "black":
                gender_bg = (
                    QColor("#0a2540") if gender == "男" else QColor("#2a0e1a")
                )
                gender_fg = (
                    QColor("#8fc2ff") if gender == "男" else QColor("#ff9fc4")
                )
            elif self.dark:
                gender_bg = (
                    QColor("#1e3a5f") if gender == "男" else QColor("#3a1f32")
                )
                gender_fg = (
                    QColor("#8fc2ff") if gender == "男" else QColor("#ff9fc4")
                )
            else:
                gender_bg = (
                    QColor("#eaf3ff") if gender == "男" else QColor("#fff0f4")
                )
                gender_fg = (
                    QColor("#2f80ed") if gender == "男" else QColor("#c0396b")
                )
            painter.setBrush(gender_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(gender_rect), 8, 8)
            gender_font = QFont(option.font)
            gender_font.setPointSizeF(7.8)
            gender_font.setBold(True)
            painter.setFont(gender_font)
            painter.setPen(gender_fg)
            painter.drawText(
                gender_rect, Qt.AlignmentFlag.AlignCenter, gender
            )

        handle_rect = QRect(rect.right() - 24, rect.top() + 10, 18, 26)
        if self.theme_mode == "black":
            handle_color = QColor("#666666")
        elif self.dark:
            handle_color = QColor("#6f8298")
        else:
            handle_color = QColor("#b0bac7")
        painter.setPen(handle_color)
        handle_font = QFont(option.font)
        handle_font.setPointSizeF(13)
        painter.setFont(handle_font)
        painter.drawText(
            handle_rect,
            Qt.AlignmentFlag.AlignCenter,
            "≡",
        )

        painter.restore()
