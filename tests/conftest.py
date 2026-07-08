"""pytest 共享夹具."""

from __future__ import annotations

from pathlib import Path

import pytest

from atprobe.infra.config.envconfig import EnvConfig, load_env_config
from atprobe.infra.serial.fakeserial import FakePortManager
from atprobe.infra.serial.interfaces import Response

EXAMPLES_ENV = """
ftp:
  host: 192.168.1.100
  port: 21
  user: test
  password: test123
default:
  apn: cmnet
fota:
  version_a: V1.0.0
  version_b: V2.0.0
  pkg_ab: fota.bin
"""


@pytest.fixture
def env() -> EnvConfig:
    return load_env_config(EXAMPLES_ENV, source="test-env")


@pytest.fixture
def fake_port() -> FakePortManager:
    return FakePortManager(sleep=lambda s: None)


@pytest.fixture
def ok_response() -> Response:
    return Response(text="OK\r\n")


@pytest.fixture
def examples_dir() -> Path:
    return Path(__file__).parent.parent / "examples"


# ---------------------------------------------------------------------------
# Qt 应用实例夹具：供需要构造 QWidget 的单测/集成测试共用。
# 模块级单例（QApplication 全进程唯一），避免每个测试文件各自定义导致冲突。
# ---------------------------------------------------------------------------
@pytest.fixture
def qapp():  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
