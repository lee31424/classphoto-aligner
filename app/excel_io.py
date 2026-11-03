"""Excel 名单读取：支持 .xlsx/.xlsm 与旧版 .xls，列映射、数字学号转字符串。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from models import RosterEntry
from utils import student_no_to_text


@dataclass(slots=True)
class SheetPreview:
    sheet_name: str
    headers: list[str]
    rows: list[list[str]]
    max_col: int
    has_header: bool


@dataclass(slots=True)
class RosterReadResult:
    entries: list[RosterEntry]
    warnings: list[str]
    duplicate_ids: set[str]
    sheet_name: str


def _is_xls(path: str | Path) -> bool:
    return Path(path).suffix.casefold() == ".xls"


def _open_xls(path: str | Path):
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError(
            "读取 .xls 需要 xlrd 库。请运行：\n"
            r"H:\PhotoRosterTool\venv\Scripts\python.exe -m pip install xlrd"
        ) from exc
    return xlrd.open_workbook(str(path), formatting_info=True)


def sheet_names(path: str | Path) -> list[str]:
    if _is_xls(path):
        book = _open_xls(path)
        try:
            return list(book.sheet_names())
        finally:
            book.release_resources()
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def _display_cell(cell) -> str:
    if cell is None:
        return ""
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _xls_display_cell(cell) -> str:
    import xlrd

    if cell is None or cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    value = cell.value
    if cell.ctype == xlrd.XL_CELL_NUMBER and isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if value else "FALSE"
    if cell.ctype == xlrd.XL_CELL_ERROR:
        return "#ERROR"
    if cell.ctype == xlrd.XL_CELL_DATE:
        return str(value)
    return str(value).strip()


def _xls_number_format(book, cell) -> str | None:
    try:
        xf = book.xf_list[cell.xf_index]
        fmt = book.format_map.get(xf.format_key)
        return fmt.format_str if fmt is not None else None
    except (AttributeError, IndexError, KeyError, TypeError):
        return None


def _xls_student_no(book, cell) -> str:
    import xlrd

    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if cell.ctype == xlrd.XL_CELL_DATE:
        raise ValueError("学号单元格是日期/时间")
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        raise ValueError("学号单元格是布尔值")
    if cell.ctype == xlrd.XL_CELL_ERROR:
        raise ValueError("学号单元格是 Excel 错误值")
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        return student_no_to_text(float(cell.value), _xls_number_format(book, cell))
    return student_no_to_text(cell.value)


def _xlsx_group_text(cell) -> str:
    if cell is None:
        return ""
    try:
        return student_no_to_text(cell.value, cell.number_format)
    except ValueError:
        return _display_cell(cell)


def _xls_group_text(book, cell) -> str:
    if cell is None:
        return ""
    try:
        return _xls_student_no(book, cell)
    except ValueError:
        return _xls_display_cell(cell)


def _preview_sheet_xlsx(
    path: str | Path,
    sheet_name: str,
    has_header: bool,
    max_rows: int,
) -> SheetPreview:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"工作表不存在：{sheet_name}")
        worksheet = workbook[sheet_name]
        max_col = max(1, min(20, worksheet.max_column or 1))
        preview_limit = max_rows + (1 if has_header else 0)
        raw_rows: list[list[str]] = []
        for row in worksheet.iter_rows(
            min_row=1, max_row=preview_limit, max_col=max_col
        ):
            raw_rows.append([_display_cell(cell) for cell in row])
    finally:
        workbook.close()
    return _make_preview(sheet_name, raw_rows, max_col, has_header)


def _preview_sheet_xls(
    path: str | Path,
    sheet_name: str,
    has_header: bool,
    max_rows: int,
) -> SheetPreview:
    book = _open_xls(path)
    try:
        if sheet_name not in book.sheet_names():
            raise ValueError(f"工作表不存在：{sheet_name}")
        worksheet = book.sheet_by_name(sheet_name)
        max_col = max(1, min(20, worksheet.ncols))
        preview_limit = max_rows + (1 if has_header else 0)
        raw_rows = [
            [_xls_display_cell(worksheet.cell(row_index, col_index)) for col_index in range(max_col)]
            for row_index in range(min(preview_limit, worksheet.nrows))
        ]
    finally:
        book.release_resources()
    return _make_preview(sheet_name, raw_rows, max_col, has_header)


def _make_preview(
    sheet_name: str,
    raw_rows: list[list[str]],
    max_col: int,
    has_header: bool,
) -> SheetPreview:
    if has_header and raw_rows:
        headers = [
            value if value else f"列 {get_column_letter(index + 1)}"
            for index, value in enumerate(raw_rows[0])
        ]
        data_rows = raw_rows[1:]
    else:
        headers = [f"列 {get_column_letter(index + 1)}" for index in range(max_col)]
        data_rows = raw_rows
    return SheetPreview(
        sheet_name=sheet_name,
        headers=headers,
        rows=data_rows,
        max_col=max_col,
        has_header=has_header,
    )


def preview_sheet(
    path: str | Path,
    sheet_name: str,
    has_header: bool = True,
    max_rows: int = 10,
) -> SheetPreview:
    if _is_xls(path):
        return _preview_sheet_xls(path, sheet_name, has_header, max_rows)
    return _preview_sheet_xlsx(path, sheet_name, has_header, max_rows)


def _normalize_header(value: str) -> str:
    value = re.sub(r"[\s_\-（）()【】\[\]]", "", value or "")
    return value.casefold()


def detect_group_columns(headers: list[str]) -> tuple[int | None, int | None]:
    """识别院系列和班级号列，找不到就返回 None。"""
    dept_col = None
    class_col = None
    dept_tokens = ("院系", "学院", "系别", "department", "faculty", "college")
    class_tokens = ("班级号", "班级", "班号", "classno", "classid", "class")
    for index, header in enumerate(headers):
        normalized = _normalize_header(header)
        if dept_col is None and (
            normalized in dept_tokens
            or any(token in normalized for token in ("院系", "学院"))
        ):
            dept_col = index
        if class_col is None and (
            normalized in class_tokens
            or "班级" in normalized
            or "班号" in normalized
        ):
            class_col = index
    return dept_col, class_col


def detect_gender_column(headers: list[str]) -> int | None:
    for index, header in enumerate(headers):
        normalized = _normalize_header(header)
        if normalized in ("性别", "gender", "sex"):
            return index
    return None


def normalize_gender(value: str) -> str:
    """只保留“男/女”，其他写法尽量归一到这两个字。"""
    text = str(value or "").strip().casefold()
    if not text:
        return ""
    if text in ("男", "m", "male", "男生", "1"):
        return "男"
    if text in ("女", "f", "female", "女生", "0"):
        return "女"
    return ""


def detect_columns(headers: list[str]) -> tuple[int | None, int | None]:
    id_col = None
    name_col = None
    id_tokens = ("学号", "学生学号", "studentid", "student_id", "id", "编号")
    name_tokens = ("姓名", "学生姓名", "name", "studentname")
    for index, header in enumerate(headers):
        normalized = _normalize_header(header)
        if id_col is None and (
            normalized in id_tokens or any(token in normalized for token in ("学号", "studentid"))
        ):
            id_col = index
        if name_col is None and (
            normalized in name_tokens or "姓名" in normalized or normalized == "name"
        ):
            name_col = index
    return id_col, name_col


def _read_roster_xlsx(
    path: str | Path,
    sheet_name: str,
    id_col: int,
    name_col: int | None,
    has_header: bool,
    department_col: int | None = None,
    class_no_col: int | None = None,
    gender_col: int | None = None,
) -> tuple[list[RosterEntry], list[str]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    warnings: list[str] = []
    entries: list[RosterEntry] = []
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"工作表不存在：{sheet_name}")
        worksheet = workbook[sheet_name]
        extra_cols = [
            col
            for col in (name_col, department_col, class_no_col, gender_col)
            if col is not None and col >= 0
        ]
        max_col = max([id_col, *extra_cols]) + 1
        start_row = 2 if has_header else 1
        for excel_row, row in enumerate(
            worksheet.iter_rows(min_row=start_row, max_col=max_col),
            start=start_row,
        ):
            id_cell = row[id_col] if id_col < len(row) else None
            name_cell = (
                row[name_col]
                if name_col is not None and 0 <= name_col < len(row)
                else None
            )
            dept_cell = (
                row[department_col]
                if department_col is not None and 0 <= department_col < len(row)
                else None
            )
            class_cell = (
                row[class_no_col]
                if class_no_col is not None and 0 <= class_no_col < len(row)
                else None
            )
            gender_cell = (
                row[gender_col]
                if gender_col is not None and 0 <= gender_col < len(row)
                else None
            )
            raw_name = _display_cell(name_cell)
            try:
                student_no = student_no_to_text(
                    id_cell.value if id_cell is not None else None,
                    id_cell.number_format if id_cell is not None else None,
                )
            except ValueError as exc:
                warnings.append(f"第 {excel_row} 行学号无法读取：{exc}")
                continue
            if not student_no:
                if raw_name:
                    warnings.append(f"第 {excel_row} 行有姓名但没有学号，已跳过")
                continue
            entries.append(
                RosterEntry(
                    student_no=student_no,
                    name=raw_name,
                    source_row=excel_row,
                    department=_xlsx_group_text(dept_cell),
                    class_no=_xlsx_group_text(class_cell),
                    gender=normalize_gender(_display_cell(gender_cell)),
                )
            )
    finally:
        workbook.close()
    return entries, warnings


def _read_roster_xls(
    path: str | Path,
    sheet_name: str,
    id_col: int,
    name_col: int | None,
    has_header: bool,
    department_col: int | None = None,
    class_no_col: int | None = None,
    gender_col: int | None = None,
) -> tuple[list[RosterEntry], list[str]]:
    import xlrd  # noqa: F401  确保扩展名为 .xls 时依赖存在

    book = _open_xls(path)
    warnings: list[str] = []
    entries: list[RosterEntry] = []
    try:
        if sheet_name not in book.sheet_names():
            raise ValueError(f"工作表不存在：{sheet_name}")
        worksheet = book.sheet_by_name(sheet_name)
        extra_cols = [
            col
            for col in (name_col, department_col, class_no_col, gender_col)
            if col is not None and col >= 0
        ]
        max_col = max([id_col, *extra_cols]) + 1
        start_row = 1 if has_header else 0
        for row_index in range(start_row, worksheet.nrows):
            excel_row = row_index + 1
            id_cell = worksheet.cell(row_index, id_col) if id_col < max_col else None
            name_cell = (
                worksheet.cell(row_index, name_col)
                if name_col is not None and 0 <= name_col < max_col
                else None
            )
            dept_cell = (
                worksheet.cell(row_index, department_col)
                if department_col is not None and 0 <= department_col < max_col
                else None
            )
            class_cell = (
                worksheet.cell(row_index, class_no_col)
                if class_no_col is not None and 0 <= class_no_col < max_col
                else None
            )
            gender_cell = (
                worksheet.cell(row_index, gender_col)
                if gender_col is not None and 0 <= gender_col < max_col
                else None
            )
            raw_name = _xls_display_cell(name_cell)
            try:
                student_no = _xls_student_no(book, id_cell) if id_cell is not None else ""
            except ValueError as exc:
                warnings.append(f"第 {excel_row} 行学号无法读取：{exc}")
                continue
            if not student_no:
                if raw_name:
                    warnings.append(f"第 {excel_row} 行有姓名但没有学号，已跳过")
                continue
            entries.append(
                RosterEntry(
                    student_no=student_no,
                    name=raw_name,
                    source_row=excel_row,
                    department=_xls_group_text(book, dept_cell),
                    class_no=_xls_group_text(book, class_cell),
                    gender=normalize_gender(_xls_display_cell(gender_cell)),
                )
            )
    finally:
        book.release_resources()
    return entries, warnings


def _finalize_result(
    entries: list[RosterEntry],
    warnings: list[str],
    sheet_name: str,
) -> RosterReadResult:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.student_no] = counts.get(entry.student_no, 0) + 1
    duplicate_ids = {student_no for student_no, count in counts.items() if count > 1}
    for student_no in sorted(duplicate_ids):
        rows = [str(entry.source_row) for entry in entries if entry.student_no == student_no]
        warnings.append(f"学号 {student_no} 重复，出现在 Excel 行：{', '.join(rows)}")
    if not entries:
        warnings.append("没有读到任何有效名单行")
    return RosterReadResult(
        entries=entries,
        warnings=warnings,
        duplicate_ids=duplicate_ids,
        sheet_name=sheet_name,
    )


def read_roster(
    path: str | Path,
    sheet_name: str,
    id_col: int,
    name_col: int | None,
    has_header: bool = True,
    department_col: int | None = None,
    class_no_col: int | None = None,
    gender_col: int | None = None,
) -> RosterReadResult:
    if id_col < 0:
        raise ValueError("必须指定学号列")
    if _is_xls(path):
        entries, warnings = _read_roster_xls(
            path,
            sheet_name,
            id_col,
            name_col,
            has_header,
            department_col,
            class_no_col,
            gender_col,
        )
    else:
        entries, warnings = _read_roster_xlsx(
            path,
            sheet_name,
            id_col,
            name_col,
            has_header,
            department_col,
            class_no_col,
            gender_col,
        )
    return _finalize_result(entries, warnings, sheet_name)
