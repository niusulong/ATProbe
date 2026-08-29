"""CLI 端到端测试（M5）."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from atprobe.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _restore_root_logging():
    """差集恢复 root logger：CLI run 进程内调 setup_logging 的清理兜底.

    run 命令在本进程调用 setup_logging（run.py），会把 RotatingFileHandler
    （真实工作区 logs/）与 StreamHandler（invoke 期间的捕获 stderr）挂上
    root 且无人摘除——invoke 结束后捕获流被关闭，后续任何通过 root 的日志
    （如 M8 job daemon 线程的「job 完成」）命中已关闭流，报 Logging error。
    测试结束差集关闭新挂 handler 并恢复原状（同 test_logging_config.py）。
    """
    root = logging.getLogger()
    saved = root.handlers[:]
    saved_level = root.level
    yield
    for h in list(root.handlers):
        if h not in saved:
            h.close()
    root.handlers = saved
    root.setLevel(saved_level)


class TestVersion:
    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "atprobe" in result.stdout


class TestListCases:
    def test_list_cases(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        result = runner.invoke(
            app,
            ["list", "cases", "--config", str(examples_dir / "atprobe.yaml")],
        )
        assert result.exit_code == 0
        assert "CSQ-查询信号质量" in result.stdout
        assert "CEREG-查询响应格式" in result.stdout

    def test_list_with_tag_filter(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        result = runner.invoke(
            app,
            ["list", "cases", "--config", str(examples_dir / "atprobe.yaml"), "--tag", "CPIN"],
        )
        assert result.exit_code == 0
        assert "CPIN-查询SIM卡PIN状态" in result.stdout
        # 其它用例被过滤（tag=CPIN 只剩 CPIN 用例，CEREG/CSQ 用例不应出现）
        assert "CEREG" not in result.stdout
        assert "CSQ" not in result.stdout

    def test_list_unknown_target_exit_2(self) -> None:
        """未知 target（打错字如 suite/port）→ stderr 报错 exit 2.

        旧实现静默落回用例列表，看似成功实则列表驴唇不对马嘴。
        """
        result = runner.invoke(app, ["list", "bogus"])
        assert result.exit_code == 2
        assert "未知的目标：bogus" in result.output

    def test_list_missing_cases_dir_exit_2(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        """用例目录不存在是输入问题 → exit 2（旧实现 1，与执行失败混淆）."""
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text(f"cases_dir: {tmp_path / 'absent'}\n", encoding="utf-8")
        result = runner.invoke(app, ["list", "cases", "--config", str(cfg)])
        assert result.exit_code == 2
        assert "用例目录不存在" in result.output

    def test_list_counts_parse_failures(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        """损坏用例可见化：路径 + 错误摘要列出，计数汇总并列（旧实现静默吞掉）."""
        cases = tmp_path / "cases"
        cases.mkdir()
        (cases / "ok.yaml").write_text(
            "name: 好用例\ntags: [smoke]\nsteps:\n  - command: AT\n"
            '    assert: { contains: "OK" }\n',
            encoding="utf-8",
        )
        (cases / "broken1.yaml").write_text("name: [坏YAML\n  steps: [[[\n", encoding="utf-8")
        (cases / "broken2.yaml").write_text("not-a-mapping\n", encoding="utf-8")
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text(f"cases_dir: {cases}\n", encoding="utf-8")

        result = runner.invoke(app, ["list", "cases", "--config", str(cfg)])

        assert result.exit_code == 0
        # 汇总计数：正常与解析失败并列
        assert "共 1 个用例，2 个解析失败" in result.stdout
        # 损坏文件路径可见（stdout 汇总 + stderr 明细由 CliRunner 合并进 output）
        assert "broken1.yaml" in result.output
        assert "broken2.yaml" in result.output
        # 错误摘要可见（截断为首行，仍含分类信息）
        assert "YAML 语法错误" in result.output
        assert "用例根节点必须是映射" in result.output

    def test_list_broken_over_show_limit_collapses(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        """损坏用例超过展示上限（10）：前 10 逐条 + 其余折叠计数（T5 审查 m-2 钉子）."""
        cases = tmp_path / "cases"
        cases.mkdir()
        for i in range(13):
            (cases / f"bad{i:02d}.yaml").write_text("not-a-mapping\n", encoding="utf-8")
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text(f"cases_dir: {cases}\n", encoding="utf-8")

        result = runner.invoke(app, ["list", "cases", "--config", str(cfg)])

        assert result.exit_code == 0
        assert "共 0 个用例，13 个解析失败" in result.stdout
        # 前 10 条可见、第 11+ 折叠为计数行
        assert "bad09.yaml" in result.output
        assert "bad10.yaml" not in result.output
        assert "其余 3 个解析失败略" in result.output


class TestRunExitCode:
    """run 退出码口径（特征测试直测 _exit_code，决策点在 run_exit_code）：

    成功/仅用户中断（Ctrl+C，无失败无跳过）→ 0；失败或跳过 → 1；
    suite_setup 失败（不产生 CaseResult，summary 全零）→ 1。
    旧实现 interrupted>0 一律 1——用户主动取消被当失败，脚本无法区分。
    """

    def _result(self, **kw: int):  # noqa: ANN003, no-untyped-def
        from atprobe.domain.report.models import ExecutionResult, Summary

        return ExecutionResult(summary=Summary(**kw))

    def test_all_pass_is_zero(self) -> None:
        from atprobe.cli.commands.run import _exit_code

        assert _exit_code(self._result(total_cases=2, passed=2)) == 0

    def test_interrupted_only_is_zero(self) -> None:
        """仅中断（用户 Ctrl+C 取消，无失败无跳过）→ 0（用户主动取消非错误）."""
        from atprobe.cli.commands.run import _exit_code

        # PASS+INTERRUPTED 混合零失败零跳过：Ctrl+C 中途的典型态——同 0
        assert _exit_code(self._result(total_cases=3, passed=1, interrupted=2)) == 0

    def test_failed_is_one(self) -> None:
        from atprobe.cli.commands.run import _exit_code

        assert _exit_code(self._result(total_cases=2, passed=1, failed=1)) == 1

    def test_skipped_is_one(self) -> None:
        """用例级 setup 失败连坐（CaseStatus.SKIPPED 唯一来源）→ 1（真实执行问题）."""
        from atprobe.cli.commands.run import _exit_code

        assert _exit_code(self._result(total_cases=2, skipped=2)) == 1

    def test_suite_setup_fail_is_one_even_with_zero_summary(self) -> None:
        """suite_setup 失败不产生任何 CaseResult（summary 全零）→ 仍 1。

        旧实现只看 summary → suite_setup 失败整场 exit 0（T5 审查 M-2：真实
        问题被当成功；"无用例"文案还会误导用户去查过滤条件）。
        """
        from atprobe.cli.commands.run import _exit_code
        from atprobe.domain.report.models import (
            ExecutionResult,
            InputType,
            StepResult,
            StepStatus,
            Summary,
        )

        fail_step = StepResult(
            step_index=1,
            phase="suite_setup",
            input_type=InputType.COMMAND,
            command="ATI",
            port="COM3",
            status=StepStatus.FAIL,
            request="ATI",
            response="",
        )
        result = ExecutionResult(summary=Summary(), suite_setup_results=(fail_step,))
        assert _exit_code(result) == 1


class TestRunDryRun:
    def test_dry_run_lists_cases(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        result = runner.invoke(
            app,
            [
                "run",
                str(
                    examples_dir
                    / "testcases"
                    / "3gpp"
                    / "network"
                    / "NETWORK-CSQ-RESP-QUERY_FORMAT.yaml"
                ),
                "--port",
                "COM99",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "CSQ-查询信号质量" in result.stdout
        assert "COM99" in result.stdout

    def test_no_port_errors(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        # 不提供 --port 且配置文件 ports 也读不到（用不存在配置）
        result = runner.invoke(
            app,
            [
                "run",
                str(
                    examples_dir
                    / "testcases"
                    / "3gpp"
                    / "network"
                    / "NETWORK-CSQ-RESP-QUERY_FORMAT.yaml"
                ),
                "--config",
                "nonexistent.yaml",
                "--dry-run",
            ],
        )
        assert result.exit_code == 2

    def test_tag_filter_no_cases(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        # 退出码口径：过滤条件清空用例集是输入/用法问题 → 2（旧实现 1，
        # 与真实执行失败混淆）
        result = runner.invoke(
            app,
            [
                "run",
                str(examples_dir / "testcases"),
                "--port",
                "COM99",
                "--tag",
                "nonexistent-tag",
                "--dry-run",
            ],
        )
        assert result.exit_code == 2


class TestParameterization:
    def test_parameters_expand_to_n_instances(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        case_file = tmp_path / "para.yaml"
        case_file.write_text(
            """
name: 多参数测试
parameters:
  - { val: A }
  - { val: B }
  - { val: C }
steps:
  - command: 'AT{{val}}'
    assert: { contains: "OK" }
""",
            encoding="utf-8",
        )
        # dry-run 展开后应显示 3 个实例
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [COM3]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(
            app, ["run", "--config", str(cfg), "--dry-run", "--vsim", str(case_file)]
        )
        assert result.exit_code == 0
        # 三个实例都列出（dry-run 打印每个用例名）
        assert result.stdout.count("多参数测试") == 3
        # 参数化实例显示 #N 后缀（与实际执行/报告一致，issue #6）
        assert "多参数测试#1" in result.stdout
        assert "多参数测试#2" in result.stdout
        assert "多参数测试#3" in result.stdout


class TestRunSuite:
    def test_run_suite_executes_cases_in_order(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # 建套件 + 两个用例
        (tmp_path / "a.yaml").write_text(
            """
name: 用例A
steps:
  - command: AT
    assert: { contains: "OK" }
""",
            encoding="utf-8",
        )
        (tmp_path / "b.yaml").write_text(
            """
name: 用例B
steps:
  - command: AT
    assert: { contains: "OK" }
""",
            encoding="utf-8",
        )
        suite_file = tmp_path / "suite-test.yaml"
        suite_file.write_text(
            """
name: 测试套件
cases:
  - a.yaml
  - b.yaml
""",
            encoding="utf-8",
        )
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [COM3]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(app, ["run", "--config", str(cfg), "--vsim", str(suite_file)])
        assert result.exit_code == 0
        assert "用例A" in result.stdout
        assert "用例B" in result.stdout

    def test_run_suite_with_tag_filter(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        (tmp_path / "a.yaml").write_text(
            """
name: 用例A
tags: [smoke]
steps:
  - command: AT
    assert: { contains: "OK" }
""",
            encoding="utf-8",
        )
        (tmp_path / "b.yaml").write_text(
            """
name: 用例B
tags: [regression]
steps:
  - command: AT
    assert: { contains: "OK" }
""",
            encoding="utf-8",
        )
        suite_file = tmp_path / "suite-test.yaml"
        suite_file.write_text(
            """
name: 测试套件
cases:
  - a.yaml
  - b.yaml
""",
            encoding="utf-8",
        )
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [COM3]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(
            app, ["run", "--config", str(cfg), "--vsim", "--tag", "smoke", str(suite_file)]
        )
        assert result.exit_code == 0
        assert "用例A" in result.stdout
        assert "用例B" not in result.stdout  # 被 tag 过滤
