"""带启动错误提示的入口，供 pythonw 双击启动使用。"""

from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path


def _show_error(message: str):
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            "照片名单对齐工具 - 启动失败",
            0x00000010,
        )
    except Exception:
        pass


def main():
    try:
        from main import main as app_main

        app_main()
    except SystemExit:
        raise
    except Exception:
        text = traceback.format_exc()
        log_path = Path(__file__).resolve().parent.parent / "logs" / "startup_error.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(text, encoding="utf-8")
        except Exception:
            pass
        _show_error(
            "工具启动失败，错误已写入日志：\n"
            f"{log_path}\n\n"
            f"{text[-3500:]}"
        )
        raise


if __name__ == "__main__":
    main()
