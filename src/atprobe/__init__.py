"""ATProbe — 串口 AT 命令自动化测试工具.

分层架构（见 docs/design/TSD-技术选型.md §4）：
    入口层 (cli/gui) → 引擎层 (engine) → 领域层 (domain) ← 基础层 (infra)

模块对应（见 docs/requirements/REQ-M*）：
    M1 串口通信管理  -> atprobe.infra.serial
    M2 测试用例定义  -> atprobe.domain.case
    M3 测试执行引擎  -> atprobe.engine
    M4 测试报告      -> atprobe.domain.report + atprobe.reporting
    M5 CLI 界面      -> atprobe.cli
    M6 UI 管理界面   -> atprobe.gui
    M7 测试环境配置  -> atprobe.engine.envconfig
"""

__version__ = "0.1.0"
