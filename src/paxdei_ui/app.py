from __future__ import annotations

import argparse
import shutil
import sys
import threading
from pathlib import Path
from typing import List

if __package__ in (None, ""):
    _pkg_root = Path(__file__).resolve().parents[1]
    if str(_pkg_root) not in sys.path:
        sys.path.insert(0, str(_pkg_root))
    __package__ = "paxdei_ui"

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
    RecipeCalculatorPage,
)
from paxdei_planner.level_planner import PlanStep
from .snapshot_store import save_snapshot, load_snapshot
from .icon_loader import IconRegistry
from .update_service import DataUpdateService
from .calculator_model import RecipeCalculator, CalculatorSnapshot
from .food_calculator import FoodCalculatorModel, FoodCalculatorPage


class ConfigPage(QtWidgets.QWidget):
    saved = QtCore.Signal()
    def __init__(
        self,
        store: ConfigStore,
        parent: QtWidgets.QWidget | None = None,
        updater: DataUpdateService | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.updater = updater
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(SectionHeader("Player Profile"))
        self.skill_table = SkillTable()
        self.skill_table.load(self.store.profile.skills)
        layout.addWidget(self.skill_table, 2)

        controls_layout = QtWidgets.QHBoxLayout()
        gap_label = QtWidgets.QLabel("Max cross-skill gap")
        controls_layout.addWidget(gap_label)
        self.gap_spin = QtWidgets.QSpinBox()
        self.gap_spin.setRange(0, 50)
        self.gap_spin.setValue(self.store.profile.max_cross_skill_gap)
        controls_layout.addWidget(self.gap_spin)
        controls_layout.addSpacing(24)
        self.premium_box = QtWidgets.QCheckBox("Premium account (+50% XP)")
        self.premium_box.setChecked(self.store.profile.premium_account)
        self.avoid_relics_box = QtWidgets.QCheckBox("Avoid relic recipes")
        self.avoid_relics_box.setChecked(self.store.profile.avoid_relics)
        controls_layout.addWidget(self.premium_box)
        controls_layout.addWidget(self.avoid_relics_box)
        controls_layout.addStretch(1)
        layout.addLayout(controls_layout)

        layout.addWidget(SectionHeader("Crafter Ownership"))
        self.crafter_table = CrafterTable()
        self.crafter_table.load(self.store.profile.crafters)
        layout.addWidget(self.crafter_table, 1)

        layout.addWidget(SectionHeader("Materials Config"))
        materials_container = QtWidgets.QWidget()
        materials_layout = QtWidgets.QVBoxLayout(materials_container)
        materials_layout.setContentsMargins(0, 0, 0, 0)
        materials_layout.setSpacing(6)
        self.material_table = MaterialTable()
        self.material_table.load(self.store.materials)
        materials_layout.addWidget(self.material_table, 1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        self.update_button = QtWidgets.QPushButton("Check for data updates")
        self.update_button.setEnabled(self.updater is not None and self.updater.is_configured())
        self.update_button.clicked.connect(self._handle_update_clicked)
        buttons.addWidget(self.update_button)
        materials_layout.addLayout(buttons)
        self.update_status = QtWidgets.QLabel("")
        materials_layout.addWidget(self.update_status)
        layout.addWidget(materials_container, 2)
        if self.updater:
            self.updater.status_changed.connect(self._handle_update_status)
            self.updater.update_finished.connect(self._handle_update_finished)

    @QtCore.Slot()
    def save(self) -> None:
        targets = self.skill_table.targets()
        levels = self.skill_table.levels()
        xp_values = self.skill_table.xp_values()
        blessings = self.skill_table.blessings()
        for skill in self.store.profile.skills:
            if skill.key in targets:
                skill.target_level = targets[skill.key]
            if skill.key in levels:
                skill.current_level = levels[skill.key]
            if skill.key in xp_values:
                skill.current_xp = xp_values[skill.key]
            skill.blessing = blessings.get(skill.key, getattr(skill, "blessing", False))
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
        self.saved.emit()

    @QtCore.Slot()
    def _handle_update_clicked(self) -> None:
        if not self.updater:
            return
        self.update_button.setEnabled(False)
        self.update_status.setText("Checking for updates...")
        self.updater.check_for_updates()

    @QtCore.Slot(str)
    def _handle_update_status(self, message: str) -> None:
        self.update_status.setText(message)

    @QtCore.Slot(bool, str)
    def _handle_update_finished(self, success: bool, message: str) -> None:
        self.update_button.setEnabled(self.updater is not None and self.updater.is_configured())
        self.update_status.setText(message)
        if success:
            QtWidgets.QMessageBox.information(self, "Bundle updated", message)
        else:
            QtWidgets.QMessageBox.warning(self, "Update", message)


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
        content = QtWidgets.QHBoxLayout()
        self.queue = PlanQueueWidget()
        self.queue.setMinimumWidth(180)
        content.addWidget(self.queue, 1)
        self.cards = PlanCardsPanel()
        content.addWidget(self.cards, 9)
        layout.addLayout(content, 1)
        self._snapshot: PlanSnapshot | None = None
        self.queue.stepSelected.connect(self._handle_selection)

    def set_steps(self, snapshot: PlanSnapshot, steps: List[PlanStep]) -> None:
        self._snapshot = snapshot
        self.queue.set_steps(
            steps,
            snapshot,
            formatter=lambda idx, step: f"Level {step.from_level}->{step.to_level}",
        )
        first = steps[0] if steps else None
        self.cards.set_step(first, snapshot)

    @QtCore.Slot(object)
    def _handle_selection(self, step: PlanStep | None) -> None:
        if not self._snapshot:
            return
        self.cards.set_step(step, self._snapshot)


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

        self.mode = "plan"
        self.calculator_model: RecipeCalculator | None = None
        self.calculator_snapshot: CalculatorSnapshot | None = None
        self.food_model: FoodCalculatorModel | None = None
        self.page_keys: List[str] = []
        self.page_views: dict[str, dict[str, QtWidgets.QWidget]] = {}
        self.plan_pages: dict[str, SkillPage] = {}
        self.calc_recipe_pages: dict[str, RecipeCalculatorPage] = {}
        self.food_page: FoodCalculatorPage | None = None
        self.icon_registry = IconRegistry()
        manifest_path = executor_config.bundle_root / "manifest.json"
        self.update_service = DataUpdateService(
            executor_config.bundle_root,
            manifest_path,
            executor_config.bundle_manifest_url,
            executor_config.bundle_archive_url,
        )
        self.config_page = ConfigPage(store, updater=self.update_service)
        self.config_page.saved.connect(self._handle_config_saved)
        self.checklist_page = ChecklistPage()
        calc_checklist_page = RecipeCalculatorPage("All Recipes")
        self.calc_recipe_pages["checklist"] = calc_checklist_page
        self._register_page("config", self.config_page, self.config_page)
        self._register_page("checklist", self.checklist_page, calc_checklist_page)

        for skill in self.store.profile.skills:
            plan_page = SkillPage(skill.name)
            calc_page = RecipeCalculatorPage(skill.name)
            self.plan_pages[skill.key] = plan_page
            self.calc_recipe_pages[skill.key] = calc_page
            self._register_page(skill.key, plan_page, calc_page)
        props_page = RecipeCalculatorPage("Building")
        self.calc_recipe_pages["building"] = props_page
        props_page.set_is_building(True)
        self._register_page("building", None, props_page)
        self.food_page = FoodCalculatorPage()
        self.food_page.selectionChanged.connect(self._handle_food_selection_changed)
        self.food_page.collapseChanged.connect(self._handle_food_collapse_changed)
        self._register_page("food", None, self.food_page)
        self._build_sidebar()
        self.sidebar.selectionChanged.connect(self._handle_sidebar_change)
        self._show_current_page()

        self.plan_service = PlanService()
        self.plan_service.plan_ready.connect(self._handle_plan_ready)
        self.plan_service.plan_failed.connect(self._handle_plan_failed)
        self.plan_service.plan_started.connect(self._handle_plan_started)
        self.plan_service.plan_progress.connect(self._handle_plan_progress)

        toolbar = self.addToolBar("Planner")
        self.run_action = QtGui.QAction("Refresh plan", self)
        self.run_action.triggered.connect(self.trigger_plan)
        toolbar.addAction(self.run_action)
        toolbar.addSeparator()
        self.plan_mode_action = QtGui.QAction("Plan mode", self, checkable=True)
        self.plan_mode_action.setChecked(True)
        self.calc_mode_action = QtGui.QAction("Calculator mode", self, checkable=True)
        toolbar.addAction(self.plan_mode_action)
        toolbar.addAction(self.calc_mode_action)
        self.plan_mode_action.triggered.connect(lambda: self._set_mode("plan"))
        self.calc_mode_action.triggered.connect(lambda: self._set_mode("calculator"))

        self.status = self.statusBar()
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        self.status.addPermanentWidget(self.progress_bar)
        self.current_snapshot: PlanSnapshot | None = None

        self.snapshot_path = Path(self.executor_config.plan_json).with_suffix(".ui_plan.json")
        self._load_cached_snapshot()

    def _load_cached_snapshot(self) -> None:
        if not getattr(self, "snapshot_path", None):
            return
        snapshot = load_snapshot(self.snapshot_path)
        if not snapshot and self.executor_config.default_snapshot:
            snapshot = load_snapshot(self.executor_config.default_snapshot)
            if snapshot:
                thread = threading.Thread(
                    target=save_snapshot, args=(snapshot, self.snapshot_path), daemon=True
                )
                thread.start()
        if not snapshot:
            return
        self.current_snapshot = snapshot
        self.checklist_page.set_snapshot(snapshot)
        for key, page in self.plan_pages.items():
            page.set_steps(snapshot, snapshot.steps_for_skill(key))

    def _current_page_key(self) -> str | None:
        idx = self.sidebar.currentRow()
        if 0 <= idx < len(self.page_keys):
            return self.page_keys[idx]
        return None

    def _build_sidebar(self) -> None:
        desired = self._current_page_key()
        default_icon = self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogDetailedView)
        config_icon = self.icon_registry.icon_for("config", default_icon)
        checklist_icon = self.icon_registry.icon_for(
            "checklist",
            self.style().standardIcon(QtWidgets.QStyle.SP_DialogYesButton),
        )
        entries: list[tuple[str, QtGui.QIcon]] = [("Config", config_icon), ("Checklist", checklist_icon)]
        keys: list[str] = ["config", "checklist"]
        for skill in self.store.profile.skills:
            safe_key = skill.name.lower().replace(" ", "_")
            icon = self.icon_registry.icon_for(safe_key, default_icon)
            entries.append((skill.name, icon))
            keys.append(skill.key)
        if self.mode == "calculator":
            building_icon = self.icon_registry.icon_for("building", default_icon)
            entries.append(("Building", building_icon))
            keys.append("building")
            food_icon = self.icon_registry.icon_for("food", default_icon)
            entries.append(("Food", food_icon))
            keys.append("food")
        self.page_keys = keys
        self.sidebar.set_entries(entries)
        if desired and desired in keys:
            row = keys.index(desired)
            self.sidebar.setCurrentRow(row)
        elif keys:
            self.sidebar.setCurrentRow(0)

    @QtCore.Slot(int)
    def _handle_sidebar_change(self, index: int) -> None:
        self._show_page_by_index(index)

    def _show_page_by_index(self, index: int) -> None:
        if index < 0 or index >= len(self.page_keys):
            return
        key = self.page_keys[index]
        mode_key = "plan" if self.mode == "plan" else "calculator"
        widget = self.page_views.get(key, {}).get(mode_key)
        if widget:
            self.stack.setCurrentWidget(widget)

    def _show_current_page(self) -> None:
        self._show_page_by_index(self.sidebar.currentRow())

    def _set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        if mode == "calculator":
            if not self._ensure_calculator_model():
                self.plan_mode_action.setChecked(True)
                self.calc_mode_action.setChecked(False)
                return
        self.mode = mode
        self.run_action.setVisible(mode == "plan")
        self.plan_mode_action.setChecked(mode == "plan")
        self.calc_mode_action.setChecked(mode == "calculator")
        self._build_sidebar()
        self._show_current_page()

    def _handle_config_saved(self) -> None:
        self.calculator_model = None
        self.calculator_snapshot = None
        self.food_model = None
        for page in self.calc_recipe_pages.values():
            page.set_model(None)
            page.set_snapshot(None)
            page.set_recipes([])
        if self.food_page:
            self.food_page.set_model(None)
        if self.mode == "calculator":
            # Reload the calculator with the freshly saved config so tabs reflect new data.
            self._ensure_calculator_model()

    def _ensure_calculator_model(self) -> bool:
        cfg = self.executor_config
        if self.calculator_model:
            if not self.food_model:
                self.food_model = FoodCalculatorModel(cfg.static, cfg.loc)
                if self.food_page:
                    self.food_page.set_model(self.food_model)
                    self.food_page.set_selected_foods(self.store.profile.food_available)
                    self.food_page.set_foods_collapsed(self.store.profile.food_panel_collapsed)
            return True
        try:
            cfg.xp_tables_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            model = RecipeCalculator(
                str(cfg.static),
                str(cfg.loc),
                str(cfg.profile),
                str(cfg.xp_tables_dir),
                str(cfg.materials_config),
            )
        except Exception as exc:  # pragma: no cover - UI safeguard
            QtWidgets.QMessageBox.critical(self, "Calculator error", str(exc))
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.calculator_model = model
        self.calculator_snapshot = CalculatorSnapshot(model)
        for page in self.calc_recipe_pages.values():
            page.set_model(model)
            page.set_snapshot(self.calculator_snapshot)
        self.food_model = FoodCalculatorModel(cfg.static, cfg.loc)
        if self.food_page:
            self.food_page.set_model(self.food_model)
            self.food_page.set_selected_foods(self.store.profile.food_available)
            self.food_page.set_foods_collapsed(self.store.profile.food_panel_collapsed)
        self._refresh_calculator_pages()
        return True

    @QtCore.Slot(list)
    def _handle_food_selection_changed(self, keys: list) -> None:
        self.store.profile.food_available = list(keys)
        self.store.save_profile()

    @QtCore.Slot(bool)
    def _handle_food_collapse_changed(self, collapsed: bool) -> None:
        self.store.profile.food_panel_collapsed = bool(collapsed)
        self.store.save_profile()

    def _refresh_calculator_pages(self) -> None:
        if not self.calculator_model:
            for page in self.calc_recipe_pages.values():
                page.set_recipes([])
            return
        checklist_page = self.calc_recipe_pages.get("checklist")
        if checklist_page:
            checklist_page.set_recipes(self.calculator_model.recipes_for_skill(None, include_building=False))
        for skill in self.store.profile.skills:
            page = self.calc_recipe_pages.get(skill.key)
            if not page:
                continue
            recipes = self.calculator_model.recipes_for_skill(skill.key, include_building=False)
            page.set_recipes(recipes)
        building_page = self.calc_recipe_pages.get("building")
        if building_page:
            building_page.set_recipes(self.calculator_model.building_recipes())

    def _register_page(
        self,
        key: str,
        plan_widget: QtWidgets.QWidget | None,
        calc_widget: QtWidgets.QWidget | None,
    ) -> None:
        self.page_views[key] = {"plan": plan_widget, "calculator": calc_widget}
        if plan_widget and self.stack.indexOf(plan_widget) == -1:
            self.stack.addWidget(plan_widget)
        if calc_widget and calc_widget is not plan_widget and self.stack.indexOf(calc_widget) == -1:
            self.stack.addWidget(calc_widget)

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
            cfg.plan_json,
            cfg.shopping_json,
            cfg.steps_json,
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


def _default_bundle_config(bundle_root: Path, filename: str) -> Path:
    candidates = [
        bundle_root / "config" / filename,
        bundle_root / "data_bundle" / "config" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _ensure_user_config(executor_config: ExecutorConfig) -> None:
    defaults = {
        executor_config.profile: _default_bundle_config(executor_config.bundle_root, "first_run_player_profile.json"),
        executor_config.materials_config: _default_bundle_config(executor_config.bundle_root, "first_run_materials_config.json"),
    }
    for target, source in defaults.items():
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copy2(source, target)
            continue
        fallback = _default_bundle_config(executor_config.bundle_root, target.name)
        if fallback.exists():
            shutil.copy2(fallback, target)
            continue
        raise FileNotFoundError(f"Missing default config source: {source}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    cfg_path = Path(args.config)
    executor_config = load_executor_config(cfg_path)
    _ensure_user_config(executor_config)
    store = ConfigStore(executor_config.profile, executor_config.materials_config)

    qt_args = sys.argv if argv is None else [sys.argv[0], *argv]
    app = QtWidgets.QApplication(qt_args)
    win = PlannerWindow(executor_config, store)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
