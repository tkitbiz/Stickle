from stickle.app.application import NoteManager
from stickle.app.i18n import Translations
from stickle.app.tray import Tray


def test_switching_language_updates_open_windows_and_the_tray(
    translations: Translations,
) -> None:
    manager = NoteManager()
    tray = Tray(manager.new_note, lambda: None, translations)
    note = manager.new_note()
    try:
        assert note.title_bar.close_button.toolTip() == "Hide note"
        assert tray.new_note_action.text() == "New note"

        translations.apply("ko")

        assert note.title_bar.close_button.toolTip() == "메모 숨기기"
        assert note.editor.accessibleName() == "메모 내용"
        assert tray.new_note_action.text() == "새 메모"
        assert tray.language_menu.title() == "언어"
        # A note opened after the switch starts in the new language too.
        assert manager.new_note().title_bar.close_button.toolTip() == "메모 숨기기"

        translations.apply("en")

        assert note.title_bar.close_button.toolTip() == "Hide note"
        assert tray.quit_action.text() == "Quit Stickle"
    finally:
        for window in manager.windows:
            window.close()


def test_language_names_stay_in_their_own_language(translations: Translations) -> None:
    tray = Tray(lambda: None, lambda: None, translations)

    translations.apply("ko")

    assert tray.language_actions["en"].text() == "English"
    assert tray.language_actions["ko"].text() == "한국어"
