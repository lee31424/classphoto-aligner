"""通用工具函数：自然排序、学号文本化、文件名清洗、格式化。"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".jpe"}

_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ZERO_FORMAT = re.compile(r"0+")


def natural_sort_key(name: str) -> tuple:
    """按自然顺序拆分文件名：IMG_2 排在 IMG_10 前面。"""
    parts = re.split(r"(\d+)", name.casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def natural_sort_paths(paths) -> list[Path]:
    return sorted(paths, key=lambda p: (natural_sort_key(p.name), p.name.casefold()))


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS


def _numeric_zero_width(number_format: str | None) -> int:
    """从 Excel 数字格式里推断前导零宽度，例如 000000 -> 6。"""
    if not number_format:
        return 0
    first_section = number_format.split(";", 1)[0]
    # 去掉引号里的字面量，避免把 "编号000" 误判成数字格式
    first_section = re.sub(r'"[^"]*"', "", first_section)
    match = _ZERO_FORMAT.search(first_section)
    return len(match.group(0)) if match else 0


def student_no_to_text(value, number_format: str | None = None) -> str:
    """把 Excel 单元格中的学号安全转成字符串。

    - 数字 2023001 / 2023001.0 -> "2023001"
    - 文本 "00123" 保留前导零
    - 数字格式为 000000 时补足前导零
    - 日期、布尔值、小数等异常值抛 ValueError
    """
    if value is None:
        return ""

    if isinstance(value, bool):
        raise ValueError("学号单元格是布尔值")

    numeric = False
    if isinstance(value, int):
        text = str(value)
        numeric = True
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"学号是小数：{value!r}")
        text = str(int(value))
        numeric = True
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError(f"学号是小数：{value!r}")
        text = str(int(value))
        numeric = True
    elif isinstance(value, (datetime, date, time)):
        raise ValueError(f"学号单元格是日期/时间：{value!r}")
    elif isinstance(value, str):
        text = value.replace("\u3000", " ").strip()
        if not text:
            return ""
        # 文本形式的 2023001.0
        if re.fullmatch(r"\d+\.0+", text):
            text = text.split(".", 1)[0]
        # 文本形式的科学计数法
        elif re.fullmatch(r"\d+(?:\.\d+)?[eE][+-]?\d+", text):
            try:
                number = Decimal(text)
            except InvalidOperation as exc:
                raise ValueError(f"无法解析学号：{text!r}") from exc
            if number != number.to_integral_value():
                raise ValueError(f"学号是小数：{text!r}")
            text = str(int(number))
    else:
        text = str(value).strip()

    if numeric:
        width = _numeric_zero_width(number_format)
        if width and text.isdigit() and len(text) < width:
            text = text.zfill(width)

    return text


def normalize_student_no_input(value: str) -> str:
    """清理手动输入的学号：去掉全角/半角空白，并统一全角数字。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text).strip()


def sanitize_filename(name: str) -> str:
    """生成 Windows 合法文件名（不含扩展名）。"""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip().rstrip(". ")
    if not cleaned:
        cleaned = "_"
    if cleaned.upper() in _RESERVED_NAMES:
        cleaned = "_" + cleaned
    # 给扩展名和路径留出空间
    return cleaned[:120]


def format_size(num_bytes: int | float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def run_id_now() -> str:
    # 微秒后缀确保连续两次导出不会覆盖同名日志
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")
