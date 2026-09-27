"""Qt's own messages in Stickle's log."""

import logging

import pytest
from PySide6.QtCore import QMessageLogContext, QtMsgType

from stickle.app.application import log_qt_message

PORTAL = (
    'Failed to register with host portal QDBusError("org.freedesktop.portal.Error.Failed", '
    '"Could not register app ID: Connection already associated with an application ID")'
)


def test_qt_warnings_are_logged_as_warnings(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="qt"):
        log_qt_message(QtMsgType.QtWarningMsg, QMessageLogContext(), "something went wrong")

    assert [record.levelno for record in caplog.records] == [logging.WARNING]


def test_a_warning_that_means_nothing_for_stickle_is_kept_quiet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Printed at every start on GNOME, and seen as an error while testing.
    with caplog.at_level(logging.DEBUG, logger="qt"):
        log_qt_message(QtMsgType.QtWarningMsg, QMessageLogContext(), PORTAL)

    assert [record.levelno for record in caplog.records] == [logging.DEBUG]
