"""照片名单对齐工具：固定照片队列 + 可拖拽名单 + 按位置导出。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QSettings,
    QTimer,
    QUrl,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QPalette,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from delegates import PhotoDelegate, RosterDelegate
from dialogs import (
    AddRosterDialog,
    ExcelImportDialog,
    ExcludedDialog,
    PhotoPreviewDialog,
    ShortcutSettingsDialog,
)
from excel_io import read_roster
from exporter import ExportWorker, build_export_items, undo_export
from grouping import (
    class_sort_key,
    normalize_class,
    parse_photo_group,
    parse_photo_major,
    resolve_departments_from_roster,
    sort_photos_by_class,
)
from models import (
    ExcludedEntry,
    PhotoItem,
    PhotoModel,
    RosterEntry,
    RosterModel,
    sort_roster_by_class,
)
from thumbnails import ThumbnailManager
from utils import (
    format_size,
    is_image_file,
    natural_sort_key,
    natural_sort_paths,
    normalize_student_no_input,
    run_id_now,
    sanitize_filename,
)
from widgets import (
    HorizontalWheelScrollArea,
    PhotoListView,
    RosterListView,
)


APP_DIR = Path(__file__).resolve().parent
APP_ROOT = APP_DIR.parent
CACHE_DIR = APP_ROOT / "cache"
LOG_DIR = APP_ROOT / "logs"
OUTPUT_ROOT = APP_ROOT / "output"
APP_VERSION = "1.0.0"

SHORTCUT_DEFAULTS = {
    "photo_delete": "Delete",
    "roster_delete": "Delete",
    "roster_end": "End",
    "roster_up": "Alt+Up",
    "roster_down": "Alt+Down",
    "undo": "Ctrl+Z",
    "redo": "Ctrl+Y",
    "export": "Ctrl+E",
}
SHORTCUT_LABELS = {
    "photo_delete": "照片：删除当前照片",
    "roster_delete": "名单：删除未到场",
    "roster_end": "名单：移到末尾",
    "roster_up": "名单：上移",
    "roster_down": "名单：下移",
    "undo": "全局：撤销",
    "redo": "全局：重做",
    "export": "全局：导出到新文件夹",
}
SHORTCUT_SCOPES = {
    "photo_delete": "photo",
    "roster_delete": "roster",
    "roster_end": "roster",
    "roster_up": "roster",
    "roster_down": "roster",
    "undo": "global",
    "redo": "global",
    "export": "global",
}
THEME_MODES = ("light", "dark", "black")
THEME_LABELS = {"light": "浅色", "dark": "深色", "black": "纯黑"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("PhotoRosterTool", "PhotoRosterTool")
        saved_theme = str(self.settings.value("theme_mode", "") or "")
        if saved_theme not in THEME_MODES:
            saved_theme = (
                "dark"
                if bool(self.settings.value("dark_theme", False, type=bool))
                else "light"
            )
        self._theme_mode = saved_theme
        self.source_dir: Path | None = None
        self.output_dir: Path | None = None
        self.last_output_dir: Path | None = None
        self.last_summary_path: Path | None = None
        saved_batch_dir = self.settings.value("batch_export_dir")
        self.batch_export_dir = (
            Path(str(saved_batch_dir)) if saved_batch_dir else OUTPUT_ROOT
        )
        self._exported_classes: set[str] = set()
        raw_exported = self.settings.value("exported_classes", "[]")
        try:
            loaded_exported = json.loads(str(raw_exported))
            if isinstance(loaded_exported, list):
                self._exported_classes = {str(value) for value in loaded_exported}
        except (TypeError, ValueError):
            pass
        self._pending_batch_key: str | None = None
        self.shortcut_values = dict(SHORTCUT_DEFAULTS)
        raw_shortcuts = self.settings.value("shortcuts_json", "")
        if raw_shortcuts:
            try:
                loaded_shortcuts = json.loads(str(raw_shortcuts))
                if isinstance(loaded_shortcuts, dict):
                    for key in self.shortcut_values:
                        if key in loaded_shortcuts:
                            self.shortcut_values[key] = str(
                                loaded_shortcuts[key]
                            )
            except (TypeError, ValueError):
                pass
        self._shortcut_objects: dict[str, QShortcut] = {}
        self.excluded: list[ExcludedEntry] = []
        self._all_photos: list[PhotoItem] = []
        self._active_entries: list[RosterEntry] = []
        self._department_filter: str | None = None
        self._class_filter: str | None = None
        self._undo_stack: list[
            tuple[
                list[RosterEntry],
                list[ExcludedEntry],
                str | None,
                str | None,
                list[PhotoItem],
            ]
        ] = []
        self._redo_stack: list[
            tuple[
                list[RosterEntry],
                list[ExcludedEntry],
                str | None,
                str | None,
                list[PhotoItem],
            ]
        ] = []
        self._syncing = False
        self.exporting = False
        self._batch_export_mode = False
        self._advance_after_export = False
        self._preview_dialog: PhotoPreviewDialog | None = None
        self.worker: ExportWorker | None = None
        self.thumbs: ThumbnailManager | None = None
        self.photo_model = PhotoModel([], self)
        self.roster_model = RosterModel([], self)
        last_export_dir = self.settings.value("last_export_dir")
        if last_export_dir:
            candidate = Path(str(last_export_dir))
            if candidate.is_dir():
                self.last_output_dir = candidate

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

        self.setWindowTitle(f"照片名单对齐工具 v{APP_VERSION}")
        self.resize(1500, 920)
        self._build_ui()
        self._restore_window_state()
        self._update_counts()
        self._update_pair_label()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(10, 10, 10, 8)
        root_layout.setSpacing(8)

        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 8, 10, 8)
        toolbar_layout.setSpacing(8)

        self.import_photos_btn = QPushButton("导入照片…")
        self.import_photos_btn.clicked.connect(self.import_photos)
        self.import_roster_btn = QPushButton("导入名单…")
        self.import_roster_btn.clicked.connect(self.import_roster)
        self.restore_btn = QPushButton("恢复未到场…")
        self.restore_btn.clicked.connect(self.restore_excluded)
        self.delete_btn = QPushButton("删除未到场")
        self.delete_btn.clicked.connect(self.delete_selected_roster)
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = QPushButton("重做")
        self.redo_btn.clicked.connect(self.redo)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setToolTip("清空当前导入的照片和名单，不删除源文件")
        self.clear_btn.clicked.connect(self.clear_all_data)

        for button in (
            self.import_photos_btn,
            self.import_roster_btn,
            self.restore_btn,
            self.delete_btn,
            self.undo_btn,
            self.redo_btn,
            self.clear_btn,
        ):
            toolbar_layout.addWidget(button)

        toolbar_layout.addStretch(1)

        self.export_btn = QPushButton("导出到新文件夹…")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.export_to_new_folder)
        self.resume_btn = QPushButton("继续上次导出…")
        self.resume_btn.clicked.connect(self.resume_last_export)
        self.undo_export_btn = QPushButton("撤销导出…")
        self.undo_export_btn.clicked.connect(self.undo_last_export)
        toolbar_layout.addWidget(self.export_btn)
        toolbar_layout.addWidget(self.resume_btn)
        toolbar_layout.addWidget(self.undo_export_btn)
        toolbar_layout.addSpacing(8)
        self.theme_btn = QPushButton("浅色")
        self.theme_btn.setObjectName("themeToggle")
        self.theme_btn.setFixedWidth(72)
        self.theme_btn.setToolTip("当前：浅色，点击切换到深色")
        self.theme_btn.clicked.connect(self._toggle_theme)
        toolbar_layout.addWidget(self.theme_btn)
        root_layout.addWidget(toolbar)

        counts_row = QHBoxLayout()
        counts_row.setContentsMargins(4, 0, 4, 0)
        self.counts_label = QLabel()
        self.counts_label.setObjectName("counts")
        self.counts_label.setTextFormat(Qt.TextFormat.RichText)
        self.validation_label = QLabel()
        self.validation_label.setObjectName("validation")
        counts_row.addWidget(self.counts_label)
        counts_row.addSpacing(18)
        counts_row.addWidget(self.validation_label, 1)

        export_row = QHBoxLayout()
        export_row.setContentsMargins(4, 0, 4, 0)
        export_row.setSpacing(8)
        export_row.addWidget(QLabel("导出路径："))
        self.export_path_edit = QLineEdit(str(self.batch_export_dir))
        self.export_path_edit.setPlaceholderText("选择导出根目录，下面会按 学院/班级 建文件夹")
        self.export_path_edit.setClearButtonEnabled(True)
        export_row.addWidget(self.export_path_edit, 1)
        self.export_path_btn = QPushButton("选择…")
        self.export_path_btn.clicked.connect(self._choose_batch_export_dir)
        export_row.addWidget(self.export_path_btn)
        self.open_export_btn = QPushButton("打开导出文件夹")
        self.open_export_btn.setToolTip("在文件资源管理器中打开当前导出目录")
        self.open_export_btn.clicked.connect(self._open_export_folder)
        export_row.addWidget(self.open_export_btn)
        self.export_path_edit.editingFinished.connect(self._save_batch_export_dir)
        root_layout.addLayout(export_row)

        filter_bar = QFrame()
        filter_bar.setObjectName("filterBar")
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(10, 6, 10, 6)
        filter_layout.setSpacing(8)
        filter_layout.addWidget(QLabel("院系："))
        self.department_filter_combo = QComboBox()
        self.department_filter_combo.setMinimumWidth(190)
        self.department_filter_combo.addItem("全部院系", None)
        filter_layout.addWidget(self.department_filter_combo)
        filter_layout.addSpacing(10)
        filter_layout.addWidget(QLabel("班级号："))
        self.class_filter_combo = QComboBox()
        self.class_filter_combo.setMinimumWidth(170)
        self.class_filter_combo.addItem("全部班级号", None)
        filter_layout.addWidget(self.class_filter_combo)
        self.filter_info_label = QLabel("尚未导入班级字段")
        self.filter_info_label.setObjectName("muted")
        filter_layout.addWidget(self.filter_info_label, 1)
        self.reset_filter_btn = QPushButton("清除筛选")
        self.reset_filter_btn.clicked.connect(self.reset_roster_filter)
        filter_layout.addWidget(self.reset_filter_btn)
        self.sort_class_btn = QPushButton("按班级分块重排")
        self.sort_class_btn.clicked.connect(self.sort_roster_by_class_clicked)
        filter_layout.addWidget(self.sort_class_btn)
        root_layout.addWidget(filter_bar)

        self.class_frames_scroll = HorizontalWheelScrollArea()
        self.class_frames_scroll.setObjectName("classFrames")
        self.class_frames_scroll.setWidgetResizable(True)
        self.class_frames_scroll.setFixedHeight(64)
        self.class_frames_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.class_frames_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.class_frames_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.class_frames_widget = QWidget()
        self.class_frames_widget.setObjectName("classFramesWidget")
        self.class_frames_widget.setAutoFillBackground(False)
        self.class_frames_layout = QHBoxLayout(self.class_frames_widget)
        self.class_frames_layout.setContentsMargins(4, 1, 4, 1)
        self.class_frames_layout.setSpacing(5)
        self.class_frames_scroll.setWidget(self.class_frames_widget)
        self.class_frames_scroll.setAutoFillBackground(False)
        self.class_frames_scroll.viewport().setAutoFillBackground(False)
        root_layout.addWidget(self.class_frames_scroll)

        self.department_filter_combo.currentIndexChanged.connect(
            self._on_department_filter_changed
        )
        self.class_filter_combo.currentIndexChanged.connect(
            self._on_class_filter_changed
        )

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.splitter, 1)

        left_panel = QFrame()
        left_panel.setObjectName("panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)
        left_header = QHBoxLayout()
        left_title = QLabel("照片 · 按班级分块，顺序固定")
        left_title.setObjectName("panelTitle")
        self.photo_count_label = QLabel("0 张")
        self.photo_count_label.setObjectName("muted")
        left_header.addWidget(left_title)
        left_header.addStretch(1)
        left_header.addWidget(self.photo_count_label)
        left_layout.addLayout(left_header)
        self.photo_group_label = QLabel("当前框：全部班级")
        self.photo_group_label.setObjectName("muted")
        left_layout.addWidget(self.photo_group_label)

        self.photo_view = PhotoListView()
        self.photo_view.setViewMode(QListView.ViewMode.IconMode)
        self.photo_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.photo_view.setMovement(QListView.Movement.Static)
        self.photo_view.setWrapping(True)
        self.photo_view.setFlow(QListView.Flow.LeftToRight)
        self.photo_view.setUniformItemSizes(True)
        self.photo_view.setLayoutMode(QListView.LayoutMode.Batched)
        self.photo_view.setBatchSize(150)
        self.photo_view.setGridSize(PhotoDelegate.CELL_SIZE)
        self.photo_view.setSpacing(0)
        self.photo_view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.photo_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.photo_view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.photo_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.photo_view.setDragEnabled(False)
        self.photo_view.setAcceptDrops(False)
        self.photo_view.setDropIndicatorShown(False)
        self.photo_view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.photo_view.setMouseTracking(True)
        self.photo_view.setObjectName("photoView")
        self.photo_delegate = PhotoDelegate(self.photo_model, None, self)
        self.photo_view.setModel(self.photo_model)
        self.photo_view.setItemDelegate(self.photo_delegate)
        self.photo_view.selectionModel().currentChanged.connect(
            self._on_photo_current_changed
        )
        self.photo_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.photo_view.customContextMenuRequested.connect(
            self._on_photo_context_menu
        )
        self.photo_view.zoom_requested.connect(self._preview_photo)
        self.photo_view.delete_requested.connect(self.delete_photo_at)
        self.photo_view.photo_double_clicked.connect(self._preview_photo)
        left_layout.addWidget(self.photo_view, 1)

        self.source_label = QLabel("尚未导入照片")
        self.source_label.setObjectName("muted")
        self.source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        left_layout.addWidget(self.source_label)

        right_panel = QFrame()
        right_panel.setObjectName("panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)
        right_header = QHBoxLayout()
        right_title = QLabel("名单 · 拖动排序，右键/快捷键删除")
        right_title.setObjectName("panelTitle")
        self.roster_count_label = QLabel("0 人")
        self.roster_count_label.setObjectName("muted")
        right_header.addWidget(right_title)
        right_header.addStretch(1)
        right_header.addWidget(self.roster_count_label)
        right_layout.addLayout(right_header)

        self.roster_view = RosterListView()
        self.roster_view.setUniformItemSizes(True)
        self.roster_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.roster_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.roster_view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.roster_view.setObjectName("rosterView")
        self.roster_delegate = RosterDelegate(self.roster_model, self)
        self.roster_view.setModel(self.roster_model)
        self.roster_view.setItemDelegate(self.roster_delegate)
        self.roster_view.move_requested.connect(self._on_move_roster)
        self.roster_view.selectionModel().currentChanged.connect(
            self._on_roster_current_changed
        )
        self.roster_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.roster_view.customContextMenuRequested.connect(
            self._on_roster_context_menu
        )
        right_layout.addWidget(self.roster_view, 1)

        hint = QLabel(
            "对齐规则：第 N 张照片 ↔ 调整后有效名单第 N 条。"
            " 删除未到场学生会让后续学生整体前移。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        right_layout.addWidget(hint)

        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([900, 600])

        bottom = QFrame()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(6, 2, 6, 2)
        bottom_layout.setSpacing(4)
        bottom_layout.addLayout(counts_row)
        self.pair_label = QLabel("请先导入照片和名单")
        self.pair_label.setObjectName("pair")
        self.pair_label.setWordWrap(False)
        counts_row.addSpacing(16)
        counts_row.addWidget(self.pair_label)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("muted")

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.progress.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_export)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel_btn)

        self.batch_export_btn = QPushButton("修改并导出本班")
        self.batch_export_btn.setObjectName("primary")
        self.batch_export_btn.setMinimumWidth(190)
        self.batch_export_btn.setFixedHeight(44)
        self.batch_export_btn.setToolTip(
            "先选择一个班级，确认当前照片和名单顺序后，立即导出到 "
            "导出路径/学院/班级"
        )
        self.batch_export_btn.clicked.connect(self.export_selected_class)

        self.eye_btn = QPushButton("有闭眼")
        self.eye_btn.setObjectName("closedEye")
        self.eye_btn.setMinimumWidth(90)
        self.eye_btn.setFixedHeight(44)
        self.eye_btn.setToolTip(
            "按正常流程导出，但班级文件夹名后追加“ 有闭眼”"
        )
        self.eye_btn.clicked.connect(
            lambda _checked=False: self.export_selected_class(
                suffix_text="有闭眼"
            )
        )

        self.review_btn = QPushButton("需核对")
        self.review_btn.setObjectName("review")
        self.review_btn.setMinimumWidth(90)
        self.review_btn.setFixedHeight(44)
        self.review_btn.setToolTip(
            "按正常流程导出，但班级文件夹名后追加“ 需核对”"
        )
        self.review_btn.clicked.connect(
            lambda _checked=False: self.export_selected_class(needs_review=True)
        )

        self.current_class_label = QLabel("")
        self.current_class_label.setObjectName("currentClass")
        self.current_class_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.current_class_label.setFixedHeight(44)
        self.current_class_label.setMinimumWidth(90)
        class_font = QFont(self.current_class_label.font())
        class_font.setPixelSize(round(44 * 2 / 3))
        class_font.setBold(True)
        self.current_class_label.setFont(class_font)

        info_row = QHBoxLayout()
        left_info = QVBoxLayout()
        left_info.setSpacing(2)
        left_info.addWidget(self.status_label)
        info_row.addLayout(left_info, 1)
        info_row.addWidget(
            self.eye_btn,
            0,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )
        info_row.addSpacing(16)
        info_row.addWidget(
            self.review_btn,
            0,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )
        info_row.addSpacing(56)
        info_row.addWidget(
            self.current_class_label,
            0,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )
        info_row.addSpacing(56)
        info_row.addWidget(
            self.batch_export_btn,
            0,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
        )
        bottom_layout.addLayout(info_row)
        bottom_layout.addLayout(progress_row)
        root_layout.addWidget(bottom)

        self._create_actions()
        self._apply_style()

    def _create_actions(self):
        self.import_photos_action = QAction("导入照片…", self)
        self.import_photos_action.triggered.connect(self.import_photos)
        self.import_roster_action = QAction("导入 Excel 名单…", self)
        self.import_roster_action.triggered.connect(self.import_roster)
        self.export_action = QAction("导出到新文件夹…", self)
        self.export_action.triggered.connect(self.export_to_new_folder)
        self.resume_action = QAction("继续上次导出（断点续跑）…", self)
        self.resume_action.triggered.connect(self.resume_last_export)
        self.undo_export_action = QAction("按日志撤销导出…", self)
        self.undo_export_action.triggered.connect(self.undo_last_export)
        self.exit_action = QAction("退出", self)
        self.exit_action.triggered.connect(self.close)

        self.undo_action = QAction("撤销名单操作", self)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = QAction("重做名单操作", self)
        self.redo_action.triggered.connect(self.redo)
        self.delete_action = QAction("删除选中的未到场学生", self)
        self.delete_action.triggered.connect(self.delete_selected_roster)
        self.restore_action = QAction("恢复未到场…", self)
        self.restore_action.triggered.connect(self.restore_excluded)
        self.shortcut_action = QAction("自定义快捷键…", self)
        self.shortcut_action.triggered.connect(self._edit_shortcuts)

        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.import_photos_action)
        file_menu.addAction(self.import_roster_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addAction(self.resume_action)
        file_menu.addAction(self.undo_export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = self.menuBar().addMenu("编辑")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.delete_action)
        edit_menu.addAction(self.restore_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.shortcut_action)

        help_menu = self.menuBar().addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

        self._create_shortcuts()
        self._apply_shortcuts()

    def _create_shortcuts(self):
        self._shortcut_objects = {
            "photo_delete": QShortcut(self.photo_view),
            "roster_delete": QShortcut(self.roster_view),
            "roster_end": QShortcut(self.roster_view),
            "roster_up": QShortcut(self.roster_view),
            "roster_down": QShortcut(self.roster_view),
        }
        for shortcut in self._shortcut_objects.values():
            shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
        self._shortcut_objects["photo_delete"].activated.connect(
            self._delete_current_photo
        )
        self._shortcut_objects["roster_delete"].activated.connect(
            self.delete_selected_roster
        )
        self._shortcut_objects["roster_end"].activated.connect(
            self._move_current_to_end
        )
        self._shortcut_objects["roster_up"].activated.connect(
            lambda: self._move_current(-1)
        )
        self._shortcut_objects["roster_down"].activated.connect(
            lambda: self._move_current(1)
        )

    def _apply_shortcuts(self):
        action_map = {
            "undo": self.undo_action,
            "redo": self.redo_action,
            "export": self.export_action,
        }
        for key, shortcut in self._shortcut_objects.items():
            sequence = QKeySequence(self.shortcut_values.get(key, ""))
            shortcut.setKey(sequence)
            shortcut.setEnabled(not sequence.isEmpty())
        for key, action in action_map.items():
            sequence = QKeySequence(self.shortcut_values.get(key, ""))
            action.setShortcut(sequence)
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)

    def _edit_shortcuts(self):
        dialog = ShortcutSettingsDialog(
            self.shortcut_values,
            SHORTCUT_LABELS,
            SHORTCUT_DEFAULTS,
            SHORTCUT_SCOPES,
            self,
        )
        if dialog.exec() != ShortcutSettingsDialog.DialogCode.Accepted:
            return
        self.shortcut_values = dialog.shortcuts()
        self._apply_shortcuts()
        self.settings.setValue(
            "shortcuts_json",
            json.dumps(self.shortcut_values, ensure_ascii=False),
        )
        self.status_label.setText("快捷键已保存")

    def _delete_current_photo(self):
        index = self.photo_view.currentIndex()
        if index.isValid():
            self.delete_photo_at(index.row())

    def _move_current_to_end(self):
        self.move_selected_roster_to_end()

    def _toggle_theme(self):
        index = THEME_MODES.index(self._theme_mode)
        self._theme_mode = THEME_MODES[(index + 1) % len(THEME_MODES)]
        self.settings.setValue("theme_mode", self._theme_mode)
        self.settings.setValue("dark_theme", self._theme_mode != "light")
        self._apply_style()
        self.status_label.setText(
            f"已切换到{THEME_LABELS[self._theme_mode]}主题"
        )

    def _theme_palette(self):
        c = self._theme_colors()
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
        palette.setColor(QPalette.ColorRole.Base, QColor(c["view"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c["panel"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
        palette.setColor(QPalette.ColorRole.Button, QColor(c["button"]))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(c["primary"]))
        palette.setColor(
            QPalette.ColorRole.HighlightedText, QColor("#ffffff")
        )
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["panel"]))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
        palette.setColor(
            QPalette.ColorRole.PlaceholderText, QColor(c["muted"])
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Text,
            QColor(c["disabled_text"]),
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            QColor(c["disabled_text"]),
        )
        return palette

    def _theme_colors(self) -> dict[str, str]:
        if self._theme_mode == "black":
            return {
                "window": "#000000",
                "panel": "#050505",
                "view": "#000000",
                "border": "#202020",
                "text": "#f2f2f2",
                "muted": "#9a9a9a",
                "button": "#111111",
                "button_hover": "#1c1c1c",
                "button_disabled": "#080808",
                "disabled_text": "#5a5a5a",
                "input": "#050505",
                "primary": "#3b82f6",
                "primary_hover": "#2f6fd0",
                "primary_disabled": "#1d3552",
                "selected_bg": "#0a2540",
                "selected_text": "#cfe6ff",
                "exported_bg": "#061f14",
                "exported_text": "#78e0a8",
                "scroll": "#333333",
            }
        if self._theme_mode == "dark":
            return {
                "window": "#0f151d",
                "panel": "#18222d",
                "view": "#131c26",
                "border": "#2b3948",
                "text": "#dce6f0",
                "muted": "#8fa1b5",
                "button": "#22303e",
                "button_hover": "#2c3d50",
                "button_disabled": "#1a2430",
                "disabled_text": "#5f7185",
                "input": "#111a24",
                "primary": "#3b82f6",
                "primary_hover": "#2f6fd0",
                "primary_disabled": "#2b4a70",
                "selected_bg": "#17395f",
                "selected_text": "#bcd9ff",
                "exported_bg": "#123528",
                "exported_text": "#7ee2ad",
                "scroll": "#34475b",
            }
        return {
            "window": "#f3f5f8",
            "panel": "#ffffff",
            "view": "#f7f8fa",
            "border": "#dfe4ec",
            "text": "#223044",
            "muted": "#6b7788",
            "button": "#ffffff",
            "button_hover": "#f2f7ff",
            "button_disabled": "#f5f6f8",
            "disabled_text": "#9aa4b2",
            "input": "#ffffff",
            "primary": "#2f80ed",
            "primary_hover": "#1f6fd6",
            "primary_disabled": "#a9c8f5",
            "selected_bg": "#eaf3ff",
            "selected_text": "#1f5fae",
            "exported_bg": "#f0fbf5",
            "exported_text": "#1f6f4a",
            "scroll": "#c5cfdb",
        }

    def _apply_style(self):
        c = self._theme_colors()
        template = """
            QMainWindow { background:@window@; }
            QWidget { color:@text@; }
            QFrame#toolbar, QFrame#panel, QFrame#filterBar {
                background:@panel@; border:1px solid @border@; border-radius:8px;
            }
            QScrollArea#classFrames { background:transparent; border:none; }
            QWidget#classFramesWidget { background:transparent; }
            QListView#photoView, QListView#rosterView {
                background:@view@; border:1px solid @border@; border-radius:6px;
            }
            QLabel#panelTitle { font-weight:700; color:@text@; font-size:10pt; }
            QLabel#counts { font-weight:700; color:@text@; }
            QLabel#validation { color:@muted@; }
            QLabel#pair { color:@text@; font-weight:600; }
            QLabel#currentClass { color:@primary@; font-weight:700; }
            QLabel#muted { color:@muted@; font-size:9pt; }
            QLabel#classFrameHint {
                color:@muted@; font-size:9pt; padding:8px;
            }
            QPushButton {
                padding:6px 12px; border:1px solid @border@; border-radius:6px;
                background:@button@; color:@text@;
            }
            QPushButton:hover {
                background:@button_hover@; border-color:@primary@;
            }
            QPushButton:disabled {
                color:@disabled_text@; background:@button_disabled@;
            }
            QPushButton#primary {
                background:@primary@; color:#ffffff; border-color:@primary@;
                font-weight:700;
            }
            QPushButton#primary:hover { background:@primary_hover@; }
            QPushButton#primary:disabled {
                background:@primary_disabled@; border-color:@primary_disabled@;
            }
            QPushButton#review {
                background:#c62828; color:#ffffff; border-color:#c62828;
                font-weight:700;
            }
            QPushButton#review:hover {
                background:#e53935; border-color:#e53935;
            }
            QPushButton#review:disabled {
                background:#6e2b2b; border-color:#6e2b2b; color:#d9b8b8;
            }
            QPushButton#closedEye {
                background:#d97706; color:#ffffff; border-color:#d97706;
                font-weight:700;
            }
            QPushButton#closedEye:hover {
                background:#f59e0b; border-color:#f59e0b;
            }
            QPushButton#closedEye:disabled {
                background:#6b4a1f; border-color:#6b4a1f; color:#ddc7a8;
            }
            QPushButton#themeToggle { padding:6px 8px; }
            QPushButton#classFrame {
                background:@panel@; border:1px solid @border@; border-radius:8px;
                padding:4px 9px; text-align:left; color:@text@;
            }
            QPushButton#classFrame:hover {
                border-color:@primary@; background:@button_hover@;
            }
            QPushButton#classFrame[exported="true"] {
                border-color:@exported_text@; background:@exported_bg@;
                color:@exported_text@;
            }
            QPushButton#classFrame[selected="true"] {
                border:2px solid @primary@; background:@selected_bg@;
                color:@selected_text@;
            }
            QLineEdit, QComboBox {
                background:@input@; color:@text@; border:1px solid @border@;
                border-radius:5px; padding:4px 6px;
            }
            QLineEdit:focus, QComboBox:focus { border-color:@primary@; }
            QComboBox QAbstractItemView {
                background:@panel@; color:@text@; border:1px solid @border@;
                selection-background-color:@selected_bg@;
                selection-color:@selected_text@;
            }
            QMenu {
                background:@panel@; color:@text@; border:1px solid @border@;
            }
            QMenu::item:selected {
                background:@selected_bg@; color:@selected_text@;
            }
            QProgressBar {
                background:@button_disabled@; border:1px solid @border@;
                border-radius:5px; text-align:center; color:@text@;
            }
            QProgressBar::chunk {
                background:@primary@; border-radius:4px;
            }
            QScrollBar:vertical, QScrollBar:horizontal {
                background:@view@; width:11px; height:11px; margin:0;
            }
            QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
                background:@scroll@; border-radius:5px; min-height:24px;
                min-width:24px;
            }
            QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
            QToolTip {
                background:@panel@; color:@text@; border:1px solid @border@;
                padding:4px;
            }
        """
        for key, value in c.items():
            template = template.replace(f"@{key}@", value)
        self.setStyleSheet(template)
        app = QApplication.instance()
        if app is not None:
            app.setPalette(self._theme_palette())
        if hasattr(self, "photo_delegate"):
            self.photo_delegate.set_theme(self._theme_mode)
        if hasattr(self, "roster_delegate"):
            self.roster_delegate.set_theme(self._theme_mode)
        for view in (
            getattr(self, "photo_view", None),
            getattr(self, "roster_view", None),
        ):
            if view is not None:
                view.viewport().update()
        if hasattr(self, "theme_btn"):
            index = THEME_MODES.index(self._theme_mode)
            next_mode = THEME_MODES[(index + 1) % len(THEME_MODES)]
            self.theme_btn.setText(THEME_LABELS[self._theme_mode])
            self.theme_btn.setToolTip(
                f"当前：{THEME_LABELS[self._theme_mode]}，"
                f"点击切换到{THEME_LABELS[next_mode]}"
            )

    # -------------------------------------------------------- window state
    def _restore_window_state(self):
        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("splitter_state")
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)

    def closeEvent(self, event):  # noqa: N802
        if self.exporting and self.worker is not None:
            answer = QMessageBox.question(
                self,
                "导出进行中",
                "照片正在复制。是否取消导出并退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel()
            if not self.worker.wait(10000):
                QMessageBox.information(
                    self,
                    "仍在收尾",
                    "当前文件还在复制，取消会在当前文件复制完成后生效。\n"
                    "请稍等几秒再关闭窗口。",
                )
                event.ignore()
                return
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("splitter_state", self.splitter.saveState())
        if self.thumbs is not None:
            self.thumbs.shutdown()
        event.accept()

    # ------------------------------------------------------------- counts
    def _update_counts(self):
        photo_count = self.photo_model.rowCount()
        photo_all_count = len(self._all_photos)
        roster_count = self.roster_model.rowCount()
        active_count = len(self._active_entries)
        excluded_count = len(self.excluded)
        diff = photo_count - roster_count
        duplicates = self.roster_model.duplicate_ids
        empty_count = sum(
            1 for entry in self.roster_model.entries() if not entry.student_no
        )
        filtering = self._filter_active()

        self.current_class_label.setText(self._class_filter or "")
        self.photo_count_label.setText(f"{photo_count} 张")
        self.roster_count_label.setText(f"{roster_count} 人")
        if filtering:
            self.photo_count_label.setText(f"{photo_count} / {photo_all_count} 张")
            self.roster_count_label.setText(f"{roster_count} / {active_count} 人")

        diff_color = "#27ae60" if diff == 0 else "#c0392b"
        self.counts_label.setText(
            f"照片 {photo_count}（全部 {photo_all_count}）  ·  "
            f"显示名单 {roster_count}（全部 {active_count}）  ·  "
            f"已剔除 {excluded_count}  ·  差值 "
            f"<span style='color:{diff_color}'>{diff:+d}</span>"
        )
        messages: list[str] = []
        if photo_count == 0:
            messages.append(
                "当前筛选没有照片" if photo_all_count else "请先导入照片"
            )
        if active_count == 0:
            messages.append("请导入 Excel 名单")
        if filtering:
            parts = []
            if self._department_filter:
                parts.append(f"院系 {self._department_filter}")
            if self._class_filter:
                parts.append(f"班级号 {self._class_filter}")
            messages.append("当前筛选：" + "，".join(parts) + "（导出只含筛选结果）")
        if duplicates:
            messages.append(f"重复学号 {len(duplicates)} 个")
        if empty_count:
            messages.append(f"空学号 {empty_count} 个")
        if photo_count and roster_count and diff != 0:
            messages.append(f"数量相差 {abs(diff)}，导出已禁用")
        if photo_count and roster_count and diff == 0 and not duplicates and not empty_count:
            messages.append("数量一致：第 N 张照片 ↔ 第 N 条名单")

        self.validation_label.setText("  ·  ".join(messages))
        ok = (
            photo_count > 0
            and roster_count > 0
            and diff == 0
            and not duplicates
            and empty_count == 0
        )
        self.validation_label.setStyleSheet(
            "color:#27ae60; font-weight:600;"
            if ok
            else "color:#c0392b; font-weight:600;"
        )

        self.photo_model.set_counterpart_count(roster_count)
        self.roster_model.set_counterpart_count(photo_count)

        can_export = ok and not self.exporting
        self.export_action.setEnabled(can_export)
        self.export_btn.setEnabled(can_export)
        can_resume = (
            can_export
            and self.last_output_dir is not None
            and self.last_output_dir.is_dir()
        )
        self.resume_action.setEnabled(can_resume)
        self.resume_btn.setEnabled(can_resume)
        can_undo_export = self.last_summary_path is not None and not self.exporting
        self.undo_export_action.setEnabled(can_undo_export)
        self.undo_export_btn.setEnabled(can_undo_export)
        self.restore_btn.setEnabled(bool(self.excluded) and not self.exporting)
        self.restore_action.setEnabled(bool(self.excluded) and not self.exporting)
        self.delete_btn.setEnabled(roster_count > 0 and not self.exporting)
        self.delete_action.setEnabled(roster_count > 0 and not self.exporting)
        self.undo_action.setEnabled(bool(self._undo_stack) and not self.exporting)
        self.redo_action.setEnabled(bool(self._redo_stack) and not self.exporting)
        self.undo_btn.setEnabled(bool(self._undo_stack) and not self.exporting)
        self.redo_btn.setEnabled(bool(self._redo_stack) and not self.exporting)
        self.import_photos_btn.setEnabled(not self.exporting)
        self.import_roster_btn.setEnabled(not self.exporting)
        self.clear_btn.setEnabled(not self.exporting)
        can_batch = bool(self._class_filter) and can_export
        self.batch_export_btn.setEnabled(can_batch)
        self.review_btn.setEnabled(can_batch)
        self.eye_btn.setEnabled(can_batch)
        self.export_path_edit.setEnabled(not self.exporting)
        self.export_path_btn.setEnabled(not self.exporting)

        has_department = any(
            entry.department for entry in self._active_entries
        ) or any(photo.department for photo in self._all_photos)
        has_class = any(
            entry.class_no for entry in self._active_entries
        ) or any(photo.class_no for photo in self._all_photos)
        self.department_filter_combo.setEnabled(
            (has_department or bool(self._department_filter)) and not self.exporting
        )
        self.class_filter_combo.setEnabled(
            (has_class or bool(self._class_filter)) and not self.exporting
        )
        self.reset_filter_btn.setEnabled(filtering and not self.exporting)
        self.sort_class_btn.setEnabled(has_class and not self.exporting)
        can_drag_roster = (
            not self.exporting
            and (not filtering or bool(self._class_filter))
        )
        self.roster_view.setDragEnabled(can_drag_roster)
        self.roster_view.setAcceptDrops(can_drag_roster)
        self.roster_view.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove
            if can_drag_roster
            else QAbstractItemView.DragDropMode.NoDragDrop
        )

        if not self._active_entries and not self._all_photos:
            self.filter_info_label.setText("尚未导入照片/名单")
        elif not self._active_entries:
            self.filter_info_label.setText(
                f"已导入照片 {photo_all_count} 张；请再导入 Excel 名单"
            )
        elif not has_department and not has_class:
            self.filter_info_label.setText("未识别到院系/班级字段")
        elif filtering:
            drag_hint = (
                "可在本班内拖动调整顺序"
                if self._class_filter
                else "请选到具体班级后再拖动调整"
            )
            self.filter_info_label.setText(
                f"当前只显示筛选结果：照片 {photo_count} / {photo_all_count}，"
                f"名单 {roster_count} / {active_count}；{drag_hint}"
            )
        else:
            self.filter_info_label.setText(
                f"全部 {photo_all_count} 张照片 / {active_count} 人；"
                "可按院系/班级同步筛选"
            )

        if filtering:
            parts = []
            if self._department_filter:
                parts.append(self._department_filter)
            if self._class_filter:
                parts.append(self._class_filter)
            self.photo_group_label.setText(
                "当前框：" + " · ".join(parts)
                + f"（照片 {photo_count} 张，名单 {roster_count} 人）"
            )
        else:
            self.photo_group_label.setText(
                f"当前框：全部班级（照片 {photo_count} 张，名单 {roster_count} 人）"
            )

    # --------------------------------------------------------- class filter
    def _filter_active(self) -> bool:
        return bool(self._department_filter or self._class_filter)

    def _refresh_filter_options(self):
        departments = sorted(
            {
                value
                for value in (
                    [entry.department for entry in self._active_entries]
                    + [photo.department for photo in self._all_photos]
                )
                if value
            },
            key=lambda value: (natural_sort_key(value), value.casefold()),
        )
        department = self._department_filter
        if department not in departments:
            department = None

        classes_by_department: dict[str, set[str]] = {}
        for entry in self._active_entries:
            class_no = normalize_class(entry.class_no)
            if entry.department and class_no:
                classes_by_department.setdefault(
                    entry.department, set()
                ).add(class_no)
        for photo in self._all_photos:
            class_no = normalize_class(photo.class_no)
            if photo.department and class_no:
                classes_by_department.setdefault(
                    photo.department, set()
                ).add(class_no)

        self.department_filter_combo.blockSignals(True)
        self.department_filter_combo.clear()
        self.department_filter_combo.addItem("全部院系", None)
        for value in departments:
            department_classes = classes_by_department.get(value, set())
            exported_all = bool(department_classes) and all(
                self._export_mark_key(value, class_no)
                in self._exported_classes
                for class_no in department_classes
            )
            label = value + ("（已全部导出）" if exported_all else "")
            self.department_filter_combo.addItem(label, value)
        position = self.department_filter_combo.findData(department)
        self.department_filter_combo.setCurrentIndex(position if position >= 0 else 0)
        self.department_filter_combo.blockSignals(False)
        self._department_filter = department

        classes = {
            normalize_class(entry.class_no)
            for entry in self._active_entries
            if entry.class_no
            and (department is None or entry.department == department)
        }
        classes.update(
            normalize_class(photo.class_no)
            for photo in self._all_photos
            if photo.class_no
            and (department is None or photo.department == department)
        )
        class_values = sorted(
            (value for value in classes if value),
            key=lambda value: (natural_sort_key(value), value.casefold()),
        )
        class_no = self._class_filter
        if class_no not in class_values:
            class_no = None

        self.class_filter_combo.blockSignals(True)
        self.class_filter_combo.clear()
        self.class_filter_combo.addItem("全部班级号", None)
        for value in class_values:
            self.class_filter_combo.addItem(value, value)
        position = self.class_filter_combo.findData(class_no)
        self.class_filter_combo.setCurrentIndex(position if position >= 0 else 0)
        self.class_filter_combo.blockSignals(False)
        self._class_filter = class_no
        self._rebuild_class_frames()

    def _clear_class_frames(self):
        while self.class_frames_layout.count():
            item = self.class_frames_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_class_frames(self):
        scroll_bar = self.class_frames_scroll.horizontalScrollBar()
        old_scroll = scroll_bar.value()
        self._clear_class_frames()
        groups: dict[tuple[str, str], list[int]] = {}
        for photo in self._all_photos:
            class_no = normalize_class(photo.class_no)
            if not class_no:
                continue
            if (
                self._department_filter
                and photo.department != self._department_filter
            ):
                continue
            key = (photo.department, class_no)
            groups.setdefault(key, [0, 0])[0] += 1
        for entry in self._active_entries:
            class_no = normalize_class(entry.class_no)
            if not class_no:
                continue
            if (
                self._department_filter
                and entry.department != self._department_filter
            ):
                continue
            key = (entry.department, class_no)
            groups.setdefault(key, [0, 0])[1] += 1

        if not groups:
            hint = QLabel(
                "该院系暂无班级"
                if self._department_filter
                else "导入带班级信息的照片/名单后，这里会为每个班级显示一个框"
            )
            hint.setObjectName("classFrameHint")
            self.class_frames_layout.addWidget(hint)
            self.class_frames_layout.addStretch(1)
            return

        photo_total = sum(item[0] for item in groups.values())
        roster_total = sum(item[1] for item in groups.values())
        all_label = (
            "本院系全部班级" if self._department_filter else "全部班级"
        )
        all_button = QPushButton(
            f"{all_label}\n照片 {photo_total} · 名单 {roster_total}"
        )
        all_button.setObjectName("classFrame")
        all_button.setFixedHeight(44)
        all_button.setMinimumWidth(145)
        all_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        all_button.installEventFilter(self)
        all_button.setProperty("selected", not self._class_filter)
        all_button.clicked.connect(self._show_all_classes_in_current_department)
        self.class_frames_layout.addWidget(all_button)

        for (department, class_no), (photo_count, roster_count) in sorted(
            groups.items(),
            key=lambda item: (
                class_sort_key(item[0][1]),
                item[0][0].casefold(),
            ),
        ):
            selected = (
                self._department_filter == department
                and self._class_filter == class_no
            )
            mark_key = self._export_mark_key(department, class_no)
            exported = mark_key in self._exported_classes
            status_line = f"照片 {photo_count} · 名单 {roster_count}"
            if exported:
                status_line += " · ✓ 已导出"
            button = QPushButton(
                f"{department or '未填院系'} · {class_no}\n{status_line}"
            )
            button.setObjectName("classFrame")
            button.setFixedHeight(44)
            button.setMinimumWidth(155)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.installEventFilter(self)
            button.setProperty("selected", selected)
            button.setProperty("exported", exported)
            button.setToolTip(
                f"院系：{department or '未填'}\n"
                f"班级号：{class_no}\n"
                f"照片 {photo_count} 张，名单 {roster_count} 人"
                + ("\n已导出" if exported else "")
            )
            button.clicked.connect(
                lambda _checked=False, d=department, c=class_no: self._select_class_frame(
                    d, c
                )
            )
            self.class_frames_layout.addWidget(button)
        self.class_frames_layout.addStretch(1)
        # 重建按钮后恢复原横向位置，避免一选班级就跳到最右边。
        QTimer.singleShot(0, lambda value=old_scroll: scroll_bar.setValue(value))

    def _select_next_class_after_export(self):
        if not self._class_filter:
            return
        pairs = set()
        for photo in self._all_photos:
            class_no = normalize_class(photo.class_no)
            if not class_no:
                continue
            if (
                self._department_filter
                and photo.department != self._department_filter
            ):
                continue
            pairs.add((photo.department, class_no))
        for entry in self._active_entries:
            class_no = normalize_class(entry.class_no)
            if not class_no:
                continue
            if (
                self._department_filter
                and entry.department != self._department_filter
            ):
                continue
            pairs.add((entry.department, class_no))
        ordered = sorted(
            pairs,
            key=lambda item: (
                class_sort_key(item[1]),
                item[0].casefold(),
            ),
        )
        current = None
        for index, pair in enumerate(ordered):
            if pair[1] != self._class_filter:
                continue
            if self._department_filter and pair[0] != self._department_filter:
                continue
            current = index
            break
        if current is None or current + 1 >= len(ordered):
            self.status_label.setText(
                "本班导出完成；当前院系已经是最后一个班级"
            )
            return
        department, class_no = ordered[current + 1]
        self._select_class_frame(department, class_no)
        self.status_label.setText(
            f"本班导出完成，已自动选择下一个班级：{class_no}"
        )

    def _select_class_frame(self, department: str, class_no: str):
        if self.exporting:
            return
        self._department_filter = department or None
        self._class_filter = normalize_class(class_no) or None
        self._refresh_filter_options()
        self._apply_filters()
        self.photo_view.scrollToTop()
        self.roster_view.scrollToTop()
        self.status_label.setText(
            f"已选择班级框：{department or '未填院系'} · {class_no}"
        )

    def _photo_matches_filter(self, photo: PhotoItem) -> bool:
        if self._department_filter and photo.department != self._department_filter:
            return False
        if self._class_filter and normalize_class(photo.class_no) != self._class_filter:
            return False
        return True

    def _roster_matches_filter(self, entry: RosterEntry) -> bool:
        if self._department_filter and entry.department != self._department_filter:
            return False
        if self._class_filter and normalize_class(entry.class_no) != self._class_filter:
            return False
        return True

    def _apply_filters(self):
        filtered_photos = [
            photo for photo in self._all_photos if self._photo_matches_filter(photo)
        ]
        filtered_roster = [
            entry
            for entry in self._active_entries
            if self._roster_matches_filter(entry)
        ]
        self.photo_model.set_photos(filtered_photos)
        self.roster_model.reset_entries(filtered_roster)
        if hasattr(self.photo_view, "reset_hover"):
            self.photo_view.reset_hover()
        self.photo_view.clearSelection()
        self.roster_view.clearSelection()
        self._update_counts()
        self._update_pair_label()

    def _on_department_filter_changed(self, _index: int):
        self._department_filter = self.department_filter_combo.currentData()
        self._refresh_filter_options()
        self._apply_filters()
        self.photo_view.scrollToTop()
        self.roster_view.scrollToTop()
        self.status_label.setText("已按院系同步筛选照片和名单")

    def _on_class_filter_changed(self, _index: int):
        self._class_filter = self.class_filter_combo.currentData()
        self._rebuild_class_frames()
        self._apply_filters()
        self.photo_view.scrollToTop()
        self.roster_view.scrollToTop()
        self.status_label.setText("已按班级号同步筛选照片和名单")

    def reset_roster_filter(self):
        if not self._filter_active():
            return
        self._department_filter = None
        self._class_filter = None
        self._refresh_filter_options()
        self._apply_filters()
        self.photo_view.scrollToTop()
        self.roster_view.scrollToTop()
        self.status_label.setText("已清除筛选，照片和名单恢复全部")

    def _show_all_classes_in_current_department(self):
        if not self._department_filter:
            self.reset_roster_filter()
            return
        self._class_filter = None
        self._refresh_filter_options()
        self._apply_filters()
        self.photo_view.scrollToTop()
        self.roster_view.scrollToTop()
        self.status_label.setText(
            f"已显示 {self._department_filter} 的全部班级"
        )

    def set_active_photos(self, photos: list[PhotoItem]):
        """设置完整照片队列；界面模型只显示筛选后的子集。"""
        self._all_photos = sort_photos_by_class(photos)
        for seq, photo in enumerate(self._all_photos, start=1):
            photo.seq = seq
        resolve_departments_from_roster(self._all_photos, self._active_entries)
        self._department_filter = None
        self._class_filter = None
        self._refresh_filter_options()
        self._apply_filters()
        self.photo_view.scrollToTop()
        self.roster_view.scrollToTop()

    def set_active_roster(self, entries: list[RosterEntry], sort_by_class: bool = True):
        """设置完整有效名单；界面模型只显示筛选后的子集。"""
        self._active_entries = (
            sort_roster_by_class(entries) if sort_by_class else list(entries)
        )
        resolve_departments_from_roster(self._all_photos, self._active_entries)
        self._department_filter = None
        self._class_filter = None
        self._refresh_filter_options()
        self._apply_filters()
        self.roster_view.scrollToTop()

    def sort_roster_by_class_clicked(self):
        if not self._active_entries:
            return
        if not any(entry.class_no for entry in self._active_entries):
            QMessageBox.information(
                self,
                "没有班级号",
                "Excel 名单没有映射班级号列，无法按班级分块排序。\n"
                "重新导入名单时可在“班级号列”中选择对应列。",
            )
            return
        self._push_history()
        self._active_entries = sort_roster_by_class(self._active_entries)
        self._apply_filters()
        self._log_action(
            "sort_by_class",
            f"count={len(self._active_entries)} "
            f"dept={self._department_filter or '*'} class={self._class_filter or '*'}",
        )
        self.status_label.setText("已按班级号分块重排；同班内保持 Excel 顺序")

    def _full_index_of_uid(self, uid: str) -> int:
        for index, entry in enumerate(self._active_entries):
            if entry.uid == uid:
                return index
        return -1

    def clear_all_data(self):
        if self.exporting:
            return
        if not self._all_photos and not self._active_entries and not self.excluded:
            self.status_label.setText("当前没有已导入的照片或名单")
            return
        answer = QMessageBox.question(
            self,
            "清空导入数据",
            "清空当前导入的所有照片和名单？\n\n"
            "只清空程序中的队列，不会删除磁盘照片或 Excel 文件。\n"
            "清空后撤销/重做历史也会重置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._stop_thumbnails()
        self._all_photos = []
        self._active_entries = []
        self.excluded = []
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._department_filter = None
        self._class_filter = None
        self._pending_batch_key = None
        self.source_dir = None
        self.source_label.setText("尚未导入照片")
        self.source_label.setToolTip("")
        self.photo_model.set_photos([])
        self.roster_model.reset_entries([])
        self._refresh_filter_options()
        self._apply_filters()
        self.photo_view.clearSelection()
        self.roster_view.clearSelection()
        self.photo_view.scrollToTop()
        self.roster_view.scrollToTop()
        self._update_counts()
        self._update_pair_label()
        self._log_action("clear_all", "photos=0 roster=0")
        self.status_label.setText("已清空所有导入的照片和名单")

    # --------------------------------------------------------- photo import
    def import_photos(self):
        start_dir = self.settings.value("last_photo_dir", "H:\\")
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择照片根文件夹（会扫描学院/班级子文件夹）",
            str(start_dir),
        )
        if not folder:
            return
        source_dir = Path(folder)
        try:
            paths = [
                path
                for path in source_dir.rglob("*")
                if path.is_file() and is_image_file(path)
            ]
        except OSError as exc:
            QMessageBox.critical(self, "读取失败", f"无法读取文件夹：\n{exc}")
            return
        paths = natural_sort_paths(paths)
        if not paths:
            QMessageBox.warning(
                self,
                "没有照片",
                "所选文件夹及其子文件夹内没有 .jpg / .jpeg 文件。",
            )
            return

        if self._all_photos:
            answer = QMessageBox.question(
                self,
                "替换照片队列",
                "重新导入会替换当前照片队列，并清空当前选择。\n"
                "名单不会被删除，但需要重新核对位置。继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        photos: list[PhotoItem] = []
        skipped: list[str] = []
        group_count: set[tuple[str, str]] = set()
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                skipped.append(path.name)
                continue
            department, class_no = parse_photo_group(path, source_dir)
            major = parse_photo_major(path, source_dir, class_no)
            if class_no:
                group_count.add((department, class_no))
            photos.append(
                PhotoItem(
                    seq=0,
                    path=path,
                    name=path.name,
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    suffix=path.suffix or ".jpg",
                    department=department,
                    major=major,
                    class_no=class_no,
                )
            )

        self._stop_thumbnails()
        self.source_dir = source_dir
        self.set_active_photos(photos)
        self.source_label.setText(str(source_dir))
        self.source_label.setToolTip(str(source_dir))
        self.thumbs = ThumbnailManager(CACHE_DIR, self)
        self.thumbs.thumb_ready.connect(self._on_thumb_ready)
        self.thumbs.thumb_failed.connect(self._on_thumb_failed)
        self.photo_delegate.set_thumbs(self.thumbs)
        self.photo_view.viewport().update()
        self.settings.setValue("last_photo_dir", str(source_dir))
        self._log_action(
            "import_photos",
            f"count={len(photos)} groups={len(group_count)} "
            f"ungrouped={sum(1 for photo in photos if not photo.class_no)} "
            f"dir={source_dir} skipped={len(skipped)}",
        )
        ungrouped = sum(1 for photo in photos if not photo.class_no)
        self.status_label.setText(
            f"已导入 {len(photos)} 张照片，按班级分为 {len(group_count)} 个块"
            + (f"，{ungrouped} 张未识别班级" if ungrouped else "")
            + (f"，跳过 {len(skipped)} 个无法读取的文件" if skipped else "")
        )
        if skipped:
            QMessageBox.warning(
                self,
                "部分文件被跳过",
                "以下文件无法读取，已跳过：\n" + "\n".join(skipped[:20]),
            )

    def _stop_thumbnails(self):
        if self.thumbs is not None:
            self.thumbs.shutdown()
            self.thumbs.deleteLater()
            self.thumbs = None
        self.photo_delegate.set_thumbs(None)

    def _on_thumb_ready(self, key: str):
        index = self.photo_model.index_for_path(Path(key))
        if index.isValid():
            self.photo_model.dataChanged.emit(
                index, index, [Qt.ItemDataRole.DisplayRole]
            )

    def _on_thumb_failed(self, key: str):
        # 失败不弹窗，避免 4000 张里个别坏图打断操作；由占位图提示
        index = self.photo_model.index_for_path(Path(key))
        if index.isValid():
            self.photo_model.dataChanged.emit(
                index, index, [Qt.ItemDataRole.DisplayRole]
            )

    # --------------------------------------------------------- roster import
    def import_roster(self):
        start_dir = self.settings.value("last_roster_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Excel 名单",
            str(start_dir),
            "Excel 文件 (*.xlsx *.xlsm *.xls)",
        )
        if not path:
            return
        try:
            dialog = ExcelImportDialog(path, self)
        except Exception as exc:
            QMessageBox.critical(self, "读取失败", f"无法读取 Excel：\n{exc}")
            return
        if dialog.exec() != ExcelImportDialog.DialogCode.Accepted:
            return
        try:
            result = read_roster(
                path,
                dialog.selected_sheet,
                dialog.id_col if dialog.id_col is not None else -1,
                dialog.name_col,
                dialog.has_header,
                dialog.department_col,
                dialog.class_no_col,
                dialog.gender_col,
            )
        except Exception as exc:
            QMessageBox.critical(self, "读取失败", f"读取名单失败：\n{exc}")
            return

        if self.roster_model.rowCount() or self.excluded:
            answer = QMessageBox.question(
                self,
                "替换名单",
                "重新导入会替换当前有效名单和已剔除列表。\n"
                "可以用 Ctrl+Z 撤销这次替换。继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._push_history()
        self.excluded = []
        self.set_active_roster(result.entries)
        self.settings.setValue("last_roster_dir", str(Path(path).parent))
        self._log_action(
            "import_roster",
            f"count={len(result.entries)} file={path} sheet={result.sheet_name}",
        )
        has_class = any(entry.class_no for entry in self._active_entries)
        self.status_label.setText(
            f"已导入名单 {len(result.entries)} 人（工作表：{result.sheet_name}）"
            + ("，已按班级号分块" if has_class else "")
        )
        if result.warnings:
            text = "\n".join(result.warnings[:20])
            if len(result.warnings) > 20:
                text += f"\n… 另有 {len(result.warnings) - 20} 条提醒"
            QMessageBox.warning(self, "名单提醒", text)

    # --------------------------------------------------------- selection sync
    def _on_photo_current_changed(self, current: QModelIndex, previous: QModelIndex):
        if self._syncing or not current.isValid():
            return
        row = current.row()
        self._syncing = True
        try:
            if row < self.roster_model.rowCount():
                index = self.roster_model.index(row, 0)
                self.roster_view.setCurrentIndex(index)
                self.roster_view.scrollTo(
                    index, QAbstractItemView.ScrollHint.PositionAtCenter
                )
            else:
                self.roster_view.clearSelection()
        finally:
            self._syncing = False
        self._update_pair_label()

    def _on_roster_current_changed(self, current: QModelIndex, previous: QModelIndex):
        if self._syncing or not current.isValid():
            return
        row = current.row()
        self._syncing = True
        try:
            if row < self.photo_model.rowCount():
                index = self.photo_model.index(row, 0)
                self.photo_view.setCurrentIndex(index)
                self.photo_view.scrollTo(
                    index, QAbstractItemView.ScrollHint.PositionAtCenter
                )
            else:
                self.photo_view.clearSelection()
        finally:
            self._syncing = False
        self._update_pair_label()

    def _update_pair_label(self):
        photo_index = self.photo_view.currentIndex()
        roster_index = self.roster_view.currentIndex()
        if photo_index.isValid() and roster_index.isValid():
            photo = self.photo_model.photo_at(photo_index.row())
            entry = self.roster_model.entry_at(roster_index.row())
            if photo is not None and entry is not None:
                self.pair_label.setText(
                    f"照片 #{photo_index.row() + 1}  {photo.name}   ↔   "
                    f"名单 #{roster_index.row() + 1}  "
                    f"{entry.student_no or '（空学号）'}  {entry.name or ''}"
                )
                return
        if self.photo_model.rowCount() and self.roster_model.rowCount():
            self.pair_label.setText("点击左侧照片或右侧名单，查看对应位置")
        else:
            self.pair_label.setText("请先导入照片和名单")

    # ------------------------------------------------------- context menus
    def _preview_photo(self, row: int):
        photo = self.photo_model.photo_at(row)
        if photo is None:
            return
        if self._preview_dialog is not None:
            self._preview_dialog.close()
        try:
            dialog = PhotoPreviewDialog(photo.path, photo.name, self)
            dialog.setModal(False)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.destroyed.connect(
                lambda _obj=None, value=dialog: self._on_preview_destroyed(
                    value
                )
            )
            self._preview_dialog = dialog
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception as exc:
            QMessageBox.critical(self, "预览失败", f"无法打开照片预览：\n{exc}")

    def _on_preview_destroyed(self, dialog):
        if self._preview_dialog is not dialog:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._preview_dialog = None

    def eventFilter(self, obj, event):  # noqa: N802
        # 班级框按钮是独立子控件，滚轮事件不会自动冒泡到 QScrollArea，
        # 这里在按钮上拦截并驱动班级条的横向滚动。
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(obj, QWidget)
            and self.class_frames_widget.isAncestorOf(obj)
        ):
            pixel = event.pixelDelta()
            delta = (
                pixel.y() if not pixel.isNull() else event.angleDelta().y()
            )
            if delta:
                bar = self.class_frames_scroll.horizontalScrollBar()
                bar.setValue(bar.value() - delta)
                event.accept()
                return True

        # 非模态预览：点击主程序窗口内、预览窗口外的任意位置时关闭预览。
        if (
            self._preview_dialog is not None
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            target = obj if isinstance(obj, QWidget) else None
            if target is not None and (
                target is self._preview_dialog
                or self._preview_dialog.isAncestorOf(target)
            ):
                pass
            else:
                self._preview_dialog.close()
                return True
        return super().eventFilter(obj, event)

    def _on_photo_context_menu(self, position: QPoint):
        if self.exporting:
            return
        index = self.photo_view.indexAt(position)
        if not index.isValid():
            return
        self.photo_view.setCurrentIndex(index)
        photo = self.photo_model.photo_at(index.row())
        if photo is None:
            return
        menu = QMenu(self)
        delete_action = menu.addAction("删除照片（仅从队列移除）")
        delete_action.setToolTip("立即从队列移除，不删除源文件；可按 Ctrl+Z 撤销")
        chosen = menu.exec(self.photo_view.viewport().mapToGlobal(position))
        if chosen == delete_action:
            self.delete_photo_at(index.row())

    def delete_photo_at(self, row: int):
        if self.exporting:
            return
        photo = self.photo_model.photo_at(row)
        if photo is None:
            return
        scroll_value = self.photo_view.verticalScrollBar().value()

        self._push_history()
        removed = False
        for index, value in enumerate(self._all_photos):
            if value is photo:
                self._all_photos.pop(index)
                removed = True
                break
        if not removed:
            self._undo_stack.pop()
            self._update_counts()
            return
        for seq, value in enumerate(self._all_photos, start=1):
            value.seq = seq
        resolve_departments_from_roster(self._all_photos, self._active_entries)
        self._refresh_filter_options()
        self._apply_filters()
        # 模型 reset 后 Qt 往往回到顶部；恢复删除前的垂直滚动位置。
        self.photo_view.verticalScrollBar().setValue(scroll_value)
        QTimer.singleShot(
            0,
            lambda value=scroll_value: self.photo_view.verticalScrollBar().setValue(
                value
            ),
        )
        self._log_action(
            "delete_photo",
            f"name={photo.name} path={photo.path} class={photo.class_no}",
        )
        self.status_label.setText(
            f"已从照片队列移除：{photo.name}（源文件未删除）"
        )

    def _on_roster_context_menu(self, position: QPoint):
        if self.exporting:
            return
        index = self.roster_view.indexAt(position)
        if index.isValid():
            selection = self.roster_view.selectionModel()
            if not selection.isSelected(index):
                self.roster_view.clearSelection()
                self.roster_view.setCurrentIndex(index)
        menu = QMenu(self)
        add_action = menu.addAction("添加学生")
        delete_action = None
        start_action = None
        end_action = None
        if index.isValid():
            menu.addSeparator()
            delete_action = menu.addAction("删除未到场")
            menu.addSeparator()
            if self._class_filter:
                start_text = "移到本班开头"
                end_text = "移到本班末尾"
            elif self._filter_active():
                start_text = "移到筛选结果开头"
                end_text = "移到筛选结果末尾"
            else:
                start_text = "移到名单开头"
                end_text = "移到名单末尾"
            start_action = menu.addAction(start_text)
            end_action = menu.addAction(end_text)
        chosen = menu.exec(self.roster_view.viewport().mapToGlobal(position))
        if chosen == add_action:
            self.add_roster_student()
        elif delete_action is not None and chosen == delete_action:
            self.delete_selected_roster()
        elif start_action is not None and chosen == start_action:
            self.move_selected_roster_to_top()
        elif end_action is not None and chosen == end_action:
            self.move_selected_roster_to_end()

    def add_roster_student(self):
        if self.exporting:
            return
        dialog = AddRosterDialog(self)
        if dialog.exec() != AddRosterDialog.DialogCode.Accepted:
            return

        student_no = normalize_student_no_input(dialog.student_no)
        if not student_no:
            return
        existing_ids = {
            entry.student_no for entry in self._active_entries
        } | {item.entry.student_no for item in self.excluded}
        if student_no in existing_ids:
            QMessageBox.warning(
                self,
                "学号重复",
                f"学号 {student_no} 已经在当前名单或已剔除列表中。",
            )
            return

        department = self._department_filter or ""
        class_no = self._class_filter or ""
        if class_no and not department:
            department, _major, _class_no = self._selected_class_identity()

        entry = RosterEntry(
            student_no=student_no,
            name=dialog.name.strip(),
            source_row=0,
            department=department,
            class_no=class_no,
            gender=dialog.gender,
        )
        self._push_history()
        self._active_entries.append(entry)
        if class_no:
            old_key = self._export_mark_key(department, class_no)
            if old_key in self._exported_classes:
                self._exported_classes.discard(old_key)
                self._save_exported_classes()
        self._refresh_filter_options()
        self._apply_filters()
        for row, value in enumerate(self.roster_model.entries()):
            if value.uid == entry.uid:
                index = self.roster_model.index(row, 0)
                self.roster_view.setCurrentIndex(index)
                self.roster_view.scrollTo(
                    index, QAbstractItemView.ScrollHint.PositionAtCenter
                )
                break
        self._log_action(
            "add_roster",
            f"id={student_no} dept={department} class={class_no}",
        )
        self.status_label.setText(f"已添加学生：{student_no}")

    def move_selected_roster_to_top(self):
        if self.exporting:
            return
        selection = self.roster_view.selectionModel()
        rows = sorted({index.row() for index in selection.selectedRows()})
        if not rows:
            current = self.roster_view.currentIndex()
            if current.isValid():
                rows = [current.row()]
        if not rows:
            return

        count = len(rows)
        if rows == list(range(count)):
            self.status_label.setText("选中项已经在开头")
            return

        entries = self.roster_model.entries()
        selected_set = set(rows)
        selected_entries = [entries[row] for row in rows]
        remaining = [
            entry for row, entry in enumerate(entries) if row not in selected_set
        ]
        new_entries = selected_entries + remaining

        self._push_history()
        self.roster_model.reset_entries(new_entries)
        if self._filter_active():
            self._sync_active_order_from_filtered()
        else:
            self._active_entries = new_entries

        first_index = self.roster_model.index(0, 0)
        last_index = self.roster_model.index(count - 1, 0)
        self.roster_view.clearSelection()
        self.roster_view.setCurrentIndex(first_index)
        self.roster_view.selectionModel().select(
            QItemSelection(first_index, last_index),
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
        self.roster_view.scrollTo(
            first_index, QAbstractItemView.ScrollHint.PositionAtCenter
        )
        self._update_counts()
        self._update_pair_label()
        self._log_action(
            "move_roster_start",
            f"count={count} ids="
            + ",".join(entry.student_no for entry in selected_entries),
        )
        self.status_label.setText(
            f"已移动 {count} 人到开头，保持选中顺序"
            if count > 1
            else "已移到名单开头"
        )

    def move_selected_roster_to_end(self):
        if self.exporting:
            return
        selection = self.roster_view.selectionModel()
        rows = sorted({index.row() for index in selection.selectedRows()})
        if not rows:
            current = self.roster_view.currentIndex()
            if current.isValid():
                rows = [current.row()]
        if not rows:
            return

        total = self.roster_model.rowCount()
        count = len(rows)
        if rows == list(range(total - count, total)):
            self.status_label.setText("选中项已经在末尾")
            return

        entries = self.roster_model.entries()
        selected_set = set(rows)
        selected_entries = [entries[row] for row in rows]
        remaining = [
            entry for row, entry in enumerate(entries) if row not in selected_set
        ]
        new_entries = remaining + selected_entries

        self._push_history()
        self.roster_model.reset_entries(new_entries)
        if self._filter_active():
            self._sync_active_order_from_filtered()
        else:
            self._active_entries = new_entries

        first_row = total - count
        last_row = total - 1
        first_index = self.roster_model.index(first_row, 0)
        last_index = self.roster_model.index(last_row, 0)
        self.roster_view.clearSelection()
        self.roster_view.setCurrentIndex(first_index)
        self.roster_view.selectionModel().select(
            QItemSelection(first_index, last_index),
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
        self.roster_view.scrollTo(
            first_index, QAbstractItemView.ScrollHint.PositionAtCenter
        )
        self._update_counts()
        self._update_pair_label()
        self._log_action(
            "move_roster_end",
            f"count={count} ids="
            + ",".join(entry.student_no for entry in selected_entries),
        )
        self.status_label.setText(
            f"已移动 {count} 人到末尾，保持选中顺序"
            if count > 1
            else "已移到名单末尾"
        )

    def move_roster_entry_to_end(self, row: int):
        if self.exporting:
            return
        if row < 0 or row >= self.roster_model.rowCount():
            return
        target = self.roster_model.rowCount()
        if row == target - 1:
            self.status_label.setText("该学生已经在末尾")
            return
        self._push_history()
        if not self.roster_model.move_row(row, target):
            self._undo_stack.pop()
            self._update_counts()
            return
        if self._filter_active():
            self._sync_active_order_from_filtered()
        else:
            self._active_entries = self.roster_model.entries()
        new_row = self.roster_model.rowCount() - 1
        new_index = self.roster_model.index(new_row, 0)
        self.roster_view.setCurrentIndex(new_index)
        self.roster_view.scrollTo(
            new_index, QAbstractItemView.ScrollHint.PositionAtCenter
        )
        self._update_counts()
        self._update_pair_label()
        entry = self.roster_model.entry_at(new_row)
        self._log_action(
            "move_roster_end",
            f"id={entry.student_no if entry else ''}",
        )
        self.status_label.setText("已移到名单末尾")

    # ------------------------------------------------------------- history
    def _snapshot(self):
        return (
            list(self._active_entries),
            list(self.excluded),
            self._department_filter,
            self._class_filter,
            list(self._all_photos),
        )

    def _push_history(self):
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_counts()

    def _restore_snapshot(self, snapshot):
        (
            entries,
            excluded,
            department_filter,
            class_filter,
            photos,
        ) = snapshot
        self._active_entries = list(entries)
        self.excluded = list(excluded)
        self._department_filter = department_filter
        self._class_filter = class_filter
        self._all_photos = list(photos)
        for seq, photo in enumerate(self._all_photos, start=1):
            photo.seq = seq
        resolve_departments_from_roster(self._all_photos, self._active_entries)
        self._refresh_filter_options()
        self._apply_filters()
        self.roster_view.clearSelection()
        self.photo_view.clearSelection()
        self._update_counts()
        self._update_pair_label()

    def undo(self):
        if not self._undo_stack or self.exporting:
            return
        current = self._snapshot()
        snapshot = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_snapshot(snapshot)
        self._log_action("undo", "roster")
        self.status_label.setText("已撤销上一次名单操作")

    def redo(self):
        if not self._redo_stack or self.exporting:
            return
        current = self._snapshot()
        snapshot = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_snapshot(snapshot)
        self._log_action("redo", "roster")
        self.status_label.setText("已重做名单操作")

    # -------------------------------------------------------- roster editing
    def _sync_active_order_from_filtered(self):
        """把当前班级内的拖动顺序写回完整名单的对应位置。"""
        filtered = self.roster_model.entries()
        positions = [
            index
            for index, entry in enumerate(self._active_entries)
            if self._roster_matches_filter(entry)
        ]
        if len(positions) != len(filtered):
            return
        for position, entry in zip(positions, filtered):
            self._active_entries[position] = entry

    def _on_move_roster(self, source: int, target: int):
        if self.exporting:
            return
        if self._filter_active() and not self._class_filter:
            self.status_label.setText(
                "当前只按院系筛选；请选到具体班级后再拖动调整顺序。"
            )
            return
        if target in (source, source + 1):
            return
        self._push_history()
        if not self.roster_model.move_row(source, target):
            self._undo_stack.pop()
            self._update_counts()
            return
        if self._class_filter:
            self._sync_active_order_from_filtered()
        else:
            self._active_entries = self.roster_model.entries()
        new_row = target if target < source else target - 1
        new_row = max(0, min(new_row, self.roster_model.rowCount() - 1))
        index = self.roster_model.index(new_row, 0)
        self.roster_view.setCurrentIndex(index)
        self.roster_view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._update_counts()
        self._update_pair_label()
        entry = self.roster_model.entry_at(new_row)
        detail = f"from={source + 1} to={new_row + 1}"
        if entry is not None:
            detail += f" id={entry.student_no}"
        self._log_action("move_roster", detail)
        self.status_label.setText("已调整名单顺序")

    def _move_current(self, delta: int):
        index = self.roster_view.currentIndex()
        if not index.isValid():
            return
        source = index.row()
        target = source - 1 if delta < 0 else source + 2
        self._on_move_roster(source, target)

    def delete_selected_roster(self):
        if self.exporting:
            return
        selection = self.roster_view.selectionModel()
        rows = sorted({index.row() for index in selection.selectedRows()}, reverse=True)
        if not rows:
            current = self.roster_view.currentIndex()
            if current.isValid():
                rows = [current.row()]
        if not rows:
            QMessageBox.information(self, "没有选择", "请先在右侧名单里选择要删除的学生。")
            return
        entries = []
        for row in rows:
            entry = self.roster_model.entry_at(row)
            if entry is None:
                continue
            full_index = self._full_index_of_uid(entry.uid)
            if full_index >= 0:
                entries.append((row, entry, full_index))
        if not entries:
            return
        self._push_history()
        removed: list[str] = []
        for row, _entry, _full_index in sorted(entries, reverse=True):
            self.roster_model.remove_row(row)
        for _row, entry, full_index in entries:
            index = self._full_index_of_uid(entry.uid)
            if index >= 0:
                self._active_entries.pop(index)
            self.excluded.append(
                ExcludedEntry(entry=entry, origin_index=full_index)
            )
            removed.append(f"{entry.student_no or '（空学号）'} {entry.name or ''}".strip())
        self.roster_view.clearSelection()
        self._refresh_filter_options()
        self._apply_filters()
        self._log_action("delete_roster", "ids=" + ",".join(removed))
        self.status_label.setText(f"已剔除 {len(removed)} 人，可从“恢复未到场”找回")

    def restore_excluded(self):
        if self.exporting or not self.excluded:
            return
        dialog = ExcludedDialog(self.excluded, self)
        if dialog.exec() != ExcludedDialog.DialogCode.Accepted:
            return
        selected_indices = dialog.selected_indices
        if not selected_indices:
            return
        self._push_history()
        selected = [self.excluded[index] for index in selected_indices]
        for index in sorted(selected_indices, reverse=True):
            self.excluded.pop(index)
        for item in sorted(selected, key=lambda value: value.origin_index):
            row = max(0, min(item.origin_index, len(self._active_entries)))
            self._active_entries.insert(row, item.entry)
        self._refresh_filter_options()
        self._apply_filters()
        self._log_action(
            "restore_roster",
            "ids=" + ",".join(item.entry.student_no for item in selected),
        )
        self.status_label.setText(f"已恢复 {len(selected)} 人到名单")

    # ------------------------------------------------------------- export
    def _save_batch_export_dir(self):
        text = self.export_path_edit.text().strip()
        if not text:
            return
        self.batch_export_dir = Path(text)
        self.settings.setValue("batch_export_dir", str(self.batch_export_dir))

    def _choose_batch_export_dir(self):
        start_dir = str(
            self.batch_export_dir
            if self.batch_export_dir
            else OUTPUT_ROOT
        )
        folder = QFileDialog.getExistingDirectory(
            self, "选择导出根目录", start_dir
        )
        if not folder:
            return
        self.batch_export_dir = Path(folder)
        self.export_path_edit.setText(str(self.batch_export_dir))
        self._save_batch_export_dir()
        self.status_label.setText(f"导出路径已设为：{self.batch_export_dir}")

    def _open_export_folder(self):
        text = self.export_path_edit.text().strip()
        if not text:
            QMessageBox.information(
                self, "没有导出路径", "请先填写或选择导出路径。"
            )
            return
        base_dir = Path(text).expanduser()
        if not base_dir.is_dir():
            QMessageBox.information(
                self,
                "导出文件夹不存在",
                f"当前导出路径还不存在：\n{base_dir}\n\n"
                "请先执行一次导出，或重新选择目录。",
            )
            return

        target_dir = base_dir
        if self._class_filter:
            class_dir = self._selected_class_output_dir(base_dir)
            if class_dir.is_dir():
                target_dir = class_dir

        if not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(target_dir.resolve()))
        ):
            QMessageBox.warning(
                self,
                "打开失败",
                f"无法打开文件夹：\n{target_dir}",
            )
            return
        self.status_label.setText(f"已打开导出文件夹：{target_dir}")

    def _selected_class_major(self) -> str:
        if not self._class_filter:
            return ""
        counts: dict[str, int] = {}
        for photo in self._all_photos:
            if normalize_class(photo.class_no) != self._class_filter:
                continue
            if (
                self._department_filter
                and photo.department != self._department_filter
            ):
                continue
            if photo.major:
                counts[photo.major] = counts.get(photo.major, 0) + 1
        if not counts:
            return ""
        return max(counts, key=lambda value: (counts[value], value.casefold()))

    @staticmethod
    def _export_mark_key(department: str, class_no: str) -> str:
        return f"{department}|{normalize_class(class_no)}"

    def _save_exported_classes(self):
        self.settings.setValue(
            "exported_classes",
            json.dumps(sorted(self._exported_classes), ensure_ascii=False),
        )

    @staticmethod
    def _major_fallback(department: str) -> str:
        text = (department or "").strip()
        for suffix in ("工程学院", "学院", "学部", "系"):
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                break
        return text or "未填专业"

    def _selected_class_identity(self) -> tuple[str, str, str]:
        department = self._department_filter or ""
        if not department:
            for entry in self.roster_model.entries():
                if normalize_class(entry.class_no) == self._class_filter:
                    department = entry.department
                    break
        if not department:
            for photo in self.photo_model.photos():
                if normalize_class(photo.class_no) == self._class_filter:
                    department = photo.department
                    break
        department = department or "未填学院"
        major = self._selected_class_major() or self._major_fallback(department)
        class_no = self._class_filter or "未填班级"
        return department, major, class_no

    def _selected_class_output_dir(
        self,
        base_dir: Path,
        needs_review: bool = False,
        suffix_text: str = "",
    ) -> Path:
        department, _major, class_no = self._selected_class_identity()
        suffix = " 需核对" if needs_review else ""
        if suffix_text:
            suffix = " " + suffix_text
        folder_name = class_no + suffix
        return (
            base_dir
            / sanitize_filename(department)
            / sanitize_filename(folder_name)
        )

    def export_selected_class(
        self, needs_review: bool = False, suffix_text: str = ""
    ):
        """修改完当前班级后，按 导出路径/学院/班级 立即导出。

        needs_review=True 时追加“ 需核对”；suffix_text 可指定其他后缀，
        例如“有闭眼”。两者都执行完整导出流程。
        """
        if self.exporting:
            return
        if not self._class_filter:
            QMessageBox.information(
                self,
                "先选择一个班级",
                "请先在“班级号”下拉框或上方班级框中选择一个班级，"
                "调整好名单顺序后，再点“修改并导出本班”。",
            )
            return
        if not self.source_dir:
            QMessageBox.warning(self, "缺少照片", "请先导入照片。")
            return
        if not self.photo_model.rowCount() or not self.roster_model.rowCount():
            QMessageBox.warning(
                self, "缺少数据", "当前班级没有照片或名单，不能导出。"
            )
            return

        self._update_counts()
        if not self.export_action.isEnabled():
            QMessageBox.warning(
                self,
                "还不能导出",
                f"当前班级照片 {self.photo_model.rowCount()} 张，"
                f"名单 {self.roster_model.rowCount()} 人。\n"
                "两边数量必须一致，且学号不能为空或重复。\n"
                "请先删除未到场学生或补齐照片。",
            )
            return

        base_text = self.export_path_edit.text().strip()
        if not base_text:
            QMessageBox.warning(
                self, "缺少导出路径", "请先在顶部填写或选择导出路径。"
            )
            return
        base_dir = Path(base_text)
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "导出路径不可用", str(exc))
            return
        self.batch_export_dir = base_dir
        self._save_batch_export_dir()

        department, _major, class_no = self._selected_class_identity()
        target_dir = self._selected_class_output_dir(
            base_dir,
            needs_review=needs_review,
            suffix_text=suffix_text,
        )

        photos = self.photo_model.photos()
        roster = self.roster_model.entries()
        try:
            preflight = build_export_items(
                photos, roster, self.source_dir, target_dir
            )
        except Exception as exc:
            QMessageBox.critical(self, "预检失败", str(exc))
            return
        if preflight.errors:
            text = "\n".join(preflight.errors[:20])
            if len(preflight.errors) > 20:
                text += f"\n… 另有 {len(preflight.errors) - 20} 条错误"
            QMessageBox.critical(self, "本班导出被阻止", text)
            return

        self._batch_export_mode = True
        self._pending_batch_key = self._export_mark_key(department, class_no)
        status_suffix = ""
        if needs_review:
            status_suffix = "（需核对）"
        elif suffix_text:
            status_suffix = f"（{suffix_text}）"
        self.status_label.setText(
            f"正在导出 {department} / {class_no}{status_suffix}…"
        )
        self._start_export(preflight.items, target_dir)

    def resume_last_export(self):
        """继续写入上一次的输出目录，利用已存在且大小一致的文件断点续跑。"""
        if self.exporting:
            return
        if self.last_output_dir is None or not self.last_output_dir.is_dir():
            QMessageBox.information(
                self,
                "没有可续跑的目录",
                "还没有上一次导出目录。请先执行一次导出；中断后可用本功能继续。",
            )
            return
        if not self.source_dir:
            QMessageBox.warning(self, "缺少照片", "请先重新导入照片。")
            return
        if not self.roster_model.rowCount():
            QMessageBox.warning(self, "缺少名单", "请先重新导入名单。")
            return
        self._update_counts()
        if not self.export_action.isEnabled():
            QMessageBox.warning(
                self,
                "还不能续跑",
                "照片数和有效名单数必须一致，且学号不能为空或重复。",
            )
            return

        output_dir = self.last_output_dir
        photos = self.photo_model.photos()
        roster = self.roster_model.entries()
        try:
            preflight = build_export_items(
                photos, roster, self.source_dir, output_dir
            )
        except Exception as exc:
            QMessageBox.critical(self, "预检失败", str(exc))
            return
        if preflight.errors:
            text = "\n".join(preflight.errors[:20])
            if len(preflight.errors) > 20:
                text += f"\n… 另有 {len(preflight.errors) - 20} 条错误"
            QMessageBox.critical(self, "续跑被阻止", text)
            return

        warning_text = ""
        if preflight.warnings:
            warning_text = "\n\n" + "\n".join(preflight.warnings[:10])
        answer = QMessageBox.question(
            self,
            "继续上次导出",
            f"继续写入上次输出目录：\n{output_dir}\n\n"
            f"计划 {len(preflight.items)} 张；已存在且大小一致 "
            f"{preflight.existing_count} 张会跳过，剩余需要写入约 "
            f"{format_size(preflight.required_bytes)}。\n"
            "源照片不会被修改。"
            f"{warning_text}\n\n继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.output_dir = output_dir
        self._batch_export_mode = False
        self._pending_batch_key = None
        self._start_export(preflight.items, output_dir)

    def export_to_new_folder(self):
        if self.exporting:
            return
        if not self.source_dir:
            QMessageBox.warning(self, "缺少照片", "请先导入照片。")
            return
        if not self.roster_model.rowCount():
            QMessageBox.warning(self, "缺少名单", "请先导入名单。")
            return
        self._update_counts()
        if not self.export_action.isEnabled():
            QMessageBox.warning(
                self,
                "还不能导出",
                "照片数和有效名单数必须一致，且学号不能为空或重复。",
            )
            return

        start_parent = self.settings.value("last_output_parent", str(OUTPUT_ROOT))
        parent = QFileDialog.getExistingDirectory(
            self, "选择输出父目录（工具会在其中新建本次导出文件夹）", str(start_parent)
        )
        if not parent:
            return
        parent_path = Path(parent)
        try:
            parent_path.resolve().relative_to(self.source_dir.resolve())
            QMessageBox.warning(
                self,
                "输出目录不合适",
                "输出父目录不能放在照片源目录里面。请选择源目录之外的文件夹。",
            )
            return
        except ValueError:
            pass
        except OSError:
            pass

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = parent_path / f"导出_{timestamp}"
        suffix = 2
        while output_dir.exists():
            output_dir = parent_path / f"导出_{timestamp}_{suffix}"
            suffix += 1
        try:
            output_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            QMessageBox.critical(self, "无法创建输出目录", str(exc))
            return

        photos = self.photo_model.photos()
        roster = self.roster_model.entries()
        try:
            preflight = build_export_items(
                photos, roster, self.source_dir, output_dir
            )
        except Exception as exc:
            QMessageBox.critical(self, "预检失败", str(exc))
            return

        if preflight.errors:
            text = "\n".join(preflight.errors[:20])
            if len(preflight.errors) > 20:
                text += f"\n… 另有 {len(preflight.errors) - 20} 条错误"
            QMessageBox.critical(self, "导出被阻止", text)
            try:
                output_dir.rmdir()
            except OSError:
                pass
            return

        total_text = format_size(preflight.total_bytes)
        required_text = format_size(preflight.required_bytes)
        warning_text = ""
        if preflight.warnings:
            warning_text = (
                "\n\n提醒：\n"
                + "\n".join(preflight.warnings[:10])
                + (
                    f"\n… 另有 {len(preflight.warnings) - 10} 条"
                    if len(preflight.warnings) > 10
                    else ""
                )
            )
        answer = QMessageBox.question(
            self,
            "确认导出",
            f"即将复制 {len(preflight.items)} 张照片到：\n{output_dir}\n\n"
            f"总大小约 {total_text}，本次实际需要写入约 {required_text}。\n"
            f"文件名使用名单中的学号，源照片不会被修改。{warning_text}\n\n"
            "继续导出？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            try:
                output_dir.rmdir()
            except OSError:
                pass
            return

        self.settings.setValue("last_output_parent", str(parent_path))
        self.output_dir = output_dir
        self._batch_export_mode = False
        self._pending_batch_key = None
        self._start_export(preflight.items, output_dir)

    def _start_export(self, items, output_dir: Path):
        self.output_dir = output_dir
        self.last_output_dir = output_dir
        self.settings.setValue("last_export_dir", str(output_dir))
        self.exporting = True
        self._update_counts()
        self.progress.setRange(0, len(items))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.status_label.setText("正在导出…")
        run_id = run_id_now()
        log_dir = LOG_DIR / "export_logs" / run_id
        self.worker = ExportWorker(
            items,
            self.source_dir,
            output_dir,
            run_id,
            parent=self,
            log_dir=log_dir,
        )
        self.worker.progress.connect(self._on_export_progress)
        self.worker.completed.connect(self._on_export_completed)
        self.worker.finished.connect(self._on_export_finished)
        self.worker.start()
        self._log_action(
            "export_start",
            f"count={len(items)} output={output_dir} run_id={run_id}",
        )

    def _on_export_progress(self, done: int, total: int, name: str, status: str):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        status_text = {
            "ok": "已完成",
            "skipped_existing": "已存在，跳过",
            "error": "失败",
        }.get(status, status)
        self.status_label.setText(f"导出 {done}/{total}：{name}（{status_text}）")

    def _on_export_completed(self, summary: dict):
        if summary.get("summary_file"):
            self.last_summary_path = Path(summary["summary_file"])
        self._update_counts()
        if summary.get("fatal_error"):
            QMessageBox.critical(
                self, "导出失败", f"导出过程发生错误：\n{summary['fatal_error']}"
            )
        else:
            total = summary.get("photo_count", 0)
            ok = summary.get("ok_count", 0)
            skipped = summary.get("skipped_count", 0)
            errors = summary.get("error_count", 0)
            canceled = summary.get("canceled", False)
            output = summary.get("output_dir", "")
            message = (
                f"总数：{total}\n成功：{ok}\n已存在跳过：{skipped}\n失败：{errors}\n"
                f"输出目录：{output}"
            )
            if canceled:
                message += "\n\n本次导出被取消，已完成的部分保留在输出目录。"
            if errors:
                message += "\n\n失败明细请查看输出目录中的 rename_log CSV。"
            self._log_action(
                "export_done",
                f"ok={ok} skipped={skipped} errors={errors} canceled={canceled} "
                f"batch={self._batch_export_mode}",
            )
            if self._batch_export_mode:
                advance = bool(
                    self._pending_batch_key
                    and not canceled
                    and errors == 0
                )
                if advance:
                    self._exported_classes.add(self._pending_batch_key)
                    self._save_exported_classes()
                    self._refresh_filter_options()
                self.status_label.setText(
                    f"本班导出完成：成功 {ok}，已存在跳过 {skipped}，失败 {errors}\n"
                    f"{output}"
                )
                self._pending_batch_key = None
                self._advance_after_export = advance
            else:
                QMessageBox.information(self, "导出完成", message)
                self.status_label.setText("导出结束")
        if self._batch_export_mode and summary.get("fatal_error"):
            self.status_label.setText("本班导出失败，请检查输出目录日志")
        elif summary.get("fatal_error"):
            self.status_label.setText("导出结束")

    def _on_export_finished(self):
        advance = self._advance_after_export
        self._advance_after_export = False
        self.exporting = False
        self._batch_export_mode = False
        self._pending_batch_key = None
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self._update_counts()
        if advance:
            QTimer.singleShot(0, self._select_next_class_after_export)

    def cancel_export(self):
        if self.worker is not None and self.exporting:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status_label.setText("正在取消导出…")

    def undo_last_export(self):
        if self.exporting:
            return
        summary_path = self.last_summary_path
        if summary_path is None or not summary_path.is_file():
            log_root = LOG_DIR / "export_logs"
            start_dir = str(log_root if log_root.is_dir() else OUTPUT_ROOT)
            summary_path_str, _ = QFileDialog.getOpenFileName(
                self,
                "选择导出汇总 JSON",
                start_dir,
                "JSON 文件 (*.json)",
            )
            if not summary_path_str:
                return
            summary_path = Path(summary_path_str)
        answer = QMessageBox.question(
            self,
            "确认撤销导出",
            "将按日志删除本次导出中成功复制的输出文件。\n"
            "照片源目录不会被修改；大小不一致或日志缺失的文件会跳过。\n\n"
            "继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = undo_export(summary_path)
        except Exception as exc:
            QMessageBox.critical(self, "撤销失败", str(exc))
            return
        if not result.get("ok"):
            QMessageBox.critical(self, "撤销失败", result.get("message", "未知错误"))
            return
        self.last_summary_path = None
        self._update_counts()
        self._log_action(
            "undo_export",
            f"deleted={result.get('deleted', 0)} failed={result.get('failed', 0)} "
            f"summary={summary_path}",
        )
        QMessageBox.information(
            self,
            "撤销完成",
            f"已删除：{result.get('deleted', 0)} 个\n"
            f"已不存在：{result.get('missing', 0)} 个\n"
            f"大小不一致跳过：{result.get('mismatched', 0)} 个\n"
            f"删除失败：{result.get('failed', 0)} 个\n\n"
            f"撤销日志：{result.get('undo_log', '')}",
        )
        self.status_label.setText("已按日志撤销本次导出")

    # ------------------------------------------------------------- logging
    def _log_action(self, action: str, detail: str):
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "detail": detail,
        }
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_DIR / "actions.log", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _about(self):
        QMessageBox.about(
            self,
            "关于照片名单对齐工具",
            f"照片名单对齐工具 v{APP_VERSION}\n\n"
            "照片按路径中的学院/班级分块并固定顺序；班级框会同步筛选照片和名单。\n"
            "选班级调整后可用“修改并导出本班”，按 学院/班级 输出。\n"
            "第 N 张照片 ↔ 当前名单第 N 条，导出时用学号命名。\n\n"
            "源照片只读；导出到新文件夹；支持 CSV 日志和按日志撤销。",
        )


def main():
    QApplication.setApplicationName("PhotoRosterTool")
    QApplication.setOrganizationName("PhotoRosterTool")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI")
    font.setPointSize(9)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
