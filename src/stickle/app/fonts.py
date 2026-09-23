"""Make sure Korean (and Chinese, Japanese) text has a font to draw with.

The system's fonts come first. Only when Korean text would come out as
empty "missing glyph" boxes, as on a minimal Linux install, is the bundled
Noto Sans CJK KR registered and added as a fallback family for the whole
application. The file is only bundled in Linux builds; Windows and macOS
always ship Korean fonts.
"""

from pathlib import Path

from PySide6.QtGui import QFontDatabase, QGuiApplication, QTextLayout

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
FALLBACK_FONT = FONTS_DIR / "NotoSansCJKkr-Regular.otf"
SAMPLE = "한글 입력 테스트"


def korean_is_drawable() -> bool:
    """Whether the application font, with Qt's fallbacks, has glyphs for Korean.

    Laying the text out is the direct test: font databases do not report
    writing-system support reliably on every platform plugin.
    """
    layout = QTextLayout(SAMPLE, QGuiApplication.font())
    layout.beginLayout()
    layout.createLine()
    layout.endLayout()
    runs = layout.glyphRuns()
    # Glyph 0 is the "missing glyph" box.
    return bool(runs) and all(0 not in run.glyphIndexes() for run in runs)


def ensure_korean_font(fallback: Path = FALLBACK_FONT) -> str | None:
    """Register the bundled font if Korean is not drawable; return its family if used."""
    if korean_is_drawable() or not fallback.exists():
        return None
    font_id = QFontDatabase.addApplicationFont(str(fallback))
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        return None
    font = QGuiApplication.font()
    current = font.families() or [font.family()]
    font.setFamilies([*current, *families])
    QGuiApplication.setFont(font)
    return families[0]
