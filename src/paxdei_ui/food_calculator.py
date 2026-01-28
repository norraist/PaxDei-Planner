from __future__ import annotations

import itertools
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from .widgets import SectionHeader


@dataclass(frozen=True)
class FoodItem:
    key: str
    name: str
    food_type: str
    tier: int | None
    item_level: int | None
    duration_sec: float
    attributes: Dict[str, float]


@dataclass(frozen=True)
class FoodLoadout:
    items: tuple[FoodItem, ...]
    total_attributes: Dict[str, float]
    avg_duration_sec: float
    name_key: str


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return False


def _index_localization(loc: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}

    def record(k: Any, v: Any) -> None:
        if isinstance(k, str) and isinstance(v, str) and k:
            out[k] = v

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            key = obj.get("Key") or obj.get("key") or obj.get("_LocalizationNameKey") or obj.get("_LocalizationDescriptionKey")
            val = obj.get("Text") or obj.get("text") or obj.get("Name") or obj.get("name") or obj.get("Description") or obj.get("description")
            if key and val:
                record(key, val)
            for k, v in obj.items():
                if isinstance(v, str) and ("localization" in str(k).lower()):
                    record(k, v)
                visit(v)
        elif isinstance(obj, list):
            for v in obj:
                visit(v)

    visit(loc)
    return out


def _food_type_from_categories(categories: Sequence[Any]) -> str | None:
    prefixes = {
        "Category.Consumable.Food.": "Food",
        "Category.Consumable.Drink.": "Drink",
    }
    for cat in categories:
        if not isinstance(cat, str):
            continue
        for prefix, label in prefixes.items():
            if cat.startswith(prefix):
                suffix = cat[len(prefix):]
                return f"{label}.{suffix}" if suffix else label
        if cat == "Category.Consumable.Food":
            return "Food"
        if cat == "Category.Consumable.Drink":
            return "Drink"
    return None


def _stat_label(stat_key: str) -> str:
    overrides = {
        "PseudoMaxHealth": "Health",
        "HealthRgn": "Health Regen",
        "PseudoMaxStamina": "Stamina",
        "StaminaRgn": "Stamina Regen",
        "SlashingPhysicalResistance": "Slashing Resistance",
        "PiercingPhysicalResistance": "Piercing Resistance",
        "BluntPhysicalResistance": "Blunt Resistance",
    }
    if stat_key == BALANCED_KEY:
        return "Balanced"
    if stat_key in overrides:
        return overrides[stat_key]
    text = stat_key.replace("_", " ")
    text = re.sub(r"(?<!^)([A-Z])", r" \1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.title()


BALANCED_KEY = "__balanced__"

PRIMARY_STATS = ["PseudoMaxHealth", "HealthRgn", "PseudoMaxStamina", "StaminaRgn"]
PHYSICAL_RESISTANCE_STATS = [
    "SlashingPhysicalResistance",
    "PiercingPhysicalResistance",
    "BluntPhysicalResistance",
]


def _is_resistance(stat_key: str) -> bool:
    return "resistance" in stat_key.lower()


def _stat_sort_key(stat_key: str) -> tuple[int, int, str]:
    if stat_key in PRIMARY_STATS:
        return (0, PRIMARY_STATS.index(stat_key), _stat_label(stat_key))
    if stat_key == BALANCED_KEY:
        return (1, 0, _stat_label(stat_key))
    if stat_key in PHYSICAL_RESISTANCE_STATS:
        return (2, PHYSICAL_RESISTANCE_STATS.index(stat_key), _stat_label(stat_key))
    if _is_resistance(stat_key):
        return (3, 0, _stat_label(stat_key))
    return (4, 0, _stat_label(stat_key))


def _stat_color(stat_key: str) -> QtGui.QColor:
    lower = stat_key.lower()
    if "health" in lower:
        return QtGui.QColor("#d1495b")
    if "stamina" in lower:
        return QtGui.QColor("#c9a66b")
    if "spirit" in lower:
        return QtGui.QColor("#3c7dcf")
    if "mana" in lower:
        return QtGui.QColor("#5a9bd5")
    return QtGui.QColor("#7a8c99")


class StatsBarChart(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: List[tuple[str, float, float, QtGui.QColor]] = []
        self._row_height = 12
        self._label_width = 96
        self._value_width = 44
        self._bar_gap = 6
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)

    def sizeHint(self) -> QtCore.QSize:
        rows = max(1, len(self._rows))
        return QtCore.QSize(220, rows * self._row_height)

    def set_data(
        self,
        totals: Dict[str, float],
        max_totals: Dict[str, float],
        stat_labels: Dict[str, str],
        stat_order: Sequence[str],
        label_width: int | None = None,
    ) -> None:
        if label_width:
            self._label_width = int(label_width)
        rows: List[tuple[str, float, float, QtGui.QColor]] = []
        for key in stat_order:
            value = totals.get(key)
            if value is None or abs(value) < 1e-6:
                continue
            max_val = max_totals.get(key, value) or value or 1.0
            label = stat_labels.get(key, key)
            rows.append((label, value, max_val, _stat_color(key)))
        self._rows = rows
        row_h = max(self._row_height, self.fontMetrics().height() + 2)
        total_h = row_h * max(1, len(self._rows))
        self.setMinimumHeight(total_h)
        self.setMaximumHeight(total_h)
        self.setVisible(bool(self._rows))
        self.updateGeometry()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        _ = event
        if not self._rows:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        fm = painter.fontMetrics()
        row_h = max(self._row_height, fm.height() + 2)
        label_w = self._label_width
        value_w = self._value_width
        bar_x = label_w + self._bar_gap
        bar_w = max(10, self.width() - bar_x - value_w - self._bar_gap)
        bar_h = 6
        y = 0
        for label, value, max_val, color in self._rows:
            painter.setPen(QtGui.QColor("#555555"))
            painter.drawText(0, y, label_w - 2, row_h, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, label)
            bar_y = y + (row_h - bar_h) // 2
            painter.fillRect(bar_x, bar_y, bar_w, bar_h, QtGui.QColor("#e6e6e6"))
            ratio = 0.0 if max_val <= 0 else min(1.0, value / max_val)
            fill_w = int(bar_w * ratio)
            painter.fillRect(bar_x, bar_y, fill_w, bar_h, color)
            painter.setPen(QtGui.QColor("#333333"))
            painter.drawText(
                bar_x + bar_w + self._bar_gap,
                y,
                value_w,
                row_h,
                QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                f"{value:.1f}",
            )
            y += row_h
        painter.end()


class FoodCalculatorModel:
    def __init__(self, static_path: str | Path, loc_path: str | Path) -> None:
        self._static_path = Path(static_path)
        self._loc_path = Path(loc_path)
        self.foods: List[FoodItem] = []
        self.foods_by_key: Dict[str, FoodItem] = {}
        self._load()

    def _load(self) -> None:
        with self._static_path.open("r", encoding="utf-8") as handle:
            static = json.load(handle)
        with self._loc_path.open("r", encoding="utf-8") as handle:
            loc = json.load(handle)
        loc_idx = _index_localization(loc)

        foods: List[FoodItem] = []

        def build_food(item_key: str, node: Dict[str, Any]) -> None:
            if _as_bool(node.get("IsDev")):
                return
            tags = node.get("GivesTags") or []
            if not isinstance(tags, list):
                return
            if "UI.Status.Food" not in tags and "UI.Status.Drink" not in tags:
                return
            categories = node.get("Categories") or []
            if not isinstance(categories, list):
                categories = []
            food_type = _food_type_from_categories(categories)
            if not food_type:
                return
            name_key = node.get("LocalizationNameKey") or ""
            name = loc_idx.get(name_key) or loc_idx.get(f"{item_key}_LocalizationNameKey") or item_key
            tier = node.get("Tier")
            item_level = node.get("ItemLevel")
            tier_val = int(tier) if isinstance(tier, (int, float)) else None
            level_val = int(item_level) if isinstance(item_level, (int, float)) else None
            duration = float(node.get("CooldownDuration") or 0.0)
            attrs_raw = node.get("GivesAttributes") or {}
            attrs: Dict[str, float] = {}
            if isinstance(attrs_raw, dict):
                for k, v in attrs_raw.items():
                    if isinstance(k, str) and isinstance(v, (int, float)):
                        attrs[k] = float(v)
            foods.append(
                FoodItem(
                    key=item_key,
                    name=name,
                    food_type=food_type,
                    tier=tier_val,
                    item_level=level_val,
                    duration_sec=duration,
                    attributes=attrs,
                )
            )

        def visit(obj: Any) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(k, str) and isinstance(v, dict):
                        build_food(k, v)
                        visit(v)
                    else:
                        visit(v)
            elif isinstance(obj, list):
                for v in obj:
                    visit(v)

        visit(static.get("static_data", static))
        foods.sort(key=lambda f: (f.food_type, f.tier or 0, f.item_level or 0, f.name))
        self.foods = foods
        self.foods_by_key = {food.key: food for food in foods}

    def stat_keys_for(self, food_keys: Iterable[str]) -> List[str]:
        seen: set[str] = set()
        for key in food_keys:
            item = self.foods_by_key.get(key)
            if not item:
                continue
            seen.update(item.attributes.keys())
        return sorted(seen, key=lambda k: _stat_label(k))

    def build_loadouts(
        self,
        food_keys: Iterable[str],
        stat_keys: Sequence[str],
    ) -> tuple[Dict[str, List[FoodLoadout]], Dict[str, float], float, Dict[str, float]]:
        items = [self.foods_by_key[k] for k in food_keys if k in self.foods_by_key]
        if not items or not stat_keys:
            return {k: [] for k in stat_keys}, {k: 0.0 for k in stat_keys}, 0.0, {}
        foods_by_type: Dict[str, List[FoodItem]] = {}
        for item in items:
            foods_by_type.setdefault(item.food_type, []).append(item)
        for food_list in foods_by_type.values():
            food_list.sort(key=lambda f: (f.tier or 0, f.item_level or 0, f.name))

        types = sorted(foods_by_type.keys())
        if not types:
            return {k: [] for k in stat_keys}, {k: 0.0 for k in stat_keys}, 0.0, {}
        loadout_size = min(3, len(types))

        loadouts: List[FoodLoadout] = []
        for type_combo in itertools.combinations(types, loadout_size):
            pools = [foods_by_type[t] for t in type_combo]
            for combo in itertools.product(*pools):
                totals: Dict[str, float] = {}
                total_time = 0.0
                for item in combo:
                    total_time += item.duration_sec
                    for key, val in item.attributes.items():
                        totals[key] = totals.get(key, 0.0) + val
                avg_time = total_time / max(1, len(combo))
                name_key = " + ".join(sorted(item.name for item in combo))
                loadouts.append(
                    FoodLoadout(
                        items=tuple(combo),
                        total_attributes=totals,
                        avg_duration_sec=avg_time,
                        name_key=name_key,
                    )
                )

        def total_for(loadout: FoodLoadout, stat: str) -> float:
            return loadout.total_attributes.get(stat, 0.0)

        max_totals: Dict[str, float] = {k: 0.0 for k in stat_keys}
        for loadout in loadouts:
            for stat in stat_keys:
                value = loadout.total_attributes.get(stat, 0.0)
                if value > max_totals[stat]:
                    max_totals[stat] = value
        max_duration = max((l.avg_duration_sec for l in loadouts), default=0.0)

        results: Dict[str, List[FoodLoadout]] = {}
        for stat in stat_keys:
            ranked = sorted(
                loadouts,
                key=lambda l: (-total_for(l, stat), -l.avg_duration_sec, l.name_key),
            )
            results[stat] = ranked[:3]
        balanced_scores: Dict[str, float] = {}
        if loadouts:
            weights = {
                "PseudoMaxHealth": 1.2,
                "PseudoMaxStamina": 1.2,
                "HealthRgn": 0.8,
                "StaminaRgn": 0.8,
            }
            duration_weight = 0.35

            def balanced_score(loadout: FoodLoadout) -> float:
                product = 1.0
                weight_sum = 0.0
                for key, weight in weights.items():
                    max_val = max_totals.get(key, 0.0)
                    if max_val <= 0:
                        continue
                    norm = loadout.total_attributes.get(key, 0.0) / max_val
                    product *= max(0.0, norm) ** weight
                    weight_sum += weight
                geom = math.pow(product, 1.0 / weight_sum) if weight_sum > 0 and product > 0 else 0.0
                if max_duration > 0:
                    duration_norm = loadout.avg_duration_sec / max_duration
                    geom *= math.pow(max(0.0, duration_norm), duration_weight)
                return geom

            balanced_ranked = sorted(
                loadouts,
                key=lambda l: (-balanced_score(l), -l.avg_duration_sec, l.name_key),
            )
            results[BALANCED_KEY] = balanced_ranked[:3]
            for loadout in loadouts:
                balanced_scores[loadout.name_key] = balanced_score(loadout)
        return results, max_totals, max_duration, balanced_scores


class FoodLoadoutPanel(QtWidgets.QFrame):
    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(2)
        self.title_label = QtWidgets.QLabel(title)
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        if title:
            layout.addWidget(self.title_label)
        else:
            self.title_label.hide()
        self.summary_label = QtWidgets.QLabel("")
        self.summary_label.setStyleSheet("color: #444;")
        layout.addWidget(self.summary_label)
        content = QtWidgets.QHBoxLayout()
        content.setSpacing(8)
        self.body_label = QtWidgets.QLabel("")
        self.body_label.setWordWrap(True)
        self.body_label.setTextFormat(QtCore.Qt.RichText)
        content.addWidget(self.body_label, 1)
        self.chart = StatsBarChart()
        content.addWidget(self.chart, 1)
        layout.addLayout(content)

    def set_loadout(
        self,
        loadout: FoodLoadout | None,
        stat_key: str,
        stat_labels: Dict[str, str],
        max_totals: Dict[str, float],
        stat_order: Sequence[str],
        balanced_scores: Dict[str, float],
        label_width: int,
    ) -> None:
        if not loadout:
            self.summary_label.setText("")
            self.body_label.setText("<i>No loadout available.</i>")
            self.chart.setVisible(False)
            return
        avg_minutes = int(round(loadout.avg_duration_sec / 60.0))
        if stat_key == BALANCED_KEY:
            score = balanced_scores.get(loadout.name_key, 0.0)
            self.summary_label.setText(f"Balanced Score: {score:.3f} | Avg Time: {avg_minutes}m")
        else:
            total = loadout.total_attributes.get(stat_key, 0.0)
            self.summary_label.setText(
                f"Total {stat_labels.get(stat_key, stat_key)}: {total:.1f} | Avg Time: {avg_minutes}m"
            )
        self.chart.set_data(loadout.total_attributes, max_totals, stat_labels, stat_order, label_width)
        lines: List[str] = []
        for item in loadout.items:
            item_minutes = int(round(item.duration_sec / 60.0))
            lines.append(f"<div>&bull; <b>{item.name}</b> ({item_minutes}m)</div>")
        self.body_label.setText("".join(lines))


class FoodStatCard(QtWidgets.QFrame):
    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(4)
        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setWordWrap(False)
        self.title_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        title_font = self.title_label.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        self.title_label.setFont(title_font)
        self._full_title = title
        self._sync_title_height()
        layout.addWidget(self.title_label)
        self.loadout_panels = [
            FoodLoadoutPanel(""),
            FoodLoadoutPanel(""),
            FoodLoadoutPanel(""),
        ]
        for panel in self.loadout_panels:
            layout.addWidget(panel)

    def set_stat(
        self,
        stat_key: str,
        stat_label: str,
        loadouts: Sequence[FoodLoadout],
        stat_labels: Dict[str, str],
        max_totals: Dict[str, float],
        stat_order: Sequence[str],
        balanced_scores: Dict[str, float],
        label_width: int,
    ) -> None:
        self._full_title = stat_label
        self._update_title_elide()
        for idx, panel in enumerate(self.loadout_panels):
            panel.set_loadout(
                loadouts[idx] if idx < len(loadouts) else None,
                stat_key,
                stat_labels,
                max_totals,
                stat_order,
                balanced_scores,
                label_width,
            )

    def _sync_title_height(self) -> None:
        fm = self.title_label.fontMetrics()
        self.title_label.setFixedHeight(fm.height() + 4)

    def _update_title_elide(self) -> None:
        if not self._full_title:
            self.title_label.setText("")
            return
        fm = self.title_label.fontMetrics()
        text = fm.elidedText(self._full_title, QtCore.Qt.ElideRight, max(10, self.title_label.width()))
        self.title_label.setText(text)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_title_height()
        self._update_title_elide()


class FoodCalculatorPage(QtWidgets.QWidget):
    selectionChanged = QtCore.Signal(list)
    collapseChanged = QtCore.Signal(bool)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: FoodCalculatorModel | None = None
        self._food_items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._stat_labels: Dict[str, str] = {}
        self._pending_selected: set[str] = set()
        self._foods_collapsed = False
        self._left_width = 260

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(SectionHeader("Food Calculator"))
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        layout.addWidget(self.splitter, 1)

        self.left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QtWidgets.QLabel("Available Foods"))
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        left_layout.addWidget(self.tree, 1)
        self.splitter.addWidget(self.left_panel)

        self.right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_header = QtWidgets.QHBoxLayout()
        right_header.addStretch(1)
        self.toggle_button = QtWidgets.QToolButton()
        self.toggle_button.setText("Hide foods")
        right_header.addWidget(self.toggle_button)
        right_layout.addLayout(right_header)
        self.results_stack = QtWidgets.QStackedLayout()
        right_layout.addLayout(self.results_stack, 1)

        self.placeholder = QtWidgets.QLabel("Select available foods to see loadouts.")
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self.results_stack.addWidget(self.placeholder)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.stats_container = QtWidgets.QWidget()
        self.stats_layout = QtWidgets.QVBoxLayout(self.stats_container)
        self.stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_layout.setSpacing(8)

        self.primary_grid = QtWidgets.QGridLayout()
        self.primary_grid.setSpacing(10)
        self.stats_layout.addLayout(self.primary_grid)

        self.secondary_grid = QtWidgets.QGridLayout()
        self.secondary_grid.setSpacing(10)
        self.stats_layout.addLayout(self.secondary_grid)
        self.stats_layout.addStretch(1)

        self.scroll.setWidget(self.stats_container)
        self.results_stack.addWidget(self.scroll)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([self._left_width, 800])

        self.tree.itemChanged.connect(self._handle_item_changed)
        self.toggle_button.clicked.connect(self._toggle_foods_panel)
        self.splitter.splitterMoved.connect(self._handle_splitter_moved)

    def set_model(self, model: FoodCalculatorModel | None) -> None:
        self._model = model
        self._rebuild_tree()
        self._refresh_loadouts()

    def set_foods_collapsed(self, collapsed: bool) -> None:
        self._foods_collapsed = bool(collapsed)
        sizes = self.splitter.sizes()
        right_size = sizes[1] if len(sizes) > 1 else 800
        if self._foods_collapsed:
            self.splitter.setSizes([0, max(1, right_size)])
            self.toggle_button.setText("Show foods")
        else:
            restore = self._left_width or 260
            self.splitter.setSizes([restore, max(1, right_size)])
            self.toggle_button.setText("Hide foods")

    def set_selected_foods(self, keys: Iterable[str]) -> None:
        self._pending_selected = {str(k) for k in keys if k}
        if self._food_items:
            self._apply_selection()

    def selected_foods(self) -> List[str]:
        return self._checked_food_keys()

    def _rebuild_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self._food_items = {}
        if not self._model:
            self.tree.blockSignals(False)
            return
        grouped: Dict[str, Dict[int | None, List[FoodItem]]] = {}
        for item in self._model.foods:
            grouped.setdefault(item.food_type, {}).setdefault(item.tier, []).append(item)

        for food_type in sorted(grouped.keys()):
            if "." in food_type:
                type_label = food_type.split(".", 1)[1]
            else:
                type_label = food_type
            type_item = QtWidgets.QTreeWidgetItem([type_label])
            type_item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(type_item)
            tiers = grouped[food_type]
            for tier in sorted(tiers.keys(), key=lambda v: (v is None, v or 0)):
                tier_label = f"Tier {tier}" if tier is not None else "Tier ?"
                tier_item = QtWidgets.QTreeWidgetItem([tier_label])
                tier_item.setFlags(QtCore.Qt.ItemIsEnabled)
                type_item.addChild(tier_item)
                items = sorted(tiers[tier], key=lambda f: (f.item_level or 0, f.name))
                for food in items:
                    minutes = int(round(food.duration_sec / 60.0))
                    label = f"{food.name} ({minutes}m)"
                    leaf = QtWidgets.QTreeWidgetItem([label])
                    leaf.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
                    leaf.setCheckState(0, QtCore.Qt.Unchecked)
                    leaf.setData(0, QtCore.Qt.UserRole, food.key)
                    tier_item.addChild(leaf)
                    self._food_items[food.key] = leaf
            type_item.setExpanded(True)
        self.tree.blockSignals(False)
        if self._pending_selected:
            self._apply_selection()

    def _checked_food_keys(self) -> List[str]:
        return [k for k, item in self._food_items.items() if item.checkState(0) == QtCore.Qt.Checked]

    def _apply_selection(self) -> None:
        self.tree.blockSignals(True)
        for key, item in self._food_items.items():
            state = QtCore.Qt.Checked if key in self._pending_selected else QtCore.Qt.Unchecked
            item.setCheckState(0, state)
        self.tree.blockSignals(False)
        self._refresh_loadouts()

    def _refresh_loadouts(self) -> None:
        if not self._model:
            self.results_stack.setCurrentIndex(0)
            return
        checked = self._checked_food_keys()
        if not checked:
            self.results_stack.setCurrentIndex(0)
            return
        stat_keys = self._model.stat_keys_for(checked)
        if not stat_keys:
            self.results_stack.setCurrentIndex(0)
            return
        self._stat_labels = {key: _stat_label(key) for key in stat_keys}
        loadouts_by_stat, max_totals, _max_duration, balanced_scores = self._model.build_loadouts(checked, stat_keys)
        if BALANCED_KEY in loadouts_by_stat:
            self._stat_labels[BALANCED_KEY] = _stat_label(BALANCED_KEY)
        stat_order = sorted(stat_keys, key=_stat_sort_key)
        label_width = self._compute_chart_label_width(stat_order)
        self._render_stat_windows(stat_keys, loadouts_by_stat, max_totals, stat_order, balanced_scores, label_width)
        self.results_stack.setCurrentIndex(1)

    def _render_stat_windows(
        self,
        stat_keys: Sequence[str],
        loadouts_by_stat: Dict[str, List[FoodLoadout]],
        max_totals: Dict[str, float],
        stat_order: Sequence[str],
        balanced_scores: Dict[str, float],
        label_width: int,
    ) -> None:
        self._clear_layout(self.primary_grid)
        self._clear_layout(self.secondary_grid)

        primary_stats = [s for s in PRIMARY_STATS if s in stat_keys]
        rest_stats: List[str] = []
        if BALANCED_KEY in loadouts_by_stat:
            rest_stats.append(BALANCED_KEY)
        rest_stats.extend([s for s in stat_order if s not in primary_stats])

        primary_positions = [
            (0, 0, "PseudoMaxHealth"),
            (0, 1, "HealthRgn"),
            (1, 0, "PseudoMaxStamina"),
            (1, 1, "StaminaRgn"),
        ]
        for row, col, stat in primary_positions:
            if stat not in stat_keys:
                continue
            card = FoodStatCard(self._stat_labels.get(stat, stat))
            loadouts = loadouts_by_stat.get(stat, [])
            card.set_stat(
                stat,
                self._stat_labels.get(stat, stat),
                loadouts,
                self._stat_labels,
                max_totals,
                stat_order,
                balanced_scores,
                label_width,
            )
            self.primary_grid.addWidget(card, row, col)

        columns = 2
        row = 0
        col = 0
        for stat in rest_stats:
            card = FoodStatCard(self._stat_labels.get(stat, stat))
            loadouts = loadouts_by_stat.get(stat, [])
            card.set_stat(
                stat,
                self._stat_labels.get(stat, stat),
                loadouts,
                self._stat_labels,
                max_totals,
                stat_order,
                balanced_scores,
                label_width,
            )
            self.secondary_grid.addWidget(card, row, col)
            col += 1
            if col >= columns:
                col = 0
                row += 1

    def _clear_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            else:
                child_layout = item.layout()
                if child_layout:
                    self._clear_layout(child_layout)

    def _compute_chart_label_width(self, stat_order: Sequence[str]) -> int:
        fm = QtGui.QFontMetrics(self.font())
        labels = [
            self._stat_labels.get(key, key)
            for key in stat_order
            if key != BALANCED_KEY
        ]
        if not labels:
            return 96
        max_width = max(fm.horizontalAdvance(label) for label in labels)
        return max(96, max_width + 8)

    @QtCore.Slot(QtWidgets.QTreeWidgetItem, int)
    def _handle_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        _ = column
        if not item.data(0, QtCore.Qt.UserRole):
            return
        self._refresh_loadouts()
        self.selectionChanged.emit(self._checked_food_keys())

    @QtCore.Slot()
    def _toggle_foods_panel(self) -> None:
        sizes = self.splitter.sizes()
        if not sizes:
            return
        if not self._foods_collapsed and sizes[0] > 0:
            self._left_width = sizes[0]
            self.splitter.setSizes([0, max(1, sizes[1])])
            self._foods_collapsed = True
            self.toggle_button.setText("Show foods")
            self.collapseChanged.emit(True)
        else:
            restore = self._left_width or 260
            self.splitter.setSizes([restore, max(1, sizes[1])])
            self._foods_collapsed = False
            self.toggle_button.setText("Hide foods")
            self.collapseChanged.emit(False)

    @QtCore.Slot(int, int)
    def _handle_splitter_moved(self, pos: int, index: int) -> None:
        _ = pos
        _ = index
        sizes = self.splitter.sizes()
        if not sizes:
            return
        prev = self._foods_collapsed
        if sizes[0] == 0:
            self._foods_collapsed = True
            self.toggle_button.setText("Show foods")
        else:
            self._foods_collapsed = False
            self._left_width = sizes[0]
            self.toggle_button.setText("Hide foods")
        if prev != self._foods_collapsed:
            self.collapseChanged.emit(self._foods_collapsed)
