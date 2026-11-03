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

    def sizeHint(self, option, index: QModelIndex) -> QSize:  # noqa: N802
        return self.CELL_SIZE

    def set_thumbs(self, thumbs):
        self.thumbs = thumbs

    def paint(self, painter: QPainter, option, index: QModelIndex):
        photo = index.data(PHOTO_ROLE)
        if photo is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        outer = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
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
            painter.setBrush(QColor("#eef1f5"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(thumb_rect), 5, 5)
            painter.setPen(QColor("#9aa4b2"))
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
        badge_color = QColor("#c0392b") if is_extra else QColor("#34495e")
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
            painter.setPen(QColor("#7a8798"))
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
        painter.setPen(QColor("#2f3b4a"))
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

        painter.restore()


class RosterDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 48

    def __init__(self, roster_model: RosterModel, parent=None):
        super().__init__(parent)
        self.roster_model = roster_model
        self.cell_width = 100

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
        if selected:
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
        number_color = QColor("#c0392b") if (is_extra or is_duplicate) else QColor("#5b6b7f")
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
        id_rect = QRect(text_left, rect.top() + 5, text_width, 21)
        name_rect = QRect(text_left, rect.top() + 24, text_width, 18)

        id_font = QFont(option.font)
        id_font.setPointSizeF(9.5)
        id_font.setBold(True)
        painter.setFont(id_font)
        painter.setPen(QColor("#c0392b") if is_duplicate else QColor("#223044"))
        metrics = QFontMetrics(id_font)
        id_text = metrics.elidedText(
            entry.student_no or "（空学号）",
            Qt.TextElideMode.ElideRight,
            id_rect.width(),
        )
        painter.drawText(
            id_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            id_text,
        )

        name_font = QFont(option.font)
        name_font.setPointSizeF(8.3)
        painter.setFont(name_font)
        painter.setPen(QColor("#6b7788"))
        metrics = QFontMetrics(name_font)
        name_text_value = entry.name or "（无姓名）"
        group_text = " / ".join(
            value for value in (entry.class_no, entry.department) if value
        )
        if group_text:
            name_text_value += f"  ·  {group_text}"
        name_text = metrics.elidedText(
            name_text_value, Qt.TextElideMode.ElideRight, name_rect.width()
        )
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            name_text,
        )

        if gender:
            gender_rect = QRect(rect.right() - 58, rect.top() + 7, 28, 18)
            gender_bg = QColor("#eaf3ff") if gender == "男" else QColor("#fff0f4")
            gender_fg = QColor("#2f80ed") if gender == "男" else QColor("#c0396b")
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
        painter.setPen(QColor("#b0bac7"))
        handle_font = QFont(option.font)
        handle_font.setPointSizeF(13)
        painter.setFont(handle_font)
        painter.drawText(
            handle_rect,
            Qt.AlignmentFlag.AlignCenter,
            "≡",
        )

        painter.restore()
