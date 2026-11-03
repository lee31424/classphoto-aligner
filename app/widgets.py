"""自定义名单列表：把拖放结果转换成 move_requested 信号。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import QListView


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
        width = self.viewport().width()
        if width <= 0:
            return
        # 窗口宽时三列，窄时两列；列宽跟随可用宽度。
        columns = 3 if width >= 560 else 2
        cell_width = max(160, (width - 2) // columns)
        self._columns = columns
        delegate = self.itemDelegate()
        if hasattr(delegate, "set_cell_width"):
            delegate.set_cell_width(cell_width)
        self.setGridSize(QSize(cell_width, self.ROW_HEIGHT))
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
