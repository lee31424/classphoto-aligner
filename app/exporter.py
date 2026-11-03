"""导出预检、后台复制、CSV/JSON 日志与按日志撤销。"""

from __future__ import annotations

import csv
import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from models import PhotoItem, RosterEntry
from utils import format_size, run_id_now, sanitize_filename


@dataclass(slots=True)
class ExportItem:
    seq: int
    source: Path
    target_name: str
    student_no: str
    name: str
    size: int


@dataclass(slots=True)
class PreflightResult:
    items: list[ExportItem]
    errors: list[str]
    warnings: list[str]
    total_bytes: int
    required_bytes: int
    existing_count: int

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def build_export_items(
    photos: list[PhotoItem],
    roster: list[RosterEntry],
    source_dir: Path,
    output_dir: Path,
) -> PreflightResult:
    errors: list[str] = []
    warnings: list[str] = []
    items: list[ExportItem] = []
    total_bytes = 0
    required_bytes = 0
    existing_count = 0

    if not photos:
        errors.append("没有导入照片。")
    if not roster:
        errors.append("有效名单为空。")
    if len(photos) != len(roster):
        errors.append(
            f"数量不一致：照片 {len(photos)} 张，有效名单 {len(roster)} 人。"
            "请先删除未到场学生或补齐名单。"
        )

    counts: dict[str, int] = {}
    for entry in roster:
        if not entry.student_no:
            errors.append(f"Excel 第 {entry.source_row} 行学号为空。")
            continue
        counts[entry.student_no] = counts.get(entry.student_no, 0) + 1
    duplicates = {student_no for student_no, count in counts.items() if count > 1}
    for student_no in sorted(duplicates):
        errors.append(f"学号重复：{student_no}。请先处理重复名单。")

    if source_dir.resolve() == output_dir.resolve():
        errors.append("输出目录不能是照片源目录本身。")
    elif _is_within(output_dir, source_dir):
        errors.append("输出目录不能放在照片源目录里面，避免下次扫描时混入输出文件。")
    elif _is_within(source_dir, output_dir):
        errors.append("照片源目录不能在输出目录里面。")

    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        errors.append(f"输出路径不是文件夹：{output_dir}")
        return PreflightResult(items, errors, warnings, 0, 0, 0)

    target_names: dict[str, int] = {}
    for seq, (photo, entry) in enumerate(zip(photos, roster), start=1):
        student_no = entry.student_no.strip()
        if not student_no:
            continue
        safe_name = sanitize_filename(student_no)
        if safe_name != student_no:
            errors.append(
                f"学号「{student_no}」含有 Windows 文件名非法字符，已阻止导出。"
            )
            continue
        target_name = safe_name + ".jpg"
        key = target_name.casefold()
        if key in target_names:
            errors.append(
                f"目标文件名重复：{target_name}（第 {target_names[key]} 张和第 {seq} 张）。"
            )
            continue
        target_names[key] = seq
        target_path = output_dir / target_name
        if target_path.exists():
            if target_path.is_file() and target_path.stat().st_size == photo.size:
                existing_count += 1
                warnings.append(f"{target_name} 已存在且大小一致，导出时会跳过。")
            else:
                errors.append(f"输出目录已有同名文件且大小不同：{target_name}")
        else:
            required_bytes += photo.size
        total_bytes += photo.size
        items.append(
            ExportItem(
                seq=seq,
                source=photo.path,
                target_name=target_name,
                student_no=student_no,
                name=entry.name,
                size=photo.size,
            )
        )

    try:
        free_bytes = shutil.disk_usage(output_dir).free
        if free_bytes < required_bytes + 50 * 1024 * 1024:
            errors.append(
                f"输出磁盘空间不足：需要约 {format_size(required_bytes)}，"
                f"当前剩余 {format_size(free_bytes)}。"
            )
    except OSError as exc:
        warnings.append(f"无法检查磁盘剩余空间：{exc}")

    return PreflightResult(
        items=items,
        errors=errors,
        warnings=warnings,
        total_bytes=total_bytes,
        required_bytes=required_bytes,
        existing_count=existing_count,
    )


class ExportWorker(QThread):
    progress = Signal(int, int, str, str)
    completed = Signal(dict)

    def __init__(
        self,
        items: list[ExportItem],
        source_dir: Path,
        output_dir: Path,
        run_id: str | None = None,
        parent=None,
        log_dir: Path | None = None,
    ):
        super().__init__(parent)
        self.items = list(items)
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.log_dir = Path(log_dir) if log_dir is not None else self.output_dir
        self.run_id = run_id or run_id_now()
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def _clean_output_folder(self):
        """把旧版本放在照片目录里的日志移到外部，照片目录只留照片。"""
        patterns = (
            "rename_plan_*.csv",
            "rename_log_*.csv",
            "rename_summary_*.json",
            "undo_log_*.csv",
            "undo_summary_*.json",
            "*.part",
        )
        legacy_dir = self.log_dir / "legacy_output_logs"
        for pattern in patterns:
            for path in self.output_dir.glob(pattern):
                if not path.is_file():
                    continue
                try:
                    legacy_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(path), str(legacy_dir / path.name))
                except OSError:
                    try:
                        path.unlink()
                    except OSError:
                        pass

    def _write_plan(self, path: Path):
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["seq", "source_name", "source_path", "target_name", "student_no", "name", "size"]
            )
            for item in self.items:
                writer.writerow(
                    [
                        item.seq,
                        item.source.name,
                        str(item.source),
                        item.target_name,
                        item.student_no,
                        item.name,
                        item.size,
                    ]
                )

    def run(self):
        started_at = datetime.now().isoformat(timespec="seconds")
        start_time = time.time()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._clean_output_folder()
        plan_path = self.log_dir / f"rename_plan_{self.run_id}.csv"
        log_path = self.log_dir / f"rename_log_{self.run_id}.csv"
        summary_path = self.log_dir / f"rename_summary_{self.run_id}.json"

        total = len(self.items)
        ok_count = 0
        skipped_count = 0
        error_count = 0
        canceled = False
        errors: list[str] = []
        completed_count = 0

        try:
            self._write_plan(plan_path)
            with open(log_path, "w", newline="", encoding="utf-8-sig") as log_file:
                writer = csv.writer(log_file)
                writer.writerow(
                    [
                        "seq",
                        "source_name",
                        "source_path",
                        "target_name",
                        "student_no",
                        "name",
                        "size",
                        "status",
                        "error",
                        "time",
                    ]
                )
                log_file.flush()

                for index, item in enumerate(self.items, start=1):
                    if self._cancel_event.is_set():
                        canceled = True
                        break

                    status = "error"
                    error = ""
                    log_size = item.size
                    target = self.output_dir / item.target_name
                    try:
                        source_size = item.source.stat().st_size
                        log_size = source_size
                        if target.exists():
                            if target.is_file() and target.stat().st_size == source_size:
                                status = "skipped_existing"
                                skipped_count += 1
                            else:
                                error = "目标文件已存在且大小不同"
                                error_count += 1
                                errors.append(f"{item.target_name}: {error}")
                        else:
                            temp = self.output_dir / f".{item.target_name}.{uuid.uuid4().hex}.part"
                            try:
                                shutil.copy2(item.source, temp)
                                if temp.stat().st_size != source_size:
                                    raise OSError("复制后文件大小不一致")
                                os.replace(temp, target)
                                status = "ok"
                                log_size = target.stat().st_size
                                ok_count += 1
                            finally:
                                if temp.exists():
                                    try:
                                        temp.unlink()
                                    except OSError:
                                        pass
                    except Exception as exc:  # 单个文件失败不影响整批
                        status = "error"
                        error = str(exc)
                        error_count += 1
                        errors.append(f"{item.target_name}: {exc}")

                    completed_count = index
                    writer.writerow(
                        [
                            item.seq,
                            item.source.name,
                            str(item.source),
                            item.target_name,
                            item.student_no,
                            item.name,
                            log_size,
                            status,
                            error,
                            datetime.now().isoformat(timespec="seconds"),
                        ]
                    )
                    log_file.flush()
                    self.progress.emit(index, total, item.target_name, status)

            finished_at = datetime.now().isoformat(timespec="seconds")
            summary = {
                "tool": "PhotoRosterTool",
                "run_id": self.run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": round(time.time() - start_time, 2),
                "source_dir": str(self.source_dir),
                "output_dir": str(self.output_dir),
                "photo_count": total,
                "roster_count": total,
                "total_bytes": sum(item.size for item in self.items),
                "completed_count": completed_count,
                "ok_count": ok_count,
                "skipped_count": skipped_count,
                "error_count": error_count,
                "pending_count": total - completed_count,
                "canceled": canceled,
                "errors": errors[:200],
                "log_file": str(log_path),
                "plan_file": str(plan_path),
                "summary_file": str(summary_path),
            }
            with open(summary_path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, ensure_ascii=False, indent=2)
            self.completed.emit(summary)
        except Exception as exc:
            finished_at = datetime.now().isoformat(timespec="seconds")
            summary = {
                "tool": "PhotoRosterTool",
                "run_id": self.run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_seconds": round(time.time() - start_time, 2),
                "source_dir": str(self.source_dir),
                "output_dir": str(self.output_dir),
                "photo_count": total,
                "roster_count": total,
                "total_bytes": sum(item.size for item in self.items),
                "completed_count": completed_count,
                "ok_count": ok_count,
                "skipped_count": skipped_count,
                "error_count": error_count + 1,
                "pending_count": total - completed_count,
                "canceled": canceled,
                "fatal_error": str(exc),
                "errors": errors[:200],
                "log_file": str(log_path),
                "plan_file": str(plan_path),
                "summary_file": str(summary_path),
            }
            try:
                with open(summary_path, "w", encoding="utf-8") as handle:
                    json.dump(summary, handle, ensure_ascii=False, indent=2)
            except OSError:
                pass
            self.completed.emit(summary)


def undo_export(summary_path: str | Path) -> dict:
    """按 summary + log 删除本次导出中成功复制的文件。源照片永远不碰。"""
    summary_path = Path(summary_path)
    if not summary_path.is_file():
        return {"ok": False, "message": f"找不到汇总文件：{summary_path}"}
    try:
        with open(summary_path, "r", encoding="utf-8") as handle:
            summary = json.load(handle)
    except Exception as exc:
        return {"ok": False, "message": f"读取汇总文件失败：{exc}"}

    output_dir = Path(summary.get("output_dir", "")).resolve()
    log_file_value = summary.get("log_file", "")
    log_path = Path(log_file_value)
    if not log_path.is_absolute():
        log_path = output_dir / log_path.name
    if not log_path.is_file():
        return {"ok": False, "message": f"找不到导出日志：{log_path}"}
    if not output_dir.is_dir():
        return {"ok": False, "message": f"输出目录不存在：{output_dir}"}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 撤销日志也放到导出日志目录，输出目录始终只保留照片。
    undo_log_path = log_path.parent / f"undo_log_{timestamp}.csv"
    deleted = 0
    missing = 0
    mismatched = 0
    failed = 0
    details: list[dict] = []

    try:
        with open(log_path, "r", newline="", encoding="utf-8-sig") as log_handle:
            reader = csv.DictReader(log_handle)
            for row in reader:
                if (row.get("status") or "").strip() != "ok":
                    continue
                target_name = (row.get("target_name") or "").strip()
                if not target_name:
                    continue
                target = (output_dir / target_name).resolve()
                if target.parent != output_dir:
                    mismatched += 1
                    details.append({"target": target_name, "result": "路径异常"})
                    continue
                expected_size = int(row.get("size") or 0)
                if not target.exists():
                    missing += 1
                    details.append({"target": target_name, "result": "文件已不存在"})
                    continue
                try:
                    actual_size = target.stat().st_size
                    if expected_size and actual_size != expected_size:
                        mismatched += 1
                        details.append(
                            {
                                "target": target_name,
                                "result": f"大小不一致（{actual_size} != {expected_size}）",
                            }
                        )
                        continue
                    target.unlink()
                    deleted += 1
                    details.append({"target": target_name, "result": "已删除"})
                except OSError as exc:
                    failed += 1
                    details.append({"target": target_name, "result": f"删除失败：{exc}"})
    except Exception as exc:
        return {"ok": False, "message": f"读取日志失败：{exc}"}

    try:
        with open(undo_log_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["target", "result"])
            writer.writeheader()
            writer.writerows(details)
    except OSError:
        undo_log_path = None

    removed_dir = False
    try:
        if output_dir.is_dir() and not any(output_dir.iterdir()):
            output_dir.rmdir()
            removed_dir = True
    except OSError:
        pass

    result = {
        "ok": True,
        "deleted": deleted,
        "missing": missing,
        "mismatched": mismatched,
        "failed": failed,
        "output_dir": str(output_dir),
        "undo_log": str(undo_log_path) if undo_log_path else "",
        "removed_dir": removed_dir,
    }
    undo_summary_path = log_path.parent / f"undo_summary_{timestamp}.json"
    try:
        with open(undo_summary_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return result
