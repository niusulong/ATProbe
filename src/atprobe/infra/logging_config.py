"""程序运行日志配置（诊断 + 长期运维）.

用标准库 logging + RotatingFileHandler，把程序运行的关键事件（启动/端口/引擎/异常）
落到 ``user_workspace()/logs/atprobe.log``（2MB×5 轮转）。后续 install_excepthook 全局
兜底子线程未捕获异常，避免引擎/读线程静默死亡表现为"UI 卡住"。

零新依赖（仅标准库）。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

from atprobe.infra.resources import user_workspace

# 日志格式：时间戳 [级别] [线程名 模块] 消息
_FORMAT = "%(asctime)s [%(levelname)s] [%(threadName)s %(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_MAX_BYTES = 2 * 1024 * 1024  # 2MB
_BACKUP_COUNT = 5


# 模块级日志目录定位（可被测试 monkeypatch 覆盖）
def _log_dir() -> Path:
    return user_workspace() / "logs"


def setup_logging(level: int = logging.INFO) -> Path:
    """配置根 logger：文件（轮转）+ 控制台 handler。返回日志文件路径。

    幂等：重复调用先移除旧 handler，避免日志重复写入。
    日志目录创建失败（权限/只读）时降级到系统 temp 目录，并 warning 记录。
    """
    root = logging.getLogger()
    # 幂等：清掉旧 handler（重复 setup 不重复挂）
    for h in root.handlers[:]:
        h.close()
        root.removeHandler(h)
    root.setLevel(level)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # 文件 handler：优先工作区 logs/，失败降级 temp
    log_path = _log_dir() / "atprobe.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        import tempfile

        log_path = Path(tempfile.gettempdir()) / "atprobe.log"
        # 降级也要先 log（用临时 stderr handler 兜底，此时文件 handler 还没建）
        logging.basicConfig(level=level, stream=sys.stderr, format=_FORMAT)
        logging.warning("日志目录 %s 不可写，降级到 %s", _log_dir(), log_path)
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        root.setLevel(level)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # 控制台 handler（开发态 / CLI 有用；GUI console=False 时无害）
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    return log_path


def install_excepthook(error_cb: Callable[[BaseException], None] | None = None) -> None:
    """安装全局异常钩子：threading.excepthook（子线程）+ sys.excepthook（主线程）。

    任何线程的未捕获异常都记 ERROR 日志（含完整 traceback），避免引擎/读线程静默死亡。
    可选 error_cb 把异常转发到 UI（调用方负责跨线程切主线程，如经 Qt Signal）。

    Args:
        error_cb: 收到异常对象时的回调（如经 progress 信号推 UI 弹窗）。None 表示仅记日志。
    """
    logger = logging.getLogger("atprobe.excepthook")

    def _thread_hook(args: Any) -> None:
        thread_name = getattr(args.thread, "name", "?")
        logger.error(
            "未捕获的线程异常 [%s]",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if error_cb is not None and args.exc_value is not None:
            try:
                error_cb(args.exc_value)
            except Exception:  # noqa: BLE001 - error_cb 失败不影响日志
                logger.error("error_cb 回调自身抛异常", exc_info=True)

    def _main_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: types.TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            # Ctrl+C 走默认行为（不记日志，避免开发态频繁打断污染）
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.error("未捕获的主线程异常", exc_info=(exc_type, exc_value, exc_tb))
        if error_cb is not None and exc_value is not None:
            try:
                error_cb(exc_value)
            except Exception:  # noqa: BLE001
                logger.error("error_cb 回调自身抛异常", exc_info=True)

    threading.excepthook = _thread_hook
    sys.excepthook = _main_hook
