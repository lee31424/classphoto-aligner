"""照片与名单的数据模型。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from grouping import class_sort_key


PHOTO_ROLE = int(Qt.ItemDataRole.UserRole) + 1
ROSTER_NO_ROLE = int(Qt.ItemDataRole.UserRole) + 1
ROSTER_NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 2
ROSTER_UID_ROLE = int(Qt.ItemDataRole.UserRole) + 3
ROSTER_SOURCE_ROW_ROLE = int(Qt.ItemDataRole.UserRole) + 4
ROSTER_DEPARTMENT_ROLE = int(Qt.ItemDataRole.UserRole) + 5
ROSTER_CLASS_ROLE = int(Qt.ItemDataRole.UserRole) + 6
ROSTER_GENDER_ROLE = int(Qt.ItemDataRole.UserRole) + 7


@dataclass(slots=True)
class PhotoItem:
    seq: int
    path: Path
    name: str
    size: int
    mtime_ns: int
    suffix: str
    department: str = ""
    major: str = ""
    class_no: str = ""


@dataclass(slots=True)
class RosterEntry:
    student_no: str
    name: str
    source_row: int
    department: str = ""
    class_no: str = ""
    gender: str = ""
    uid: str = field(default_factory=lambda: uuid4().hex)


@dataclass(slots=True)
class ExcludedEntry:
    entry: RosterEntry
    origin_index: int


def sort_roster_by_class(entries: list[RosterEntry]) -> list[RosterEntry]:
    """以班级号为块排序；同班内保留 Excel 原始行顺序。

    班级号优先，院系只用于区分同号班级；如果整份名单没有班级号，
    则完全保持原顺序。
    """
    if not any(entry.class_no for entry in entries):
        return list(entries)
    classified = [entry for entry in entries if entry.class_no]
    unclassified = [entry for entry in entries if not entry.class_no]
    classified.sort(
        key=lambda entry: (
            class_sort_key(entry.class_no),
            entry.department.casefold(),
            entry.source_row,
        )
    )
    return classified + unclassified


class PhotoModel(QAbstractListModel):
    """只读照片队列，顺序在导入时冻结。"""

    def __init__(self, photos: list[PhotoItem] | None = None, parent=None):
        super().__init__(parent)
        self._photos: list[PhotoItem] = list(photos or [])
        self._path_to_row: dict[Path, int] = {}
        self._counterpart_count = 0
        self._rebuild_path_map()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._photos)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._photos):
            return None
        photo = self._photos[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return photo.name
        if role == Qt.ItemDataRole.ToolTipRole:
            group = " / ".join(
                value
                for value in (photo.department, photo.major, photo.class_no)
                if value
            )
            group_line = f"分组：{group}\n" if group else ""
            return (
                f"{photo.name}\n{photo.path}\n{group_line}"
                f"{photo.size:,} 字节"
            )
        if role == PHOTO_ROLE:
            return photo
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def set_photos(self, photos: list[PhotoItem]):
        self.beginResetModel()
        self._photos = list(photos)
        self._rebuild_path_map()
        self.endResetModel()

    def _rebuild_path_map(self):
        self._path_to_row = {photo.path: row for row, photo in enumerate(self._photos)}

    def photo_at(self, row: int) -> PhotoItem | None:
        if 0 <= row < len(self._photos):
            return self._photos[row]
        return None

    def index_for_path(self, path: Path) -> QModelIndex:
        row = self._path_to_row.get(path)
        return self.index(row, 0) if row is not None else QModelIndex()

    @property
    def counterpart_count(self) -> int:
        return self._counterpart_count

    def set_counterpart_count(self, count: int):
        count = max(0, int(count))
        if count == self._counterpart_count:
            return
        self._counterpart_count = count
        if self._photos:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._photos) - 1, 0),
                [Qt.ItemDataRole.DisplayRole],
            )

    def photos(self) -> list[PhotoItem]:
        return list(self._photos)


class RosterModel(QAbstractListModel):
    """可拖拽排序的名单模型；未到场条目由窗口移出本模型。"""

    def __init__(self, entries: list[RosterEntry] | None = None, parent=None):
        super().__init__(parent)
        self._entries: list[RosterEntry] = list(entries or [])
        self._counterpart_count = 0
        self._duplicate_ids: set[str] = set()
        self._refresh_duplicates()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._entries)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{entry.student_no}  {entry.name}".strip()
        if role == Qt.ItemDataRole.ToolTipRole:
            return (
                f"第 {index.row() + 1} 位\n"
                f"学号：{entry.student_no or '（空）'}\n"
                f"姓名：{entry.name or '（空）'}\n"
                f"院系：{entry.department or '（空）'}\n"
                f"班级号：{entry.class_no or '（空）'}\n"
                f"性别：{entry.gender or '（空）'}\n"
                f"Excel 行：{entry.source_row}"
            )
        if role == ROSTER_NO_ROLE:
            return entry.student_no
        if role == ROSTER_NAME_ROLE:
            return entry.name
        if role == ROSTER_UID_ROLE:
            return entry.uid
        if role == ROSTER_SOURCE_ROW_ROLE:
            return entry.source_row
        if role == ROSTER_DEPARTMENT_ROLE:
            return entry.department
        if role == ROSTER_CLASS_ROLE:
            return entry.class_no
        if role == ROSTER_GENDER_ROLE:
            return entry.gender
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )

    def supportedDropActions(self):  # noqa: N802
        return Qt.DropAction.MoveAction

    def entry_at(self, row: int) -> RosterEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def entries(self) -> list[RosterEntry]:
        return list(self._entries)

    def reset_entries(self, entries: list[RosterEntry]):
        self.beginResetModel()
        self._entries = list(entries)
        self._refresh_duplicates()
        self.endResetModel()

    def insert_entry(self, row: int, entry: RosterEntry):
        row = max(0, min(int(row), len(self._entries)))
        self.beginInsertRows(QModelIndex(), row, row)
        self._entries.insert(row, entry)
        self._refresh_duplicates()
        self.endInsertRows()

    def remove_row(self, row: int) -> RosterEntry | None:
        if not 0 <= row < len(self._entries):
            return None
        self.beginRemoveRows(QModelIndex(), row, row)
        entry = self._entries.pop(row)
        self._refresh_duplicates()
        self.endRemoveRows()
        return entry

    def move_row(self, source: int, target_before: int) -> bool:
        """把 source 行移动到 target_before 插入位置。

        target_before 是“移动之前”的插入下标，范围 0..rowCount。
        """
        count = len(self._entries)
        if not 0 <= source < count:
            return False
        target_before = max(0, min(int(target_before), count))
        if target_before in (source, source + 1):
            return False
        if not self.beginMoveRows(
            QModelIndex(), source, source, QModelIndex(), target_before
        ):
            return False
        entry = self._entries.pop(source)
        if target_before > source:
            target_before -= 1
        self._entries.insert(target_before, entry)
        self.endMoveRows()
        return True

    def _refresh_duplicates(self):
        counts = Counter(entry.student_no for entry in self._entries if entry.student_no)
        self._duplicate_ids = {student_no for student_no, n in counts.items() if n > 1}

    @property
    def duplicate_ids(self) -> set[str]:
        return set(self._duplicate_ids)

    def refresh_validation(self):
        self._refresh_duplicates()
        if self._entries:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._entries) - 1, 0),
                [Qt.ItemDataRole.DisplayRole],
            )

    @property
    def counterpart_count(self) -> int:
        return self._counterpart_count

    def set_counterpart_count(self, count: int):
        count = max(0, int(count))
        if count == self._counterpart_count:
            return
        self._counterpart_count = count
        if self._entries:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._entries) - 1, 0),
                [Qt.ItemDataRole.DisplayRole],
            )

    def row_for_uid(self, uid: str) -> int:
        for row, entry in enumerate(self._entries):
            if entry.uid == uid:
                return row
        return -1
