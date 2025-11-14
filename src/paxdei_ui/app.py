from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List
import threading

from PySide6 import QtCore, QtGui, QtWidgets

from .config_store import ConfigStore
from .paths import ExecutorConfig, load_executor_config
from .plan_service import PlanService, PlanSnapshot
from .widgets import (
    Sidebar,
    SkillTable,
    MaterialTable,
    CrafterTable,
    SectionHeader,
    PlanQueueWidget,
    PlanCardsPanel,
)
from paxdei_planner.level_planner import PlanStep
from .snapshot_store import save_snapshot, load_snapshot
from .icon_loader import IconRegistry


class ConfigPage(QtWidgets.QWidget):
    def __init__(self, store: ConfigStore, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(SectionHeader("Player Profile"))
        self.skill_table = SkillTable()
        self.skill_table.load(self.store.profile.skills)
        layout.addWidget(self.skill_table, 1)

        flags_layout = QtWidgets.QHBoxLayout()
        self.premium_box = QtWidgets.QCheckBox("Premium account (+50% XP)")
        self.premium_box.setChecked(self.store.profile.premium_account)
        self.avoid_relics_box = QtWidgets.QCheckBox("Avoid relic recipes")
        self.avoid_relics_box.setChecked(self.store.profile.avoid_relics)
        flags_layout.addWidget(self.premium_box)
        flags_layout.addWidget(self.avoid_relics_box)
        layout.addLayout(flags_layout)

        gap_layout = QtWidgets.QHBoxLayout()
        gap_layout.addWidget(QtWidgets.QLabel("Max cross-skill gap"))
        self.gap_spin = QtWidgets.QSpinBox()
        self.gap_spin.setRange(0, 50)
        self.gap_spin.setValue(self.store.profile.max_cross_skill_gap)
        gap_layout.addWidget(self.gap_spin)
        gap_layout.addStretch(1)
        layout.addLayout(gap_layout)

        layout.addWidget(SectionHeader("Crafter Ownership"))
        self.crafter_table = CrafterTable()
        self.crafter_table.load(self.store.profile.crafters)
        layout.addWidget(self.crafter_table, 1)

        layout.addWidget(SectionHeader("Materials Config"))
        self.material_table = MaterialTable()
        self.material_table.load(self.store.materials)
        layout.addWidget(self.material_table, 2)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)
        layout.addStretch(1)

    @QtCore.Slot()
    def save(self) -> None:
        targets = self.skill_table.targets()
        for skill in self.store.profile.skills:
            if skill.key in targets:
                skill.target_level = targets[skill.key]
        self.store.profile.premium_account = self.premium_box.isChecked()
        self.store.profile.avoid_relics = self.avoid_relics_box.isChecked()
        self.store.profile.max_cross_skill_gap = int(self.gap_spin.value())

        toggles = self.material_table.toggles()
        for material in self.store.materials:
            if material.key in toggles:
                material.enabled = toggles[material.key]

        crafter_owned = self.crafter_table.toggles()
        for crafter in self.store.profile.crafters:
            if crafter.key in crafter_owned:
                crafter.owned = crafter_owned[crafter.key]

        self.store.save_profile()
        self.store.save_materials()
        QtWidgets.QMessageBox.information(self, "Configuration saved", "Profile and materials have been updated.")


class ChecklistPage(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(SectionHeader("Global Checklist"))
        layout.addWidget(SectionHeader("Top choices"))
        content = QtWidgets.QHBoxLayout()
        self.queue = PlanQueueWidget()
        self.queue.setMinimumWidth(180)
        content.addWidget(self.queue, 1)
        self.cards = PlanCardsPanel()
        content.addWidget(self.cards, 9)
        layout.addLayout(content, 1)
        self._snapshot: PlanSnapshot | None = None
        self.queue.stepSelected.connect(self._handle_selection)

    def set_snapshot(self, snapshot: PlanSnapshot) -> None:
        self._snapshot = snapshot
        self.queue.set_steps(snapshot.steps, snapshot)
        first = snapshot.first_step()
        self.cards.set_step(first, snapshot)

    @QtCore.Slot(object)
    def _handle_selection(self, step: PlanStep | None) -> None:
        if not self._snapshot:
            return
        self.cards.set_step(step, self._snapshot)


class SkillPage(QtWidgets.QWidget):
    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(SectionHeader(title))
        layout.addWidget(SectionHeader("Top choices"))
        self.cards = PlanCardsPanel()
        layout.addWidget(self.cards, 1)
        self._snapshot: PlanSnapshot | None = None

    def set_steps(self, snapshot: PlanSnapshot, steps: List[PlanStep]) -> None:
        self._snapshot = snapshot
        step = steps[0] if steps else None
        self.cards.set_step(step, snapshot)


class PlannerWindow(QtWidgets.QMainWindow):
    def __init__(self, executor_config: ExecutorConfig, store: ConfigStore) -> None:
        super().__init__()
        self.executor_config = executor_config
        self.store = store
        self.setWindowTitle("Pax Dei Leveling Planner UI")
        self.resize(1280, 720)
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout(central)
        self.sidebar = Sidebar()
        layout.addWidget(self.sidebar)

        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.plan_pages: dict[str, SkillPage] = {}
        self.icon_registry = IconRegistry()
        self.config_page = ConfigPage(store)
        self.side_entries: list[tuple[str, QtGui.QIcon]] = []
        self._build_sidebar()
        self.sidebar.selectionChanged.connect(self.stack.setCurrentIndex)

        self.stack.addWidget(self.config_page)
        self.checklist_page = ChecklistPage()
        self.stack.addWidget(self.checklist_page)

        for skill in self.store.profile.skills:
            page = SkillPage(skill.name)
            self.plan_pages[skill.key] = page
            self.stack.addWidget(page)

        self.plan_service = PlanService()
        self.plan_service.plan_ready.connect(self._handle_plan_ready)
        self.plan_service.plan_failed.connect(self._handle_plan_failed)
        self.plan_service.plan_started.connect(self._handle_plan_started)
        self.plan_service.plan_progress.connect(self._handle_plan_progress)

        toolbar = self.addToolBar("Planner")
        run_action = QtGui.QAction("Refresh plan", self)
        run_action.triggered.connect(self.trigger_plan)
        toolbar.addAction(run_action)

        self.status = self.statusBar()
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        self.status.addPermanentWidget(self.progress_bar)
        self.current_snapshot: PlanSnapshot | None = None

        self.snapshot_path = Path(self.executor_config.plan_csv).with_suffix(".ui_plan.json")
        self._load_cached_snapshot()

    def _load_cached_snapshot(self) -> None:
        if not getattr(self, "snapshot_path", None):
            return
        snapshot = load_snapshot(self.snapshot_path)
        if not snapshot:
            return
        self.current_snapshot = snapshot
        self.checklist_page.set_snapshot(snapshot)
        for key, page in self.plan_pages.items():
            page.set_steps(snapshot, snapshot.steps_for_skill(key))

    def _build_sidebar(self) -> None:
        default_icon = self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView)
        config_icon = self.icon_registry.icon_for("config", default_icon)
        checklist_icon = self.icon_registry.icon_for(
            "checklist",
            self.style().standardIcon(QtWidgets.QStyle.SP_DialogYesButton),
        )
        entries: list[tuple[str, QtGui.QIcon]] = [("Config", config_icon), ("Checklist", checklist_icon)]
        for skill in self.store.profile.skills:
            safe_key = skill.name.lower().replace(" ", "_")
            icon = self.icon_registry.icon_for(safe_key, default_icon)
            entries.append((skill.name, icon))
        self.sidebar.set_entries(entries)

    @QtCore.Slot()
    def trigger_plan(self) -> None:
        cfg = self.executor_config
        self.status.showMessage("Running planner...")
        self.plan_service.request_plan(
            cfg.static,
            cfg.loc,
            cfg.profile,
            cfg.xp_tables_dir,
            cfg.materials_config,
            cfg.topk,
            cfg.plan_csv,
            cfg.shopping_csv,
            cfg.steps_txt,
        )

    @QtCore.Slot(object)
    def _handle_plan_ready(self, snapshot: PlanSnapshot) -> None:
        self.current_snapshot = snapshot
        self.status.showMessage(f"Plan ready with {len(snapshot.steps)} steps.", 5000)
        self.checklist_page.set_snapshot(snapshot)
        for key, page in self.plan_pages.items():
            page.set_steps(snapshot, snapshot.steps_for_skill(key))
        thread = threading.Thread(
            target=save_snapshot, args=(snapshot, self.snapshot_path), daemon=True
        )
        thread.start()
        self._hide_progress()

    @QtCore.Slot(Exception)
    def _handle_plan_failed(self, exc: Exception) -> None:
        self._hide_progress()
        QtWidgets.QMessageBox.critical(self, "Planner failed", str(exc))

    @QtCore.Slot()
    def _handle_plan_started(self) -> None:
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0, 0)  # indeterminate until first progress tick
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Planning...")
        self.progress_bar.show()
        self.status.showMessage("Running planner...")

    @QtCore.Slot(float, int, int)
    def _handle_plan_progress(self, pct: float, done: int, total: int) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(pct * 100))
        self.progress_bar.setFormat(f"{pct*100:4.1f}% ({done}/{total} levels)")
        self.status.showMessage(f"Planning... {done}/{total} levels completed.")

    def _hide_progress(self) -> None:
        QtWidgets.QApplication.restoreOverrideCursor()
        self.progress_bar.hide()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Pax Dei planner UI.")
    parser.add_argument(
        "--config",
        default="config/executor_config.json",
        help="Executor config JSON (defaults to config/executor_config.json).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    cfg_path = Path(args.config)
    executor_config = load_executor_config(cfg_path)
    store = ConfigStore(executor_config.profile, executor_config.materials_config)

    qt_args = sys.argv if argv is None else [sys.argv[0], *argv]
    app = QtWidgets.QApplication(qt_args)
    win = PlannerWindow(executor_config, store)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
