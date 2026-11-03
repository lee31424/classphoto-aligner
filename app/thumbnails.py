"""异步缩略图加载：磁盘缓存 + 内存 LRU + 线程池。"""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap


class ThumbnailSignals(QObject):
    loaded = Signal(str, QImage)
    failed = Signal(str, str)


class ThumbnailTask(QRunnable):
    def __init__(
        self,
        key: str,
        path: Path,
        cache_dir: Path,
        size: QSize,
        signals: ThumbnailSignals,
    ):
        super().__init__()
        self.key = key
        self.path = path
        self.cache_dir = cache_dir
        self.size = size
        self.signals = signals
        self.setAutoDelete(True)

    def _cache_file(self) -> Path:
        try:
            stat = self.path.stat()
            source = f"{self.path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{self.size.width()}x{self.size.height()}"
        except OSError:
            source = f"{self.path}|missing"
        digest = hashlib.sha1(source.encode("utf-8", errors="replace")).hexdigest()
        return self.cache_dir / f"{digest}.jpg"

    def run(self):
        try:
            cache_file = self._cache_file()
            if cache_file.exists():
                cached = QImage(str(cache_file))
                if not cached.isNull():
                    self.signals.loaded.emit(self.key, cached)
                    return
                try:
                    cache_file.unlink()
                except OSError:
                    pass

            reader = QImageReader(str(self.path))
            reader.setAutoTransform(True)
            source_size = reader.size()
            if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
                # QSize.scaled 只接受 (size, mode)，不能传平滑变换参数。
                scaled_size = source_size.scaled(
                    self.size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                )
                reader.setScaledSize(scaled_size)

            image = reader.read()
            if image.isNull():
                self.signals.failed.emit(self.key, reader.errorString() or "无法读取图片")
                return

            if image.width() > self.size.width() or image.height() > self.size.height():
                image = image.scaled(
                    self.size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temp_file = cache_file.with_suffix(".tmp")
            if image.save(str(temp_file), "JPEG", 85):
                try:
                    os.replace(temp_file, cache_file)
                except OSError:
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass

            self.signals.loaded.emit(self.key, image)
        except Exception as exc:  # 线程里必须兜底，否则 QThreadPool 只打印异常
            self.signals.failed.emit(self.key, str(exc))


class ThumbnailManager(QObject):
    """按需加载缩略图，主线程只保存有限的 QPixmap。"""

    thumb_ready = Signal(str)
    thumb_failed = Signal(str)

    def __init__(
        self,
        cache_dir: Path,
        parent=None,
        thumb_size: QSize | None = None,
        max_memory_items: int = 500,
        threads: int = 4,
    ):
        super().__init__(parent)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.thumb_size = thumb_size or QSize(170, 160)
        self.max_memory_items = max(50, max_memory_items)
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._signals: dict[str, ThumbnailSignals] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, threads))

    def request(self, path: Path | str) -> QPixmap | None:
        key = str(path)
        pixmap = self._cache.get(key)
        if pixmap is not None:
            self._cache.move_to_end(key)
            return pixmap
        if key in self._pending or key in self._failed:
            return None

        signals = ThumbnailSignals()
        signals.loaded.connect(self._on_loaded)
        signals.failed.connect(self._on_failed)
        self._signals[key] = signals
        self._pending.add(key)
        self._pool.start(
            ThumbnailTask(key, Path(path), self.cache_dir, self.thumb_size, signals)
        )
        return None

    def _on_loaded(self, key: str, image: QImage):
        self._pending.discard(key)
        self._signals.pop(key, None)
        if image.isNull():
            self._failed.add(key)
            self.thumb_failed.emit(key)
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self._failed.add(key)
            self.thumb_failed.emit(key)
            return
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_memory_items:
            self._cache.popitem(last=False)
        self.thumb_ready.emit(key)

    def _on_failed(self, key: str, message: str):
        self._pending.discard(key)
        self._signals.pop(key, None)
        self._failed.add(key)
        self.thumb_failed.emit(key)

    def shutdown(self):
        self._pool.clear()
        self._pool.waitForDone(2000)
        self._cache.clear()
        self._pending.clear()
        self._signals.clear()
