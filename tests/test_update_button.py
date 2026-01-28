import bootstrap  # noqa: F401

import pytest
from PySide6 import QtCore, QtWidgets

from paxdei_ui.app import ConfigPage
from paxdei_ui.config_store import CrafterEntry, MaterialEntry, ProfileData, SkillEntry


class _FakeUpdater(QtCore.QObject):
    status_changed = QtCore.Signal(str)
    update_finished = QtCore.Signal(bool, str)

    def __init__(self, configured: bool = True) -> None:
        super().__init__()
        self._configured = configured
        self.check_called = False

    def is_configured(self) -> bool:
        return self._configured

    def check_for_updates(self) -> None:
        self.check_called = True


class _FakeStore:
    def __init__(self) -> None:
        self.profile = ProfileData(
            premium_account=False,
            avoid_relics=False,
            max_cross_skill_gap=5,
            skills=[SkillEntry("skill_test", "Test", 1, 0, 40)],
            crafters=[CrafterEntry("crafter_test", "Test Crafter", False)],
        )
        self.materials = [
            MaterialEntry("item_test", "Test Item", "Desc", True),
        ]

    def save_profile(self) -> None:
        pass

    def save_materials(self) -> None:
        pass


@pytest.fixture()
def qapp() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_update_button_disabled_when_not_configured(qapp: QtWidgets.QApplication) -> None:
    store = _FakeStore()
    updater = _FakeUpdater(configured=False)
    page = ConfigPage(store, updater=updater)

    assert not page.update_button.isEnabled()


def test_update_button_flow_success(qapp: QtWidgets.QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _FakeStore()
    updater = _FakeUpdater(configured=True)
    page = ConfigPage(store, updater=updater)

    info_calls = []
    warning_calls = []

    def _info(*_args, **_kwargs) -> None:
        info_calls.append((_args, _kwargs))

    def _warn(*_args, **_kwargs) -> None:
        warning_calls.append((_args, _kwargs))

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", _info)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _warn)

    assert page.update_button.isEnabled()
    page.update_button.click()
    QtWidgets.QApplication.processEvents()

    assert updater.check_called is True
    assert not page.update_button.isEnabled()
    assert page.update_status.text() == "Checking for updates..."

    updater.update_finished.emit(True, "Bundle updated.")
    QtWidgets.QApplication.processEvents()

    assert page.update_button.isEnabled()
    assert page.update_status.text() == "Bundle updated."
    assert len(info_calls) == 1
    assert len(warning_calls) == 0


def test_update_button_flow_failure(qapp: QtWidgets.QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _FakeStore()
    updater = _FakeUpdater(configured=True)
    page = ConfigPage(store, updater=updater)

    info_calls = []
    warning_calls = []

    def _info(*_args, **_kwargs) -> None:
        info_calls.append((_args, _kwargs))

    def _warn(*_args, **_kwargs) -> None:
        warning_calls.append((_args, _kwargs))

    monkeypatch.setattr(QtWidgets.QMessageBox, "information", _info)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _warn)

    page.update_button.click()
    QtWidgets.QApplication.processEvents()

    updater.update_finished.emit(False, "Update failed.")
    QtWidgets.QApplication.processEvents()

    assert page.update_button.isEnabled()
    assert page.update_status.text() == "Update failed."
    assert len(info_calls) == 0
    assert len(warning_calls) == 1
