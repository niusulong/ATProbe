"""程序运行日志配置测试（logging_config）."""

from __future__ import annotations

import logging


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
