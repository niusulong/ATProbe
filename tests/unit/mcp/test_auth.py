"""auth 单元测试：Token 加载优先级 + ASGI 中间件 401/放行."""

from __future__ import annotations

import logging
import types

import pytest

from atprobe.mcp import auth
from atprobe.mcp.auth import bearer_middleware, load_token


def test_load_token_priority(tmp_path, monkeypatch):
    tf = tmp_path / "secret.txt"
    tf.write_text("  file-token  \n", encoding="utf-8")
    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    assert load_token(token_file=None, token=None) is None
    assert load_token(token_file=str(tf), token=None) == "file-token"  # 首尾剥离
    assert load_token(token_file=None, token="cli-token") == "cli-token"
    # 全空白文件 → None
    ws = tmp_path / "ws.txt"
    ws.write_text("   \n\t \n", encoding="utf-8")
    assert load_token(token_file=str(ws), token=None) is None
    monkeypatch.setenv("ATPROBE_MCP_TOKEN", "env-token")
    assert load_token(token_file=None, token=None) == "env-token"
    # 优先级矩阵：file > token > env
    assert load_token(token_file=str(tf), token="cli-token") == "file-token"
    assert load_token(token_file=str(tf), token=None) == "file-token"
    assert load_token(token_file=None, token="cli-token") == "cli-token"

    with pytest.raises(FileNotFoundError):
        load_token(token_file=str(tmp_path / "absent.txt"), token=None)


def test_load_token_config_priority(tmp_path, monkeypatch):
    """四级契约（M8 §7）：--token-file > --token > env > 配置 mcp.token_file."""
    cf = tmp_path / "cfg-secret.txt"
    cf.write_text("cfg-token\n", encoding="utf-8")
    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    # config 单独给 → 生效
    assert load_token(token_file=None, token=None, config_token_file=str(cf)) == "cfg-token"
    # token 给 → token 胜
    assert load_token(token_file=None, token="cli-token", config_token_file=str(cf)) == "cli-token"
    # env 给 → env 胜
    monkeypatch.setenv("ATPROBE_MCP_TOKEN", "env-token")
    assert load_token(token_file=None, token=None, config_token_file=str(cf)) == "env-token"
    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    # config 文件缺失 → FileNotFoundError
    with pytest.raises(FileNotFoundError):
        load_token(token_file=None, token=None, config_token_file=str(tmp_path / "absent.txt"))
    # config 文件全空白 → None
    cws = tmp_path / "cfg-ws.txt"
    cws.write_text("  \n", encoding="utf-8")
    assert load_token(token_file=None, token=None, config_token_file=str(cws)) is None


def test_load_token_config_relative_anchored_to_workspace(tmp_path, monkeypatch):
    """F-18：config mcp.token_file 相对路径锚定到用户工作区（非 cwd）.

    工作区（开发态=仓库根、打包态=exe 同级）与 cwd 分置——只有走
    resolve_workspace_path 锚定才能找到文件；绝对路径原样。
    """
    import atprobe.infra.resources as resources

    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    (tmp_path / "token.txt").write_text("ws-token\n", encoding="utf-8")
    monkeypatch.setattr(resources, "app_root", lambda: tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # cwd 无 token.txt——证明锚定的是工作区而非 cwd
    assert load_token(token_file=None, token=None, config_token_file="token.txt") == "ws-token"
    # 绝对路径原样（resolve_workspace_path 语义），不受工作区影响
    abs_tf = elsewhere / "other.txt"
    abs_tf.write_text("abs-token\n", encoding="utf-8")
    assert load_token(token_file=None, token=None, config_token_file=str(abs_tf)) == "abs-token"


def test_load_token_path_is_directory(tmp_path):
    """Token 文件路径是目录 → ValueError（文案含"目录"），不裸抛
    IsADirectoryError/PermissionError（Windows 对目录 read_text 抛后者）."""
    d = tmp_path / "adir"
    d.mkdir()
    with pytest.raises(ValueError, match="目录"):
        load_token(token_file=str(d), token=None)
    with pytest.raises(ValueError, match="目录"):
        load_token(token_file=None, token=None, config_token_file=str(d))


def test_load_token_cli_token_stripped(monkeypatch):
    """--token strip（S-4）：首尾空白剥离；strip 后全空白 → 落到下一级 env."""
    long_token = "t" * 32  # ≥32：不混入强度 warning 断言面
    assert load_token(token_file=None, token=f"  {long_token}  \n") == long_token
    monkeypatch.setenv("ATPROBE_MCP_TOKEN", "env-token")
    assert load_token(token_file=None, token="   ") == "env-token"  # 空白视为未提供
    monkeypatch.delenv("ATPROBE_MCP_TOKEN", raising=False)
    assert load_token(token_file=None, token="\t\n ") is None


def test_load_token_weak_token_warns(caplog):
    """强度 warning（S-4）：<32 字符 → WARNING（含阈值与强随机建议）；≥32 静默."""
    weak = "w" * 31
    with caplog.at_level(logging.WARNING, logger="atprobe.mcp"):
        assert load_token(token_file=None, token=weak) == weak  # 仅告警不阻断
    assert "32" in caplog.text
    assert "secrets.token_hex(32)" in caplog.text
    strong = "s" * 32
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="atprobe.mcp"):
        assert load_token(token_file=None, token=strong) == strong
    assert caplog.text == ""


@pytest.fixture
def recorded_sleeps(monkeypatch):
    """桩掉 auth 模块引用的 asyncio（失败退避 sleep），记录延迟序列.

    只替换 atprobe.mcp.auth 命名空间内的 asyncio 引用，不碰全局；
    供中间件测试断言指数退避序列，同时避免真实 sleep 拖慢套件。
    """
    calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr(auth, "asyncio", types.SimpleNamespace(sleep=fake_sleep))
    return calls


@pytest.mark.anyio
async def test_middleware_401_and_pass(recorded_sleeps):
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
    assert (b"content-type", b"application/json") in sent[0]["headers"]
    assert sent[1]["body"] == b'{"error":"unauthorized"}'
    # 错误 Token → 401
    sent.clear()
    await mw(
        {"type": "http", "headers": [(b"authorization", b"Bearer wrong")]},
        receive,
        send,
    )
    assert sent[0]["status"] == 401
    # 非 ASCII 的 Authorization（latin-1 可编码原始字节）→ 401，而非 TypeError → 500
    sent.clear()
    await mw(
        {"type": "http", "headers": [(b"authorization", "Bearer café".encode())]},
        receive,
        send,
    )
    assert sent[0]["status"] == 401
    assert sent[1]["body"] == b'{"error":"unauthorized"}'
    # 3 次失败退避序列（S-4）：0.5s 起 ×2
    assert recorded_sleeps == [0.5, 1.0, 2.0]
    # 正确 Token → 放行到下游（且成功不产生退避）
    sent.clear()
    await mw(
        {"type": "http", "headers": [(b"authorization", b"Bearer secret")]},
        receive,
        send,
    )
    assert sent[0]["status"] == 200
    assert recorded_sleeps == [0.5, 1.0, 2.0]


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


@pytest.mark.anyio
async def test_middleware_wrong_token_lengths_equivalent(recorded_sleeps):
    """长度信号消除（S-4）：短/长错误凭据行为等价（均 401 + JSON 体）.

    双侧 SHA-256 后比较恒定 32 字节——不做时序断言，仅断言行为等价。
    """
    sent: list[dict] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    mw = bearer_middleware(app, "expected-secret-of-decent-length")
    wrongs = [b"Bearer x", b"Bearer ", b"Bearer " + b"x" * 300, "Bearer 密码".encode()]
    for wrong in wrongs:
        sent.clear()
        await mw({"type": "http", "headers": [(b"authorization", wrong)]}, receive, send)
        assert sent[0]["status"] == 401
        assert sent[1]["body"] == b'{"error":"unauthorized"}'


@pytest.mark.anyio
async def test_middleware_failure_backoff_cap_and_reset(monkeypatch):
    """失败限速（S-4）：0.5s 起 ×2 封顶 5s；退避先于 401；成功 reset 回 0.5s.

    推到连续 6 次失败验证封顶：第 5、6 次恒 5.0。
    """
    sent: list[dict] = []
    events: list[tuple[str, float | str]] = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        events.append(("send", str(msg.get("type", msg.get("status")))))
        sent.append(msg)

    async def fake_sleep(seconds: float) -> None:
        events.append(("sleep", seconds))

    monkeypatch.setattr(auth, "asyncio", types.SimpleNamespace(sleep=fake_sleep))

    mw = bearer_middleware(app, "secret")

    async def fail_once() -> None:
        sent.clear()
        await mw(
            {"type": "http", "headers": [(b"authorization", b"Bearer wrong")]},
            receive,
            send,
        )
        assert sent[0]["status"] == 401

    # 第 1 次失败：退避 sleep 先于 401 响应发送
    await fail_once()
    assert events == [
        ("sleep", 0.5),
        ("send", "http.response.start"),
        ("send", "http.response.body"),
    ]
    # 连续 3 次失败：[0.5, 1.0, 2.0]
    await fail_once()
    await fail_once()
    assert [e[1] for e in events if e[0] == "sleep"] == [0.5, 1.0, 2.0]

    # 成功 → reset（成功路径无退避）
    events.clear()
    sent.clear()
    await mw(
        {"type": "http", "headers": [(b"authorization", b"Bearer secret")]},
        receive,
        send,
    )
    assert sent[0]["status"] == 200
    assert [e for e in events if e[0] == "sleep"] == []

    # reset 后：第 4 次（本轮第 1 次）失败回到 0.5；连推 6 次封顶——第 5、6 次恒 5.0
    events.clear()
    for _ in range(6):
        await fail_once()
    assert [e[1] for e in events if e[0] == "sleep"] == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0]


def test_fail_limiter_thread_safe_sequence():
    """_FailLimiter 契约直测：序列 0.5→5.0 封顶；reset 清零（锁为防御，单线程验证语义）."""
    from atprobe.mcp.auth import _FailLimiter

    lim = _FailLimiter()
    assert [lim.delay_for_failure() for _ in range(7)] == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0, 5.0]
    lim.reset()
    assert lim.delay_for_failure() == 0.5
