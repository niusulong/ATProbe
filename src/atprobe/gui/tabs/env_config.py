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
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新增参数", f"{group} 组的新参数名:")
        if ok and name:
            self._group_widgets.setdefault(group, {})
            # 重建该组（简单实现）
            self._collect_and_update_env()
            # 确保 dict 里存在
            self._group_widgets[group][name] = QLineEdit()
            self._rebuild_form()

    def _collect_and_update_env(self) -> None:
        groups: dict[str, dict[str, str]] = {}
        for gname, entries in self._group_widgets.items():
            params: dict[str, str] = {}
            for pname, edit in entries.items():
                params[pname] = edit.text()
            groups[gname] = params
        self._env = EnvConfig(_groups=groups, source=str(self._path) if self._path else None)

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
