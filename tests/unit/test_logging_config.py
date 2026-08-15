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
    # 记录进入测试前的根 logger handler 快照（teardown 差集关闭的基准）
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
        # 差集关闭：只 close setup_logging 新挂的 handler；进入测试前已有的
        # （pytest 等）不 close、原样恢复——否则后台线程（如 M8 job daemon）
        # 后续写日志会命中已关闭的 handler，报 Logging error
        for h in list(root.handlers):
            if h not in saved_handlers:
                h.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_thread_excepthook_logs_exception(tmp_path, monkeypatch):
    """install_excepthook 后，触发 threading.excepthook 回调，日志文件含异常信息."""
    from atprobe.infra import logging_config

    monkeypatch.setattr(logging_config, "_log_dir", lambda: tmp_path / "logs")
    # 快照须在 setup_logging 之前取（差集关闭的基准）
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
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
        # 差集关闭：只 close 本测试新挂的 handler，进入前已有的原样恢复
        for h in list(root.handlers):
            if h not in saved_handlers:
                h.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)


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
        # 差集关闭：只 close setup_logging 新挂的 handler；进入测试前已有的
        # （pytest 等）不 close、原样恢复——否则后台线程（如 M8 job daemon）
        # 后续写日志会命中已关闭的 handler，报 Logging error
        for h in list(root.handlers):
            if h not in saved_handlers:
                h.close()
        root.handlers = saved_handlers
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
        # 差集关闭：只 close setup_logging 新挂的 handler；进入测试前已有的
        # （pytest 等）不 close、原样恢复——否则后台线程（如 M8 job daemon）
        # 后续写日志会命中已关闭的 handler，报 Logging error
        for h in list(root.handlers):
            if h not in saved_handlers:
                h.close()
        root.handlers = saved_handlers
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
        # 差集关闭：只 close setup_logging 新挂的 handler；进入测试前已有的
        # （pytest 等）不 close、原样恢复——否则后台线程（如 M8 job daemon）
        # 后续写日志会命中已关闭的 handler，报 Logging error
        for h in list(root.handlers):
            if h not in saved_handlers:
                h.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)
