"""MCP 集成测试共享夹具（vsim 服务 + 最小用例文件）.

注意：本目录**不放** ``__init__.py``——tests/integration 一旦成为包根，
本目录会被 import 系统当作顶层 ``mcp`` 包，遮蔽已安装的 mcp SDK（实测
``import mcp`` 解析到 ``tests/integration/mcp/__init__.py``）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

REPO_ROOT = Path(__file__).resolve().parents[3]

MINIMAL_CASE = """\
name: mcp_it
tags: [smoke]
steps:
  - command: "AT"
    port: VSIM0
    assert:
      - contains: "OK"
"""


@pytest.fixture
def case_file(tmp_path):
    f = tmp_path / "mcp_it.yaml"
    f.write_text(MINIMAL_CASE, encoding="utf-8")
    return f


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _can_spawn_piped_subprocess() -> bool:
    """探测当前环境是否允许子进程管道（受限沙箱会 EPERM）."""
    try:
        p = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (PermissionError, OSError):
        return False
    p.communicate(timeout=10)
    return True


CAN_PIPE = _can_spawn_piped_subprocess()
