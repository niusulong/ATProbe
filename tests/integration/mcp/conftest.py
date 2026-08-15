"""MCP 集成测试共享夹具与公共 helper（vsim 服务 + 最小用例 + 工具结果解析）.

注意：本目录**不放** ``__init__.py``——tests/integration 一旦成为包根，
本目录会被 import 系统当作顶层 ``mcp`` 包，遮蔽已安装的 mcp SDK（实测
``import mcp`` 解析到 ``tests/integration/mcp/__init__.py``）。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from mcp import ClientSession

pytest.importorskip("mcp")

REPO_ROOT = Path(__file__).resolve().parents[3]

# 最小用例单一模板（case_file 夹具与 test_http 的 100 用例批量生成共用；{name} 占位）
MINIMAL_CASE_TEMPLATE = """\
name: {name}
tags: [smoke]
steps:
  - command: "AT"
    port: VSIM0
    assert:
      - contains: "OK"
"""


def make_case_yaml(directory: Path, name: str) -> Path:
    """在 directory 写入名为 name 的最小用例 YAML，返回文件路径."""
    f = directory / f"{name}.yaml"
    f.write_text(MINIMAL_CASE_TEMPLATE.format(name=name), encoding="utf-8")
    return f


@pytest.fixture
def case_file(tmp_path):
    return make_case_yaml(tmp_path, "mcp_it")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def payload(res: Any) -> dict[str, Any]:
    """解析 call_tool 出参：错误文本带 ``Error executing tool <name>: `` 前缀，从首个 ``{`` 起取 JSON.

    断言失败信息携带原始结果/文本，便于定位 SDK 行为变化。
    """
    assert res.content, f"空 content: {res!r}"
    text = res.content[0].text
    pos = text.find("{")
    assert pos >= 0, f"非 JSON 工具结果: {text!r}"
    return json.loads(text[pos:])


async def wait_finished(
    session: ClientSession, job_id: str, timeout: float = 30.0
) -> dict[str, Any]:
    """轮询 get_job 至终态（0.2s 间隔；超时抛 AssertionError）."""
    deadline = time.monotonic() + timeout
    while True:
        res = await session.call_tool("get_job", {"job_id": job_id})
        assert res.is_error is not True
        snap = payload(res)
        if snap["status"] != "running":
            return snap
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job_id} 未在 {timeout}s 内结束")
        await asyncio.sleep(0.2)


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
    try:
        p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return False
    return True


CAN_PIPE = _can_spawn_piped_subprocess()
