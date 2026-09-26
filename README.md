# Stickle

**Sticky notes for your desktop — the same notes on every computer, Windows, Linux or macOS, through your own cloud.**

[한국어](README.ko.md)

> **Status: in development.** Stickle is not ready for everyday notes yet. To hear when the
> first test build (0.1) is out, click **Watch → Custom → Releases** at the top of this page.
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
| 0.1 *(in progress)* | Everyday sticky notes on a single computer: colours, formatting, notes that remember where they were, always on top, tray icon, start with your computer |
| 0.2 | Search, trash, keyboard shortcuts, portable mode |
| 1.0 | Sync between your computers through a synced folder; packages for Windows (Microsoft Store), Linux (Flathub, AppImage, deb) and macOS (Homebrew) |
| Later | WebDAV and S3 storage, what-you-see-is-what-you-get editing, tags, shared notes and a browser extension, a read-only viewer for phones |

## Try a test build

Test builds will appear under [Releases](https://github.com/tkitbiz/Stickle/releases),
marked *pre-release*: a zip for Windows (x64 or ARM64) and an AppImage for Linux; macOS
builds are on the way. Test builds can have bugs that lose notes, so keep anything important
elsewhere too. The builds there today are technical checks and do not keep notes yet.

## Help test

Reports from real computers are the most useful help right now, especially from macOS,
KDE, less common Linux distributions, input methods, and multi-monitor or high-DPI setups.
[Open an issue](https://github.com/tkitbiz/Stickle/issues/new) and include:

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

## License

[GPL-3.0-or-later](LICENSE).
