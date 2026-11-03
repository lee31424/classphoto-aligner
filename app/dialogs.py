"""Excel 列映射对话框与“恢复未到场”对话框。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from excel_io import (
    SheetPreview,
    detect_columns,
    detect_gender_column,
    detect_group_columns,
    preview_sheet,
    sheet_names,
)
from models import ExcludedEntry


class ExcelImportDialog(QDialog):
    def __init__(self, path: str | Path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.selected_sheet = ""
        self.id_col: int | None = None
        self.name_col: int | None = None
        self.department_col: int | None = None
        self.class_no_col: int | None = None
        self.gender_col: int | None = None
        self.has_header = True
        self._preview: SheetPreview | None = None

        self.setWindowTitle("导入 Excel 名单")
        self.resize(940, 620)
        self._build_ui()
        self._load_sheets()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(QLabel("工作表："))
        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumWidth(220)
        top.addWidget(self.sheet_combo)
        self.header_check = QCheckBox("首行是表头")
        self.header_check.setChecked(True)
        top.addWidget(self.header_check)
        top.addStretch(1)
        layout.addLayout(top)

        self.info_label = QLabel("正在读取工作簿…")
        self.info_label.setStyleSheet("color:#5b6b7f;")
        layout.addWidget(self.info_label)

        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.verticalHeader().setDefaultSectionSize(26)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.preview_table, 1)

        mapping = QGridLayout()
        mapping.setHorizontalSpacing(10)
        mapping.setVerticalSpacing(8)
        mapping.addWidget(QLabel("学号列："), 0, 0)
        self.id_combo = QComboBox()
        self.id_combo.setMinimumWidth(250)
        mapping.addWidget(self.id_combo, 0, 1)
        mapping.addWidget(QLabel("姓名列："), 0, 2)
        self.name_combo = QComboBox()
        self.name_combo.setMinimumWidth(250)
        mapping.addWidget(self.name_combo, 0, 3)
        mapping.addWidget(QLabel("院系列："), 1, 0)
        self.department_combo = QComboBox()
        self.department_combo.setMinimumWidth(250)
        mapping.addWidget(self.department_combo, 1, 1)
        mapping.addWidget(QLabel("班级号列："), 1, 2)
        self.class_combo = QComboBox()
        self.class_combo.setMinimumWidth(250)
        mapping.addWidget(self.class_combo, 1, 3)
        mapping.addWidget(QLabel("性别列："), 2, 0)
        self.gender_combo = QComboBox()
        self.gender_combo.setMinimumWidth(250)
        mapping.addWidget(self.gender_combo, 2, 1)
        mapping.setColumnStretch(1, 1)
        mapping.setColumnStretch(3, 1)
        layout.addLayout(mapping)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("读取名单")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.sheet_combo.currentTextChanged.connect(self._reload)
        self.header_check.toggled.connect(self._reload)

    def _load_sheets(self):
        try:
            names = sheet_names(self.path)
        except Exception as exc:
            QMessageBox.critical(self, "读取失败", f"无法打开 Excel 文件：\n{exc}")
            self.reject()
            return
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(names)
        self.sheet_combo.blockSignals(False)
        if names:
            self._reload()

    def _reload(self):
        sheet = self.sheet_combo.currentText().strip()
        if not sheet:
            return
        try:
            preview = preview_sheet(
                self.path, sheet, has_header=self.header_check.isChecked(), max_rows=10
            )
        except Exception as exc:
            self.info_label.setText(f"读取失败：{exc}")
            self.preview_table.clear()
            self.id_combo.clear()
            self.name_combo.clear()
            self.department_combo.clear()
            self.class_combo.clear()
            self.gender_combo.clear()
            return

        self._preview = preview
        self.info_label.setText(
            f"工作表「{sheet}」：预览前 {len(preview.rows)} 行，共 {preview.max_col} 列。"
            " 学号会按文本读取，保留 Excel 中的数字格式。"
        )
        self._fill_table(preview)
        self._fill_columns(preview)

    def _fill_table(self, preview: SheetPreview):
        self.preview_table.clear()
        self.preview_table.setColumnCount(len(preview.headers))
        self.preview_table.setHorizontalHeaderLabels(preview.headers)
        self.preview_table.setRowCount(len(preview.rows))
        start_row = 2 if preview.has_header else 1
        self.preview_table.setVerticalHeaderLabels(
            [str(start_row + index) for index in range(len(preview.rows))]
        )
        for row_index, row in enumerate(preview.rows):
            for col_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.preview_table.setItem(row_index, col_index, item)
        self.preview_table.resizeColumnsToContents()
        for col in range(self.preview_table.columnCount()):
            self.preview_table.setColumnWidth(
                col, min(260, max(90, self.preview_table.columnWidth(col)))
            )

    def _fill_columns(self, preview: SheetPreview):
        combos = (
            self.id_combo,
            self.name_combo,
            self.department_combo,
            self.class_combo,
            self.gender_combo,
        )
        previous = {combo: combo.currentData() for combo in combos}
        for combo in combos:
            combo.blockSignals(True)
            combo.clear()

        for index, header in enumerate(preview.headers):
            label = f"{self._column_letter(index)}：{header}"
            for combo in combos:
                combo.addItem(label, index)

        self.name_combo.insertItem(0, "（不使用姓名列）", -1)
        self.department_combo.insertItem(0, "（不使用院系列）", -1)
        self.class_combo.insertItem(0, "（不使用班级号列）", -1)
        self.gender_combo.insertItem(0, "（不使用性别列）", -1)

        auto_id, auto_name = detect_columns(preview.headers)
        auto_department, auto_class = detect_group_columns(preview.headers)
        auto_gender = detect_gender_column(preview.headers)
        detected = {
            self.id_combo: auto_id,
            self.name_combo: auto_name,
            self.department_combo: auto_department,
            self.class_combo: auto_class,
            self.gender_combo: auto_gender,
        }
        for combo, detected_value in detected.items():
            previous_value = previous.get(combo)
            if previous_value is not None:
                position = combo.findData(previous_value)
                if position >= 0:
                    detected_value = previous_value
            detected[combo] = detected_value

        if detected[self.id_combo] is None:
            detected[self.id_combo] = 0 if preview.headers else None
        if (
            detected[self.name_combo] is None
            and len(preview.headers) > 1
            and detected[self.id_combo] != 1
        ):
            detected[self.name_combo] = 1

        for combo in combos:
            value = detected[combo]
            if value is None:
                value = -1
            position = combo.findData(value)
            if position < 0 and combo is self.id_combo and preview.headers:
                position = 0
            if position >= 0:
                combo.setCurrentIndex(position)
            combo.blockSignals(False)

    @staticmethod
    def _column_letter(index: int) -> str:
        from openpyxl.utils import get_column_letter

        return get_column_letter(index + 1)

    def _accept(self):
        sheet = self.sheet_combo.currentText().strip()
        if not sheet:
            QMessageBox.warning(self, "缺少工作表", "请选择工作表。")
            return
        id_col = self.id_combo.currentData()
        if id_col is None or int(id_col) < 0:
            QMessageBox.warning(self, "缺少学号列", "请选择学号列。")
            return
        name_col = self.name_combo.currentData()
        if name_col is not None and int(name_col) < 0:
            name_col = None
        department_col = self.department_combo.currentData()
        if department_col is not None and int(department_col) < 0:
            department_col = None
        class_no_col = self.class_combo.currentData()
        if class_no_col is not None and int(class_no_col) < 0:
            class_no_col = None
        gender_col = self.gender_combo.currentData()
        if gender_col is not None and int(gender_col) < 0:
            gender_col = None
        self.selected_sheet = sheet
        self.id_col = int(id_col)
        self.name_col = int(name_col) if name_col is not None else None
        self.department_col = (
            int(department_col) if department_col is not None else None
        )
        self.class_no_col = int(class_no_col) if class_no_col is not None else None
        self.gender_col = int(gender_col) if gender_col is not None else None
        self.has_header = self.header_check.isChecked()
        self.accept()


class AddRosterDialog(QDialog):
    """手动添加一条名单；学号必填，姓名和性别可空。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.student_no = ""
        self.name = ""
        self.gender = ""
        self.setWindowTitle("添加名单学生")
        self.resize(430, 250)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("必填，例如 2659A01")
        form.addRow("学号：", self.id_edit)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("可空白")
        form.addRow("姓名：", self.name_edit)
        self.gender_combo = QComboBox()
        self.gender_combo.addItem("（不填）", "")
        self.gender_combo.addItem("男", "男")
        self.gender_combo.addItem("女", "女")
        form.addRow("性别：", self.gender_combo)
        layout.addLayout(form)

        note = QLabel("新学生将直接追加到名单最后一位。")
        note.setObjectName("muted")
        layout.addWidget(note)
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("添加")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        student_no = self.id_edit.text().strip()
        if not student_no:
            QMessageBox.warning(self, "缺少学号", "学号不能为空。")
            self.id_edit.setFocus()
            return
        self.student_no = student_no
        self.name = self.name_edit.text().strip()
        self.gender = str(self.gender_combo.currentData() or "")
        self.accept()


class ShortcutSettingsDialog(QDialog):
    """编辑照片/名单/全局快捷键。"""

    def __init__(
        self,
        values: dict[str, str],
        labels: dict[str, str],
        defaults: dict[str, str],
        scopes: dict[str, str],
        parent=None,
    ):
        super().__init__(parent)
        self.labels = labels
        self.defaults = defaults
        self.scopes = scopes
        self.edits: dict[str, QKeySequenceEdit] = {}
        self.setWindowTitle("自定义快捷键")
        self.resize(520, 430)
        self._build_ui(values)

    def _build_ui(self, values: dict[str, str]):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        note = QLabel("留空表示禁用该快捷键。照片和名单的 Delete 是分开的，互不影响。")
        note.setWordWrap(True)
        note.setStyleSheet("color:#6b7788;")
        layout.addWidget(note)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(9)
        for key, label in self.labels.items():
            edit = QKeySequenceEdit(QKeySequence(values.get(key, "")))
            self.edits[key] = edit
            form.addRow(label, edit)
        layout.addLayout(form)
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        reset_button = buttons.addButton(
            "恢复默认", QDialogButtonBox.ButtonRole.ResetRole
        )
        reset_button.clicked.connect(self._reset_defaults)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reset_defaults(self):
        for key, edit in self.edits.items():
            edit.setKeySequence(QKeySequence(self.defaults.get(key, "")))

    def _accept(self):
        seen: dict[tuple[str, str], str] = {}
        for key, edit in self.edits.items():
            sequence = edit.keySequence()
            if sequence.isEmpty():
                continue
            normalized = sequence.toString(
                QKeySequence.SequenceFormat.PortableText
            )
            scope = self.scopes.get(key, "global")
            token = (scope, normalized)
            if token in seen:
                QMessageBox.warning(
                    self,
                    "快捷键重复",
                    f"“{self.labels[key]}”和“{self.labels[seen[token]]}”"
                    f"在同一个操作范围内使用了相同的快捷键：{normalized}",
                )
                return
            seen[token] = key
        self.accept()

    def shortcuts(self) -> dict[str, str]:
        return {
            key: edit.keySequence().toString(
                QKeySequence.SequenceFormat.PortableText
            )
            for key, edit in self.edits.items()
        }


class ExcludedDialog(QDialog):
    """查看/恢复被软删除的未到场学生。"""

    def __init__(self, excluded: list[ExcludedEntry], parent=None):
        super().__init__(parent)
        self.excluded = list(excluded)
        self.selected_indices: list[int] = []
        self.setWindowTitle("恢复未到场学生")
        self.resize(620, 460)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(
            QLabel(
                "这些条目已从有效名单中剔除，不参与照片配对。"
                "选中后可恢复到名单中原来的大致位置。"
            )
        )
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        for index, item in enumerate(self.excluded):
            entry = item.entry
            text = (
                f"原第 {item.origin_index + 1} 位    "
                f"{entry.student_no or '（空学号）'}    {entry.name or '（无姓名）'}"
            )
            list_item = QListWidgetItem(text)
            list_item.setData(Qt.ItemDataRole.UserRole, index)
            self.list_widget.addItem(list_item)
        layout.addWidget(self.list_widget, 1)

        bottom = QHBoxLayout()
        select_all = QPushButton("全选")
        select_all.clicked.connect(self.list_widget.selectAll)
        bottom.addWidget(select_all)
        bottom.addStretch(1)

        restore = QPushButton("恢复选中")
        restore.setDefault(True)
        restore.clicked.connect(self._accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(restore)
        bottom.addWidget(cancel)
        layout.addLayout(bottom)

    def _accept(self):
        indices = []
        for item in self.list_widget.selectedItems():
            value = item.data(Qt.ItemDataRole.UserRole)
            if value is not None:
                indices.append(int(value))
        if not indices:
            QMessageBox.information(self, "没有选择", "请先选择要恢复的条目。")
            return
        self.selected_indices = sorted(set(indices))
        self.accept()
