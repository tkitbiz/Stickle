"""Open the notes database at start-up, asking the user only when needed.

The key comes from the credential store without any question, or from a
password. When the notes cannot be opened, the recovery dialog explains why;
nothing is created, replaced or deleted on the way.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import apsw

from stickle.app.password_dialog import PasswordDialog
from stickle.app.recovery_dialog import Choice, Problem, RecoveryDialog
from stickle.crypto.keyfile import KeyFileError, WrongPasswordError
from stickle.data.database import WrongKeyError
from stickle.data.export import export_markdown
from stickle.data.schema import MigrationError, NewerSchemaError, open_store, schema_version
from stickle.unlock import Blocked, NeedPassword, Unlock, Unlocked

log = logging.getLogger(__name__)

# Replaceable in tests.
type AskPassword = Callable[[PasswordDialog], bool]
type AskRecovery = Callable[[RecoveryDialog], Choice]


def _exec(dialog: PasswordDialog) -> bool:
    return dialog.exec() == PasswordDialog.DialogCode.Accepted


def _run(dialog: RecoveryDialog) -> Choice:
    return dialog.run()


def _describe(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def _password_key(unlock: Unlock, create: bool, ask: AskPassword) -> bytes | None:
    key: bytes | None = None
    dialog: PasswordDialog

    def submit(password: str) -> str | None:
        nonlocal key
        try:
            key = unlock.create_password(password) if create else unlock.enter_password(password)
        except WrongPasswordError:
            return dialog.wrong_password()
        except (KeyFileError, OSError) as error:
            log.error("password key failed: %s", _describe(error))
            return dialog.key_file_failed(type(error).__name__)
        return None

    dialog = PasswordDialog(create, submit)
    return key if ask(dialog) else None


def _open_problem(error: Exception) -> Problem:
    if isinstance(error, WrongKeyError):
        return Problem("wrong_key", _describe(error))
    if isinstance(error, NewerSchemaError):
        return Problem("newer_version", _describe(error))
    if isinstance(error, MigrationError):
        return Problem("upgrade_failed", _describe(error), error.diff)
    return Problem("open_failed", _describe(error))


def open_notes(
    unlock: Unlock,
    ask_password: AskPassword = _exec,
    ask_recovery: AskRecovery = _run,
) -> apsw.Connection | None:
    """The open database, or None when the user chose to quit."""
    folder: Path = unlock.folder
    while True:
        outcome = unlock.outcome()
        if isinstance(outcome, Blocked):
            log.warning("notes cannot be unlocked: %s", outcome.problem)
            if ask_recovery(RecoveryDialog(Problem(outcome.problem), folder)) == Choice.QUIT:
                return None
            unlock.start()
            continue
        if isinstance(outcome, NeedPassword):
            key = _password_key(unlock, outcome.create, ask_password)
            if key is None:
                log.info("quit at the password prompt")
                return None
            source = "password"
        else:
            assert isinstance(outcome, Unlocked)
            key, source = outcome.key, outcome.source
        while True:
            try:
                connection = open_store(unlock.database, key)
            except (WrongKeyError, NewerSchemaError, MigrationError, apsw.Error) as error:
                problem = _open_problem(error)
                log.error("notes could not be opened: %s", problem.error)
                can_export = problem.kind in {"newer_version", "upgrade_failed", "open_failed"}
                dialog = RecoveryDialog(
                    problem,
                    folder,
                    (lambda target, key=key: export_markdown(unlock.database, key, target))
                    if can_export and unlock.database.exists()
                    else None,
                )
                if ask_recovery(dialog) == Choice.QUIT:
                    return None
                continue
            log.info(
                "notes opened (key from the %s, schema v%d)", source, schema_version(connection)
            )
            return connection
