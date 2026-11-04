"""自定义名单列表：把拖放结果转换成 move_requested 信号。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import QListView


class PhotoListView(QListView):
    """照片网格：悬停时在卡片上显示放大/删除按钮。"""

    zoom_requested = Signal(int)
    delete_requested = Signal(int)
    photo_double_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_row = -1
        self.setMouseTracking(True)

    def _button_at(self, position):
        index = self.indexAt(position)
        if not index.isValid():
            return None
        delegate = self.itemDelegate()
        if not hasattr(delegate, "overlay_rects"):
            return None
        zoom_rect, delete_rect = delegate.overlay_rects(
            self.visualRect(index)
        )
        if delete_rect.contains(position):
            return "delete", index
        if zoom_rect.contains(position):
            return "zoom", index
        return None

    def _set_hover_row(self, row: int):
        if row == self._hover_row:
            return
        old_row = self._hover_row
        self._hover_row = row
        delegate = self.itemDelegate()
        if hasattr(delegate, "set_hover_row"):
            delegate.set_hover_row(row)
        model = self.model()
        if model is not None:
            for value in (old_row, row):
                if value >= 0:
                    index = model.index(value, 0)
                    if index.isValid():
                        self.viewport().update(self.visualRect(index))

    def reset_hover(self):
        self._set_hover_row(-1)
        self.unsetCursor()

    def mouseMoveEvent(self, event):  # noqa: N802
        position = event.position().toPoint()
        hit = self._button_at(position)
        index = self.indexAt(position)
        self._set_hover_row(index.row() if index.isValid() else -1)
        if hit is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._set_hover_row(-1)
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        hit = self._button_at(event.position().toPoint())
        if hit is not None and event.button() == Qt.MouseButton.LeftButton:
            action, index = hit
            self.setCurrentIndex(index)
            self._set_hover_row(-1)
            if action == "zoom":
                self.zoom_requested.emit(index.row())
            else:
                self.delete_requested.emit(index.row())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        position = event.position().toPoint()
        if self._button_at(position) is None:
            index = self.indexAt(position)
            if index.isValid():
                self.photo_double_clicked.emit(index.row())
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


class RosterListView(QListView):
    move_requested = Signal(int, int)
    ROW_HEIGHT = 54

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_source: int | None = None
        self._columns = 2
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(200)
        self.setGridSize(QSize(260, self.ROW_HEIGHT))
        self.setSpacing(0)
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)

    def _update_columns(self):
        # 列数和列宽都只根据控件总宽度计算，不读 viewport 宽度。
        # viewport 会因垂直滚动条出现/消失而变宽变窄；如果用它算网格宽度，
        # setGridSize 会再次触发布局，形成“滚动条 ↔ 列宽”的高频循环。
        total_width = self.width()
        if total_width <= 0:
            return

        columns = 3 if total_width >= 560 else 2
        scrollbar_width = self.verticalScrollBar().sizeHint().width()
        usable_width = max(
            1, total_width - 2 * self.frameWidth() - scrollbar_width - 2
        )
        cell_width = max(160, usable_width // columns)
        grid = QSize(cell_width, self.ROW_HEIGHT)
        changed = columns != self._columns or grid != self.gridSize()
        self._columns = columns
        delegate = self.itemDelegate()
        if hasattr(delegate, "set_cell_width"):
            delegate.set_cell_width(cell_width)
        if not changed:
            return
        self.setGridSize(grid)
        self.scheduleDelayedItemsLayout()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._update_columns()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._update_columns()

    def startDrag(self, supported_actions):  # noqa: N802
        index = self.currentIndex()
        if not index.isValid():
            return
        self._drag_source = index.row()
        super().startDrag(supported_actions)

    def dropEvent(self, event):  # noqa: N802
        if self._drag_source is None:
            event.ignore()
            return
        source = self._drag_source
        self._drag_source = None
        position: QPoint = event.position().toPoint()
        index = self.indexAt(position)
        if index.isValid():
            rect = self.visualRect(index)
            # 多列网格：下半区或同一行右半区都表示插到该项之后。
            after = position.y() > rect.center().y() or (
                abs(position.y() - rect.center().y()) <= rect.height() // 2
                and position.x() > rect.center().x()
            )
            target = index.row() + (1 if after else 0)
        else:
            target = self.model().rowCount() if self.model() is not None else 0
        if target in (source, source + 1):
            event.ignore()
            return
        self.move_requested.emit(source, target)
        event.acceptProposedAction()
