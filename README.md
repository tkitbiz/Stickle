# Stickle

**Sticky notes for your desktop — the same notes on every computer, Windows, Linux or macOS, through your own cloud.**

[한국어](README.ko.md) · [Website](https://stickle.linkro.co) ·
[Microsoft Store](https://apps.microsoft.com/detail/9MZ6BHN3JKFR)

> **Status: preview.** The 0.2 preview is out: sticky notes on one computer, for Windows and
> Linux, now with search, a trash, keyboard shortcuts and a portable mode. Syncing between
> computers is not there yet — see [Try the preview](#try-the-preview).
> To hear about new versions, click **Watch → Custom → Releases** at the top of this page.
> A star tells us you are interested, but does not notify you.

## Why Stickle

- **No account, no Stickle server.** Your notes sync through a folder you already sync for yourself —
  Dropbox, OneDrive, Google Drive, iCloud Drive, Syncthing, Nextcloud and the like.
  Your notes never pass through us, and we could not read them if we tried.
- **Private by design.** Notes are encrypted on your computer, with optional end-to-end
  encryption for sync. There is no analytics or telemetry of any kind. The only other
  connection the app makes is a daily update check that you can turn off.
- **Works offline.** Every feature works without a network, and notes sync by themselves
  once you are back online.
- **Notes are plain Markdown.** Type `# heading`, `**bold**`, `==highlight==` or `- [ ]` and
  the note shows it formatted, with boxes you can tick; double-click to edit the text. Your
  notes stay ordinary text you can read anywhere — no special format to be locked into.
  Not into Markdown? Just write.
- **Notes never disappear without you knowing.** When two computers change the same note, both versions
  are kept. Deleted notes stay in the trash for a year, and a recovery key opens your notes
  if you forget your password.
- **Free, with every feature.** No ads, no locked features, no paid tier. Stickle is free
  software (GPL) and is funded by donations only.
- **Stays out of your way.** No reminders, banners or pop-ups asking for anything.
- **Just works.** Nothing else to install: every library and font the app needs comes with
  it. Input methods work, tested with Korean on Windows and with fcitx5 and IBus on Linux.

## Roadmap

| Version | What you get |
| --- | --- |
| 0.1 *(preview out)* | Everyday sticky notes on a single computer: colours, formatting, notes that remember where they were, always on top, tray icon, start with your computer |
| 0.2 *(preview out)* | Search, a trash that keeps notes for a year, shortcuts from anywhere, see-through and locked notes, full keyboard use, portable mode; on the [Microsoft Store](https://apps.microsoft.com/detail/9MZ6BHN3JKFR) |
| 1.0 | Sync between your computers through a synced folder; packages for Linux (Flathub, AppImage, deb) and macOS (Homebrew) |
| Later | WebDAV and S3 storage, what-you-see-is-what-you-get editing, tags, shared notes and a browser extension, a read-only viewer for phones |

## Try the preview

Previews are under [Releases](https://github.com/linkro-app/Stickle/releases), marked
*pre-release*. macOS builds are on the way.

- **Windows** (10 or 11): get Stickle from the
  [Microsoft Store](https://apps.microsoft.com/detail/9MZ6BHN3JKFR). Microsoft signs it, so
  Windows installs it without a warning and keeps it up to date. The Store version and the zip
  below keep notes in the same folder (`%APPDATA%\Stickle`), so moving from one to the other
  keeps your notes.

  Or download the zip for your computer (`x64`, or `arm64` for ARM
  laptops), unzip it anywhere and run `stickle.exe`. The zip is not signed yet, so Windows
  may say it protected your PC: choose **More info → Run anyway**. When **Start Stickle
  when I log in** is on, Microsoft Defender has been seen to block it as
  `Trojan:Win32/Bearfoos.A!ml`: its machine learning takes an unsigned program that starts
  itself at login for a trojan. This is a false positive, which we are reporting to
  Microsoft; signed builds are planned. Until then that option starts off on Windows. If
  Defender blocks Stickle for you, please
  [open an issue](https://github.com/linkro-app/Stickle/issues/new) so we know.
- **Linux**: download the AppImage, make it executable (`chmod +x Stickle-x86_64.AppImage`,
  or in its file properties) and run it. Stickle offers to add itself to your application list.
  With automatic login, the desktop's keyring stays locked, so when Stickle starts with you it
  asks for your login password to unlock it, as any app using the keyring does. To avoid that,
  turn automatic login off, or give the login keyring an empty password.
- The first start asks a few questions and shows a **recovery key**. Keep it somewhere safe,
  away from this computer: it opens your notes if the key stored on this computer is ever lost.
- Downloads can be checked against `SHA256SUMS.txt` in the same release.

New in 0.2:

- **Search** every note from the Stickle window (`Ctrl+F`), Korean included.
- **Trash**: deleted notes stay there for a year and can be put back.
- **Shortcuts from anywhere**: `Ctrl+Alt+N` a new note, `Ctrl+Alt+S` the Stickle window,
  `Ctrl+Alt+H` every note out of sight for a moment (and back). They can be changed in the
  Stickle window. On Wayland the desktop asks once whether to allow them.
- A new note from the **clipboard**, from the Stickle window.
- **See-through** notes while you work elsewhere, and **locked** notes that cannot be moved
  or edited by accident (in each note's `⋯` menu).
- **Keyboard only**: move between notes with `Ctrl+Tab`, tick boxes and open links from the
  keyboard, move and resize a note with the arrow keys.
- Notes made with the 0.1.2 preview open as they were: just replace the program. A copy of
  the notes from before is kept in the `backups` folder where the notes are
  (`%APPDATA%\Stickle\backups` on Windows, `~/.local/share/stickle/backups` on Linux).

### Portable use

To carry Stickle and its notes on a USB stick, on Windows download the `-portable.zip`,
unzip it anywhere and run `stickle.exe`. It is the same program with a `stickle-data`
folder next to `stickle.exe`. Any other copy of Stickle becomes portable the same way:
create an empty folder named `stickle-data` in the folder that holds `stickle.exe` (on
Linux, the folder that holds the AppImage).

Stickle then keeps its settings and notes only in that folder: it always asks for a
password, since it does not use this computer's password store, and it does not start at
login or add itself to the application list. On Wayland it has no shortcuts from anywhere,
which the desktop would have to keep.

What a preview is, and is not:

- Notes are kept on this computer only, encrypted. There is no syncing or backup yet.
- Later versions are meant to open notes made with a preview, but the way notes are stored
  may still change, and a preview can have bugs. Keep anything important elsewhere too.

## Help test

Reports from real computers are the most useful help right now, especially from macOS,
KDE, less common Linux distributions, input methods, and multi-monitor or high-DPI setups.
[Open an issue](https://github.com/linkro-app/Stickle/issues/new) and include:

- your operating system and version, and on Linux your desktop (GNOME, KDE, …) and input method;
- what you did, what you expected, and what happened instead;
- if Stickle shows a problem screen, the text from its **Copy details** button;
- if possible, the log file. It contains no personal information such as note text or
  folder paths:

| System | Log file |
| --- | --- |
| Windows | `%APPDATA%\Stickle\logs\stickle.log` |
| Linux | `~/.local/share/stickle/logs/stickle.log` |
| macOS | `~/Library/Application Support/Stickle/logs/stickle.log` |

## Run from source

With [uv](https://docs.astral.sh/uv/) installed:

```
uv sync
uv run python -m stickle
```

Tests: `uv run pytest`.

## Privacy

Stickle collects nothing and has no server: see the [privacy policy](PRIVACY.md).

## License

[GPL-3.0-or-later](LICENSE).
