"""M8 MCP 服务模块：测试能力经 MCP 协议开放给大模型（TSD §11（M8 MCP 服务））.

子模块：
    errors    — McpError 结构化错误（kind 枚举判定，全模块共用）
    urcbuffer — URC 订阅注册表（游标式环形缓冲）
    jobs      — JobManager 异步作业状态机（单并发 BUSY/进度快照/报告渲染）
    auth      — Bearer Token 认证（四级优先级加载 + 纯 ASGI 中间件）
    service   — McpService 设备门面（资源发现/手动调试/URC/批量测试编排）
    tools     — 13 个 MCP 工具注册（官方 SDK @server.tool，JSON 文本出参）
    server    — 服务装配：构建 MCPServer 与两种传输（stdio / HTTP serve）
"""
