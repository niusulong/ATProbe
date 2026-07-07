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
from pathlib import Path

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
