# 参数化（parameters 矩阵）

用一套步骤模板 + 多组参数，自动展开成多次独立执行。测"同一个指令换不同参数都通过"时用它，避免为每组参数复制一份用例。

## 定义方式

在用例顶层加 `parameters` 字段（参数矩阵，一个列表），用例按每行参数展开为 N 次独立执行：

```yaml
name: PDP激活-多APN
parameters:
  - { apn: cmnet,  type: IP }
  - { apn: cmiot,  type: IP }
  - { apn: '',      type: IPV6 }
steps:
  - command: 'AT+CGDCONT=1,"{{type}}","{{apn}}"'
    assert: { contains: "OK" }
```

## 行为规则

- `parameters` 是列表，每个元素是一个参数字典。
- 用例执行时按列表**展开为 N 次独立执行**，每次参数注入到**用例级变量作用域**（最高优先级，见 `variables.md`）。
- `{{param}}` 在 command / data / path 中做字符串模板替换。
- 报告中每次执行作为独立用例实例展示（name 加后缀 `#1` / `#2` …）。
- 参数化用例的 extract 变量与参数变量同作用域，**extract 提取的同名变量覆盖参数值**（后赋值覆盖）。

## 与变量系统的关系

参数注入本质是"用例开始时往变量池写一组初始值"，和 extract 写变量池是同一套机制（见 `variables.md`「变量作用域」）。所以：
- 参数变量在 setup/steps/teardown 全程可见。
- 参数变量可被后续 extract 同名覆盖。
- 参数变量可在 `when` 条件里裸名引用。

> 报告中每次执行作为独立用例实例展示，name 加后缀 `#1`/`#2`/…（由引擎在载入时展开并标记）。
