"""stdio 集成测试：子进程拉起 ``atprobe mcp stdio --vsim`` + SDK 客户端全链路.

覆盖（M8 Task 8）：initialize → open_port → send_at（OK）→ start_run →
轮询 get_job 至 finished/passed==1（报告落盘）→ get_job 未知 id →
is_error + kind=NOT_FOUND。

子进程为真实 CLI 进程（``python -m atprobe mcp stdio --vsim -c <临时配置>``，
atprobe 为 editable 安装；PYTHONPATH 再兜底指向 src）。受限沙箱可能禁止
子进程管道（EPERM）——conftest 模块级探测 CAN_PIPE，不可用时整模块 skip
（在普通终端可跑），skip 不是 xfail：该环境下功能无法被验证而非预期失败。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from atprobe.infra.serial.vsim import VSIM_PORT
from conftest import CAN_PIPE, REPO_ROOT, payload, wait_finished

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not CAN_PIPE, reason="当前环境禁止子进程管道（如受限沙箱），在普通终端可跑"),
]


def _write_config(tmp: Path) -> Path:
    """写临时 atprobe.yaml：cases/reports/logs/env 全锚定 tmp（绝对路径原样生效）."""
    cfg = tmp / "atprobe.yaml"
    lines = [
        f"{key}: {(tmp / rel).as_posix()}"
        for key, rel in (
            ("cases_dir", "cases"),
            ("report_dir", "reports"),
            ("log_dir", "logs"),
            ("env_config", "noenv.yaml"),
        )
    ]
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cfg


async def test_stdio_full_flow(tmp_path: Path, case_file: Path) -> None:
    cfg = _write_config(tmp_path)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "atprobe", "mcp", "stdio", "--vsim", "-c", str(cfg)],
        cwd=REPO_ROOT,
        # SDK 侧 env 在默认环境之上合并（get_default_environment() | server.env），
        # 传全量 os.environ + PYTHONPATH：保留 PATH/SYSTEMROOT 等，防平台性意外
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            res = await session.call_tool("open_port", {"port_expr": f"{VSIM_PORT}:115200:8N1"})
            assert res.is_error is not True
            assert payload(res)["name"] == VSIM_PORT

            res = await session.call_tool("send_at", {"port": VSIM_PORT, "command": "AT"})
            assert res.is_error is not True
            assert "OK" in payload(res)["text"]

            res = await session.call_tool("start_run", {"paths": [str(case_file)]})
            job_id = payload(res)["job_id"]
            snap = await wait_finished(session, job_id)
            assert snap["status"] == "finished"
            assert snap["summary"]["passed"] == 1
            assert snap["summary"]["failed"] == 0
            assert snap["report_path"]
            assert Path(snap["report_path"]).exists()

            # 错误通道：未知 job → is_error=True + kind=NOT_FOUND
            res = await session.call_tool("get_job", {"job_id": "no-such-job"})
            assert res.is_error is True
            assert payload(res)["kind"] == "NOT_FOUND"
