"""M8 单测共享夹具（anyio backend 参数化）.

anyio 的 pytest 插件经 ``pytest11`` entry point 随包自动全局注册，无需（且 pytest 9
禁止）在非顶层 conftest 中声明 ``pytest_plugins``；此处仅覆盖 anyio_backend 夹具，
将 M8 异步测试限定为 asyncio 单 backend。
"""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
