"""Finding a Stream Deck, laying a chart's lanes out on its keys, and resetting it afterwards."""

import ctypes
import os
from dataclasses import dataclass

from StreamDeck.DeviceManager import DeviceManager

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_LANES = 4
MAX_LANES = 8
CONSOLE_CLOSE_EVENTS = (2, 5, 6)  # window closed, logging off, shutting down


def find_decks(transport=None):
    """Connected Stream Decks with screens on their keys and enough keys for 4K."""
    if transport is None:
        # Lets the library find hidapi.dll next to these scripts
        os.add_dll_directory(HERE)
    decks = DeviceManager(transport).enumerate()
    return [d for d in decks if d.is_visual() and d.key_count() >= MIN_LANES]


def max_lanes(deck):
    return min(MAX_LANES, deck.key_count())


def has_screen(deck):
    """True for the Neo's small screen; the Plus's touch strip counts separately, as is_touch()."""
    return deck.screen_image_format()["size"][0] > 0


@dataclass
class Layout:
    key_lane: list  # the lane each key plays, or None if it's unused
    shown_key: list  # the key each lane's notes appear on
    quit_key: int | None  # a spare key that quits, on decks with no touch strip or touch buttons
    rows_used: int


def make_layout(deck, lanes):
    """Puts the lanes on the bottom rows, split evenly and centered, left to right."""
    rows, cols = deck.key_layout()
    rows_used = -(-lanes // cols)
    if rows_used > rows:
        raise ValueError(f"A {deck.deck_type()} has too few keys for {lanes}K")
    key_lane = [None] * deck.key_count()
    shown_key = []
    for r in range(rows_used):
        count = lanes // rows_used + (1 if r < lanes % rows_used else 0)
        first = (rows - rows_used + r) * cols + (cols - count) // 2
        for key in range(first, first + count):
            key_lane[key] = len(shown_key)
            shown_key.append(key)
    quit_key = None
    if not deck.is_touch() and not deck.touch_key_count():
        spare = [key for key, lane in enumerate(key_lane) if lane is None]
        if spare:
            # The top-right key if it's free, otherwise the last free one
            quit_key = cols - 1 if cols - 1 in spare else spare[-1]
    return Layout(key_lane, shown_key, quit_key, rows_used)


def describe_layout(deck, layout, lanes):
    rows, cols = deck.key_layout()
    if layout.rows_used == 1:
        text = f"{lanes}K: play on the bottom row."
    else:
        upper = sum(1 for key in layout.shown_key if key // cols == rows - 2)
        text = f"{lanes}K: lanes 1-{upper} are the upper row, lanes {upper + 1}-{lanes} the bottom row."
    if any(lane is None and key != layout.quit_key for key, lane in enumerate(layout.key_lane)):
        text += " Gray keys aren't used."
    return text


def describe_quit(deck, layout):
    if deck.is_touch():
        return "Tap QUIT on the touch strip 3 times to stop early."
    if deck.touch_key_count():
        return "Press either touch button 3 times to stop early."
    if layout.quit_key is not None:
        return "Press the QUIT key 3 times to stop early."
    return "Press Ctrl+C in this window to stop early."


def reset_deck(deck):
    with deck:
        if deck.is_open():
            deck.reset()
            deck.close()


def reset_on_console_close(deck):
    """Resets the deck if the console window is closed, since Windows then skips normal cleanup."""

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
    def handler(event):
        if event not in CONSOLE_CLOSE_EVENTS:
            return False  # Ctrl+C carries on to Python as usual
        reset_deck(deck)
        return True

    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
    # The caller keeps this alive; a collected callback would crash when Windows calls it
    return handler
