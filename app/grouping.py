"""从照片路径和名单中提取学院/班级分组信息。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, TYPE_CHECKING

from utils import natural_sort_key

if TYPE_CHECKING:
    from models import PhotoItem, RosterEntry


# 实际路径示例：
#   学籍机械/机械26211/IMG_0001.JPG
#   北校区/26621/IMG_0002.JPG
#   学籍262401班/IMG_0003.JPG
# 兼容 1班、2023级1班 这类文字班级。
_CLASS_CODE_RE = re.compile(r"(?<!\d)(\d{5,6}|\d{3,6}[A-Z]\d{0,2})(?!\d)")
_CLASS_TEXT_RE = re.compile(r"((?:20\d{2}级)?[0-9一二三四五六七八九十]+班)")


def normalize_class(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace(" ", "").replace("　", "")
    if not text:
        return ""
    match = _CLASS_CODE_RE.search(text)
    if match:
        return match.group(1).upper()
    match = _CLASS_TEXT_RE.search(text)
    if match:
        return match.group(1)
    return text


def class_key(value: str) -> str:
    """用于照片/名单位置匹配的班级键。"""
    return normalize_class(value).casefold()


def class_sort_key(value: str):
    """班级代码按字符序，普通“1班/2班/10班”按自然序。"""
    text = normalize_class(value)
    if re.fullmatch(r"\d{5,6}", text) or re.fullmatch(
        r"\d{3,6}[A-Z]\d{0,2}", text
    ):
        return (0, text.casefold(), 0, "")
    return (1, "", 0, natural_sort_key(text))


def _class_from_component(component: str) -> str:
    text = component.strip()
    if not text:
        return ""
    match = _CLASS_CODE_RE.search(text)
    if match:
        return match.group(1).upper()
    match = _CLASS_TEXT_RE.search(text)
    if match:
        return match.group(1)
    return ""


def _department_from_component(component: str, class_value: str) -> str:
    text = component.strip()
    if not text:
        return ""
    if text.startswith("学籍"):
        text = text[2:]
    if not text:
        return ""
    # 机械26211 -> 机械；学籍机电 -> 机电。
    if class_value:
        position = text.upper().find(class_value.upper())
        if position > 0:
            prefix = text[:position].strip("_-— ·")
            if prefix:
                return prefix
    if re.search(r"(?:学院|学部|系)$", text):
        return text
    # 北校区 这类校区名保留；有名单后会用班级代码校正成真实院系。
    if re.search(r"[\u4e00-\u9fa5]", text) and not _class_from_component(text):
        return text
    return ""


def parse_photo_group(path: str | Path, root: str | Path) -> tuple[str, str]:
    """从照片相对路径提取 (院系/校区, 班级代码)。

    优先看父目录，文件名只作为兜底。院系可能是简称，之后会用名单
    中相同班级代码对应的完整院系名称校正。
    """
    photo_path = Path(path)
    root_path = Path(root)
    try:
        relative = photo_path.relative_to(root_path)
        parts = list(relative.parts)
    except ValueError:
        parts = list(photo_path.parts)
    if not parts:
        return "", ""

    # 文件名不参与班级提取，避免把 IMG_12345 里的数字误认成班级。
    directory_parts = parts[:-1]
    class_value = ""
    for part in reversed(directory_parts):
        class_value = _class_from_component(part)
        if class_value:
            break
    if not class_value:
        # 文件名中只有明确带“班”的写法才识别。
        stem = Path(parts[-1]).stem
        if "班" in stem:
            class_value = _class_from_component(stem)
    if not class_value:
        # 也允许直接把某个班级文件夹作为导入根目录。
        class_value = _class_from_component(root_path.name)

    department = ""
    if class_value:
        for part in reversed(directory_parts):
            if class_value.upper() in part.upper():
                candidate = _department_from_component(part, class_value)
                if candidate and candidate != class_value:
                    department = candidate
                    break
    if not department:
        for part in reversed(directory_parts):
            candidate = _department_from_component(part, "")
            if candidate and not _class_from_component(part):
                department = candidate
                break
    if not department and class_value:
        candidate = _department_from_component(root_path.name, class_value)
        if candidate:
            department = candidate
        else:
            parent_name = root_path.parent.name
            if parent_name:
                candidate = _department_from_component(parent_name, "")
                if candidate:
                    department = candidate
    if not department:
        # 只有根目录本身明确是学院/系/学部时才兜底，避免把“2026学籍-原图”
        # 这种目录名当成院系。
        candidate = _department_from_component(root_path.name, "")
        if candidate and re.search(r"(?:学院|学部|系)$", candidate):
            department = candidate
    return department.strip(), class_value.strip()


def parse_photo_major(path: str | Path, root: str | Path, class_no: str) -> str:
    """从班级文件夹名或上一级文件夹提取专业名。

    例如 `学籍机械/机械26211` -> 机械；
         `信息学院/计算机/1班` -> 计算机。
    """
    if not class_no:
        return ""
    photo_path = Path(path)
    root_path = Path(root)
    try:
        relative = photo_path.relative_to(root_path)
        parts = list(relative.parts)
    except ValueError:
        parts = list(photo_path.parts)
    directory_parts = parts[:-1]
    class_position = -1
    for index in range(len(directory_parts) - 1, -1, -1):
        if class_no.upper() in directory_parts[index].upper():
            class_position = index
            break
    if class_position < 0:
        # 直接选了班级文件夹作为根目录。
        if class_no.upper() in root_path.name.upper():
            directory_parts = [root_path.name]
            class_position = 0
        else:
            return ""

    component = directory_parts[class_position]
    position = component.upper().find(class_no.upper())
    prefix = component[:position].strip("_-— ·") if position > 0 else ""
    if prefix:
        prefix = re.sub(r"^学籍", "", prefix).strip()
        if prefix:
            return prefix

    if class_position > 0:
        candidate = directory_parts[class_position - 1].strip()
        candidate = re.sub(r"^学籍", "", candidate).strip()
        if (
            candidate
            and not re.search(r"(?:校区|学院|学部|系)$", candidate)
            and not _class_from_component(candidate)
        ):
            return candidate
    return ""


def resolve_departments_from_roster(
    photos: Iterable["PhotoItem"], entries: Iterable["RosterEntry"]
) -> None:
    """用班级代码把照片路径里的院系简称补全为名单中的完整院系名。"""
    departments_by_class: dict[str, set[str]] = {}
    for entry in entries:
        key = class_key(entry.class_no)
        if key and entry.department:
            departments_by_class.setdefault(key, set()).add(entry.department)

    for photo in photos:
        key = class_key(photo.class_no)
        departments = departments_by_class.get(key)
        if not departments:
            continue
        if photo.department in departments:
            continue
        # 优先匹配“机械”->“机械工程学院”这种前缀关系。
        matched = next(
            (
                value
                for value in departments
                if photo.department and photo.department in value
            ),
            None,
        )
        if matched is None and len(departments) == 1:
            matched = next(iter(departments))
        if matched is not None:
            photo.department = matched


def sort_photos_by_class(photos: Iterable["PhotoItem"]) -> list["PhotoItem"]:
    """按班级代码分块排序，同班内保持文件名自然顺序。"""
    photo_list = list(photos)
    if not any(photo.class_no for photo in photo_list):
        return photo_list
    classified = [photo for photo in photo_list if photo.class_no]
    unclassified = [photo for photo in photo_list if not photo.class_no]
    classified.sort(
        key=lambda photo: (
            class_sort_key(photo.class_no),
            photo.department.casefold(),
            natural_sort_key(photo.name),
            str(photo.path).casefold(),
        )
    )
    return classified + unclassified
