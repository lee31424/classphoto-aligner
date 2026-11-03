# ClassPhoto Aligner

A Windows desktop tool for aligning a **fixed-order photo queue** with a **class roster**, then exporting each class as `学号.jpg` into a clean `学院/专业/班级` folder tree.

This project was built for student ID-photo workflows where thousands of camera photos are supplied in a fixed order, while the roster must be adjusted for absent students and class order. It deliberately **does not use face recognition**; the mapping is positional.

## Features

- Fixed natural-sort photo order; photos cannot be reordered in the UI.
- Excel roster import: `.xlsx`, `.xlsm`, `.xls`.
- Optional roster columns: student ID, name, department, class, gender.
- Class and department grouping, with one clickable frame per class.
- Responsive roster grid: **2 columns** on narrow windows, **3 columns** on wide windows.
- Synchronized filtering: choosing a department/class filters both photos and roster.
- Class-scoped drag sorting and soft-delete for absent students.
- Right-click a photo to remove it from the queue without touching the source file.
- Right-click a roster row to soft-delete or move it to the end of the list/class. Both are undoable.
- Gender badge limited to **男 / 女**.
- Per-class export with **✓ 已导出** markers:
  - `ExportRoot/学院/专业/班级/学号.jpg`
- Batch copy with progress, cancel, resume, per-file CSV logs and JSON summaries.
- Log-based undo that only removes files written by the tool.
- Virtualized thumbnails and a 4000+ photo list without decoding every image at once.

## Screens / Workflow

1. Import a photo root folder. Subfolders are scanned recursively.
2. Import the Excel roster and map the columns.
3. Pick a class frame, adjust roster order/attendance.
4. Click **修改并导出本班** to export that class immediately.
5. Repeat for the next class.

The class information comes from the photo path. Supported examples:

```text
学籍机械/机械26211/IMG_0001.JPG   -> 机械工程学院 / 机械 / 26211
北校区/26621/IMG_0002.JPG         -> 汽车工程学院 / 汽车 / 26621
学籍262401班/IMG_0003.JPG          -> 机械工程学院 / 机械 / 262401
```

If the path only has a short department name, the class code from the roster is used to resolve the full department name.

## Quick Start (Windows)

Requirements: Python 3.13+ (64-bit) and Windows 10/11.

```powershell
git clone https://github.com/lee31424/classphoto-aligner.git
cd classphoto-aligner

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Start normally (no console)
.\run.bat

# Start with console for troubleshooting
.\run_debug.bat
```

`run.bat` prefers `.venv\Scripts\pythonw.exe`, then `pyw -3`, then `pythonw`.

## Output Layout

```text
ExportRoot/
└─ 机械工程学院/
   └─ 机械/
      └─ 26211/
         ├─ 2621101.jpg
         ├─ 2621102.jpg
         ├─ rename_plan_*.csv
         ├─ rename_log_*.csv
         └─ rename_summary_*.json
```

- Source photos are never renamed, moved, or deleted.
- Output must be outside the photo source folder.
- Existing targets with the same size are skipped during resume.
- Undo reads the generated summary/log and verifies size before deleting.

## Project Layout

```text
app/
  main.py          UI, filtering, class frames, export orchestration
  models.py        photo/roster models and class sorting
  grouping.py      path-based department/class/major parsing
  excel_io.py      .xlsx/.xlsm/.xls reader
  dialogs.py       Excel column mapping and excluded-student dialog
  delegates.py     photo cards and roster cards
  exporter.py      preflight, copy worker, CSV/JSON logs, undo
  thumbnails.py    lazy thumbnail loader/cache
  widgets.py       responsive roster grid and drag-drop target handling
  tests/smoke_test.py
```

Chinese documentation: [README.zh-CN.md](README.zh-CN.md).

## Tests

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python app\tests\smoke_test.py
```

The smoke test creates synthetic photos and Excel data, then verifies import, class filtering, gender mapping, responsive columns, class-scoped dragging, export/resume/undo, thumbnails, and 4000-item virtualization.

## Notes

- This is a local Windows desktop tool, not a web service.
- Photo ordering is fixed at import time. The roster is the only side that can be reordered.
- The app stores window/export preferences with `QSettings`; generated logs/cache/output are ignored by git.
- No license has been specified yet. Add one before redistributing if needed.
