"""auth 单元测试：Token 加载优先级 + ASGI 中间件 401/放行."""

from __future__ import annotations

import pytest

from atprobe.mcp.auth import bearer_middleware, load_token


def test_load_token_priority(tmp_path, monkeypatch):
    tf = tmp_path / "secret.txt"
    tf.write_text("  file-token  \n", encoding="utf-8")
    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    assert load_token(token_file=None, token=None) is None
    assert load_token(token_file=str(tf), token=None) == "file-token"  # 首尾剥离
    assert load_token(token_file=None, token="cli-token") == "cli-token"
    monkeypatch.setenv("ATPROBE_MCP_TOKEN", "env-token")
    assert load_token(token_file=None, token=None) == "env-token"
    # 显式参数优先于环境变量
    assert load_token(token_file=str(tf), token=None) == "file-token"
    assert load_token(token_file=None, token="cli-token") == "cli-token"

    with pytest.raises(FileNotFoundError):
        load_token(token_file=str(tmp_path / "absent.txt"), token=None)


@pytest.mark.anyio
async def test_middleware_401_and_pass():
    sent: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    mw = bearer_middleware(app, "secret")

    # 无 Authorization → 401
    await mw({"type": "http", "headers": []}, receive, send)
    assert sent[0]["status"] == 401
    # 错误 Token → 401
    sent.clear()
    await mw(
        {"type": "http", "headers": [(b"authorization", b"Bearer wrong")]},
        receive,
        send,
    )
    assert sent[0]["status"] == 401
    # 正确 Token → 放行到下游
    sent.clear()
    await mw(
        {"type": "http", "headers": [(b"authorization", b"Bearer secret")]},
        receive,
        send,
    )
    assert sent[0]["status"] == 200


@pytest.mark.anyio
async def test_middleware_non_http_passthrough():
    called: list[str] = []

    async def app(scope, receive, send):
        called.append(scope["type"])

    async def noop():
        return {"type": "http.request", "body": b""}

    mw = bearer_middleware(app, "secret")
    await mw({"type": "lifespan"}, noop, noop)
    assert called == ["lifespan"]
