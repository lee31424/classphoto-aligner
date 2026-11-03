"""本地冒烟测试：不依赖真实名单，使用合成照片/Excel。"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from PySide6.QtCore import QEventLoop, QItemSelectionModel, QSize, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QPushButton

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from delegates import PhotoDelegate  # noqa: E402
from excel_io import (  # noqa: E402
    detect_columns,
    detect_gender_column,
    detect_group_columns,
    preview_sheet,
    read_roster,
)
from exporter import ExportWorker, build_export_items, undo_export  # noqa: E402
from grouping import parse_photo_group, parse_photo_major  # noqa: E402
from main import CACHE_DIR, MainWindow  # noqa: E402
from models import (  # noqa: E402
    PhotoItem,
    PhotoModel,
    RosterEntry,
    RosterModel,
    sort_roster_by_class,
)
from thumbnails import ThumbnailManager  # noqa: E402
from utils import natural_sort_paths, student_no_to_text  # noqa: E402


TEST_ROOT = APP_DIR.parent / "testdata"


def make_test_data():
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    photos_dir = TEST_ROOT / "photos"
    photos_dir.mkdir(parents=True)
    for number in range(1, 13):
        image = QImage(240, 320, QImage.Format.Format_RGB32)
        image.fill(QColor(40 + number * 10, 80, 160))
        painter = QPainter(image)
        painter.setPen(QColor("white"))
        painter.drawText(20, 40, f"IMG {number}")
        painter.end()
        path = photos_dir / f"IMG_{number}.jpg"
        assert image.save(str(path), "JPEG", 90), path

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "名单"
    sheet.append(["班级", "学号", "姓名"])
    names = ["张三", "李四", "王五", "赵六", "钱七", "孙八", "周九", "吴十", "郑一", "冯二", "陈三", "褚四"]
    # 故意不按学号升序，验证保留 Excel 原顺序
    ids = [2023003, 2023001, 2023002, 2023012, 2023004, 2023005, 2023006, 2023007, 2023008, 2023009, 2023010, 2023011]
    for index, (student_no, name) in enumerate(zip(ids, names), start=2):
        sheet.cell(index, 1, "一班")
        sheet.cell(index, 2, student_no)
        sheet.cell(index, 3, name)
    workbook.save(TEST_ROOT / "roster.xlsx")
    return photos_dir, TEST_ROOT / "roster.xlsx", ids, names


def test_utils_and_excel(roster_path: Path, ids: list[int]):
    assert student_no_to_text(2023001) == "2023001"
    assert student_no_to_text(2023001.0) == "2023001"
    assert student_no_to_text("00123") == "00123"
    assert student_no_to_text(123, "00000") == "00123"
    try:
        student_no_to_text(1.5)
    except ValueError:
        pass
    else:
        raise AssertionError("小数应被拒绝")

    preview = preview_sheet(roster_path, "名单", True)
    assert preview.headers[:3] == ["班级", "学号", "姓名"]
    assert detect_columns(preview.headers) == (1, 2)
    result = read_roster(roster_path, "名单", 1, 2, True)
    assert len(result.entries) == 12
    assert [entry.student_no for entry in result.entries] == [str(value) for value in ids]
    assert result.entries[0].name == "张三"
    assert not result.warnings, result.warnings
    print("TEST excel/utils OK")


def test_class_columns_and_filter():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "分组名单"
    sheet.append(["院(系)/部", "班级名称", "学号", "姓名", "性别"])
    rows = [
        ("信息学院", "2班", 2023003, "王五", "男"),
        ("机械学院", "1班", 2023001, "张三", "男"),
        ("信息学院", "10班", 2023004, "赵六", "女"),
        ("信息学院", "2班", 2023002, "李四", "女"),
        ("机械学院", "1班", 2023005, "钱七", "男"),
    ]
    for row in rows:
        sheet.append(row)
    path = TEST_ROOT / "class_roster.xlsx"
    workbook.save(path)

    preview = preview_sheet(path, "分组名单", True)
    assert detect_group_columns(preview.headers) == (0, 1)
    assert detect_gender_column(preview.headers) == 4
    result = read_roster(path, "分组名单", 2, 3, True, 0, 1, 4)
    assert [entry.gender for entry in result.entries] == ["男", "男", "女", "女", "男"]
    assert [entry.student_no for entry in result.entries] == [
        "2023003",
        "2023001",
        "2023004",
        "2023002",
        "2023005",
    ]
    ordered = sort_roster_by_class(result.entries)
    assert [entry.student_no for entry in ordered] == [
        "2023001",
        "2023005",
        "2023003",
        "2023002",
        "2023004",
    ]
    assert parse_photo_group(
        TEST_ROOT / "学籍机械" / "机械26211" / "IMG_1.jpg", TEST_ROOT
    ) == ("机械", "26211")
    assert parse_photo_group(
        TEST_ROOT / "北校区" / "26621" / "IMG_2.jpg", TEST_ROOT
    ) == ("北校区", "26621")
    assert parse_photo_group(
        TEST_ROOT / "学籍262401班" / "IMG_3.jpg", TEST_ROOT
    ) == ("", "262401")
    assert parse_photo_major(
        TEST_ROOT / "学籍机械" / "机械26211" / "IMG_1.jpg",
        TEST_ROOT,
        "26211",
    ) == "机械"
    assert parse_photo_major(
        TEST_ROOT / "信息学院" / "计算机" / "1班" / "IMG_4.jpg",
        TEST_ROOT,
        "1班",
    ) == "计算机"

    window = MainWindow()
    photos = [
        PhotoItem(
            seq=index + 1,
            path=TEST_ROOT / f"class_photo_{index + 1}.jpg",
            name=f"class_photo_{index + 1}.jpg",
            size=1,
            mtime_ns=0,
            suffix=".jpg",
            department=department,
            major=major,
            class_no=class_no,
        )
        for index, (department, major, class_no) in enumerate(
            [
                ("机械学院", "机械", "1班"),
                ("机械学院", "机械", "1班"),
                ("信息学院", "计算机", "2班"),
                ("信息学院", "计算机", "2班"),
                ("信息学院", "计算机", "10班"),
            ]
        )
    ]
    window.set_active_photos(photos)
    window.set_active_roster(result.entries)
    assert window.roster_model.rowCount() == 5
    assert window.photo_model.rowCount() == 5
    assert [entry.student_no for entry in window.roster_model.entries()] == [
        "2023001",
        "2023005",
        "2023003",
        "2023002",
        "2023004",
    ]
    assert window.roster_view.dragEnabled()
    assert window.export_action.isEnabled()

    department_index = window.department_filter_combo.findData("信息学院")
    assert department_index >= 0
    window.department_filter_combo.setCurrentIndex(department_index)
    QApplication.processEvents()
    assert window.roster_model.rowCount() == 3
    assert window.photo_model.rowCount() == 3
    assert window.export_action.isEnabled()
    class_frame_texts = [
        button.text()
        for button in window.class_frames_widget.findChildren(QPushButton)
    ]
    assert not any("机械学院" in text for text in class_frame_texts)
    assert window.class_filter_combo.findData("2班") >= 0
    assert window.class_filter_combo.findData("1班") < 0
    assert not window.roster_view.dragEnabled()

    class_index = window.class_filter_combo.findData("2班")
    window.class_filter_combo.setCurrentIndex(class_index)
    QApplication.processEvents()
    assert [entry.student_no for entry in window.roster_model.entries()] == [
        "2023003",
        "2023002",
    ]
    assert window.photo_model.rowCount() == 2
    assert window.export_action.isEnabled()
    assert window._selected_class_identity() == ("信息学院", "计算机", "2班")
    assert window._selected_class_output_dir(Path("H:/batch_out")).as_posix() == (
        "H:/batch_out/信息学院/计算机/2班"
    )
    assert window.roster_view.dragEnabled()

    # 班级筛选下拖动，只改本班在完整名单里的相对顺序
    window._on_move_roster(0, 2)
    assert [entry.student_no for entry in window.roster_model.entries()] == [
        "2023002",
        "2023003",
    ]
    assert [entry.student_no for entry in window._active_entries] == [
        "2023001",
        "2023005",
        "2023002",
        "2023003",
        "2023004",
    ]
    window.undo()
    window._exported_classes.add(
        window._export_mark_key("信息学院", "2班")
    )
    window._rebuild_class_frames()
    marked_texts = [
        button.text()
        for button in window.class_frames_widget.findChildren(QPushButton)
    ]
    assert any("已导出" in text for text in marked_texts)

    frames = [
        button
        for button in window.class_frames_widget.findChildren(QPushButton)
        if "信息学院 · 10班" in button.text()
    ]
    assert frames
    frames[0].click()
    QApplication.processEvents()
    assert window._department_filter == "信息学院"
    assert window._class_filter == "10班"
    assert window.photo_model.rowCount() == 1
    assert window.roster_model.rowCount() == 1

    window.reset_roster_filter()
    assert window.roster_model.rowCount() == 5
    assert window.photo_model.rowCount() == 5
    assert window.roster_view.dragEnabled()
    window.close()
    print("TEST class columns/filter OK")


def test_models(photos, entries):
    photo_model = PhotoModel(photos)
    roster_model = RosterModel(entries)
    assert photo_model.rowCount() == 12
    assert roster_model.rowCount() == 12
    before = [entry.student_no for entry in roster_model.entries()]
    assert roster_model.move_row(0, 3)
    after = [entry.student_no for entry in roster_model.entries()]
    assert after == before[1:3] + [before[0]] + before[3:]
    assert roster_model.move_row(2, 0)
    assert [entry.student_no for entry in roster_model.entries()] == before
    print("TEST models OK")


def test_export(photos, entries):
    output_dir = TEST_ROOT / "output"
    output_dir.mkdir(parents=True)
    preflight = build_export_items(photos, entries, TEST_ROOT / "photos", output_dir)
    assert preflight.ok, preflight.errors
    assert len(preflight.items) == 12
    before_sizes = {photo.path: photo.path.stat().st_size for photo in photos}

    loop = QEventLoop()
    summary: dict = {}
    worker = ExportWorker(preflight.items, TEST_ROOT / "photos", output_dir)
    worker.completed.connect(lambda value: summary.update(value))
    worker.finished.connect(loop.quit)
    QTimer.singleShot(15000, loop.quit)
    worker.start()
    loop.exec()
    assert worker.wait(5000)
    assert summary, "导出线程没有返回汇总"
    assert summary["ok_count"] == 12, summary
    assert summary["error_count"] == 0, summary
    for photo in photos:
        target = output_dir / f"{entries[photos.index(photo)].student_no}.jpg"
        assert target.is_file(), target
        assert target.stat().st_size == photo.size
    assert all(photo.path.stat().st_size == before_sizes[photo.path] for photo in photos)

    # 断点续跑：第二次应全部识别为已存在
    loop2 = QEventLoop()
    summary2: dict = {}
    worker2 = ExportWorker(preflight.items, TEST_ROOT / "photos", output_dir)
    worker2.completed.connect(lambda value: summary2.update(value))
    worker2.finished.connect(loop2.quit)
    QTimer.singleShot(15000, loop2.quit)
    worker2.start()
    loop2.exec()
    assert worker2.wait(5000)
    assert summary2["ok_count"] == 0, summary2
    assert summary2["skipped_count"] == 12, summary2

    # 放一个用户自己的文件，撤销时不能删除
    user_file = output_dir / "不要删除.txt"
    user_file.write_text("user data", encoding="utf-8")
    undo_result = undo_export(summary["summary_file"])
    assert undo_result["ok"], undo_result
    assert undo_result["deleted"] == 12, undo_result
    assert user_file.is_file()
    assert not list(output_dir.glob("*.jpg"))
    print("TEST export/resume/undo OK")


def test_thumbnails(photos):
    manager = ThumbnailManager(CACHE_DIR, thumb_size=QSize(160, 160))
    loaded = []
    manager.thumb_ready.connect(loaded.append)
    manager.request(photos[0].path)
    loop = QEventLoop()
    manager.thumb_ready.connect(lambda _key: loop.quit())
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    manager.shutdown()
    assert loaded, "缩略图没有加载"
    print("TEST thumbnail OK")


def test_ui(photos, entries):
    app = QApplication.instance()
    window = MainWindow()
    window.set_active_photos(photos)
    window.set_active_roster(entries)
    window.source_dir = TEST_ROOT / "photos"
    window.thumbs = ThumbnailManager(CACHE_DIR, window)
    window.photo_delegate.set_thumbs(window.thumbs)
    window._update_counts()
    assert window.export_action.isEnabled()
    window.show()
    app.processEvents()
    window.resize(1600, 900)
    app.processEvents()
    assert window.roster_view._columns == 3
    window.resize(1200, 900)
    app.processEvents()
    assert window.roster_view._columns == 2

    window.photo_view.setCurrentIndex(window.photo_model.index(2, 0))
    app.processEvents()
    assert window.roster_view.currentIndex().row() == 2
    window.roster_view.setCurrentIndex(window.roster_model.index(5, 0))
    app.processEvents()
    assert window.photo_view.currentIndex().row() == 5

    before = [entry.student_no for entry in window.roster_model.entries()]
    window._on_move_roster(0, 3)
    assert [entry.student_no for entry in window.roster_model.entries()] != before
    window.undo()
    assert [entry.student_no for entry in window.roster_model.entries()] == before

    index = window.roster_model.index(2, 0)
    window.roster_view.setCurrentIndex(index)
    window.roster_view.selectionModel().select(
        index, QItemSelectionModel.SelectionFlag.ClearAndSelect
    )
    window.delete_selected_roster()
    assert len(window.excluded) == 1
    assert window.roster_model.rowCount() == 11
    assert not window.export_action.isEnabled()
    window.undo()
    assert window.roster_model.rowCount() == 12
    assert not window.excluded

    window.grab().save(str(TEST_ROOT / "ui_screenshot.png"))
    window.close()
    print("TEST UI OK")


def test_virtualization():
    app = QApplication.instance()
    window = MainWindow()
    dummy = [
        PhotoItem(
            seq=index,
            path=Path(f"H:/PhotoRosterTool/does_not_exist/IMG_{index}.jpg"),
            name=f"IMG_{index}.jpg",
            size=1,
            mtime_ns=0,
            suffix=".jpg",
        )
        for index in range(1, 4001)
    ]
    window.set_active_photos(dummy)
    window.thumbs = ThumbnailManager(CACHE_DIR, window)
    window.photo_delegate.set_thumbs(window.thumbs)
    window._update_counts()
    calls = {"count": 0}
    original_request = window.thumbs.request

    def wrapped(path):
        calls["count"] += 1
        return original_request(path)

    window.thumbs.request = wrapped
    window.show()
    app.processEvents()
    window.grab()
    app.processEvents()
    window.close()
    assert calls["count"] < 1000, calls
    print(f"TEST virtualization OK: thumbnail requests={calls['count']} / 4000")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    photos_dir, roster_path, ids, names = make_test_data()
    test_utils_and_excel(roster_path, ids)
    test_class_columns_and_filter()
    raw_photos = natural_sort_paths(
        [path for path in photos_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg"}]
    )
    assert [path.name for path in raw_photos] == [f"IMG_{index}.jpg" for index in range(1, 13)]
    photos = [
        PhotoItem(
            seq=index,
            path=path,
            name=path.name,
            size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns,
            suffix=path.suffix,
        )
        for index, path in enumerate(raw_photos, start=1)
    ]
    entries = [
        RosterEntry(student_no=str(student_no), name=name, source_row=index + 2)
        for index, (student_no, name) in enumerate(zip(ids, names))
    ]
    test_models(photos, entries)
    test_export(photos, entries)
    test_thumbnails(photos)
    test_ui(photos, entries)
    test_virtualization()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
