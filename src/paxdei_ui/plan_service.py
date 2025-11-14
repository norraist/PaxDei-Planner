from __future__ import annotations

import queue
import traceback
from pathlib import Path
from typing import List

from PySide6 import QtCore

from paxdei_planner.level_planner import LevelPlanner, PlanStep


class PlanSnapshot:
    __slots__ = ("steps", "skill_names", "item_names")

    def __init__(self, steps: List[PlanStep], skill_names: dict[str, str], item_names: dict[str, str]) -> None:
        self.steps = steps
        self.skill_names = skill_names
        self.item_names = item_names

    def steps_for_skill(self, skill_key: str) -> List[PlanStep]:
        return [step for step in self.steps if step.skill == skill_key]

    def first_step(self) -> PlanStep | None:
        return self.steps[0] if self.steps else None

    def first_step_for_skill(self, skill_key: str) -> PlanStep | None:
        for step in self.steps:
            if step.skill == skill_key:
                return step
        return None

    def skill_label(self, key: str) -> str:
        return self.skill_names.get(key, key)

    def item_label(self, key: str) -> str:
        return self.item_names.get(key, key)


class PlanWorker(QtCore.QObject):
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(Exception)

    def __init__(
        self,
        static_path: Path,
        loc_path: Path,
        profile_path: Path,
        xp_tables_dir: Path,
        materials_config_path: Path,
        top_k: int,
        plan_csv: Path,
        shopping_csv: Path,
        steps_txt: Path,
    ) -> None:
        super().__init__()
        self.static_path = static_path
        self.loc_path = loc_path
        self.profile_path = profile_path
        self.xp_tables_dir = xp_tables_dir
        self.materials_config_path = materials_config_path
        self.top_k = top_k
        self.plan_csv = plan_csv
        self.shopping_csv = shopping_csv
        self.steps_txt = steps_txt
        self._progress_updates: "queue.Queue[tuple[float, int, int]]" = queue.Queue()

    def take_progress_updates(self) -> list[tuple[float, int, int]]:
        updates: list[tuple[float, int, int]] = []
        while True:
            try:
                updates.append(self._progress_updates.get_nowait())
            except queue.Empty:
                break
        return updates

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self.xp_tables_dir.mkdir(parents=True, exist_ok=True)
            planner = LevelPlanner(
                str(self.static_path),
                str(self.loc_path),
                str(self.profile_path),
                str(self.xp_tables_dir),
                materials_config_path=str(self.materials_config_path),
            )
            plan = planner.plan(top_k=self.top_k, progress_cb=self._record_progress)
            skill_names = {}
            profile = getattr(planner, "profile", {})
            for key, node in profile.get("skills", {}).items():
                if isinstance(node, dict):
                    skill_names[key] = str(node.get("name", key))
            item_names = getattr(planner, "item_names", {})
            planner.write_csv(plan, str(self.plan_csv))
            planner.write_materials_csv(plan, str(self.shopping_csv))
            planner.write_steps_text(plan, str(self.steps_txt))
            self.finished.emit(PlanSnapshot(plan, skill_names, item_names))
        except Exception as exc:  # pragma: no cover - UI thread logging
            traceback.print_exc()
            self.failed.emit(exc)

    def _record_progress(self, pct: float, done: int, total: int) -> None:
        self._progress_updates.put((pct, done, total))


class PlanService(QtCore.QObject):
    plan_ready = QtCore.Signal(object)
    plan_failed = QtCore.Signal(Exception)
    plan_started = QtCore.Signal()
    plan_progress = QtCore.Signal(float, int, int)

    def __init__(self) -> None:
        super().__init__()
        self._thread: QtCore.QThread | None = None
        self._worker: PlanWorker | None = None
        self._progress_timer: QtCore.QTimer | None = None

    def request_plan(
        self,
        static_path: Path,
        loc_path: Path,
        profile_path: Path,
        xp_tables_dir: Path,
        materials_config_path: Path,
        top_k: int,
        plan_csv: Path,
        shopping_csv: Path,
        steps_txt: Path,
    ) -> None:
        self.cancel()
        worker = PlanWorker(
            static_path,
            loc_path,
            profile_path,
            xp_tables_dir,
            materials_config_path,
            top_k,
            plan_csv,
            shopping_csv,
            steps_txt,
        )
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._handle_finished)
        worker.failed.connect(self._handle_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        self._start_progress_timer()
        self.plan_started.emit()
        thread.start()

    def cancel(self) -> None:
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self._stop_progress_timer()

    def _handle_finished(self, snapshot: PlanSnapshot) -> None:
        self._poll_progress()
        self.plan_ready.emit(snapshot)
        self._cleanup()

    def _handle_failed(self, exc: Exception) -> None:
        self._poll_progress()
        self.plan_failed.emit(exc)
        self._cleanup()

    def _start_progress_timer(self) -> None:
        if self._progress_timer:
            self._progress_timer.stop()
            self._progress_timer.deleteLater()
        self._progress_timer = QtCore.QTimer(self)
        self._progress_timer.setInterval(200)
        self._progress_timer.timeout.connect(self._poll_progress)
        self._progress_timer.start()

    def _stop_progress_timer(self) -> None:
        if self._progress_timer:
            self._progress_timer.stop()
            self._progress_timer.deleteLater()
            self._progress_timer = None

    @QtCore.Slot()
    def _poll_progress(self) -> None:
        if not self._worker:
            return
        for pct, done, total in self._worker.take_progress_updates():
            self.plan_progress.emit(pct, done, total)

    def _cleanup(self) -> None:
        self._stop_progress_timer()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
        self._worker = None
