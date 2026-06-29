"""mainwindow env_config_path 回退路径改造后的回归测试。

不启动 Qt，直接测 MainWindow.env_config_path 的回退逻辑。
由于该方法是实例方法，用 __new__ 跳过 __init__（避免 Qt 依赖），只绑所需属性。
"""

from __future__ import annotations

from pathlib import Path

from atprobe.infra.config.appconfig import AppConfig


def test_env_config_path_falls_back_to_builtin(tmp_path):
    """用户 env_config 不存在时，回退到内置 resources.builtin_resource('env.yaml')。"""
    from atprobe.gui.mainwindow import MainWindow

    cfg = AppConfig(env_config=str(tmp_path / "nonexistent.yaml"))
    mw = MainWindow.__new__(MainWindow)  # 跳过 __init__（避免 Qt）
    mw._app_config = cfg

    result = mw.env_config_path()
    assert result is not None
    p = Path(result)
    assert p.exists()
    assert p.name == "env.yaml"


def test_env_config_path_uses_user_file_when_exists(tmp_path):
    """用户 env_config 存在时，优先用用户文件。"""
    from atprobe.gui.mainwindow import MainWindow

    user_env = tmp_path / "my-env.yaml"
    user_env.write_text("env: {}\n", encoding="utf-8")

    cfg = AppConfig(env_config=str(user_env))
    mw = MainWindow.__new__(MainWindow)
    mw._app_config = cfg

    assert mw.env_config_path() == str(user_env)
