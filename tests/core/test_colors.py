"""Note colours: the palette, and the colours worked out from a background."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stickle.core.colors import (
    DEFAULT_COLOR,
    HIGHLIGHT_DIFFERENCE,
    MIN_CONTRAST,
    PALETTE,
    Rgb,
    colors_for,
    contrast,
    difference,
    luminance,
    note_colors,
)

channels = st.integers(0, 255)
any_color = st.builds(Rgb, channels, channels, channels)


def test_contrast_follows_wcag() -> None:
    assert contrast(Rgb(0, 0, 0), Rgb(255, 255, 255)) == pytest.approx(21)
    assert contrast(Rgb(119, 119, 119), Rgb(255, 255, 255)) == pytest.approx(4.48, abs=0.01)
    assert contrast(Rgb(10, 20, 30), Rgb(10, 20, 30)) == 1


def test_palette_has_twelve_colours_stored_by_key() -> None:
    assert len(PALETTE) == 12
    assert DEFAULT_COLOR in PALETTE
    assert all(key.isidentifier() for key in PALETTE)


@pytest.mark.parametrize("key", list(PALETTE))
def test_every_palette_colour_reads_well(key: str) -> None:
    colors = note_colors(key)

    assert colors.background == PALETTE[key]  # already readable: shown as chosen
    assert contrast(colors.text, colors.background) >= MIN_CONTRAST
    assert contrast(colors.title_text, colors.title_bar) >= MIN_CONTRAST
    assert contrast(colors.text, colors.highlight) >= MIN_CONTRAST
    assert contrast(colors.text, colors.code_background) >= MIN_CONTRAST
    assert difference(colors.highlight, colors.background) >= HIGHLIGHT_DIFFERENCE
    assert colors.title_bar != colors.background
    assert colors.border != colors.background


def test_highlight_prefers_yellow_but_not_on_a_yellow_note() -> None:
    assert note_colors("blue").highlight == Rgb.from_hex("#ffe14d")
    assert note_colors("yellow").highlight != Rgb.from_hex("#ffe14d")


def test_unknown_key_shows_the_default_colour() -> None:
    assert note_colors("teal2") == note_colors(DEFAULT_COLOR)


@given(any_color)
def test_any_background_gets_readable_text(background: Rgb) -> None:
    colors = colors_for(background)

    assert contrast(colors.text, colors.background) >= MIN_CONTRAST
    assert contrast(colors.title_text, colors.title_bar) >= MIN_CONTRAST
    assert contrast(colors.text, colors.highlight) >= MIN_CONTRAST
    assert contrast(colors.text, colors.code_background) >= MIN_CONTRAST


def test_a_dark_note_gets_light_text_and_a_lighter_title_bar() -> None:
    colors = colors_for(Rgb(40, 44, 52))

    assert colors.text == Rgb(255, 255, 255)
    assert luminance(colors.title_bar) > luminance(colors.background)
    assert luminance(colors.border) > luminance(colors.background)


@given(any_color)
def test_hex_round_trip(color: Rgb) -> None:
    assert Rgb.from_hex(color.hex) == color
