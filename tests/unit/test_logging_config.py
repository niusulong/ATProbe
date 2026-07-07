"""程序运行日志配置测试（logging_config）."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path


def test_setup_logging_configures_root_logger(tmp_path, monkeypatch):
    """setup_logging 后根 logger 含 FileHandler + StreamHandler，级别正确，返回的路径存在."""
    from atprobe.infra import logging_config

    # 把工作区定向到 tmp_path，避免污染真实 logs/
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    # 重置根 logger（清理其他测试可能挂的 handler）
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        log_path = logging_config.setup_logging(level=logging.INFO)
        assert log_path.exists()  # 文件已创建
        assert log_path.parent == tmp_path / "logs"
        # 根 logger 至少含一个 FileHandler 和一个 StreamHandler
        handler_types = [type(h) for h in root.handlers]
        assert any(issubclass(t, logging.FileHandler) for t in handler_types)
        assert any(issubclass(t, logging.StreamHandler) for t in handler_types)
        assert root.level == logging.INFO
    finally:
        # 恢复根 logger，避免污染其他测试
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


def test_thread_excepthook_logs_exception(tmp_path, monkeypatch):
    """install_excepthook 后，触发 threading.excepthook 回调，日志文件含异常信息."""
    from atprobe.infra import logging_config

    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    log_path = logging_config.setup_logging(level=logging.INFO)

    captured: list[BaseException] = []
    saved_thread_hook = threading.excepthook
    saved_sys_hook = sys.excepthook
    try:
        logging_config.install_excepthook(error_cb=captured.append)

        # 构造一个真实的异常并模拟线程异常回调
        try:
            raise RuntimeError("测试线程异常")
        except RuntimeError:
            exc_info = sys.exc_info()
        # structseq 需以序列构造（不支持关键字参数）
        fake_args = threading.ExceptHookArgs(
            (exc_info[0], exc_info[1], exc_info[2], threading.current_thread())
        )
        threading.excepthook(fake_args)

        # 日志文件含异常类型与消息
        content = log_path.read_text(encoding="utf-8")
        assert "RuntimeError" in content
        assert "测试线程异常" in content
        assert captured  # error_cb 被调用，收到异常对象
    finally:
        threading.excepthook = saved_thread_hook
        sys.excepthook = saved_sys_hook
        # 清理根 logger handler
        root = logging.getLogger()
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)


def test_setup_logging_falls_back_to_temp_on_permission_error(monkeypatch):
    """logs/ 创建失败（权限/路径非法）时降级到系统 temp 目录。"""
    import tempfile

    from atprobe.infra import logging_config

    # 跨平台稳定：直接让 Path.mkdir 抛 OSError，避免不同平台对非法路径行为差异
    def _raise_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise OSError("模拟无权限")

    monkeypatch.setattr(Path, "mkdir", _raise_mkdir)
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        log_path = logging_config.setup_logging(level=logging.INFO)
        # 降级到 temp
        assert str(log_path).startswith(tempfile.gettempdir())
        assert log_path.name == "atprobe.log"
    finally:
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


def test_setup_logging_is_idempotent(monkeypatch, tmp_path):
    """重复调 setup_logging 不重复挂 handler。"""
    from atprobe.infra import logging_config

    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        logging_config.setup_logging(level=logging.INFO)
        count_after_first = len(root.handlers)
        logging_config.setup_logging(level=logging.INFO)
        count_after_second = len(root.handlers)
        assert count_after_second == count_after_first  # 不重复挂
    finally:
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


def test_setup_logging_debug_level(monkeypatch, tmp_path):
    """setup_logging(level=DEBUG) 后根 logger 级别为 DEBUG."""
    from atprobe.infra import logging_config
    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        logging_config.setup_logging(level=logging.DEBUG)
        assert root.level == logging.DEBUG
    finally:
        for h in root.handlers[:]:
            h.close()
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
