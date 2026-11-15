"""The cached radar-picture tiles: addresses, dates, merging, and what is kept on disk. No network."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from PIL import Image

from nisar_investigator import config, radar_tiles

END = date(2026, 10, 29)


def _picture(color: tuple[int, int, int, int], box: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGBA", (radar_tiles.TILE, radar_tiles.TILE), (0, 0, 0, 0))
    image.paste(color, box)
    return image


@pytest.fixture()
def gibs(monkeypatch, tmp_path):
    """A stand-in for NASA GIBS: `passes` maps a day to its picture; `down` lists days that fail."""
    state = {"passes": {}, "down": set(), "asked": []}

    def fetch(day, bbox, size=radar_tiles.TILE):
        state["asked"].append((day, size))
        if day in state["down"]:
            raise radar_tiles.UpstreamError("down")
        return state["passes"].get(day)

    monkeypatch.setattr(config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(radar_tiles, "_fetch_day", fetch)
    monkeypatch.setattr(radar_tiles, "_today", lambda: date(2026, 11, 14))
    return state


def test_square_addresses_cover_the_world():
    assert radar_tiles._bbox(0, 0, 0) == f"{-radar_tiles._HALF_WORLD},{-radar_tiles._HALF_WORLD},{radar_tiles._HALF_WORLD},{radar_tiles._HALF_WORLD}"
    west, south, east, north = map(float, radar_tiles._bbox(1, 1, 0).split(","))
    assert (west, south) == (0.0, 0.0) and east == pytest.approx(radar_tiles._HALF_WORLD) and north == pytest.approx(radar_tiles._HALF_WORLD)


def test_squares_for_a_box_include_the_place():
    squares = radar_tiles.tiles_for_bbox((-120.56, 50.675, -120.40, 50.735), 8)
    assert squares == [(8, 42, 86)]


def test_days_are_oldest_first_and_never_before_the_first_picture():
    days = radar_tiles._days(END, 12)
    assert days[0] == END - timedelta(days=11) and days[-1] == END
    assert radar_tiles._days(radar_tiles.FIRST_DAY + timedelta(days=2), 12) == [radar_tiles.FIRST_DAY + timedelta(days=i) for i in range(3)]


def test_opening_day_is_complete_and_holds_for_a_week(monkeypatch):
    seen = set()
    for offset in range(7):
        monkeypatch.setattr(radar_tiles, "_today", lambda offset=offset: date(2026, 11, 12) + timedelta(days=offset))
        end = radar_tiles.default_end()
        assert radar_tiles.is_settled(end)
        seen.add(end)
    assert len(seen) == 1


def test_days_are_merged_with_the_latest_pass_on_top(gibs):
    gibs["passes"] = {
        END - timedelta(days=3): _picture((255, 0, 0, 255), (0, 0, 300, 300)),
        END: _picture((0, 0, 255, 255), (200, 200, 512, 512)),
    }
    tile = radar_tiles.tile(3, 1, 2, END, 12)
    assert tile.media_type == "image/webp" and tile.complete
    merged = Image.open(io.BytesIO(tile.data)).convert("RGBA")
    red, blue, clear = merged.getpixel((50, 50)), merged.getpixel((250, 250)), merged.getpixel((400, 50))
    assert red[0] > 200 and red[2] < 60
    assert blue[2] > 200 and blue[0] < 60  # where the passes overlap, the later one shows
    assert clear[3] == 0
    assert len(gibs["asked"]) == 12


def test_a_square_is_fetched_from_nasa_once(gibs):
    gibs["passes"] = {END: _picture((0, 255, 0, 255), (0, 0, 512, 512))}
    first = radar_tiles.tile(3, 1, 2, END, 12)
    asked = len(gibs["asked"])
    again = radar_tiles.tile(3, 1, 2, END, 12)
    assert again.data == first.data and len(gibs["asked"]) == asked
    assert radar_tiles.cache_control(END, first.complete) == "public, max-age=2592000, s-maxage=2592000, immutable"


def test_a_square_with_no_pass_is_remembered_as_blank(gibs):
    blank = radar_tiles.tile(3, 1, 2, END, 12)
    assert blank.media_type == "image/png" and blank.data == radar_tiles.BLANK_PNG and blank.complete
    asked = len(gibs["asked"])
    radar_tiles.tile(3, 1, 2, END, 12)
    assert len(gibs["asked"]) == asked


def test_a_failed_day_is_not_kept_as_a_gap(gibs):
    day = END - timedelta(days=1)
    gibs["passes"] = {day: _picture((255, 255, 0, 255), (0, 0, 512, 512))}
    gibs["down"] = {day}
    broken = radar_tiles.tile(3, 1, 2, END, 12)
    assert not broken.complete and radar_tiles.cache_control(END, broken.complete) == "no-store"
    gibs["down"] = set()
    mended = radar_tiles.tile(3, 1, 2, END, 12)  # asked again, because nothing was kept
    assert mended.complete and mended.media_type == "image/webp"


def test_deep_squares_ask_only_for_days_with_a_pass_nearby(gibs):
    day = END - timedelta(days=4)
    gibs["passes"] = {day: _picture((255, 0, 255, 255), (0, 0, 512, 512))}
    radar_tiles.tile(10, 300, 400, END, 12)
    full_size = [d for d, size in gibs["asked"] if size == radar_tiles.TILE]
    assert full_size == [day]  # 12 small look-ups for the region, then 1 full picture
    gibs["asked"].clear()
    radar_tiles.tile(10, 301, 401, END, 12)  # a neighbour in the same region: no look-ups at all
    assert gibs["asked"] == [(day, radar_tiles.TILE)]


def test_an_unanswered_look_up_does_not_hide_a_day(gibs):
    day = END - timedelta(days=4)
    gibs["passes"] = {day: _picture((255, 0, 255, 255), (0, 0, 512, 512))}
    gibs["down"] = {day}
    assert not radar_tiles.tile(10, 300, 400, END, 12).complete
    gibs["down"] = set()
    assert radar_tiles.tile(10, 300, 400, END, 12).media_type == "image/webp"


def test_bad_addresses_and_dates_are_refused(gibs):
    with pytest.raises(radar_tiles.TileError):
        radar_tiles.tile(radar_tiles.MAX_ZOOM + 1, 0, 0, END)
    with pytest.raises(radar_tiles.TileError):
        radar_tiles.tile(2, 4, 0, END)
    with pytest.raises(radar_tiles.TileError):
        radar_tiles.tile(2, 0, 0, date(2026, 12, 1))
