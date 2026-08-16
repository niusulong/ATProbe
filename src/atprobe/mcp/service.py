"""M8 McpService 设备门面：把端口/用例/URC/作业粘成 MCP 工具的单一入口.

分层定位（TSD §11）：本模块是 mcp 入口层的领域门面——只做参数解析、
错误转译（→ McpError kind 枚举）与跨组件编排，不含协议细节（tools.py）
与业务状态机（JobManager / UrcRegistry）。

端口所有权（契约冻结）：start_run 不手动开关端口——引擎 scheduler 自己
open 差集、结束后 close 差集；open_port/close_port 是手动调试通道。
send_at 与作业互斥：引擎持有端口期间手动发送一律 BUSY。

原始日志（M8 修复）：常驻 RawLogger 注入 PortManager 与 JobManager——
作业日志由引擎按用例绑定（logs/<job_id>/<端口>/<用例名>.*，与 CLI 同款）；
手动通道经 rx/tx observer 落 manual 会话（logs/manual_*/<端口>/manual.*，
原始字节流，未经 urc_filter 剥离）。
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from atprobe.domain.case.models import Case, Step
from atprobe.domain.case.parser import CaseParseError
from atprobe.domain.suite import SuiteParseError
from atprobe.domain.suite.collect import (
    collect_case_paths,
    filter_by_tags,
    load_cases,
    read_suite_meta,
)
from atprobe.engine.config import EngineConfig
from atprobe.infra.config.appconfig import AppConfig, AppConfigError, parse_port_expr
from atprobe.infra.config.envconfig import EnvConfig, EnvConfigError, load_env_config_file
from atprobe.infra.resources import resolve_workspace_path, user_workspace
from atprobe.infra.serial.config import PortConfig
from atprobe.infra.serial.exceptions import SerialError
from atprobe.infra.serial.interfaces import ERROR_KIND_NONE
from atprobe.infra.serial.portmanager import PortManager
from atprobe.infra.serial.rawlog import RawLogger
from atprobe.infra.serial.vsim import VSIM_PORT, VsimPortManager
from atprobe.infra.version import current_version
from atprobe.mcp.errors import busy, device_error, invalid_input
from atprobe.mcp.jobs import JobManager
from atprobe.mcp.urcbuffer import UrcRegistry


def _display_name(c: Case) -> str:
    """用例展示名：参数化实例带 #N 后缀（与执行/报告一致）."""
    return c.name if c.param_index is None else f"{c.name}#{c.param_index}"


class McpService:
    """MCP 工具的设备门面（资源发现 / 手动调试 / URC 监控 / 批量测试）.

    vsim=True 时端口管理器为进程内虚拟模组（演示/联调），否则为真实
    PortManager。所有公开方法返回 JSON 可序列化的 dict 或 list[dict]，
    失败抛 McpError（tools.py 统一转 is_error=True 的结构化 JSON 文本）。

    线程模型（对齐 JobManager 锁纪律）：公开方法由 SDK 线程池并发调用；
    ``_port_urc_handles`` 的「检查已挂转发 + 挂接」/「pop + 摘除」两个
    check-then-act 段经 ``_urc_handles_lock`` 互斥——pm 层挂接/摘除是
    快操作（仅改内部 dict/列表）可在锁内，端口 open/close 等重活不持锁。
    """

    def __init__(
        self,
        app_cfg: AppConfig,
        vsim: bool = False,
        report_root: Path | str | None = None,
    ) -> None:
        self._app_cfg = app_cfg
        self._vsim = vsim
        # 常驻原始日志记录器（M8 修复：共享 PM 模式下引擎/手动通道此前不落盘——
        # connection 的 _raw_logger 来自 PM 构造参数，裸 PortManager() 为 None，
        # _bind_case_logs 只建目录不写文件）。进程生命周期内 start 一次，跨 job 复用；
        # 写线程 daemon，进程退出即止（每条记录写后即 flush，尾部丢失窗口毫秒级）。
        self._raw_logger = RawLogger()
        self._raw_logger.start()
        self.port_manager: PortManager | VsimPortManager = (
            VsimPortManager(raw_logger=self._raw_logger)
            if vsim
            else PortManager(raw_logger=self._raw_logger)
        )
        self.jobs = JobManager(
            report_root or resolve_workspace_path(app_cfg.report_dir),
            raw_logger=self._raw_logger,
        )
        self.urc_registry = UrcRegistry()
        # port → pm 层 URC 转发句柄（每端口只挂一次 urc_registry.feed）；
        # 挂接/摘除必须持 _urc_handles_lock（check-then-act 互斥，见类 docstring）
        self._port_urc_handles: dict[str, object] = {}
        # 手动调试通道原始日志（M8）：进程生命周期一个 manual 会话，
        # 每端口经 rx/tx observer 记原始字节流（真原始数据，未经 urc_filter 剥离）。
        # port → (tx_handle, rx_handle)；与 URC 转发共用 _urc_handles_lock。
        self._manual_log_handles: dict[str, tuple[object, object]] = {}
        self._manual_session = (
            f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
        )
        self._urc_handles_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 资源发现
    # ------------------------------------------------------------------
    def server_info(self) -> dict[str, Any]:
        """服务端信息：工作区与产物目录的**绝对路径** + 版本 + 运行形态.

        供远程编码机配合文件传输工具定位测试机上的用例/日志/报告——用例
        本就是测试机本地文件（MCP 按路径引用不传输），编码机把写好的用例
        放到 cases_dir、从 log_dir/report_dir 取回产物即可。cases/log 路径
        解析与 CLI/GUI 同一规则（resolve_workspace_path：相对 → 工作区锚定）；
        report_dir 取 JobManager 实际使用的根目录（构造参数 report_root 优先
        于 app_cfg.report_dir，M3 修复——报告真实落盘处以本值为准）。
        """
        return {
            "version": current_version(),
            "vsim": self._vsim,
            "workspace": str(user_workspace()),
            "paths": {
                "cases_dir": str(resolve_workspace_path(self._app_cfg.cases_dir)),
                "log_dir": str(resolve_workspace_path(self._app_cfg.log_dir)),
                "report_dir": str(self.jobs.report_root),
            },
        }

    def list_ports(self) -> list[dict[str, Any]]:
        """枚举可用串口：{name, description, connected}（connected 为本进程连接态）."""
        return [
            {
                "name": info.name,
                "description": info.description,
                "connected": self.port_manager.is_connected(info.name),
            }
            for info in self.port_manager.enumerate_ports()
        ]

    def list_cases(
        self, path: str | None = None, tags: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """列出用例（参数化已展开，name 带 #N；解析失败的文件跳过——对齐 CLI list 语义）.

        path 省略时用配置 cases_dir；tags 非空时按并集过滤。
        """
        base = Path(path) if path else resolve_workspace_path(self._app_cfg.cases_dir)
        case_files, _warnings = collect_case_paths(None, base)
        cases: list[Case] = []
        for f in case_files:
            try:
                cases.extend(load_cases([f]).cases)
            except (CaseParseError, SuiteParseError):
                continue
        return [
            {
                "name": _display_name(c),
                "tags": list(c.tags),
                "file": c.source_file or "",
            }
            for c in filter_by_tags(cases, tags or [], [])
        ]

    def list_suites(self, path: str | None = None) -> list[dict[str, Any]]:
        """列出套件（suite- 前缀文件，轻量元信息，不打开引用的用例文件）."""
        base = Path(path) if path else resolve_workspace_path(self._app_cfg.cases_dir)
        suite_files = sorted({*base.rglob("suite-*.yaml"), *base.rglob("suite-*.yml")})
        out: list[dict[str, Any]] = []
        for f in suite_files:
            meta = read_suite_meta(f)
            out.append(
                {
                    "name": meta.name or f.stem,
                    "description": meta.description or "",
                    "case_count": meta.case_count,
                    "tags": list(meta.tags),
                    "file": str(f),
                }
            )
        return out

    # ------------------------------------------------------------------
    # 手动调试
    # ------------------------------------------------------------------
    def open_port(self, port_expr: str) -> dict[str, Any]:
        """打开端口（手动调试通道）：COM3:115200:8N1 复合表达式.

        Raises:
            McpError: INVALID_INPUT——表达式非法；DEVICE_ERROR——打开失败
                （可能被 GUI 或其他程序占用）。
        """
        try:
            cfg = parse_port_expr(port_expr)
        except AppConfigError as exc:
            raise invalid_input(f"端口表达式无效：{exc}", port_expr=port_expr) from exc
        try:
            self.port_manager.open(cfg)
        except (SerialError, OSError) as exc:
            raise device_error(
                f"端口打开失败：{cfg.name}（{exc}；可能被 GUI 或其他程序占用）",
                port=cfg.name,
            ) from exc
        self._attach_manual_log(cfg.name)
        return {"name": cfg.name, "baud": cfg.baudrate, "frame": str(cfg.frame)}

    def _attach_manual_log(self, port: str) -> None:
        """挂接手动通道原始日志（幂等）：rx/tx observer → manual 会话日志.

        observer 记录的是串口原始字节流（含回显/GPS 噪声等，未经 urc_filter
        剥离），与 GUI 监控同机制（M6 §6.2）；不经 set_case_log，与作业的
        用例级日志互不干扰（作业运行时引擎自行绑定/覆盖用例日志路径）。
        真实 send_command 派发 TX/RX observer（connection L348/L546），故
        send_at 的收发全部被记录。
        """
        with self._urc_handles_lock:
            if port in self._manual_log_handles:
                return
            log_dir = resolve_workspace_path(self._app_cfg.log_dir)
            stem = self._raw_logger.begin_case(log_dir, self._manual_session, port, "manual")
            pm = self.port_manager

            def _tx_sink(data: bytes, s: Path = stem) -> None:
                self._raw_logger.log(s, "TX", data)

            def _rx_sink(data: bytes, s: Path = stem) -> None:
                self._raw_logger.log(s, "RX", data)

            tx_h = pm.subscribe_tx(port, _tx_sink)
            rx_h = pm.subscribe_rx(port, _rx_sink)
            self._manual_log_handles[port] = (tx_h, rx_h)

    def _detach_manual_log(self, port: str) -> None:
        """拆除手动通道日志 observer（close_port 时；幂等）."""
        with self._urc_handles_lock:
            handles = self._manual_log_handles.pop(port, None)
        if handles is not None:
            self.port_manager.unsubscribe_tx(handles[0])
            self.port_manager.unsubscribe_rx(handles[1])

    def close_port(self, port: str) -> dict[str, Any]:
        """关闭端口（幂等）；同时拆除该端口的 URC 转发与手动日志 observer.

        摘除段持 ``_urc_handles_lock``：与 subscribe_urc/open_port 的挂接段互斥，
        避免并发下漏拆/重复摘除同一转发；pm.unsubscribe_* 是快操作
        （仅改内部 dict/列表）放锁内可接受，close 本身是重活在锁外。
        """
        with self._urc_handles_lock:
            handle = self._port_urc_handles.pop(port, None)
            if handle is not None:
                self.port_manager.unsubscribe_urc(handle)
        self._detach_manual_log(port)
        self.port_manager.close(port)
        return {"closed": True, "port": port}

    def send_at(
        self,
        port: str,
        command: str,
        timeout: float | None = None,
        wait_urc: str | None = None,
    ) -> dict[str, Any]:
        """手动发送单条 AT 命令并等待完整响应.

        Raises:
            McpError: INVALID_INPUT——端口未开（先 open_port）；BUSY——作业运行中
                （detail.job_id 为占用中的作业）；DEVICE_ERROR——发送异常。
        """
        if not self.port_manager.is_connected(port):
            raise invalid_input(f"端口未打开：{port}（请先 open_port）", port=port)
        running = self.jobs.running_job_id()
        if running is not None:
            raise busy(f"作业运行中不可手动发送：{running}", job_id=running)
        try:
            resp = self.port_manager.send_command(port, command, timeout=timeout, wait_urc=wait_urc)
        except (SerialError, OSError) as exc:
            raise device_error(f"发送失败：{exc}", port=port) from exc
        out: dict[str, Any] = {"text": resp.text, "status": resp.status.value}
        if resp.error:
            out["error"] = resp.error
        if resp.error_kind != ERROR_KIND_NONE:
            out["error_kind"] = resp.error_kind
        return out

    # ------------------------------------------------------------------
    # URC 监控
    # ------------------------------------------------------------------
    def subscribe_urc(self, port: str, pattern: str | None = None) -> dict[str, Any]:
        """订阅端口 URC（可选正则过滤，匹配剥离首尾空白的整行文本）.

        端口首次订阅时把 ``urc_registry.feed`` 挂到 PortManager 的 URC 派发
        （每端口只挂一次，句柄存 ``_port_urc_handles``）；后续订阅共享同一转发。

        Raises:
            McpError: INVALID_INPUT——端口未开（先 open_port）或正则非法。
        """
        if not self.port_manager.is_connected(port):
            raise invalid_input(f"端口未打开：{port}（请先 open_port）", port=port)
        sub_id = self.urc_registry.subscribe(port, pattern)
        # 挂接段持锁：保护「检查 port 是否已挂转发 + 挂接」的 check-then-act
        # 窗口——并发 subscribe 不重复挂接，且与 close_port 的摘除段互斥。
        # pm.subscribe_urc 是快操作（仅改内部 dict/列表），放锁内可接受。
        with self._urc_handles_lock:
            if port not in self._port_urc_handles:
                try:
                    self._port_urc_handles[port] = self.port_manager.subscribe_urc(
                        port, self.urc_registry.feed
                    )
                except KeyError as exc:  # PortManager 对未开端口抛 KeyError（契约 4）
                    self.urc_registry.unsubscribe(sub_id)  # 回滚，不留悬挂订阅
                    raise invalid_input(f"端口未打开：{port}（请先 open_port）", port=port) from exc
        return {"subscription_id": sub_id}

    def poll_urc(self, subscription_id: str, cursor: int = 0, limit: int = 100) -> dict[str, Any]:
        """按游标增量拉取订阅事件.

        limit 先钳制为 ``max(1, limit)`` 再进注册表——limit ≤ 0 的负切片语义
        （Python 切片倒取尾部）不是调用方想要的（Task 3 审查冻结契约）。

        Raises:
            McpError: NOT_FOUND——订阅不存在或已退订。
        """
        return self.urc_registry.poll(subscription_id, cursor, max(1, limit))

    def unsubscribe_urc(self, subscription_id: str) -> dict[str, Any]:
        """退订（幂等）.

        有意不拆 PortManager 层的 URC 转发：同一端口可能还有其他订阅共享
        同一转发，转发保留到 close_port（close 时随端口一起拆除）。
        """
        self.urc_registry.unsubscribe(subscription_id)
        return {"unsubscribed": True}

    # ------------------------------------------------------------------
    # 批量测试
    # ------------------------------------------------------------------
    def _resolve_run_inputs(
        self,
        paths: list[str] | None,
        ports: list[str] | None,
        tags: list[str] | None,
    ) -> tuple[list[PortConfig], list[Case], tuple[Step, ...], tuple[Step, ...]]:
        """校验并组装运行输入：端口配置 + 过滤后用例 + 套件前后置步骤.

        Raises:
            McpError: INVALID_INPUT——无用例文件 / 用例解析失败 / 标签过滤后为空 /
                端口表达式非法 / 未指定端口。
        """
        base_paths = [Path(p) for p in paths] if paths else None
        case_files, _warnings = collect_case_paths(
            base_paths, resolve_workspace_path(self._app_cfg.cases_dir)
        )
        if not case_files:
            raise invalid_input(
                "未找到任何用例文件（检查 paths 参数或配置 cases_dir）", paths=paths or []
            )
        try:
            collected = load_cases(case_files)
        except (CaseParseError, SuiteParseError) as exc:
            raise invalid_input(f"用例解析失败：{exc}") from exc
        cases = filter_by_tags(list(collected.cases), tags or [], [])
        if not cases:
            raise invalid_input("标签过滤后无可用用例", tags=tags or [])

        if self._vsim:
            port_configs = [PortConfig(name=VSIM_PORT)]
        elif ports:
            try:
                port_configs = [parse_port_expr(p) for p in ports]
            except AppConfigError as exc:
                raise invalid_input(f"端口表达式无效：{exc}") from exc
        elif self._app_cfg.ports:
            port_configs = list(self._app_cfg.ports)
        else:
            raise invalid_input("未指定端口（ports 参数、配置文件 ports，或 vsim 模式）")
        # 噪声 URC 过滤注入所有端口（对齐 run.py：仅真实串口分支，vsim 不注入）
        if not self._vsim:
            port_configs = [replace(p, urc_filter=self._app_cfg.urc_filter) for p in port_configs]
        return port_configs, cases, collected.suite_setup, collected.suite_teardown

    def validate_run(
        self,
        paths: list[str] | None = None,
        ports: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """dry-run 语义校验：不执行，只报告将跑的用例与端口（及系统可用端口）."""
        port_configs, cases, _setup, _teardown = self._resolve_run_inputs(paths, ports, tags)
        result: dict[str, Any] = {
            "case_count": len(cases),
            "cases": [_display_name(c) for c in cases],
            "ports": [p.name for p in port_configs],
        }
        if not self._vsim:
            # 端口可用性提示（vsim 虚拟端口不枚举）；枚举失败不阻断，标记跳过
            try:
                result["ports_available"] = sorted(
                    {i.name for i in self.port_manager.enumerate_ports()}
                )
            except Exception:  # noqa: BLE001 - 提示性信息，枚举失败仅降级
                result["ports_available"] = "枚举失败，已跳过"
        return result

    def start_run(
        self,
        paths: list[str] | None = None,
        ports: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """启动异步测试作业（单并发），返回 {job_id}（job_id 即报告目录名）.

        端口所有权归引擎：本方法不碰端口（scheduler 自己 open 差集 close 差集）。
        session_id 由 JobManager 工厂注入（= job_id）。

        Raises:
            McpError: INVALID_INPUT——输入校验失败（见 _resolve_run_inputs / _load_env）；
                BUSY——已有作业在执行。
        """
        port_configs, cases, setup, teardown = self._resolve_run_inputs(paths, ports, tags)
        env_cfg = self._load_env()
        cfg = EngineConfig(
            ports=tuple(port_configs),
            cases=tuple(cases),
            suite_setup=setup,
            suite_teardown=teardown,
            step_timeout_default=self._app_cfg.step_timeout,
            pressure_pass_threshold=self._app_cfg.pressure_pass_rate_threshold,
            env_config=env_cfg,
            session_id="",  # JobManager 工厂按 job_id 注入
            log_dir=str(resolve_workspace_path(self._app_cfg.log_dir)),
        )
        job_id = self.jobs.start(
            build_engine_cfg=lambda jid: replace(cfg, session_id=jid),
            sender_factory=lambda: self.port_manager,
        )
        return {"job_id": job_id}

    def _load_env(self) -> EnvConfig | None:
        """加载环境配置（M7）：配置路径存在则加载，不存在返回 None.

        Raises:
            McpError: INVALID_INPUT——环境配置文件加载失败。
        """
        env_path = resolve_workspace_path(self._app_cfg.env_config)
        if not env_path.exists():
            return None
        try:
            return load_env_config_file(env_path)
        except EnvConfigError as exc:
            raise invalid_input(f"环境配置加载失败：{exc}") from exc

    def get_job(self, job_id: str) -> dict[str, Any]:
        """作业快照（状态/进度/summary/报告路径/最近事件），直接外抛 JobManager snapshot.

        Raises:
            McpError: NOT_FOUND——作业不存在或已被历史淘汰。
        """
        return self.jobs.snapshot(job_id)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """取消 running 作业（幂等：非 running 返回 cancelled=False）.

        Raises:
            McpError: NOT_FOUND——作业不存在或已被历史淘汰。
        """
        return {"cancelled": self.jobs.cancel(job_id)}
