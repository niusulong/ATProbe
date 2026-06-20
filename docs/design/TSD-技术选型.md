# ATProbe 技术选型文档（TSD）

> 版本：v0.1（草稿）
> 日期：2026-06-20
> 状态：草稿
> 范围：覆盖 M1-M7 全模块的全局技术选型与架构总览。模块内部实现细节留待 `DSD-{模块}-详细设计.md` 阶段
> 依赖：PRD-总体需求 v1.3、REQ-M1 v1.7、REQ-M2 v1.4、REQ-M3 v0.2、REQ-M4 v0.2、REQ-M5 v0.2、REQ-M6 v0.3、REQ-M7 v0.1

---

## 1. 设计目标

### 1.1 工具定位回顾

ATProbe 是面向嵌入式通信模组（蜂窝/WiFi/蓝牙）的**本地串口 AT 命令自动化测试工具**，同时提供 CLI（M5）与桌面 GUI（M6）两个入口，两者共享同一套引擎（M1-M4 + M7）。本工具的负载特征是：

- **串口 I/O 密集型**，非 CPU 密集型。绝大部分运行时间在"等待设备响应"（AT 响应数十毫秒到数秒），工具自身只做发送/接收/解析的薄逻辑。
- **串行执行模型**（M3 §1/§6）：一个时刻只有一个步骤在执行，端口间无并发竞争。并行测试走多进程实例外部化。
- **本地单用户工具**，无远程执行、无网络服务面、无并发用户。

### 1.2 技术选型的核心目标（按优先级）

| 优先级 | 目标 | 衡量标准 |
|--------|------|---------|
| P0 | **稳定性优先** | 断连/超时/异常不崩溃，资源正确释放，长期运行无内存泄漏（PRD §9.1） |
| P0 | **AI 开发友好** | 选型须最大化 AI 一次性生成正确代码的能力：领域生态成熟、语言 AI 熟练、反馈循环快（无需编译等待）、单语言栈 |
| P1 | **可测试性** | 串口层可 mock，引擎逻辑可脱离硬件单测，支持自动化测试金字塔 |
| P1 | **可扩展性** | 新增报告格式、设备类型、GUI 选项卡类型、环境配置组无需改主框架（PRD §9.2、M6 §2.3/§10.5、M7 §5） |
| P1 | **跨平台** | Win / Linux / macOS 三平台（PRD §10.1、M6 §10.1） |
| P2 | **性能达标** | 工具收发开销 < 10ms，4 端口管理不卡顿（PRD §9.4）。I/O 瓶颈在外部设备，语言运行时非瓶颈 |
| P2 | **现代美观 UI** | 扁平化、浅深主题、矢量图标、等宽字体、MDI 选项卡（M6 §2.2/§2.3） |

### 1.3 非目标（明确不追求）

- 不追求极致运行时性能（非计算密集场景，Python 足够）。
- 不追求最小分发体积（本地桌面工具，PyInstaller 打包体积可接受）。
- 不追求 Web 远程访问（PRD §8.2 已确认桌面 GUI，不实现远程执行）。
- 不追求高并发服务能力（本地单用户，串行执行模型）。

---

## 2. 核心设计原则

整个工具的设计须遵循以下原则。这些原则既是技术选型的判据，也是后续 DSD 与编码的统一约束。

### 2.1 SOLID 原则的应用

| 原则 | 在 ATProbe 的落地 |
|------|-----------------|
| **单一职责（SRP）** | 七个模块各司其职：M1 只管串口字节流、M2 只定义用例数据结构、M3 只编排执行、M4 只渲染报告、M5/M6 只是薄入口、M7 只管全局配置。模块内部再按职责拆类（如 M1 拆 Connection/Receiver/Logger/URCDispatcher） |
| **开闭（OCP）** | 通过注册表/插件机制对扩展开放：M4 报告格式注册表（HTML/Console/JUnit 预留）、M6 选项卡类型注册表（manual_debug/case_execute/...，M6 §2.3）、M7 配置组动态加载（M7 §5）。新增能力 = 注册新类型 + 实现接口，不改主框架 |
| **里氏替换（LSP）** | 所有可替换部件以抽象接口（Python `Protocol`/ABC）定义契约：串口层 `ISerialPort`、报告渲染器 `IReporter`、选项卡视图 `ITabView`。测试用 Fake 实现替换真实实现，契约行为一致 |
| **接口隔离（ISP）** | 接口按消费方需要细分，不造胖接口。例如 M3 引擎对 M1 的依赖拆为 `ICommandSender`（发送命令）+ `IDataStreamSender`（发送数据流）+ `IConnectionEvents`（连接事件订阅），而非一个大 `ISerial` |
| **依赖倒置（DIP）** | 高层模块不依赖低层具体实现，均依赖抽象接口。M3 依赖 `ISerialPort` 抽象而非 pyserial 具体类；M5/M6 依赖 `IEngine` 抽象。依赖通过构造注入，便于测试替换与未来换库 |

### 2.2 分层架构

```
┌──────────────────────────────────────────────┐
│  入口层 (Entry)   M5 CLI · M6 GUI             │  薄入口，只做翻译/编排/渲染
├──────────────────────────────────────────────┤
│  引擎层 (Engine)  M3 执行引擎 · M7 环境配置    │  编排与领域逻辑核心
├──────────────────────────────────────────────┤
│  领域层 (Domain)  M2 用例模型 · M4 报告模型    │  纯数据结构与规则，无 I/O
├──────────────────────────────────────────────┤
│  基础层 (Infra)   M1 串口通信 · 文件/日志/时间 │  外设与系统资源
└──────────────────────────────────────────────┘
```

**分层规则：**

- **依赖方向单向向下**：上层依赖下层，下层不感知上层。M1 不 import M2/M3，M3 不 import M5/M6。
- **跨层通信走接口**：层间依赖通过 §5 定义的抽象接口，不依赖具体类。
- **领域层纯净**：M2（用例数据模型）、M4（报告数据模型）是纯数据结构 + 规则，不持有任何 I/O 资源，可脱离硬件完全单测。
- **横向解耦**：M1-M7 之间的横向依赖也走接口，不直接 import 对方实现。依赖关系图见 §4.2。

### 2.3 串行优先（简化原则）

充分利用 M3 已确立的"串行执行"前提，最大化简化设计：

- **引擎主循环单线程**：一个时刻一个步骤，无锁、无竞态、无线程安全问题。变量池、上下文均为单线程访问，无需同步原语。
- **并发只用在三个明确隔离的点**：URC 后台监听线程、串口字节读取线程、GUI 主线程。这三者通过 §6 定义的线程安全通道通信，边界清晰。
- **避免过早抽象并发**：不引入 asyncio、不引入线程池做用例并行——需求已明确不需要（M3 §2.3 并行外部化为多进程）。

### 2.4 可测试性优先

- **依赖注入**：所有 I/O 资源（串口、文件、时钟）通过构造函数注入，测试可传 Fake。
- **纯函数化领域逻辑**：模板替换、正则 extract、条件表达式求值、断言判定、结果聚合等均实现为无副作用的纯函数/方法，单测无需任何 mock。
- **接口驱动**：§5 每个跨模块依赖都有抽象接口，测试用 Fake 实现替换。
- **测试金字塔**：详见 §8，单测（领域逻辑，占比最大）> 集成测（引擎 + Fake 串口）> 端到端测（真实硬件，少量）。

### 2.5 可扩展性契约

三类已识别的扩展点，均以注册表/插件机制承载，新增不改主框架：

| 扩展点 | 机制 | 详见 |
|--------|------|------|
| 报告格式 | `IReporter` 注册表，M4 按格式名分发 | M4 §1、本文 §5.3 |
| GUI 选项卡类型 | `ITabView` 注册表，M6 侧边栏/选项卡栏作为稳定外壳 | M6 §2.3/§10.5 |
| 环境配置组 | YAML 顶层键即组，加载器动态遍历，UI 按组动态渲染 | M7 §3/§5/§7 |

### 2.6 失败导向与可观测

- **结构化错误**：所有错误用自定义异常类（带错误码、上下文），不抛裸字符串。M1 §8 各异常类型有明确策略。
- **失败可追溯**：M3 产出结构化 `ExecutionResult`，M4 报告失败用例直接关联 M1 原始日志（M4 §4.5/§4.6）。
- **原始日志全留**：M1 §7 收发字节流全量落盘（HEX+TEXT），事后可回放。

---

## 3. 技术栈选型

### 3.1 核心技术栈总览

| 层 | 技术 | 版本基线 | 选型理由 |
|----|------|---------|---------|
| **语言** | Python | 3.11+ | AI 最熟练的语言；领域生态最强；动态反馈无需编译；3.11 起性能显著提升且支持现代语法（match-case、`Self`、改进异常组）。用 `mypy --strict` + 类型注解补足类型安全 |
| **串口库** | pyserial | 3.5+ | AT/串口测试领域事实标准，AI 训练数据统治级，跨平台成熟，支持自定义波特率/帧格式/流控/超时/二进制读写。M1 全部能力（连接级/行为级参数、数据流分块、热插拔检测）均能覆盖 |
| **GUI 框架** | PySide6（Qt6 官方 Python 绑定） | 6.6+ (LGPL) | 原生支持 MDI（`QMdiArea`/选项卡视图）、QSS 样式表（圆角/阴影/动效）、SVG 矢量图标、浅深主题、信号槽事件机制。Qt 是 SSCOM 类串口工具主流栈，AI 对其 API 熟悉。LGPL 协议可商用 |
| **CLI 框架** | Typer（基于 Click） | 0.9+ | 类型注解驱动声明式 CLI，AI 生成质量高；自动生成 `--help`；子命令/选项/复合表达式（`--port COM3:115200:8N1`）易实现；与 Pydantic 配置模型契合 |
| **配置/用例解析** | ruamel.yaml | 0.18+ | round-trip YAML（保留注释/顺序），适合 M2 用例、M5 `atprobe.yaml`、M7 `env.yaml` 的人工编辑+程序读写场景；比 PyYAML 更利于"人编辑后程序写回不丢格式" |
| **数据模型** | Pydantic | 2.x | 类型安全的配置/数据模型校验，错误信息清晰（行号+原因，满足 M5 §3.5 解析失败提示）；M2 用例 schema、M5 配置、M7 环境配置均用其建模 |
| **模板替换** | 不用 Jinja2，自研极简替换器 | — | M2/M7 的 `{{var}}`/`{{group.param}}` 语义简单（仅字符串替换 + 作用域查找），自研 < 50 行，避免 Jinja2 模板注入风险与过度能力。详见 §5.6 |
| **正则** | 标准库 `re` | — | M2 extract、URC 匹配均用标准库，无需引入第三方 |
| **测试框架** | pytest | 8.x | AI 最熟练、生态最丰富；参数化、fixture、覆盖率（pytest-cov）齐全；`FakeSerial` 等 fixture 易写 |
| **类型检查** | mypy（strict） | 1.x | 静态类型门禁，配合类型注解在 CI 拦截类型错误，弥补动态类型短板 |
| **代码风格** | ruff（lint + format） | 0.4+ | 一体化 lint+format，极快，替代 black+isort+flake8 全家桶 |
| **日志** | 标准库 logging + structlog（可选） | — | 应用日志用 logging；若需结构化日志再引入 structlog。M1 原始日志是自研格式（HEX+TEXT，M1 §7.2），不走 logging |
| **HTML 报告渲染** | Jinja2（仅报告侧） | 3.x | M4 报告是固定的纯静态 HTML 模板，Jinja2 渲染 `ExecutionResult` → HTML。模板不可信（无用户输入注入风险），此场景用 Jinja2 安全 |
| **打包分发** | PyInstaller（onefile/onedir） | 6.x | 打包成单可执行文件或目录，跨平台。第一阶段先 onedir（启动快、调试友好），稳定后可切 onefile |
| **构建/任务** | PEP 621 `pyproject.toml` + uv（或 hatch） | — | 现代化项目元数据与依赖管理，uv 解析安装极快。CI 用 `uv sync` |

### 3.2 为何选 Python + PySide6（核心论据）

**首要判据：AI 开发友好度。** 本项目主要靠 AI 开发，故"AI 一次性生成正确代码的能力"是选型的第一性原理。分解：

1. **领域生态决定 AI 生成质量上限**。AT/串口测试自动化领域，`pyserial` 是绝对事实标准，训练数据统治级。AI 生成"串口收发、AT 响应完整性判定、URC 分流、断连重连、分块发送"等 M1/M3 核心逻辑时，用 pyserial 几乎即用即对；换 Rust/Go 串口库则要反复试错，AI 熟练度与生成质量显著下降。
2. **Python 是 AI 最熟练的语言**，训练数据量最大、代码自然度与正确率最高。
3. **动态反馈无需编译**，迭代反馈循环最快——这对 AI"生成→运行→修正"的闭环至关重要，Rust/C++ 的编译等待会拖慢这个循环。
4. **PySide6 满足 M6 现代化要求**：Qt6 的 QSS/SVG/动画/MDI/主题切换足够，是 SSCOM 类串口工具的主流栈。
5. **单语言栈**：M1-M7 全 Python，CLI 与 GUI 同进程复用引擎（M6 §1.3），AI 不需跨语言切换。
6. **动态类型短板可补**：`mypy --strict` + 类型注解 + pytest 测试形成"AI 写实现 + AI 写测试 + CI 验证"的高效闭环。

**代价（已权衡可接受）：**
- 分发体积偏大（PyInstaller onedir 约 80-120MB）。本地桌面工具可接受。
- 运行时性能非顶尖，但本场景 I/O 瓶颈在外部设备，Python 足够（§7 性能预算）。
- GIL 限制真并行，但本工具的并发模型（§6）刻意避免了 CPU 并行需求，URC/串口读是 I/O 阻塞型，GIL 不构成瓶颈。

**对比淘汰的其他方案：**

| 方案 | 淘汰理由 |
|------|---------|
| Rust + Tauri | 串口 crate 较新、AI 熟练度低、编译慢拖慢 AI 反馈循环、开发速度偏慢。优势（极致性能/体积）在本场景收益有限 |
| Go + Wails | 串口库较新、AT 测试自动化生态弱于 Python、GUI 走 Web 前端增加前端开发负担 |
| C++ + Qt6 | 开发慢、构建/分发复杂、迭代成本高，对 AI 开发不友好 |
| TypeScript + Electron | Web UI 对 AI 最友好，但 Electron 体积大/启动慢、主渲染进程 IPC 复杂、serialport(npm) 在 AT 领域生态不如 pyserial。本地轻量串口工具不理想 |

### 3.3 版本与依赖策略

- **Python 3.11+**：用 3.11 起的性能改进与现代语法。不锁定过新（如 3.13），保证 PyInstaller/PySide6 等生态兼容。
- **依赖最小化**：核心运行时依赖严格控制在上述清单内，避免依赖膨胀。开发依赖（pytest/mypy/ruff）单独分组。
- **版本锁定**：用 `uv.lock` 锁定全版本，保证 AI 多次生成/CI/本地环境一致。

---

## 4. 架构总览

### 4.1 分层架构图

```
┌─────────────────────────────────────────────────────────────────┐
│  入口层 Entry                                                    │
│  ┌──────────────────────┐    ┌──────────────────────────────┐   │
│  │  M5 CLI (Typer)       │    │  M6 GUI (PySide6/Qt6)        │   │
│  │  - 参数解析/配置加载   │    │  - MDI 选项卡外壳            │   │
│  │  - 事件订阅/控制台渲染 │    │  - 选项卡类型注册表          │   │
│  │  - 报告触发            │    │  - 端口/用例/监控/报告视图    │   │
│  └──────────┬───────────┘    └──────────────┬───────────────┘   │
└─────────────┼────────────────────────────────┼──────────────────┘
              │ IEngine                        │ IEngine
              ▼                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  引擎层 Engine                                                   │
│  ┌────────────────────────────────┐  ┌────────────────────────┐ │
│  │  M3 执行引擎                    │  │  M7 环境配置           │ │
│  │  - 串行调度器                   │←→│  - env.yaml 加载       │ │
│  │  - 步骤执行器(retry/poll/when)  │  │  - 模板上下文注入      │ │
│  │  - 失败处理(on_failure)         │  │  - 引用校验            │ │
│  │  - 结果聚合                     │  │  - (只读快照)          │ │
│  │  - 进度事件发射                 │  │                        │ │
│  └──────┬──────────────┬──────────┘  └────────────────────────┘ │
│         │              │                                         │
│         │ ICaseLoader  │ ISerialPort (ICommandSender/...)        │
│         ▼              ▼                                         │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│  领域层 Domain (纯数据结构 + 规则，无 I/O)                        │
│  ┌────────────────────────────────┐  ┌────────────────────────┐ │
│  │  M2 用例模型                    │  │  M4 报告模型           │ │
│  │  - Case/Step/Assert/Extract     │  │  - ExecutionResult     │ │
│  │  - YAML schema (Pydantic)       │  │  - Summary/CaseResult  │ │
│  │  - 模板替换器(纯函数)           │  │  - IReporter 注册表    │ │
│  │  - 条件表达式求值(纯函数)       │  │  - HTML/Console 渲染   │ │
│  │  - 断言求值(纯函数)             │  │                        │ │
│  └────────────────────────────────┘  └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│  基础层 Infra                                                    │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  M1 串口通信 (pyserial)                                     │ │
│  │  - SerialConnection (连接级参数)                            │ │
│  │  - ResponseReceiver (后台读线程 + 完整性判定)               │ │
│  │  - URCDispatcher (URC 分流)                                 │ │
│  │  - DataStreamSender (分块发送)                              │ │
│  │  - RawLogger (HEX+TEXT 落盘)                                │ │
│  │  - PortManager (多端口、热插拔、重连)                        │ │
│  └────────────────────────────────────────────────────────────┘ │
│  文件系统 · 时间服务 · 应用日志(logging)                         │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 模块依赖关系图

依赖方向严格单向向下。横向依赖走抽象接口（见 §5）。

```
         ┌──── M5 (CLI) ────┐         ┌──── M6 (GUI) ────┐
         │                   │         │                   │
         │   (薄入口，编排)   │         │   (薄入口，渲染)   │
         └────────┬──────────┘         └────────┬──────────┘
                  │                              │
                  └──────────┬───────────────────┘
                             │ IEngine / ICaseLoader / IReporter
                             ▼
                       ┌──── M3 (引擎) ────┐         ┌──── M7 (环境配置) ────┐
                       │   (编排核心)       │←──────→│   (只读配置注入)       │
                       └──┬─────────────┬──┘         └───────────────────────┘
                          │             │
                ICaseRepo │             │ ISerialPort (ICommandSender/...)
                          ▼             ▼
                   ┌──── M2 (用例) ────┐         ┌──── M1 (串口) ────┐
                   │   (数据模型+规则)  │         │   (pyserial I/O)   │
                   └───────────────────┘         └─────────┬──────────┘
                                                          │
                   ┌──── M4 (报告) ────┐                   │
                   │   (渲染模型)       │←── 引用 M1 原始日志路径
                   └───────────────────┘
```

**关键依赖说明：**

| 依赖 | 性质 | 备注 |
|------|------|------|
| M5/M6 → M3 | 引擎控制（`IEngine.start/stop`） | 进程内直接调用（M6 §1.3） |
| M3 → M1 | 串口操作（`ISerialPort` 族接口） | 经抽象接口，测试可替换为 Fake |
| M3 → M2 | 读取用例数据模型 | M2 是纯数据结构 |
| M3 ↔ M7 | 加载环境配置、注入模板上下文 | M7 启动时一次性加载为只读快照 |
| M3 → M4 | 产出 `ExecutionResult` 给报告 | M3 不依赖 M4 的渲染实现，只产数据 |
| M4 → M1 | 引用原始日志文件路径 | 仅路径引用，不调用 M1 |
| M2/M7 → (模板替换器) | M7 是 M2 模板替换的兜底层数据源 | 模板替换器属 M2 领域逻辑 |

> M2 与 M4 同属领域层，互不依赖。M5 与 M6 互不依赖（平级入口）。

### 4.3 进程与部署模型

```
┌─────────────────────────────────────────┐
│  单一 Python 进程                        │
│  ┌───────────────────────────────────┐  │
│  │  主线程                            │  │
│  │  - CLI: Typer 事件循环             │  │
│  │  - 或 GUI: Qt 事件循环             │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │  引擎线程（执行期间）              │  │  M3 start 后在此跑用例串行循环
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │  串口读线程 × N（每端口一个）       │  │  M1 后台读字节 + 完整性判定
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │  URC 分发线程（可选，合并到读线程）  │  │  M1 §6 URC 监听
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

- **单进程多线程**：CLI 模式与 GUI 模式均为单进程。线程模型见 §6。
- **并行外部化**：需要并行测试多端口 → 启动多个工具进程实例，各自绑定端口与用例（M3 §2.3）。进程间完全隔离，无 IPC。
- **CLI 与 GUI 互斥运行**：同一时刻一个进程要么是 CLI 要么是 GUI，由启动入口决定。两者共享全部引擎代码。

---

## 5. 接口契约规范

### 5.1 接口设计约定

- 所有跨模块依赖以 **Python `Protocol`（结构化子类型）或 `abc.ABC`** 定义，放各模块的 `interfaces.py`。
- 优先用 `Protocol`（PEP 544）：消费方不需继承显式声明，便于测试写 Fake（鸭子类型）。
- 接口按消费方需要**细分**（ISP），避免胖接口。
- 接口方法签名用完整类型注解，`mypy --strict` 校验。
- 数据传递用领域层的**不可变数据类**（`@dataclass(frozen=True)` 或 Pydantic 模型），避免可变共享状态。

### 5.2 关键接口清单（核心契约，签名示意）

> 以下为接口契约的**意图与形状**示意，精确签名（参数名/异常类型/返回结构）在 DSD 阶段细化。

#### 5.2.1 引擎控制接口（M5/M6 → M3）

```python
# M3 对外暴露的极简控制接口（M3 §7.2：仅 start/stop）
class IEngine(Protocol):
    def start(self, config: EngineConfig) -> None: ...
    def stop(self, mode: StopMode = StopMode.CURRENT) -> None: ...
    def state(self) -> EngineState: ...
    def events(self) -> "ProgressEventStream": ...  # 订阅进度事件（M3 §7.4）

class StopMode(Enum):
    CURRENT = "current"   # 中断当前用例，继续后续
    ALL = "all"           # 中断当前用例，停止全部（M5 §5.3）

class EngineState(Enum):
    IDLE / RUNNING / FINISHED / ERROR
```

#### 5.2.2 串口操作接口（M3 → M1，ISP 拆分）

```python
# 发送命令并等待完整响应（直接输入，M1 §3.1）
class ICommandSender(Protocol):
    def send_command(self, port: str, command: str, timeout: float) -> Response: ...

# 发送数据流（M1 §3.2，分块）
class IDataStreamSender(Protocol):
    def send_data_stream(self, port: str, spec: DataStreamSpec,
                         cancel: CancelToken) -> Response: ...

# 连接管理
class IConnectionManager(Protocol):
    def open(self, port: str, config: PortConfig) -> None: ...
    def close(self, port: str) -> None: ...
    def enumerate_ports(self) -> list[PortInfo]: ...   # M5 list ports
    def is_connected(self, port: str) -> bool: ...

# URC 订阅（M1 §6）
class IURCSubscriber(Protocol):
    def subscribe(self, port: str, handler: URCEventHandler) -> Subscription: ...

# 数据流监听（M6 §6.2 实时监控）
class IDataStreamObserver(Protocol):
    def observe(self, port: str, sink: DataSink) -> Subscription: ...
```

#### 5.2.3 用例加载接口（M3/M5/M6 → M2）

```python
class ICaseRepository(Protocol):
    def load(self, paths: list[Path], tag_filter: TagFilter | None) -> list[Case]: ...
    def load_directory(self, dir: Path, tag_filter: TagFilter | None) -> list[Case]: ...
```

#### 5.2.4 报告渲染接口（M5/M6 → M4，OCP 注册表）

```python
class IReporter(Protocol):
    format_name: str   # "html" / "console" / "junit"（预留）
    def render(self, result: ExecutionResult, output: ReportOutput) -> None: ...

# 注册表：M4 启动时注册各 Reporter，消费方按 format_name 取用
class ReporterRegistry:
    def register(self, reporter: IReporter) -> None: ...
    def get(self, format_name: str) -> IReporter: ...
```

#### 5.2.5 环境配置接口（M3 → M7）

```python
class IEnvConfigProvider(Protocol):
    def load(self, path: Path) -> EnvConfig: ...           # 启动时加载，失败抛 EnvLoadError
    def resolve(self, ref: str) -> str: ...                # 解析 {{group.param}}，未定义抛 UndefinedRefError
    def snapshot(self) -> Mapping[str, Mapping[str, Any]]: ...  # 只读快照
```

#### 5.2.6 GUI 选项卡视图接口（M6 §2.3/§10.5，OCP 注册表）

```python
class ITabView(Protocol):
    type_name: str        # "manual_debug" / "case_execute" / ...
    def create(self, binding: TabBinding) -> QWidget: ...
    def icon(self) -> QIcon: ...
    def title(self, binding: TabBinding) -> str: ...

class TabTypeRegistry:
    def register(self, view: ITabView) -> None: ...
    def types(self) -> list[str]: ...
    def create(self, type_name: str, binding: TabBinding) -> QWidget: ...
```

### 5.3 扩展点与注册表对照

| 扩展点 | 接口 | 注册表 | 触发扩展的典型场景 |
|--------|------|--------|------------------|
| 报告格式 | `IReporter` | `ReporterRegistry` | 新增 JUnit XML 输出（M4 §6 预留） |
| GUI 选项卡类型 | `ITabView` | `TabTypeRegistry` | 新增"用例可视化编辑器""报告对比"（M6 §12） |
| 串口实现 | `ISerialPort` 族 | （依赖注入，无全局注册表） | 单测注入 FakeSerial；未来支持 USB 直连 |
| 环境配置组 | （YAML 顶层键，无代码注册） | 加载器动态遍历 | 用户新增 `coap`/`lwm2m` 等组（M7 §5） |

### 5.4 异常体系约定

- 每个模块定义自己的异常根类（如 `SerialError`、`EngineError`、`CaseLoadError`、`EnvConfigError`、`ReportError`）。
- 异常携带**结构化上下文**（错误码、端口名、用例名、步骤号、原始原因链 `__cause__`），便于 M4 报告与日志展示。
- 跨层传递时**保留原因链**（`raise NewError(...) from original`），不吞异常。
- M1 §8 的各类异常（断连/超时/打开失败/数据源错误）均映射为 M1 异常子类，M3 捕获后转译为步骤失败。

### 5.5 配置模型约定

- M5 `atprobe.yaml`、M7 `env.yaml`、M2 用例 YAML 均用 **Pydantic 模型**建模，加载时校验。
- 校验失败 → 抛带行号/字段的 `ValidationError`，M5 捕获后按 §3.5 提示行号原因退出（ERROR，退出码 2）。
- 配置默认值集中在 Pydantic 模型的 `Field(default=...)`，单一事实源。

### 5.6 模板替换器（M2/M7 共用，领域层纯函数）

- 自研极简替换器（非 Jinja2），仅支持 `{{name}}` 与 `{{group.param}}` 两种占位符的字符串替换。
- 查找顺序严格遵循 M7 §4.1：点号名只查环境配置、简单名先查用例级变量池再查环境配置默认组。
- 无控制结构、无表达式求值（表达式求值是独立的 `when`/`poll.until` 求值器，§5.7）。
- 无注入风险：占位符值来自受控的配置与 extract，不接受任意用户模板逻辑。
- 实现为无副作用纯函数，易单测。

### 5.7 条件表达式求值器（M2 §6，领域层纯函数）

- `when`/`poll.until` 用同一求值器（M2 §6.1）。
- 自研极简递归下降解析器，支持 §6.2 文法定义（and/or/比较运算/null 判断/字面量/变量名）。
- 求值规则严格遵循 §6.3（null 比较、类型规则、空值处理）。
- 实现为纯函数 `evaluate(expr: str, scope: Mapping[str, Any]) -> bool`，易单测。
- 兼容旧写法 `{{var}} == "OK"`：检测到 `{{}}` 先文本替换再求值（兼容期，M2 §6.5）。

---

## 6. 并发与线程模型

### 6.1 线程模型总览（线程模型方案）

采用**线程模型**（用户已确认）。充分利用 M3 串行执行前提，并发只用在三个明确隔离的点。

```
┌─────────────────────────────────────────────────────────────────┐
│  线程 1：主线程（唯一 UI / CLI 入口线程）                         │
│  - GUI 模式：Qt 事件循环（QApplication.exec）                    │
│  - CLI 模式：Typer 命令处理 + 阻塞等待引擎完成                    │
│  - 职责：用户交互、视图刷新、发起 start/stop                      │
│  - 约束：不做任何阻塞 I/O，不跑用例逻辑（避免卡 UI/CLI）          │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│  线程 2：引擎线程（每次 start 启动一个，结束即退出）              │
│  - 职责：跑 M3 串行调度循环（setup→steps→teardown × N 用例）      │
│  - 约束：单线程串行，无锁；通过 ISerialPort 同步调用 M1           │
│  - 通信：通过线程安全队列向主线程投递进度事件（§6.3）             │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│  线程 3..N：串口读线程（每个已连接端口一个）                      │
│  - 职责：M1 后台持续读字节 → 按完整性判定组装响应 → 分流 URC       │
│  - 约束：仅做字节读取与初步组装，不做业务判定                      │
│  - 通信：通过线程安全队列向引擎线程交付响应、向订阅者投递 URC       │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 各线程职责详述

#### 主线程

- **GUI 模式**：运行 Qt 事件循环。用户操作（点执行、停、手动发 AT）→ 调用 `IEngine.start/stop`（内部启动引擎线程，立即返回不阻塞）。进度事件通过 Qt 信号（`pyqtSignal`/`Signal`）从引擎线程投递到主线程刷新视图（Qt 自动跨线程信号槽，线程安全）。
- **CLI 模式**：Typer 命令处理函数内启动引擎线程，主线程进入"事件渲染循环"——从进度事件队列取事件、按 M4 §3 格式渲染到控制台，同时监听 Ctrl+C（§6.5）。引擎线程结束后主线程汇总退出。
- **绝不阻塞**：主线程不调用任何阻塞 I/O。手动调试（M6 §4）的发送命令虽是同步等待响应，但响应由串口读线程异步填充，主线程通过事件/未来对象等待，期间 Qt 事件循环不卡（用 `QTimer` 轮询或 `concurrent.futures`）。

#### 引擎线程

- M3 `start(config)` 在此线程执行串行调度循环。
- 同步调用 `ISerialPort.send_command(...)`——该方法内部从该端口的响应队列取完整响应（由读线程填充），带超时。
- 用例变量池、模板上下文均为**本线程私有**，无需同步（串行执行，无并发访问）。
- 步骤结果、用例结果通过进度事件队列投递给主线程。
- `stop(mode)` 由主线程调用：设置一个线程安全的停止标志，引擎线程在当前步骤边界检查并响应（委托 M1 取消阻塞读，M1 §4.3）。

#### 串口读线程（每端口一个）

- 持续 `read()` 字节，按 AT 响应终结标志（`OK`/`ERROR`/URC 前缀）做**响应完整性判定**（M1 §7.5）。
- 完整响应 → 投入该端口的响应队列（引擎线程的 `send_command` 在此取）。
- URC（含等待响应期间提取的 URC，M1 §6.4）→ 投入 URC 分发，触发订阅者回调。
- 原始字节流 → 同时投递给 M1 RawLogger 落盘、M6 数据流观察者（实时监控，M6 §6.2）。
- 断连检测 → 通知 PortManager 触发重连流程（M1 §4.2）。

### 6.3 线程间通信机制

| 通信方向 | 机制 | 说明 |
|---------|------|------|
| 主线程 → 引擎线程 | 线程安全停止标志（`threading.Event`） | stop(mode) 设置标志 + 委托 M1 取消阻塞读 |
| 引擎线程 → 主线程 | 进度事件队列（`queue.Queue`）/ Qt 信号 | 引擎线程 put 事件，主线程 get 并渲染 |
| 读线程 → 引擎线程 | 每端口响应队列（`queue.Queue`） | `send_command` 带超时 get |
| 读线程 → 订阅者 | URC 事件回调 / Qt 信号 | URC 分发线程安全投递 |
| 读线程 → RawLogger/观察者 | 直接调用（落盘/入环形缓冲） | RawLogger 内部用队列异步落盘避免拖慢读线程 |

**关键约束：**

- 所有跨线程共享可变状态用 `queue.Queue` 或 `threading.Event`，**不用裸锁**（减少锁错误）。
- 数据类用 `frozen=True` 不可变，跨线程传递天然安全。
- Qt 信号跨线程自动走 `QueuedConnection`，主线程槽函数在主线程执行，无需手动锁。

### 6.4 取消机制（配合 M3 stop）

- 每个阻塞操作接收一个 `CancelToken`（包装 `threading.Event`）。
- 主线程 `stop(mode)`：
  1. 设置引擎停止标志（决定 mode=all 是否继续后续用例）。
  2. 对当前正在阻塞的串口读操作触发 cancel（M1 §4.3）：读线程的 `read()` 立即返回，`send_command` 的队列 get 立即抛 `CancelledError`。
  3. 引擎线程捕获 `CancelledError`，当前用例标 INTERRUPTED，按 mode 决定是否继续下一个用例。
- 取消后串口连接**保持**（不关闭），供后续用例/手动调试继续用（M1 §4.3）。

### 6.5 信号处理（CLI Ctrl+C，M5 §5）

- CLI 模式主线程注册 SIGINT 处理：捕获后弹交互式提示（[c]/[q]/继续，M5 §5.2），根据选择调用 `stop(mode=current|all)`。
- GUI 模式忽略 SIGINT（窗口关闭按钮走正常退出流程）。
- Python 在 Windows 上 SIGINT 处理有限，用 `signal.signal(signal.SIGINT, handler)` + 主线程轮询事件队列相结合，保证响应。

### 6.6 资源生命周期

- 所有 I/O 资源（串口连接、文件句柄）实现上下文管理器（`__enter__`/`__exit__`），用 `with` 保证释放（PRD §9.1）。
- 引擎线程结束时确保：关闭所有端口、flush 日志、释放队列。
- 异常情况下 `finally` 块兜底释放，杜绝资源泄漏。

---

## 7. 性能与稳定性保障

### 7.1 性能预算（对应 PRD §9.4）

| 指标 | 预算 | 实现保障 |
|------|------|---------|
| 命令发送→响应接收的工具自身开销 | < 10ms（不含设备响应延迟） | pyserial 写入即时；读线程字节到达即组装；队列 get 无轮询 |
| 4 端口同时管理不卡顿 | UI 帧率 ≥ 30fps | 串口读线程独立，不阻塞主线程；UI 刷新走 Qt 信号异步投递 |
| 单用例执行开销（引擎调度） | 可忽略（< 1ms/步） | 引擎循环纯内存操作，无 I/O 阻塞 |
| 长时间监控内存稳定 | 不随时间线性增长 | 环形缓冲（§7.3）；原始日志即时落盘不堆积内存 |

**结论：** Python 在本 I/O 密集场景下完全满足性能预算。瓶颈在串口与设备的物理延迟（数十 ms~秒级），工具自身开销（ms 级）占比可忽略。

### 7.2 稳定性设计要点

| 风险 | 设计对策 |
|------|---------|
| 串口断连/超时崩溃 | M1 §8 异常分类处理；断连走自动重连（用例级重试），不抛到顶层 |
| 资源泄漏 | 所有 I/O 用上下文管理器（`with`）；引擎线程 `finally` 兜底关闭端口、flush 日志 |
| 内存泄漏 | 环形缓冲限制 UI 数据堆积；日志即时落盘；不持有用例结果的冗余引用 |
| 长时间运行卡死 | 所有阻塞操作有超时 + CancelToken；无无限等待（M3 §5.5） |
| 异常吞没 | 异常带原因链 `raise ... from`；跨层不吞；M4 报告完整记录 |
| 多线程数据竞争 | 串行执行消除主要竞态；跨线程只经 `Queue`/`Event`/不可变数据类通信 |

### 7.3 环形缓冲（M6 §10.3 落地）

- **UI 数据流缓冲**：手动调试响应区、实时监控区采用固定容量的环形缓冲（默认 10000 行，可配置 M6 §12），超出自动丢弃旧行。避免长时间监控撑爆内存。
- **实现**：用 `collections.deque(maxlen=N)`，O(1) 追加与淘汰，线程安全需配合锁或单线程访问（Qt 信号槽保证槽在主线程执行）。
- **与落盘解耦**：环形缓冲只管 UI 显示，原始日志由 M1 独立即时落盘（完整保留，不受缓冲淘汰影响）。

### 7.4 原始日志的异步落盘

- 读线程不直接写文件（避免 I/O 拖慢字节读取），而是把日志记录投入一个**日志队列**，由独立的**日志写入线程**消费落盘。
- 日志写入线程批量 flush（按时间或条数），平衡延迟与 I/O 次数。
- 程序退出前确保日志队列 drain 完毕（`finally` join）。

### 7.5 断连重连的稳定性（M1 §4.2 落地）

- 重连在 PortManager 内独立逻辑，固定间隔 3s、最多 10 次、同用例连续 3 次仍断连放弃该用例。
- 重连期间正在执行的步骤暂停等待（不计入步骤超时），重连成功后由 M3 从当前用例重新执行。
- 重连失败不抛顶层异常，标记用例失败后继续下一用例，保证整体执行不中断。

---

## 8. 可测试性策略

### 8.1 测试金字塔

```
            ┌──────────────┐
            │  E2E 测试     │  少量：真实串口硬件 + 真实设备（或串口回环），验证全链路
            ├──────────────┤
            │  集成测试     │  中量：引擎 + FakeSerial + Fake 时钟，验证多模块协作
        ┌───┴──────────────┴───┐
        │    单元测试            │  大量：领域纯函数 + 各类单元，无任何 I/O mock
        └───────────────────────┘
```

### 8.2 单元测试（占比最大，AI 最易生成）

针对**领域层纯函数**，无 I/O 依赖，测试简单快速：

| 测试对象 | 覆盖内容 |
|---------|---------|
| 模板替换器（§5.6） | `{{var}}`/`{{group.param}}` 替换、查找优先级、未定义报错、点号名边界（M7 §4.4） |
| 条件表达式求值器（§5.7） | `when`/`poll.until` 全语法、null 比较、类型规则、兼容旧写法（M2 §6） |
| 断言求值器 | 响应断言（contains/matches/equals）、变量断言（eq/gt/between/in）、未定义处理（M2 §4） |
| extract 提取器 | 正则捕获分组、提取失败空值（M2 §5.1） |
| 结果聚合器 | 用例状态汇总规则（PASS/FAIL/SKIPPED/INTERRUPTED，M3 §4.6）、pass_rate 计算 |
| 压测统计 | min/max/avg/P95/P99 计算、warmup 排除、超时不计入分布（M3 §8.6/§8.7） |
| 配置模型校验 | atprobe.yaml / env.yaml / 用例 YAML 的 Pydantic 校验、错误信息 |
| YAML 用例解析 | M2 各字段组合、参数化展开、retry/poll 互斥校验 |

### 8.3 集成测试

| 场景 | 用 Fake 实现 |
|------|-------------|
| 单用例常规执行（全 PASS） | FakeSerial 按预设脚本返回响应 |
| 失败处理（on_failure abort/skip/continue） | FakeSerial 返回断言失败响应 |
| retry / poll 机制 | FakeSerial 按次数返回不同响应 |
| 断连重连 | FakeSerial 中途抛断连异常，验证重试逻辑 |
| 跨端口用例变量共享 | 两个 FakeSerial 实例 |
| stop(mode=current/all) | 执行中触发取消，验证中断语义 |
| 环境配置注入 | 加载 env.yaml，验证模板填充 |
| 报告生成 | 执行后生成 HTML，断言关键字段 |

### 8.4 端到端测试（少量）

- 真实串口硬件或 **虚拟串口对**（如 Windows 上的 com0com、Linux 上的 socat）做回环测试。
- 验证 pyserial 真实行为、热插拔、多端口、实际报告可读性。
- 这类测试不在 CI 高频跑（依赖硬件），手动或定期跑。

### 8.5 FakeSerial 设计（关键测试基建）

- 实现 `ISerialPort` 族接口（§5.2.2），内部维护一个**响应脚本队列**：测试预设"发 X 返回 Y"，FakeSerial 按序消费。
- 支持注入异常（断连、超时、错乱数据）以测试异常路径。
- 支持时间控制（FakeClock）：retry/poll 的等待可立即推进，不真实 sleep，测试飞快。
- FakeSerial 放 `tests/fakes/`，作为测试共享基建，AI 可基于接口契约自动生成。

### 8.6 测试覆盖率目标

- 领域层（M2/M4 模型与纯函数）：**≥ 90%**。
- 引擎层（M3）：≥ 80%（集成测为主）。
- 基础层（M1）：≥ 60%（大量依赖真实硬件，Fake 覆盖核心路径）。
- 入口层（M5/M6）：≥ 50%（薄入口，核心逻辑少，重点测参数解析与事件渲染）。
- CI 用 `pytest-cov` 卡覆盖率门禁。

---

## 9. 项目结构与构建分发

### 9.1 项目目录结构

```
atprobe/
├── pyproject.toml                  # PEP 621 元数据、依赖、工具配置（ruff/mypy/pytest）
├── uv.lock                         # 依赖锁定
├── README.md
├── src/
│   └── atprobe/
│       ├── __init__.py
│       ├── __main__.py             # python -m atprobe 入口
│       ├── domain/                 # 领域层（纯数据结构 + 规则，无 I/O）
│       │   ├── case/               # M2 用例模型
│       │   │   ├── models.py       # Case/Step/Assert/Extract (Pydantic)
│       │   │   ├── parser.py       # YAML → Case
│       │   │   ├── templater.py    # 模板替换器（纯函数）
│       │   │   ├── evaluator.py    # 条件表达式求值器（纯函数）
│       │   │   ├── assessor.py     # 断言求值（纯函数）
│       │   │   └── extractor.py    # extract 提取（纯函数）
│       │   └── report/             # M4 报告模型
│       │       ├── models.py       # ExecutionResult/Summary/CaseResult
│       │       └── aggregator.py   # 结果聚合（纯函数）
│       ├── infra/                  # 基础层（外设与系统资源）
│       │   ├── serial/             # M1 串口通信
│       │   │   ├── interfaces.py   # ISerialPort 族 Protocol
│       │   │   ├── connection.py   # SerialConnection (pyserial)
│       │   │   ├── receiver.py     # ResponseReader（读线程）
│       │   │   ├── urc.py          # URCDispatcher
│       │   │   ├── datastream.py   # DataStreamSender（分块）
│       │   │   ├── rawlog.py       # RawLogger（HEX+TEXT 落盘）
│       │   │   ├── portmanager.py  # PortManager（多端口/重连）
│       │   │   └── fakeserial.py   # FakeSerial（也可放 tests，按需）
│       │   ├── config/             # 配置加载（atprobe.yaml/env.yaml）
│       │   ├── logging.py          # 应用日志
│       │   └── clock.py            # 时钟抽象（便于 Fake）
│       ├── engine/                 # 引擎层
│       │   ├── interfaces.py       # IEngine/StopMode/EngineState
│       │   ├── scheduler.py        # M3 串行调度器
│       │   ├── step_runner.py      # 单步执行器（retry/poll/when）
│       │   ├── failure.py          # on_failure 处理
│       │   ├── pressure.py         # 压测循环
│       │   ├── events.py           # 进度事件定义与发射
│       │   └── envconfig.py        # M7 环境配置加载与注入
│       ├── reporting/              # M4 报告渲染（消费领域层模型）
│       │   ├── interfaces.py       # IReporter/ReporterRegistry
│       │   ├── console.py          # 控制台渲染
│       │   ├── html/               # HTML 渲染
│       │   │   ├── renderer.py
│       │   │   └── templates/      # Jinja2 模板
│       │   └── junit.py            # JUnit XML（预留）
│       ├── cli/                    # M5 CLI 入口
│       │   ├── main.py             # Typer app
│       │   ├── commands/           # run/list/gui 子命令（version 是 --version/-V 标志）
│       │   ├── options.py          # --port 复合表达式解析等
│       │   └── rendering.py        # 进度事件 → 控制台行
│       └── gui/                    # M6 GUI 入口
│           ├── app.py              # QApplication 启动
│           ├── mainwindow.py       # 主窗口（侧栏+MDI+状态栏外壳）
│           ├── tabs/               # 选项卡类型实现
│           │   ├── registry.py     # TabTypeRegistry
│           │   ├── manual_debug.py
│           │   ├── case_execute.py
│           │   ├── monitor.py
│           │   ├── report_view.py
│           │   └── env_config.py
│           ├── widgets/            # 复用控件
│           ├── theme/              # QSS 主题、design token、图标
│           └── controllers/        # 视图层控制器（转发用户操作到引擎）
├── tests/
│   ├── unit/                       # 单元测试（按模块镜像 src 结构）
│   ├── integration/                # 集成测试
│   ├── e2e/                        # 端到端测试
│   ├── fakes/                      # FakeSerial/FakeClock 等共享基建
│   └── fixtures/                   # 测试用例 YAML、配置样例
├── examples/                       # 示例用例套件（随工具分发）
│   ├── atprobe.yaml
│   ├── env.yaml
│   └── testcases/
└── docs/                           # 文档（本目录）
```

### 9.2 模块边界与导入规则

- **src layout**：用 `src/atprobe/` 布局，避免测试误导入本地目录，强制通过安装的包导入。
- **导入方向单向向下**：`cli/gui → engine → domain ← infra`，`reporting → domain`。禁止反向导入（如 domain 不 import infra）。
- **入口层不含业务逻辑**：`cli/` 与 `gui/` 只做翻译/编排/渲染，所有业务在 `engine`/`domain`/`infra`。
- **ruff 的 `flake8-import-constraints`**（或 import-linter）配置为 CI 检查，强制层间依赖方向。

### 9.3 依赖管理

- 用 **uv** 管理依赖与虚拟环境（解析安装极快，AI 友好）。
- `pyproject.toml` 分组：
  - `[project.dependencies]`：运行时依赖（pyserial、PySide6、typer、ruamel.yaml、pydantic、jinja2）。
  - `[project.optional-dependencies.dev]`：开发依赖（pytest、pytest-cov、mypy、ruff）。
- `uv.lock` 锁全版本，CI 与本地一致。

### 9.4 构建与分发

| 阶段 | 方式 |
|------|------|
| 开发 | `uv sync` 装依赖，`uv run pytest` 跑测试，`uv run python -m atprobe` 运行 |
| 打包 | PyInstaller 打包。第一阶段 **onedir**（启动快、调试友好、崩溃可定位），规格 `atprobe.spec` |
| 分发 | GitHub Release 上传打包后的 zip（Win/Linux/macOS 各一份）。无自动更新（本地工具） |
| CLI 与 GUI 同包 | 一个可执行文件，默认进 GUI；`atprobe --cli` 或 `atprobe run ...` 进 CLI（或两个入口脚本指向同一包） |

> onefile 体积小但启动慢（每次解压到临时目录）、调试难；onedir 体积略大但更稳。第一阶段选 onedir，后续视反馈调整。

### 9.5 CI 流水线

GitHub Actions（或同等）三平台矩阵（Win/Linux/macOS）：

1. `uv sync` 安装。
2. `ruff check` + `ruff format --check` 代码风格门禁。
3. `mypy --strict src` 类型检查门禁。
4. `pytest --cov --cov-fail-under=...` 测试 + 覆盖率门禁。
5. （发版时）PyInstaller 打包 + 上传 Release。

---

## 10. 开发规范

### 10.1 编码规范

- **类型注解强制**：所有公共 API 与函数签名完整注解，`mypy --strict` 通过。
- **ruff 统一风格**：lint + format 一体化，配置在 `pyproject.toml`。规则集采纳推荐 + 适度收紧（如禁止裸 `except`）。
- **文档字符串**：公共模块/类/函数用 Google 风格 docstring，便于 AI 生成与 IDE 提示。
- **命名**：模块/文件 snake_case，类 PascalCase，常量 UPPER_SNAKE，接口名 `I` 前缀（`IEngine`）或无前缀纯 Protocol（团队定，本 TSD 倾向 `I` 前缀显式区分抽象）。
- **不可变优先**：数据类优先 `@dataclass(frozen=True)` 或 Pydantic `frozen=True` 模型。

### 10.2 错误处理规范

- 禁止裸 `except:` / `except Exception:` 吞异常（ruff 规则强制）。
- 跨层抛异常用 `raise NewError(ctx) from original` 保留原因链。
- 业务可恢复错误（断连、超时、断言失败）转译为步骤失败，不抛顶层。
- 不可恢复错误（配置错误、端口全开失败）抛顶层，引擎转 ERROR 状态。

### 10.3 日志规范

- **应用日志**（`logging`）：记录程序运行轨迹（DEBUG/INFO/WARNING/ERROR），分级可控。
- **原始日志**（M1 RawLogger）：独立的 HEX+TEXT 格式，记录串口收发字节，不走 logging。
- **进度事件**（M3）：结构化事件，投递给 M5/M6 渲染，不是日志。
- 三者职责分明，不混用。

### 10.4 配置规范

- 所有可变参数集中在配置文件（atprobe.yaml / env.yaml），代码不硬编码魔法值。
- 配置默认值集中在 Pydantic 模型 `Field(default=...)`，单一事实源。
- 命令行参数覆盖配置文件，配置文件覆盖内置默认值（优先级，M5 §3.2）。

### 10.5 Git 与提交规范（建议）

- Conventional Commits（`feat:`/`fix:`/`docs:`/`refactor:`/`test:`/`chore:`）。
- PR 关联需求文档章节（如 `feat(m3): retry 机制，落实 REQ-M3 §4.3`）。

---

## 11. 待决策项（留待 DSD 或后续迭代）

| 项 | 说明 | 倾向 | 决策时机 |
|----|------|------|---------|
| 接口命名是否用 `I` 前缀 | `IEngine` vs 纯 `Protocol` | 倾向 `I` 前缀显式区分抽象 | DSD 阶段定 |
| 选项卡插件加载方式 | 启动时静态注册 vs 运行时动态发现 | 第一阶段静态注册（`TabTypeRegistry.register` 在 app 启动调用），动态发现留后续 | DSD-M6 |
| 配置 schema 校验强度 | Pydantic 严格校验 vs 宽松 | Pydantic 严格（错误信息清晰，AI 友好），M7 环境配置组保持宽松（用户自由增组） | 已倾向 |
| 日志写入线程的批量化策略 | 按条 vs 按时间 vs 混合 | 混合（达到 N 条或 T ms 任一即 flush） | DSD-M1 |
| FakeSerial 是否随包分发 | 仅测试用 vs 作为"演示模式"随包 | 仅测试用（随包演示用独立的回放数据集更合适） | DSD 阶段 |
| 多语言 i18n | M6 §10.5 预留 | 第一阶段中文硬编码 + 文案集中管理（为 i18n 预留结构），不引 i18n 库 | 已倾向 |
| 报告内图表 | M4 §6 第一阶段表格，后续 Chart.js | 第一阶段表格（纯静态无 JS 满足），图表后续 | 已倾向（M4 §6） |
| 压测高并发场景的进程编排 | 多实例手动启动 vs 工具内编排 | 第一阶段多实例手动（M3 §2.3），编排后续 | 已倾向 |
| 应用自更新 | 是否需要自动更新 | 不需要（本地工具，手动更新） | 已倾向 |

---

## 12. 与需求文档的对应关系

本 TSD 的每个核心决策都能追溯到需求文档的具体章节：

| TSD 决策 | 需求依据 |
|---------|---------|
| Python + pyserial | M1 全模块（串口能力）、PRD §10.1（跨平台） |
| PySide6 / Qt6 MDI | M6 §2.2（现代化）、§2.3（MDI 选项卡）、§10.1（UI 技术约束） |
| 串行执行 + 线程模型 | M3 §1/§6（串行执行）、M1 §5.1（串行模型）、M6 §10.2（线程模型） |
| 分层 + SOLID + 接口隔离 | PRD §9.2（可扩展性、分层清晰）、M6 §10.5（视图与逻辑分离） |
| 注册表/插件扩展 | M4 §1（报告格式）、M6 §2.3/§10.5（选项卡类型）、M7 §5（配置组） |
| 上下文管理器 + 异常分类 | M1 §8（异常处理）、PRD §9.1（可靠性） |
| 环形缓冲 | M6 §10.3（监控内存稳定）、PRD §9.1（无泄漏） |
| 测试金字塔 + FakeSerial | PRD §9.2（架构分层便于测试）、本文 §8 |
| 模板替换器 + 表达式求值器 | M2 §5/§6、M7 §4 |
| 性能预算 | PRD §9.4 |
| 打包分发 | PRD §10.1（跨平台运行环境） |

---

## 13. 下一步

1. **本 TSD 评审确认**：确认核心技术栈（Python + PySide6）、线程模型、分层架构、接口契约方向。
2. **进入 DSD 阶段**：按模块产出详细设计文档（`DSD-M1-详细设计.md` 等），精确到类/方法/数据结构/算法。建议顺序：M1（基础层，其他都依赖）→ M2（领域模型）→ M3（引擎核心）→ M4（报告）→ M7（环境配置）→ M5（CLI）→ M6（GUI）。
3. **搭建项目骨架**：按 §9.1 创建目录结构、pyproject.toml、CI，建立 FakeSerial 等测试基建，跑通最小 CLI（`atprobe --version`）+ 最小用例执行闭环。
4. **迭代实现**：按 DSD 逐模块实现，每模块配套单测 + 集成测，CI 门禁把关。

---

## 附录 A：技术选型决策记录（ADR 摘要）

| # | 决策 | 结论 | 关键理由 |
|---|------|------|---------|
| ADR-01 | 语言 | Python 3.11+ | AI 开发友好度最高；AT/串口领域生态最强；I/O 密集场景性能足够 |
| ADR-02 | GUI 框架 | PySide6 (Qt6) | 原生 MDI/现代 UI/QSS/主题，SSCOM 类工具主流栈，满足 M6 §2.2 |
| ADR-03 | 串口库 | pyserial | AT 测试领域事实标准，AI 训练数据统治级 |
| ADR-04 | 并发模型 | 线程模型（非 asyncio） | 契合串行执行前提，直观易调试，避免 asyncio 栈传染 |
| ADR-05 | 模板引擎 | 自研极简替换器（非 Jinja2，用于用例） | `{{var}}`/`{{group.param}}` 语义简单，避免注入与过度能力；Jinja2 仅用于 M4 HTML 报告渲染 |
| ADR-06 | 类型安全 | mypy --strict + Pydantic | 弥补动态类型短板，CI 门禁 |
| ADR-07 | 分发 | PyInstaller onedir | 本地工具，体积可接受，启动快调试友好 |
| ADR-08 | 扩展机制 | 注册表 + Protocol 接口 | 报告格式/选项卡类型/串口实现均可扩展不改主框架（OCP） |

