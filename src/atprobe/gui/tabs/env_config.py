"""环境配置编辑选项卡（M6 §7 / M7 §7）—— env.yaml 可视化编辑."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from atprobe.gui.tabs.registry import ITabView, TabBinding
from atprobe.infra.config.envconfig import (
    EnvConfig,
    EnvConfigError,
    dump_env_config,
    empty_env_config,
    load_env_config_file,
)


class EnvConfigTab(ITabView):
    type_name = "env_config"
    display_name = "环境配置"
    _icon = "config"

    def icon_name(self) -> str:
        return self._icon

    def create_widget(self, binding: TabBinding, main_window: object) -> QWidget:
        return EnvConfigWidget(binding, main_window)


class EnvConfigWidget(QWidget):
    """环境配置编辑视图（M7 §7.1/§7.2）."""

    def __init__(self, binding: TabBinding, main_window: object) -> None:
        super().__init__()
        self._main = main_window
        self._env: EnvConfig = empty_env_config()
        self._path: Path | None = None
        self._group_widgets: dict[str, dict[str, QLineEdit]] = {}
        self._init_ui()
        # 尝试加载默认 env.yaml
        if hasattr(self._main, "env_config_path"):
            p = self._main.env_config_path()
            if p:
                self._load_path(Path(p))

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        load_btn = QPushButton("加载文件")
        load_btn.clicked.connect(self._load)
        bar.addWidget(load_btn)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        bar.addWidget(save_btn)
        add_group_btn = QPushButton("＋新建组")
        add_group_btn.clicked.connect(self._add_group)
        bar.addWidget(add_group_btn)
        bar.addStretch()
        layout.addLayout(bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.form = QVBoxLayout(self.container)
        self._scroll.setWidget(self.container)
        layout.addWidget(self._scroll, 1)

    def _load(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "加载环境配置", "", "YAML (*.yaml *.yml)")
        if f:
            self._load_path(Path(f))

    def _load_path(self, path: Path) -> None:
        try:
            self._env = load_env_config_file(path)
            self._path = path
        except EnvConfigError as exc:
            QMessageBox.critical(self, "加载失败", str(exc))
            return
        self._rebuild_form()

    def _rebuild_form(self) -> None:
        # 清空
        while self.form.count():
            item = self.form.takeAt(0)
            assert item is not None
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._group_widgets.clear()

        for gname, params in self._env.groups().items():
            self._build_group(gname, dict(params))

    def _build_group(self, gname: str, params: dict[str, object]) -> None:
        from PySide6.QtWidgets import QGroupBox

        group = QGroupBox(gname)
        form = QFormLayout()
        entries: dict[str, QLineEdit] = {}
        for pname, val in params.items():
            edit = QLineEdit(str(val))
            # 密码脱敏（§7.2）
            if any(k in pname.lower() for k in ("password", "pass", "secret")):
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            # 文本编辑即时同步内存：所见即所跑（无需点保存）
            edit.textChanged.connect(self._collect_and_update_env)
            form.addRow(pname, edit)
            entries[pname] = edit
        add_param_btn = QPushButton("＋参数")
        add_param_btn.clicked.connect(lambda _checked=False, g=gname: self._add_param(g))
        form.addRow(add_param_btn)
        group.setLayout(form)
        self.form.addWidget(group)
        self._group_widgets[gname] = entries

    def _add_group(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新建组", "组名:")
        if ok and name and name not in self._group_widgets:
            self._build_group(name, {})
            self._collect_and_update_env()

    def _add_param(self, group: str) -> None:
        """新增参数到指定组（B5 修复：旧实现功能完全失效）.

        旧实现塞游离 QLineEdit 再 rebuild_form（会 clear 丢失引用），且 _env 不含
        新参数 → 重建后表单无变化。修复：collect 当前值 → 把新参数注入 _env（重建
        EnvConfig）→ _rebuild_form 基于含新参数的 _env 重建。
        """
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新增参数", f"{group} 组的新参数名:")
        if not (ok and name):
            return
        # 先把当前表单值收集到 _env
        self._collect_and_update_env()
        # 把新参数注入 _env：重建 groups 字典并加入新参数
        groups = {g: dict(p) for g, p in self._env.groups().items()}
        if group not in groups:
            groups[group] = {}
        if name in groups[group]:
            QMessageBox.warning(self, "已存在", f"参数 {name} 在 {group} 组已存在")
            return
        groups[group][name] = ""
        self._env = EnvConfig(_groups=groups, source=str(self._path) if self._path else None)
        self._rebuild_form()

    def _collect_and_update_env(self) -> None:
        # 浅拷贝内层 dict，避免把可变 dict 直接塞进 EnvConfig（其 _groups 注解为
        # Mapping，暗示不可变；防引擎/报告代码持有引用跨用例累积的隐患）。
        groups: dict[str, dict[str, str]] = {}
        for gname, entries in self._group_widgets.items():
            params: dict[str, str] = {}
            for pname, edit in entries.items():
                params[pname] = edit.text()
            groups[gname] = dict(params)
        self._env = EnvConfig(_groups=groups, source=str(self._path) if self._path else None)

    # ------------------------------------------------------------------
    # 实时生效接口：供 MainWindow.run_cases 读取内存值（所见即所跑）
    # ------------------------------------------------------------------
    def current_env(self) -> EnvConfig:
        """返回当前表单内存中的 EnvConfig（已 collect，含未保存的编辑）."""
        return self._env

    def is_dirty(self) -> bool:
        """内存值是否与磁盘不一致（有未保存改动）.

        无 path（从未保存过）→ True；否则比对序列化文本。
        """
        if self._path is None or not self._path.exists():
            return True
        try:
            on_disk = self._path.read_text(encoding="utf-8")
        except OSError:
            return True
        return dump_env_config(self._env) != on_disk

    def save_if_dirty(self) -> None:
        """若有未保存改动则静默写盘（run_cases 前调用，保证内存=磁盘单一数据源）.

        与「保存」按钮的区别：不弹"已保存"框；path 为空时（从未保存过）不写，
        由 run_cases 回退到内存值。
        """
        if self._path is None:
            return
        if not self.is_dirty():
            return
        text = dump_env_config(self._env)
        try:
            self._path.write_text(text, encoding="utf-8")
        except OSError:
            pass  # 写盘失败不影响内存生效（run_cases 仍用内存值）

    def _save(self) -> None:
        self._collect_and_update_env()
        if self._path is None:
            f, _ = QFileDialog.getSaveFileName(self, "保存环境配置", "env.yaml", "YAML (*.yaml)")
            if not f:
                return
            self._path = Path(f)
        text = dump_env_config(self._env)
        self._path.write_text(text, encoding="utf-8")
        QMessageBox.information(self, "已保存", f"配置已保存到 {self._path}")
