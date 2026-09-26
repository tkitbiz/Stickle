"""Saving while typing: soon after a pause, regularly while typing goes on,
the character being composed once committed, and again after a failure."""

import random
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from stickle.app.note_window import NoteWindow
from stickle.app.notes import NoteManager
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store

KEY = secrets.token_bytes(32)
IDLE_MS = 50
MAX_MS = 300


class Recorder:
    """Every text the repository was asked to store, in order."""

    def __init__(self, repository: NoteRepository, monkeypatch: pytest.MonkeyPatch) -> None:
        self.saved: list[str] = []
        self.fail = False
        create, update = repository.create, repository.update_body

        def recording_create(body: str = "", color: str = "yellow"):
            self._maybe_fail()
            self.saved.append(body)
            return create(body, color)

        def recording_update(note_id: str, body: str):
            self._maybe_fail()
            self.saved.append(body)
            return update(note_id, body)

        monkeypatch.setattr(repository, "create", recording_create)
        monkeypatch.setattr(repository, "update_body", recording_update)

    def _maybe_fail(self) -> None:
        if self.fail:
            raise apsw.FullError("database or disk is full")


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[NoteRepository]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield NoteRepository(connection)
    connection.close()


@pytest.fixture
def recorder(repository: NoteRepository, monkeypatch: pytest.MonkeyPatch) -> Recorder:
    return Recorder(repository, monkeypatch)


@pytest.fixture
def manager(qtbot: QtBot, repository: NoteRepository) -> Iterator[NoteManager]:
    manager = NoteManager(repository, idle_ms=IDLE_MS, max_ms=MAX_MS)
    yield manager
    for window in manager.windows:
        window.release()


def type_into(window: NoteWindow, text: str) -> None:
    window.editor.moveCursor(QTextCursor.MoveOperation.End)
    window.editor.insertPlainText(text)


def stored(repository: NoteRepository) -> list[str]:
    return [note.body for note in repository.all()]


def compose(window: NoteWindow, preedit: str, commit: str = "") -> None:
    """What an input method sends: the character being composed, and what it commits."""
    event = QInputMethodEvent(preedit, [])
    if commit:
        event.setCommitString(commit)
    QApplication.sendEvent(window.editor, event)


# A. A pause of a second (here: IDLE_MS) saves, without closing anything.
def test_a_pause_saves(qtbot: QtBot, manager: NoteManager, repository: NoteRepository) -> None:
    window = manager.new_note()
    type_into(window, "회의록")
    assert stored(repository) == []  # not at once: a moment after typing stops

    qtbot.waitUntil(lambda: stored(repository) == ["회의록"], timeout=2000)
    assert not window.unsaved


# B. Typing without a pause still saves regularly.
def test_steady_typing_still_saves(qtbot: QtBot, manager: NoteManager, recorder: Recorder) -> None:
    window = manager.new_note()
    for _ in range(40):  # a keystroke every 20 ms for 0.8 s, never pausing for IDLE_MS
        type_into(window, "가")
        qtbot.wait(20)
        if recorder.saved:
            break

    assert recorder.saved, "nothing saved during steady typing"
    assert len(window.text) > len(recorder.saved[0]) or window.text == recorder.saved[0]


# C. The character being composed is not saved until it is committed.
def test_composing_character_is_saved_once_committed(
    qtbot: QtBot, manager: NoteManager, repository: NoteRepository
) -> None:
    window = manager.new_note()
    type_into(window, "안녕")
    compose(window, "하")
    assert window.composing
    assert window.text == "안녕"

    qtbot.waitUntil(lambda: stored(repository) == ["안녕"], timeout=2000)
    compose(window, "", commit="하")
    assert not window.composing

    qtbot.waitUntil(lambda: stored(repository) == ["안녕하"], timeout=2000)


def test_hiding_while_composing_keeps_the_character(
    qtbot: QtBot, manager: NoteManager, repository: NoteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = manager.new_note()
    type_into(window, "안녕")
    compose(window, "하")

    # The input method commits when asked; here it is asked through the window.
    monkeypatch.setattr(window, "commit_composition", lambda: compose(window, "", commit="하"))
    window.title_bar.close_button.click()

    assert [n.body for n in repository.hidden()] == ["안녕하"]


# D. The session ending saves everything, and nothing becomes hidden.
def test_session_end_saves_without_hiding(manager: NoteManager, repository: NoteRepository) -> None:
    first, second = manager.new_note(), manager.new_note()
    type_into(first, "첫째")
    type_into(second, "둘째")

    manager.save_all(commit=True)

    assert sorted(stored(repository)) == ["둘째", "첫째"]
    assert repository.hidden() == []
    assert len(manager.windows) == 2
    second.title_bar.close_button.click()  # afterwards everything still works as usual
    assert [n.body for n in repository.hidden()] == ["둘째"]


# E. The system's sleep announcement triggers a save.
@pytest.mark.skipif(sys.platform != "win32", reason="Windows power messages")
def test_windows_sleep_message_is_recognised() -> None:
    assert sys.platform == "win32"  # for the type checker on other systems
    import ctypes

    from stickle.platform.windows.power import (
        MSG,
        PBT_APMSUSPEND,
        WM_POWERBROADCAST,
        SleepFilter,
    )

    calls: list[int] = []
    sleep_filter = SleepFilter(lambda: calls.append(1))
    for message, param, expected in (
        (WM_POWERBROADCAST, PBT_APMSUSPEND, 1),
        (WM_POWERBROADCAST, 0x0007, 0),  # resuming
        (0x0100, PBT_APMSUSPEND, 0),  # a key press
    ):
        msg = MSG()
        msg.message = message
        msg.wParam = param
        before = len(calls)
        sleep_filter.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
        assert len(calls) - before == expected


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="systemd-logind")
def test_logind_sleep_signal_is_recognised(qtbot: QtBot) -> None:
    from stickle.platform.linux.power import SleepWatcher

    calls: list[int] = []
    watcher = SleepWatcher(lambda: calls.append(1))
    watcher.prepare_for_sleep(True)
    watcher.prepare_for_sleep(False)  # waking up
    assert calls == [1]


def test_sleep_watch_never_fails_to_start(qtbot: QtBot) -> None:
    from stickle.platform.power import watch_sleep

    watch_sleep(lambda: None)  # without a system bus or on macOS: nothing watched, no error


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="systemd-logind")
def test_logind_connection_is_accepted(qtbot: QtBot) -> None:
    # Regression: PySide6 rejected the slot in the bytes form its type hints ask for,
    # which failed only where a system bus exists (every Linux desktop).
    from PySide6.QtDBus import QDBusConnection

    from stickle.platform.linux.power import SleepWatcher

    watcher = SleepWatcher(lambda: None)
    assert watcher.connected == QDBusConnection.systemBus().isConnected()


def test_a_failing_sleep_watch_is_only_logged(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from stickle.platform import power

    def broken(_: object) -> object:
        raise ValueError("wrong argument values")

    monkeypatch.setattr(power, "_watch", broken)
    assert power.watch_sleep(lambda: None) is None
    assert "sleep is not watched" in caplog.text


# F. A failed save keeps the text, says so, and is tried again.
def test_failed_save_is_shown_and_retried(
    qtbot: QtBot,
    manager: NoteManager,
    repository: NoteRepository,
    recorder: Recorder,
    caplog: pytest.LogCaptureFixture,
) -> None:
    window = manager.new_note()
    recorder.fail = True
    type_into(window, "디스크가 가득 참")

    qtbot.waitUntil(lambda: window.unsaved, timeout=2000)
    assert window.text == "디스크가 가득 참"
    assert manager.waiting_to_save()  # a retry is scheduled
    window.title_bar.close_button.click()
    assert window in manager.windows  # not closed: that would lose the text

    recorder.fail = False
    window.title_bar.unsaved_button.click()  # "try now"

    assert not window.unsaved
    assert stored(repository) == ["디스크가 가득 참"]
    assert "could not save a note: FullError" in caplog.text
    assert "디스크" not in caplog.text


# G. Nothing keeps running once everything is saved.
def test_no_timer_runs_when_all_is_saved(
    qtbot: QtBot, manager: NoteManager, repository: NoteRepository
) -> None:
    window = manager.new_note()
    type_into(window, "끝")
    assert manager.waiting_to_save()

    qtbot.waitUntil(lambda: stored(repository) == ["끝"], timeout=2000)
    assert not manager.waiting_to_save()


# H. Saving leaves the editing alone: cursor and undo history stay.
def test_saving_does_not_disturb_editing(
    qtbot: QtBot, manager: NoteManager, repository: NoteRepository
) -> None:
    window = manager.new_note()
    window.editor.insertPlainText("abc")
    cursor = window.editor.textCursor()
    cursor.setPosition(1)
    window.editor.setTextCursor(cursor)

    qtbot.waitUntil(lambda: stored(repository) == ["abc"], timeout=2000)

    assert window.editor.textCursor().position() == 1
    window.editor.undo()
    assert window.text == ""


# Invariant 1: whatever is stored was, at some moment, exactly the window's text.
def test_every_save_is_a_state_the_window_had(
    qtbot: QtBot, manager: NoteManager, recorder: Recorder
) -> None:
    window = manager.new_note()
    states = {""}
    window.editor.textChanged.connect(lambda: states.add(window.text))
    rng = random.Random(4)
    for _ in range(60):
        action = rng.random()
        if action < 0.6:
            type_into(window, rng.choice(["가", "a", " ", "\n", "😀"]))
        elif action < 0.8 and window.text:
            window.editor.textCursor().deletePreviousChar()
        else:
            qtbot.wait(rng.choice([5, 30, 80]))
    qtbot.waitUntil(
        lambda: bool(recorder.saved) and recorder.saved[-1] == window.text, timeout=3000
    )

    assert set(recorder.saved) <= states


def test_focus_loss_saves_at_once(manager: NoteManager, repository: NoteRepository) -> None:
    from PySide6.QtGui import QFocusEvent

    window = manager.new_note()
    type_into(window, "바로")
    QApplication.sendEvent(window.editor, QFocusEvent(QEvent.Type.FocusOut))

    assert stored(repository) == ["바로"]
