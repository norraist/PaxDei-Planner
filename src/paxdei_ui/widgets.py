from __future__ import annotations

import html
import math
from typing import Any, Callable, Iterable, List, Optional, Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from paxdei_planner.level_planner import (
    PlanStep,
    PlanStepOption,
    RecipeEntry,
    MissingCrafterError,
    LockedRecipeError,
)


class Sidebar(QtWidgets.QListWidget):
    selectionChanged = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setIconSize(QtCore.QSize(32, 32))
        self.setFixedWidth(200)
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
        self.setColumnCount(5)
        self.setHorizontalHeaderLabels(
            ["Skill", "Blessing", "Current Level", "Current XP", "Target Level"]
        )
        self.horizontalHeader().setStretchLastSection(True)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        header = self.horizontalHeader()
        for col in range(5):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)

    def load(self, skills: Iterable) -> None:
        rows = list(skills)
        self.setRowCount(len(rows))
        for idx, skill in enumerate(rows):
            name_item = QtWidgets.QTableWidgetItem(skill.name)
            name_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            self.setItem(idx, 0, name_item)

            bless_check = QtWidgets.QCheckBox()
            bless_check.setChecked(getattr(skill, "blessing", False))
            bless_check.setProperty("skill_key", skill.key)
            bless_wrap = QtWidgets.QWidget()
            bless_layout = QtWidgets.QHBoxLayout(bless_wrap)
            bless_layout.setContentsMargins(0, 0, 0, 0)
            bless_layout.setAlignment(QtCore.Qt.AlignCenter)
            bless_layout.addWidget(bless_check)
            self.setCellWidget(idx, 1, bless_wrap)

            lvl_spin = QtWidgets.QSpinBox()
            lvl_spin.setMinimum(1)
            lvl_spin.setMaximum(200)
            lvl_spin.setValue(skill.current_level)
            lvl_spin.setAlignment(QtCore.Qt.AlignCenter)
            lvl_spin.setProperty("skill_key", skill.key)
            self.setCellWidget(idx, 2, lvl_spin)

            xp_edit = QtWidgets.QLineEdit(str(skill.current_xp))
            xp_edit.setAlignment(QtCore.Qt.AlignCenter)
            xp_edit.setValidator(QtGui.QIntValidator(0, 1_000_000_000, xp_edit))
            xp_edit.setProperty("skill_key", skill.key)
            self.setCellWidget(idx, 3, xp_edit)

            spin = QtWidgets.QSpinBox()
            spin.setMinimum(skill.current_level)
            spin.setMaximum(200)
            spin.setValue(skill.target_level)
            spin.setAlignment(QtCore.Qt.AlignCenter)
            spin.setProperty("skill_key", skill.key)
            spin.setProperty("target_spin", True)
            self.setCellWidget(idx, 4, spin)

    def blessings(self) -> dict[str, bool]:
        out: dict[str, bool] = {}
        for row in range(self.rowCount()):
            wrapper = self.cellWidget(row, 1)
            if not wrapper:
                continue
            check = wrapper.findChild(QtWidgets.QCheckBox)
            if isinstance(check, QtWidgets.QCheckBox):
                key = check.property("skill_key")
                if key:
                    out[str(key)] = check.isChecked()
        return out

    def targets(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 4)
            if isinstance(widget, QtWidgets.QSpinBox):
                key = widget.property("skill_key")
                if key:
                    out[str(key)] = int(widget.value())
        return out

    def levels(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 2)
            if isinstance(widget, QtWidgets.QSpinBox):
                key = widget.property("skill_key")
                if key:
                    out[str(key)] = int(widget.value())
        return out

    def xp_values(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 3)
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
        self.setWordWrap(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
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
        self.setWordWrap(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
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

        self.section_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.section_splitter.setChildrenCollapsible(False)
        outer.addWidget(self.section_splitter, 1)

        def add_scroll_section(name: str) -> QtWidgets.QTextBrowser:
            container = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(container)
            layout.setContentsMargins(0, 4, 0, 4)
            layout.setSpacing(2)
            label = QtWidgets.QLabel(name)
            label.setStyleSheet("font-weight: bold; font-size: 11px;")
            layout.addWidget(label)
            body = QtWidgets.QTextBrowser()
            body.setOpenExternalLinks(False)
            body.setOpenLinks(False)
            body.setReadOnly(True)
            body.setFrameShape(QtWidgets.QFrame.NoFrame)
            body.setStyleSheet("font-size: 11px; background: transparent;")
            body.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            body.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
            layout.addWidget(body, 1)
            self.section_splitter.addWidget(container)
            return body

        self.synergy_body = add_scroll_section("Synergy boosts")
        self.xp_body = add_scroll_section("XP breakdown")
        self.breakdown_body = add_scroll_section("Ingredient breakdown")
        self.base_body = add_scroll_section("Base materials")

    def set_option(self, option: PlanStepOption | None, snapshot) -> None:
        if not option:
            self.title.setText("No option")
            self.meta.setText("")
            self.synergy_body.setHtml("<i>No cross-skill synergies.</i>")
            self.xp_body.setHtml("<i>No XP data.</i>")
            self.breakdown_body.setHtml("<i>No ingredient data.</i>")
            self.base_body.setHtml("<i>No base materials.</i>")
            return
        self.title.setText((option.recipe_name or option.recipe_key) + f" x{option.crafts}")
        lines = []
        if option.crafter:
            crafter_name = snapshot.item_label(option.crafter) if snapshot else option.crafter
            lines.append(f"Crafter: {crafter_name}")
        lines.append(f"Crafts: {option.crafts}")
        lines.append(f"Final XP per craft: {option.xp_per_craft:.1f}")
        lines.append(f"Final XP total: {option.total_xp:.1f}")
        chain_xp = getattr(option, "total_xp_chain", 0.0)
        if chain_xp:
            lines.append(f"Chain XP total (this skill): {chain_xp:.1f}")
        mats_qty = getattr(option, "materials_qty", 0)
        if mats_qty:
            lines.append(f"Total materials: {mats_qty}")
        self.meta.setText("\n".join(lines))
        self.synergy_body.setHtml(self._format_synergy(option, snapshot))
        self.xp_body.setHtml(self._format_xp(option))
        self.breakdown_body.setHtml(self._format_breakdown(option, snapshot))
        self.base_body.setHtml(self._format_base_materials(option, snapshot))

    def _format_xp(self, option: PlanStepOption) -> str:
        if not option.xp_breakdown:
            return "<i>No XP data.</i>"
        lines: List[str] = []
        for name, chance, xs, xf, avg, count in option.xp_breakdown:
            failure_str = "-" if (not isinstance(xf, float) or math.isnan(xf)) else f"{xf:.1f}"
            chance_text = f"{chance*100:5.1f}%"
            if option.blessing_active:
                chance_text = f"<span style='color:#1a73e8;font-weight:bold;'>{chance_text}</span>"
            else:
                chance_text = html.escape(chance_text)
            name_html = html.escape(name)
            lines.append(
                f"<div>- {name_html} x{count}: {chance_text} success chance, {xs:.1f} on success, {failure_str} on failure, {avg:.1f} expected XP</div>"
            )
        return "".join(lines)

    def _format_synergy(self, option: PlanStepOption, snapshot) -> str:
        if not option.synergy_support:
            return "<i>No cross-skill synergies.</i>"
        lines = []
        for skill_key, item_key, qty in option.synergy_support:
            skill_label = snapshot.skill_label(skill_key) if snapshot else skill_key
            item_label = snapshot.item_label(item_key) if snapshot else item_key
            skill_html = html.escape(skill_label)
            item_html = html.escape(item_label)
            lines.append(f"<div>- <b>{skill_html}</b>: {item_html} x{qty}</div>")
        return "".join(lines)

    def _format_base_materials(self, option: PlanStepOption, snapshot) -> str:
        def label_for(item_key: str, default: str = "Unknown item") -> str:
            if snapshot and item_key:
                label = snapshot.item_label(item_key)
                if label:
                    return label
            return item_key or default

        gather_totals: dict[tuple[str, str], int] = {}
        craft_totals: dict[tuple[str, str], int] = {}

        def add_entry(target: dict[tuple[str, str], int], item_key: str, label: str, qty: int) -> None:
            if qty <= 0:
                return
            key = (item_key or label, label)
            target[key] = target.get(key, 0) + qty

        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return
            item_key = str(node.get("item") or "")
            label = node.get("label") or label_for(item_key)
            qty = int(node.get("required") or 0)
            source = (node.get("source") or "").lower()
            key_lower = item_key.lower()
            treat_as_gather = source == "gather" or "water" in key_lower
            if treat_as_gather:
                add_entry(gather_totals, item_key, label, qty)
            else:
                add_entry(craft_totals, item_key, label, qty)
            for child in node.get("children") or []:
                visit(child)

        if option.ingredient_breakdown:
            for node in option.ingredient_breakdown:
                visit(node)
        else:
            for item, qty in option.materials or []:
                add_entry(gather_totals, item, label_for(item), qty)

        def render_entries(entries: dict[tuple[str, str], int]) -> List[str]:
            lines: List[str] = []
            for (_, label), qty in sorted(entries.items(), key=lambda entry: entry[0][1]):
                label_html = html.escape(label)
                lines.append(f"<div>&bull; {label_html} <span style='font-weight:bold;'>x{qty}</span></div>")
            return lines

        gather_lines = render_entries(gather_totals)
        craft_lines = render_entries(craft_totals)

        parts = ["<div><b>Gathered</b></div>"]
        if gather_lines:
            parts.extend(gather_lines)
        else:
            parts.append("<div style='margin-left:12px;'><i>No gathered materials.</i></div>")
        parts.append("<div style='margin-top:8px;'><b>Crafted</b></div>")
        if craft_lines:
            parts.extend(craft_lines)
        else:
            parts.append("<div style='margin-left:12px;'><i>No crafted ingredients.</i></div>")
        return "".join(parts)

    def _format_breakdown(self, option: PlanStepOption, snapshot) -> str:
        nodes = option.ingredient_breakdown
        if not nodes:
            return "<i>No ingredient breakdown available.</i>"
        lines: List[str] = []
        for node in nodes:
            self._append_breakdown_node(lines, node, snapshot, depth=0)
        return "".join(lines)

    def _append_breakdown_node(self, lines: List[str], node: Any, snapshot, depth: int) -> None:
        if not isinstance(node, dict):
            return
        item_key = node.get("item", "")
        label = node.get("label") or (snapshot.item_label(item_key) if snapshot and item_key else item_key) or "Unknown item"
        required = int(node.get("required") or 0)
        indent_px = depth * 18
        label_html = html.escape(label)
        if depth == 0:
            label_html = f"<span style='font-weight:bold; text-decoration: underline;'>{label_html}</span>"
            qty_html = f"<span style='font-weight:bold; font-style: italic;'>x{required}</span>"
            bullet = ""
        else:
            qty_html = f"x{required}"
            bullet = "&bull; "
        details: List[str] = []
        source = (node.get("source") or "").lower()
        stock_used = int(node.get("stock_used") or 0)
        if source == "stock":
            details.append("uses leftovers")
        elif source == "gather":
            details.append("gather")
        elif source == "craft":
            crafts_used = int(node.get("crafts") or 0)
            recipe_name = node.get("recipe") or ""
            station = node.get("station") or ""
            skill_key = node.get("skill") or ""
            skill_label = ""
            if skill_key:
                skill_label = snapshot.skill_label(skill_key) if snapshot else skill_key
            craft_bits: List[str] = []
            if recipe_name:
                craft_bits.append(recipe_name)
            if crafts_used:
                craft_bits.append(f"{crafts_used} craft{'s' if crafts_used != 1 else ''}")
            if station and skill_label:
                craft_bits.append(f"via {station} ({skill_label})")
            elif station:
                craft_bits.append(f"via {station}")
            elif skill_label:
                craft_bits.append(f"via {skill_label}")
            produced = int(node.get("produced") or 0)
            extra = int(node.get("extra") or 0)
            if produced:
                craft_bits.append(f"yields {produced}")
            if extra:
                craft_bits.append(f"{extra} extra")
            if craft_bits:
                details.append(", ".join(craft_bits))
        elif source == "cycle":
            details.append("cycle detected")
        if stock_used and source != "stock":
            details.append(f"{stock_used} from leftovers")
        attempts = int(node.get("attempts") or 0)
        success_rate = float(node.get("success_rate") or 0.0)
        if attempts > 0:
            if success_rate >= 0.999:
                details.append(f"{attempts} attempts")
            else:
                details.append(f"~{attempts} attempts @ {success_rate*100:.1f}%")
        detail_html = ""
        if details:
            detail_html = " <span style='color:#666;'>(" + "; ".join(html.escape(text) for text in details) + ")</span>"
        line = f"<div style='margin-left:{indent_px}px'>{bullet}{label_html} {qty_html}{detail_html}</div>"
        lines.append(line)
        children = node.get("children") or []
        for child in children:
            self._append_breakdown_node(lines, child, snapshot, depth + 1)


class PlanCardsPanel(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot = None
        self._options_by_category: dict[str, list[PlanStepOption]] = {}
        self._selection: dict[str, int] = {}
        self.category_keys = ["chain", "final", "economy"]
        self.category_labels = {
            "chain": "Top XP (chain)",
            "final": "Top XP (final)",
            "economy": "Most economical",
        }

        self._stack = QtWidgets.QStackedLayout(self)
        self.placeholder = QtWidgets.QLabel("Select a step to view recommendations.")
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._stack.addWidget(self.placeholder)

        cards_container = QtWidgets.QWidget()
        cards_layout = QtWidgets.QHBoxLayout(cards_container)
        cards_layout.setSpacing(12)
        self.cards: dict[str, OptionCard] = {}
        self.button_rows: dict[str, list[QtWidgets.QToolButton]] = {}
        for cat in self.category_keys:
            col_widget = QtWidgets.QWidget()
            col_layout = QtWidgets.QVBoxLayout(col_widget)
            col_layout.setSpacing(6)
            label = QtWidgets.QLabel(self.category_labels.get(cat, cat.title()))
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setStyleSheet("font-weight: bold;")
            col_layout.addWidget(label)
            btn_row = QtWidgets.QHBoxLayout()
            btn_row.setSpacing(4)
            btns: list[QtWidgets.QToolButton] = []
            for idx in range(3):
                btn = QtWidgets.QToolButton()
                btn.setText(str(idx + 1))
                btn.setCheckable(True)
                btn.clicked.connect(lambda _checked, c=cat, i=idx: self._select_rank(c, i))
                btn_row.addWidget(btn)
                btns.append(btn)
            col_layout.addLayout(btn_row)
            card = OptionCard()
            col_layout.addWidget(card, 1)
            self.cards[cat] = card
            self.button_rows[cat] = btns
            cards_layout.addWidget(col_widget, 1)
        self._stack.addWidget(cards_container)

    def set_step(self, step: PlanStep | None, snapshot) -> None:
        self._snapshot = snapshot
        if not step or not step.options:
            self._stack.setCurrentIndex(0)
            for card in self.cards.values():
                card.set_option(None, snapshot)
            return
        self._snapshot = snapshot
        options_by_category = getattr(step, "category_options", {}) or {}
        # If category data is missing (older snapshot), rebuild per-category lists from option fields.
        if not options_by_category:
            opts = list(step.options)
            options_by_category = {
                "chain": sorted(opts, key=lambda o: getattr(o, "total_xp_chain", 0.0), reverse=True)[:3],
                "final": sorted(opts, key=lambda o: getattr(o, "total_xp", 0.0), reverse=True)[:3],
                "economy": sorted(opts, key=lambda o: (getattr(o, "materials_qty", 0), getattr(o, "material_burden", 0.0)))[:3],
            }
        self._options_by_category = {cat: list(options_by_category.get(cat, [])) for cat in self.category_keys}
        for cat in self.category_keys:
            opts = self._options_by_category.get(cat, [])
            self._selection[cat] = 0
            for idx, btn in enumerate(self.button_rows.get(cat, [])):
                btn.setEnabled(idx < len(opts))
                btn.blockSignals(True)
                btn.setChecked(idx == 0 and idx < len(opts))
                btn.blockSignals(False)
        self._stack.setCurrentIndex(1)
        for cat in self.category_keys:
            self._refresh_card(cat)

    def _select_rank(self, category: str, index: int) -> None:
        if category not in self.category_keys:
            return
        opts = self._options_by_category.get(category, [])
        if not opts or index >= len(opts):
            return
        self._selection[category] = index
        for idx, btn in enumerate(self.button_rows.get(category, [])):
            btn.blockSignals(True)
            btn.setChecked(idx == index)
            btn.blockSignals(False)
        self._refresh_card(category)

    def _refresh_card(self, category: str) -> None:
        card = self.cards.get(category)
        if not card:
            return
        opts = self._options_by_category.get(category, [])
        idx = self._selection.get(category, 0)
        option = opts[idx] if 0 <= idx < len(opts) else None
        card.set_option(option, self._snapshot)


class PlanQueueWidget(QtWidgets.QListWidget):
    stepSelected = QtCore.Signal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps: List[PlanStep] = []
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.setUniformItemSizes(False)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
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


class RecipeTable(QtWidgets.QTableWidget):
    recipeSelected = QtCore.Signal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["Name", "Success %", "Exp XP", "Can Craft"])
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.verticalHeader().hide()
        self._recipes: List[RecipeEntry] = []
        self._recipe_map: dict[str, RecipeEntry] = {}
        self.itemSelectionChanged.connect(self._emit_selection)

    def set_recipes(self, recipes: List[RecipeEntry]) -> None:
        self.setSortingEnabled(False)
        self.clearContents()
        self.setRowCount(len(recipes))
        self._recipes = recipes
        self._recipe_map = {recipe.recipe_key: recipe for recipe in recipes}
        for row, recipe in enumerate(recipes):
            name_item = QtWidgets.QTableWidgetItem(recipe.recipe_name)
            name_item.setData(QtCore.Qt.UserRole, recipe.recipe_key)
            self.setItem(row, 0, name_item)

            chance_item = QtWidgets.QTableWidgetItem()
            chance_item.setData(QtCore.Qt.DisplayRole, int(round(recipe.success_chance * 100.0)))
            chance_item.setData(QtCore.Qt.UserRole, recipe.success_chance)
            chance_item.setTextAlignment(QtCore.Qt.AlignCenter)
            if recipe.blessing_active:
                font = chance_item.font()
                font.setBold(True)
                chance_item.setFont(font)
                chance_item.setForeground(QtGui.QBrush(QtGui.QColor("#1a73e8")))
                chance_item.setToolTip("Blessing active")
            self.setItem(row, 1, chance_item)

            xp_item = QtWidgets.QTableWidgetItem()
            xp_item.setData(QtCore.Qt.DisplayRole, int(round(recipe.expected_xp)))
            xp_item.setData(QtCore.Qt.UserRole, recipe.expected_xp)
            xp_item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.setItem(row, 2, xp_item)

            can_craft_item = QtWidgets.QTableWidgetItem("")
            can_craft_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            state = QtCore.Qt.Checked if recipe.can_craft else QtCore.Qt.Unchecked
            can_craft_item.setData(QtCore.Qt.CheckStateRole, state)
            can_craft_item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.setItem(row, 3, can_craft_item)

            if recipe.materials_blocked or recipe.dependency_blocked:
                color = QtGui.QColor("#7a1f1f" if recipe.materials_blocked else "#a05f23")
                for col in range(4):
                    item = self.item(row, col)
                    if item:
                        item.setBackground(color)
        self.setSortingEnabled(True)
        if recipes:
            self.selectRow(0)
        else:
            self.clearSelection()

    def selected_entry(self) -> RecipeEntry | None:
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if not (0 <= idx < self.rowCount()):
            return None
        item = self.item(idx, 0)
        if not item:
            return None
        key = item.data(QtCore.Qt.UserRole)
        if not key:
            return None
        return self._recipe_map.get(key)

    def _emit_selection(self) -> None:
        entry = self.selected_entry()
        self.recipeSelected.emit(entry)


class CalculatorDetailPanel(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel("Quantity:"))
        self.qty_spin = QtWidgets.QSpinBox()
        self.qty_spin.setRange(1, 9999)
        self.qty_spin.setValue(1)
        controls.addWidget(self.qty_spin)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.card = OptionCard()
        layout.addWidget(self.card, 1)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: #b04040;")
        layout.addWidget(self.status_label)
        self._model = None
        self._snapshot = None
        self._recipe_key: str | None = None
        self._recipe_entry: RecipeEntry | None = None
        self.qty_spin.valueChanged.connect(self._handle_qty_changed)

    def set_snapshot(self, snapshot) -> None:
        self._snapshot = snapshot

    def set_model(self, model) -> None:
        self._model = model

    def set_recipe(self, entry: RecipeEntry | None) -> None:
        self._recipe_entry = entry
        self._recipe_key = entry.recipe_key if entry else None
        self.qty_spin.blockSignals(True)
        self.qty_spin.setValue(1)
        self.qty_spin.blockSignals(False)
        self._refresh_option()

    def _handle_qty_changed(self, value: int) -> None:
        _ = value
        self._refresh_option()

    def _refresh_option(self) -> None:
        if not self._model or not self._recipe_key:
            self.card.set_option(None, self._snapshot)
            self.status_label.setText("")
            return
        try:
            option = self._model.option_for_recipe(self._recipe_key, int(self.qty_spin.value()))
        except MissingCrafterError as exc:
            self.card.set_option(None, self._snapshot)
            label = self._model.item_label(exc.crafter_key) if self._model else exc.crafter_key
            self.status_label.setText(f"Missing dependency: {label}")
            return
        except LockedRecipeError as exc:
            self.card.set_option(None, self._snapshot)
            skill_label = self._snapshot.skill_label(exc.skill_key) if self._snapshot else exc.skill_key
            self.status_label.setText(
                f"Impossible (requires {skill_label} level {exc.required_level} for >0% success)"
            )
            return
        except Exception as exc:  # pragma: no cover - UI safeguard
            self.card.set_option(None, self._snapshot)
            self.status_label.setText(str(exc))
            return
        messages: List[str] = []
        entry = self._recipe_entry
        if entry and entry.missing_crafters:
            crafter_names = [
                (self._snapshot.item_label(ck) if self._snapshot else ck) for ck in entry.missing_crafters
            ]
            messages.append(f"Missing crafter(s): {', '.join(crafter_names)}")
        if entry and entry.blocked_materials:
            mat_names = [
                (self._snapshot.item_label(item) if self._snapshot else item) for item in entry.blocked_materials
            ]
            messages.append(f"Disabled material(s): {', '.join(mat_names)}")
        unmet: List[str] = []
        for skill, need, item, delta in option.prereq_gaps:
            if delta <= 0:
                continue
            skill_label = self._snapshot.skill_label(skill) if self._snapshot else skill
            item_label = self._snapshot.item_label(item) if self._snapshot else item
            unmet.append(f"{skill_label} needs {need} to craft {item_label}")
        if unmet:
            lines = ["Missing dependency:"] + [f" - {entry}" for entry in unmet]
            messages.append("\n".join(lines))
        self.status_label.setText("\n\n".join(messages).strip())
        self.card.set_option(option, self._snapshot)


class RecipeCalculatorPage(QtWidgets.QWidget):
    def __init__(
        self,
        title: str,
        snapshot=None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._model = None
        self._is_building = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(SectionHeader(title))
        content = QtWidgets.QHBoxLayout()
        self.table = RecipeTable()
        content.addWidget(self.table, 4)
        self.detail = CalculatorDetailPanel()
        if snapshot:
            self.detail.set_snapshot(snapshot)
        content.addWidget(self.detail, 6)
        layout.addLayout(content, 1)
        self.legend_label = QtWidgets.QLabel("")
        self.legend_label.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(self.legend_label)
        self.table.recipeSelected.connect(self._handle_recipe_selected)
        self._update_legend()

    def set_model(self, model) -> None:
        self._model = model
        self.detail.set_model(model)

    def set_snapshot(self, snapshot) -> None:
        self._snapshot = snapshot
        self.detail.set_snapshot(snapshot)

    def set_is_building(self, value: bool) -> None:
        self._is_building = value
        self._update_legend()

    def set_recipes(self, recipes: List[RecipeEntry]) -> None:
        self.table.set_recipes(recipes)
        entry = self.table.selected_entry()
        self.detail.set_recipe(entry)

    def _handle_recipe_selected(self, recipe_entry: RecipeEntry | None) -> None:
        self.detail.set_recipe(recipe_entry)

    def _update_legend(self) -> None:
        if self._is_building:
            self.legend_label.setText(
                "<b>Legend:</b> <span style='background-color:#7a1f1f;color:#fff;padding:2px 6px;'>Blocked</span> = Missing crafter prerequisites"
            )
        else:
            self.legend_label.setText(
                "<b>Legend:</b> <span style='background-color:#7a1f1f;color:#fff;padding:2px 6px;'>Blocked</span> = Contains materials disabled in your config "
                "<span style='background-color:#a05f23;color:#fff;padding:2px 6px;margin-left:8px;'>Dependency</span> = Missing skill or crafter prerequisites"
            )
