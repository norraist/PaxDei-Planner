from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, List, Sequence, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from paxdei_planner.level_planner import PlanStep, PlanStepOption


class Sidebar(QtWidgets.QListWidget):
    selectionChanged = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setIconSize(QtCore.QSize(32, 32))
        self.setFixedWidth(140)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.currentRowChanged.connect(self.selectionChanged.emit)

    def set_entries(self, entries: Sequence[tuple[str, QtGui.QIcon]]) -> None:
        self.clear()
        for label, icon in entries:
            item = QtWidgets.QListWidgetItem(icon, label)
            item.setSizeHint(QtCore.QSize(120, 48))
            self.addItem(item)
        if entries:
            self.setCurrentRow(0)


class SectionHeader(QtWidgets.QLabel):
    def __init__(self, text: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        font = self.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        self.setFont(font)
        self.setContentsMargins(0, 8, 0, 4)


class SkillTable(QtWidgets.QTableWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(
            ["Skill", "Current Level", "Current XP", "Target Level"]
        )
        self.horizontalHeader().setStretchLastSection(True)
        self.setAlternatingRowColors(True)

    def load(self, skills: Iterable) -> None:
        rows = list(skills)
        self.setRowCount(len(rows))
        for idx, skill in enumerate(rows):
            name_item = QtWidgets.QTableWidgetItem(skill.name)
            name_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.setItem(idx, 0, name_item)

            lvl_spin = QtWidgets.QSpinBox()
            lvl_spin.setMinimum(1)
            lvl_spin.setMaximum(200)
            lvl_spin.setValue(skill.current_level)
            lvl_spin.setAlignment(QtCore.Qt.AlignCenter)
            lvl_spin.setProperty("skill_key", skill.key)
            self.setCellWidget(idx, 1, lvl_spin)

            xp_edit = QtWidgets.QLineEdit(str(skill.current_xp))
            xp_edit.setAlignment(QtCore.Qt.AlignCenter)
            xp_edit.setValidator(QtGui.QIntValidator(0, 1_000_000_000, xp_edit))
            xp_edit.setProperty("skill_key", skill.key)
            self.setCellWidget(idx, 2, xp_edit)

            spin = QtWidgets.QSpinBox()
            spin.setMinimum(skill.current_level)
            spin.setMaximum(200)
            spin.setValue(skill.target_level)
            spin.setAlignment(QtCore.Qt.AlignCenter)
            spin.setProperty("skill_key", skill.key)
            spin.setProperty("target_spin", True)
            self.setCellWidget(idx, 3, spin)

    def targets(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 3)
            if isinstance(widget, QtWidgets.QSpinBox):
                key = widget.property("skill_key")
                if key:
                    out[str(key)] = int(widget.value())
        return out

    def levels(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 1)
            if isinstance(widget, QtWidgets.QSpinBox):
                key = widget.property("skill_key")
                if key:
                    out[str(key)] = int(widget.value())
        return out

    def xp_values(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 2)
            if isinstance(widget, QtWidgets.QLineEdit):
                key = widget.property("skill_key")
                if key:
                    try:
                        out[str(key)] = int(widget.text() or "0")
                    except ValueError:
                        out[str(key)] = 0
        return out

    def levels(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 1)
            if isinstance(widget, QtWidgets.QSpinBox):
                key = widget.property("skill_key")
                if key:
                    out[str(key)] = int(widget.value())
        return out

    def xp_values(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 2)
            if isinstance(widget, QtWidgets.QLineEdit):
                key = widget.property("skill_key")
                if key:
                    try:
                        out[str(key)] = int(widget.text() or "0")
                    except ValueError:
                        out[str(key)] = 0
        return out


class MaterialTable(QtWidgets.QTableWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["Enabled", "Name", "Description"])
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().hide()
        self.setAlternatingRowColors(True)
        self._checks: List[QtWidgets.QCheckBox] = []

    def load(self, materials: Iterable) -> None:
        rows = list(materials)
        self.setRowCount(len(rows))
        self._checks = []
        for idx, m in enumerate(rows):
            wrapper = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(wrapper)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(QtCore.Qt.AlignCenter)
            check = QtWidgets.QCheckBox()
            check.setChecked(m.enabled)
            check.setProperty("material_key", m.key)
            layout.addWidget(check)
            self.setCellWidget(idx, 0, wrapper)
            self._checks.append(check)

            name_item = QtWidgets.QTableWidgetItem(m.name)
            name_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.setItem(idx, 1, name_item)

            clean_desc = (
                m.description.replace("\\n", " ")
                .replace("\r\n", " ")
                .replace("\n", " ")
                .replace("\r", " ")
            )
            desc_item = QtWidgets.QTableWidgetItem(clean_desc)
            desc_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.setItem(idx, 2, desc_item)

    def toggles(self) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for check in self._checks:
            key = check.property("material_key")
            if key:
                out[str(key)] = check.isChecked()
        return out


class CrafterTable(QtWidgets.QTableWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["Owned", "Crafter"])
        self.verticalHeader().hide()
        self.horizontalHeader().setStretchLastSection(True)
        self.setAlternatingRowColors(True)
        self._checks: List[QtWidgets.QCheckBox] = []

    def load(self, crafters: Iterable) -> None:
        rows = list(crafters)
        self.setRowCount(len(rows))
        self._checks = []
        for idx, crafter in enumerate(rows):
            wrapper = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(wrapper)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(QtCore.Qt.AlignCenter)
            owned_check = QtWidgets.QCheckBox()
            owned_check.setChecked(crafter.owned)
            owned_check.setProperty("crafter_key", crafter.key)
            layout.addWidget(owned_check)
            self.setCellWidget(idx, 0, wrapper)
            self._checks.append(owned_check)

            name_item = QtWidgets.QTableWidgetItem(crafter.name)
            name_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.setItem(idx, 1, name_item)

    def toggles(self) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for check in self._checks:
            key = check.property("crafter_key")
            if key:
                out[str(key)] = check.isChecked()
        return out


class OptionCard(QtWidgets.QFrame):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setObjectName("OptionCard")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setSpacing(6)
        self.title = QtWidgets.QLabel("No option")
        title_font = self.title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        self.title.setFont(title_font)
        self.title.setWordWrap(True)
        outer.addWidget(self.title)

        self.meta = QtWidgets.QLabel("")
        self.meta.setWordWrap(True)
        self.meta.setStyleSheet("color: #666;")
        outer.addWidget(self.meta)

        def add_section(name: str) -> QtWidgets.QLabel:
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.HLine)
            line.setFrameShadow(QtWidgets.QFrame.Sunken)
            outer.addWidget(line)
            label = QtWidgets.QLabel(name)
            label.setStyleSheet("font-weight: bold; font-size: 11px;")
            outer.addWidget(label)
            body = QtWidgets.QLabel("")
            body.setWordWrap(True)
            body.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            body.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            body.setStyleSheet("font-size: 11px;")
            outer.addWidget(body)
            return body

        self.xp_label = add_section("XP breakdown")
        self.gather_label = add_section("Gather")
        self.craft_label = add_section("Craft steps")

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        outer.addWidget(line)
        dep_header = QtWidgets.QLabel("Dependency tree")
        dep_header.setStyleSheet("font-weight: bold; font-size: 11px;")
        outer.addWidget(dep_header)
        self.dependency = QtWidgets.QPlainTextEdit()
        self.dependency.setReadOnly(True)
        self.dependency.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.dependency.setStyleSheet("font-family: Consolas, 'Courier New', monospace; font-size: 11px; background: transparent;")
        self.dependency.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        outer.addWidget(self.dependency, 1)

    def set_option(self, option: PlanStepOption | None, snapshot) -> None:
        if not option:
            self.title.setText("No option")
            self.meta.setText("")
            self.xp_label.setText("No XP data.")
            self.gather_label.setText("No materials.")
            self.craft_label.setText("No craft steps.")
            self.dependency.setPlainText("")
            return
        self.title.setText((option.recipe_name or option.recipe_key) + f" x{option.crafts}")
        crafter = option.crafter or "Any crafter"
        lines = []
        if option.crafter:
            crafter_name = snapshot.item_label(option.crafter) if snapshot else option.crafter
            lines.append(f"Crafter: {crafter_name}")
        lines.append(f"Crafts: {option.crafts}")
        lines.append(f"XP per craft: {option.xp_per_craft:.1f}")
        self.meta.setText("\n".join(lines))
        self.xp_label.setText(self._format_xp(option))
        self.gather_label.setText(self._format_gather(option, snapshot))
        self.craft_label.setText(self._format_crafts(option, snapshot))
        dep_text = option.materials_tree.strip() if option.materials_tree else ""
        self.dependency.setPlainText(dep_text or "No dependency data.")

    def _format_xp(self, option: PlanStepOption) -> str:
        if not option.xp_breakdown:
            return "No XP data."
        lines: List[str] = []
        for name, chance, xs, xf, avg, count in option.xp_breakdown:
            failure_str = "-" if (not isinstance(xf, float) or math.isnan(xf)) else f"{xf:.1f}"
            lines.append(
                f"- {name} x{count}: {chance*100:5.1f}% success chance, {xs:.1f} on success, {failure_str} on failure, {avg:.1f} expected XP"
            )
        return "\n".join(lines)

    def _format_gather(self, option: PlanStepOption, snapshot) -> str:
        if not option.materials:
            return "No base materials required."
        lines = [
            f"- {(snapshot.item_label(item) if snapshot else item)} x{qty}" for item, qty in option.materials
        ]
        return "\n".join(lines)

    def _format_crafts(self, option: PlanStepOption, snapshot) -> str:
        if not option.craft_summary:
            return "No craft steps recorded."
        lines = []
        for entry in option.craft_summary:
            skill_key = entry.get("skill", "")
            skill_name = snapshot.skill_label(skill_key) if snapshot else skill_key
            station = entry.get("station") or ""
            station_clause = f", via {station}" if station else ""
            outputs = entry.get("outputs", {})
            outputs_str = ", ".join(
                f"{(snapshot.item_label(k) if snapshot else k)} x{v}" for k, v in outputs.items()
            )
            if outputs_str:
                outputs_str = f" -> {outputs_str}"
            recipe_name = entry.get("name") or entry.get("key", "Recipe")
            lines.append(
                f"- Craft {recipe_name} x{entry.get('count',0)} ({skill_name}{station_clause}){outputs_str}"
            )
        return "\n".join(lines)


class PlanCardsPanel(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot = None
        self._stack = QtWidgets.QStackedLayout(self)
        self.placeholder = QtWidgets.QLabel("Select a step to view recommendations.")
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._stack.addWidget(self.placeholder)

        cards_container = QtWidgets.QWidget()
        cards_layout = QtWidgets.QHBoxLayout(cards_container)
        cards_layout.setSpacing(12)
        self.cards = [OptionCard() for _ in range(3)]
        for card in self.cards:
            cards_layout.addWidget(card, 3)
        self._stack.addWidget(cards_container)

    def set_step(self, step: PlanStep | None, snapshot) -> None:
        self._snapshot = snapshot
        if not step or not step.options:
            self._stack.setCurrentIndex(0)
            for card in self.cards:
                card.set_option(None, snapshot)
            return
        self._stack.setCurrentIndex(1)
        for idx, card in enumerate(self.cards):
            option = step.options[idx] if idx < len(step.options) else None
            card.set_option(option, snapshot)


class PlanQueueWidget(QtWidgets.QListWidget):
    stepSelected = QtCore.Signal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps: List[PlanStep] = []
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.currentRowChanged.connect(self._on_row_changed)

    def set_steps(
        self,
        steps: Sequence[PlanStep],
        snapshot,
        formatter: Optional[Callable[[int, PlanStep], str]] = None,
    ) -> None:
        self._steps = list(steps)
        self.clear()
        for idx, step in enumerate(self._steps, start=1):
            if formatter:
                text = formatter(idx, step)
            else:
                label = snapshot.skill_label(step.skill) if snapshot else step.skill
                text = f"{idx}. {label} {step.from_level}->{step.to_level}"
            self.addItem(QtWidgets.QListWidgetItem(text))
        if self._steps:
            self.setCurrentRow(0)
        else:
            self.stepSelected.emit(None)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._steps):
            self.stepSelected.emit(self._steps[row])
        else:
            self.stepSelected.emit(None)
