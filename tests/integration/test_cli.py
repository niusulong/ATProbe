"""CLI 端到端测试（M5）."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from atprobe.cli.main import app

runner = CliRunner()


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
        assert "NETAPN-查询响应格式" in result.stdout
        assert "UPDATETIME-查询设置响应格式" in result.stdout

    def test_list_with_tag_filter(self, examples_dir: Path) -> None:  # type: ignore[no-unbuilt-def]
        result = runner.invoke(
            app,
            ["list", "cases", "--config", str(examples_dir / "atprobe.yaml"), "--tag", "NTP"],
        )
        assert result.exit_code == 0
        assert "UPDATETIME" in result.stdout
        # tcp 用例被过滤（tag=NTP 只剩 NTP 块，TCP 用例不应出现）
        assert "NETAPN" not in result.stdout
        assert "TCPSETUP" not in result.stdout


class TestRunDryRun:
    def test_dry_run_lists_cases(self, examples_dir: Path) -> None:  # type: ignore[no-unbuilt-def]
        result = runner.invoke(
            app,
            ["run", str(examples_dir / "testcases" / "tcp" / "TCP-NETAPN-PARA-VALID_APN.yaml"),
             "--port", "COM99", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "NETAPN-合法APN设置" in result.stdout
        assert "COM99" in result.stdout

    def test_no_port_errors(self, examples_dir: Path) -> None:  # type: ignore[no-unbuilt-def]
        # 不提供 --port 且配置文件 ports 也读不到（用不存在配置）
        result = runner.invoke(
            app,
            ["run", str(examples_dir / "testcases" / "tcp" / "TCP-NETAPN-PARA-VALID_APN.yaml"),
             "--config", "nonexistent.yaml", "--dry-run"],
        )
        assert result.exit_code == 2

    def test_tag_filter_no_cases(self, examples_dir: Path) -> None:  # type: ignore[no-untyped-def]
        result = runner.invoke(
            app,
            ["run", str(examples_dir / "testcases"),
             "--port", "COM99", "--tag", "nonexistent-tag", "--dry-run"],
        )
        assert result.exit_code == 1


class TestParameterization:
    def test_parameters_expand_to_n_instances(self, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        case_file = tmp_path / "para.yaml"
        case_file.write_text("""
name: 多参数测试
parameters:
  - { val: A }
  - { val: B }
  - { val: C }
steps:
  - command: 'AT{{val}}'
    assert: { contains: "OK" }
""", encoding="utf-8")
        # dry-run 展开后应显示 3 个实例
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [COM3]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(app, ["run", "--config", str(cfg), "--dry-run", "--vsim", str(case_file)])
        assert result.exit_code == 0
        # 三个实例都列出（dry-run 打印每个用例名）
        assert result.stdout.count("多参数测试") == 3
        # 参数化实例显示 #N 后缀（与实际执行/报告一致，issue #6）
        assert "多参数测试#1" in result.stdout
        assert "多参数测试#2" in result.stdout
        assert "多参数测试#3" in result.stdout


class TestRunSuite:
    def test_run_suite_executes_cases_in_order(self, tmp_path: Path) -> None:  # type: ignore[no-unbuilt-def]
        # 建套件 + 两个用例
        (tmp_path / "a.yaml").write_text("""
name: 用例A
steps:
  - command: AT
    assert: { contains: "OK" }
""", encoding="utf-8")
        (tmp_path / "b.yaml").write_text("""
name: 用例B
steps:
  - command: AT
    assert: { contains: "OK" }
""", encoding="utf-8")
        suite_file = tmp_path / "suite-test.yaml"
        suite_file.write_text("""
name: 测试套件
cases:
  - a.yaml
  - b.yaml
""", encoding="utf-8")
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [COM3]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(app, ["run", "--config", str(cfg), "--vsim", str(suite_file)])
        assert result.exit_code == 0
        assert "用例A" in result.stdout
        assert "用例B" in result.stdout

    def test_run_suite_with_tag_filter(self, tmp_path: Path) -> None:  # type: ignore[no-unbuilt-def]
        (tmp_path / "a.yaml").write_text("""
name: 用例A
tags: [smoke]
steps:
  - command: AT
    assert: { contains: "OK" }
""", encoding="utf-8")
        (tmp_path / "b.yaml").write_text("""
name: 用例B
tags: [regression]
steps:
  - command: AT
    assert: { contains: "OK" }
""", encoding="utf-8")
        suite_file = tmp_path / "suite-test.yaml"
        suite_file.write_text("""
name: 测试套件
cases:
  - a.yaml
  - b.yaml
""", encoding="utf-8")
        cfg = tmp_path / "atprobe.yaml"
        cfg.write_text("ports: [COM3]\ncases_dir: .\n", encoding="utf-8")
        result = runner.invoke(app, ["run", "--config", str(cfg), "--vsim", "--tag", "smoke", str(suite_file)])
        assert result.exit_code == 0
        assert "用例A" in result.stdout
        assert "用例B" not in result.stdout  # 被 tag 过滤
