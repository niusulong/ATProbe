# 每指令必备用例清单矩阵

按指令形态套模板，照做即不漏。读指令文档，看该指令支持哪些形态，每个形态套下表模板，汇总即该指令全部必备用例。

## 形态 × 必备模板

| 指令支持的形态 | 必备用例（类型-变体） | 数量 |
|---|---|---|
| `=?` 测试命令 | `RESP-TEST_RANGE` | ×1 |
| `?` 查询命令 | `RESP-QUERY_FORMAT` | ×1 |
| `=<参数>` 设置命令 | `PARA-VALID_<场景>`（覆盖默认/典型/边界合法值） | ≥1 |
| | `PARA-OVER_<参数名>`（每个数值参数越上限） | 每参数 ×1 |
| | `PARA-UNDER_<参数名>`（每个数值参数越下限） | 每参数 ×1 |
| | `PARA-WRONG_FORMAT_<场景>`（缺引号/缺参/类型错） | 每场景 ×1 |
| 执行命令（无参动作） | `FUNC-NORMAL`（需注网则 description 注明） | ×1 |
| | `FUNC-PRECONDITION_FAIL`（前置不满足，如未建链） | ×1 |
| 带参数的动作指令（如 TCPSEND） | 上述 PARA 全套 **+** `FUNC-NORMAL_<动作>` **+** `FUNC-NOLINK` | PARA 数 + 2 |

## 三个测试类型的精确定义

| 类型 | 名称 | 定义 | 断言重点 |
|---|---|---|---|
| **RESP** | 响应格式 | 校验查询（`?`）/测试（`=?`）指令的**响应字节格式**：空格数、换行、字段结构。不关心值对错 | `matches: '^...$'` 严格字节级 |
| **FUNC** | 功能验证 | 在**正常/真实业务路径**下指令是否做了该做的事。含成功路径 + 该指令**自身**的业务失败路径（如未建链） | 业务结果码 / 业务码 |
| **PARA** | 参数与边界 | 指令**合法参数**是否被接受（→ OK）**以及**非法/越界参数是否被拒绝（→ CME）。变体名区分 success/fail | `OK` 或 `+CME ERROR: <code>` |

## 类型设计依据

- **PARAM 与 BND 合并为 PARA**：参数校验与边界针对同一组设置类指令，只是断言期望不同（OK vs CME）。合并后集中在同一类型下便于整体查漏，变体名（`VALID_*` / `OVER_*` / `WRONG_FORMAT_*`）已显式标注 success/fail。
- **业务失败路径归 FUNC**：指令自身前提不满足（如 TCPSEND 未建链）属该指令正常行为范畴，不另设错误类。业务码（`+TCPSEND: ERROR`）与 CME 错误码（参数越界）走不同类型，语义清晰。

## 跨类型说明：带参数的动作指令

带参数的动作指令（如 TCPSEND）有两条独立验证线，各自独立成文件：
- **PARA 类**测"参数是否被接受"（断 OK/CME）——不实际触发业务
- **FUNC 类**测"动作是否真的发生"（断业务结果）——需真实环境

两条线不冲突。

## 完整示例：TCPSEND 指令的文件集

TCPSEND 支持设置形态 `=<linkid>,<length>` 且是动作指令，套矩阵：

```
TCP-TCPSEND-PARA-VALID_LENGTH.yaml      # 合法长度 → OK
TCP-TCPSEND-PARA-OVER_LENGTH.yaml       # 4097 → CME 53
TCP-TCPSEND-FUNC-NORMAL_SEND.yaml       # 实际发送成功（description 注明需注网）
TCP-TCPSEND-FUNC-NOLINK.yaml            # 未建链 → +TCPSEND: SOCKET ID OPEN FAILED
```

## 功能块级通用用例

测模组指令识别机制（如指令名拼错 → CME 58）这类不专属某指令的用例，用特殊指令段 `CMDPARSE`，每功能块最多一个文件：`<功能块>-CMDPARSE-FUNC-INVALID_NAME.yaml`。

## 自查清单

为一条新指令写完用例后，按此自查防遗漏：

- [ ] 该指令支持的每个形态（`?`/`=?`/`=`/执行）是否都有对应类型用例
- [ ] 每个数值参数是否都有 OVER 和 UNDER 边界用例（若文档给了范围）
- [ ] 动作指令是否有 FUNC-NORMAL（成功）和 FUNC-NOLINK/PRECONDITION_FAIL（前提失败）
- [ ] 用例文件名是否符合 `<功能块>-<指令>-<类型>-<变体>.yaml` 四段格式
- [ ] 每个文件是否只测一个指令
