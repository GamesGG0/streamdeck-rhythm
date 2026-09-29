"""Stream Deck+ rhythm game: osu!mania 4K to 8K charts on a 4x2 grid of keys."""

import argparse
import array
import math
import os
import random
import statistics
import tempfile
import threading
import time
import wave

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from PIL import ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import TouchscreenEventType
from StreamDeck.ImageHelpers import PILHelper

import osu
import scoring
from scoring import GOOD, GREAT, MEH, MISS, OK, PERFECT, RESULTS

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_FOLDERS = [os.path.join(os.environ.get("APPDATA", ""), "osu", "exports"), os.path.join(HERE, "maps")]

KEY_COLUMNS = 4
KEY_COUNT = 8
MIN_LANES = 4
MAX_LANES = 8
DEMO_OD = 5
FLASH_TIME = 0.15
EASY_MIN_GAP = 1 / 3  # easy demo: at most 3 notes per second
EASY_MAX_GAP = 1.2  # and roughly at least 1
LEAD_IN = 2.0
SAMPLE_RATE = 44100
FRAME_CACHE_LIMIT = 5000

EASINGS = {
    "linear": lambda p: p,
    "quad_in": lambda p: p * p,
    "cubic_in": lambda p: p * p * p,
    "expo_in": lambda p: 0.0 if p <= 0 else 2 ** (10 * p - 10),
    "expo_out": lambda p: 1.0 if p >= 1 else 1 - 2 ** (-10 * p),
}

OUTLINE_COLOR = (70, 70, 90)
UNUSED_COLOR = (45, 45, 52)  # keys a chart with fewer lanes doesn't use
HOLD_COLOR = (190, 90, 255)
LOOSE_HOLD_COLOR = (110, 110, 125)  # a hold you've let go of but can still grab
QUIT_BUTTON = (630, 12, 788, 88)  # left, top, right, bottom on the touch strip
QUIT_TAPS = 3
QUIT_TAP_GAP = 0.6  # most seconds allowed between taps
SNAP_COLORS = {1: (235, 70, 70), 2: (70, 140, 255), 3: (255, 110, 180), 4: (240, 200, 40)}
OTHER_SNAP_COLOR = (150, 150, 160)
SECOND_COLOR = (245, 245, 245)  # the next note in a lane, when it overlaps the current one
SECOND_HOLD_COLOR = (225, 190, 255)
SECOND_WIDTH = 4
SIZE_STEP = 4
RESULT_COLORS = {
    PERFECT: (150, 235, 255),
    GREAT: (255, 215, 0),
    GOOD: (80, 220, 120),
    OK: (60, 140, 255),
    MEH: (140, 140, 150),
    MISS: (220, 50, 50),
}


class Note:
    def __init__(self, lane, time_, end=None, snap=1):
        self.lane = lane
        self.time = time_
        self.end = end
        self.snap = snap
        self.head = None  # result of the press
        self.error = None
        self.tail = None  # result of letting go, holds only
        self.body_done = False
        self.broken = False  # let go too early at some point
        self.holding = False

    @property
    def is_hold(self):
        return self.end is not None

    @property
    def done(self):
        return self.head is not None and (not self.is_hold or self.tail is not None)


class Lane:
    def __init__(self, notes):
        self.notes = notes
        self.first = 0  # notes before this index are done
        self.holding = None
        self.hold_key = None
        self.flash = None  # (result, song time)

    def upcoming(self, count):
        found = []
        for i in range(self.first, len(self.notes)):
            if not self.notes[i].done:
                found.append(self.notes[i])
                if len(found) == count:
                    break
        return found + [None] * (count - len(found))

    def current(self):
        return self.upcoming(1)[0]


def key_layout(lanes):
    """Returns the lane each key plays (None if unused) and the key each lane's notes show on."""
    if lanes <= KEY_COLUMNS:
        # One lane per column: notes show on the bottom row and either key hits
        key_lane = [i if i < lanes else None for i in range(KEY_COLUMNS)] * 2
        return key_lane, [KEY_COLUMNS + i for i in range(lanes)]
    # Left half of the lanes on the top row, right half on the bottom row
    top = (lanes + 1) // 2
    key_lane = [None] * KEY_COUNT
    shown = []
    for lane in range(lanes):
        key = lane if lane < top else KEY_COLUMNS + lane - top
        key_lane[key] = lane
        shown.append(key)
    return key_lane, shown


def describe_layout(lanes):
    if lanes <= KEY_COLUMNS:
        return f"{lanes}K: hit the bottom row (either key in a column works)."
    top = (lanes + 1) // 2
    text = f"{lanes}K: lanes 1-{top} are the top row, lanes {top + 1}-{lanes} the bottom row."
    if None in key_layout(lanes)[0]:
        text += " Gray keys aren't used."
    return text


def make_easy_chart(rng, beat, length, lanes):
    # Whole-beat gaps only, picked so there are 1 to 3 notes per second
    gaps = [k for k in range(1, 9) if EASY_MIN_GAP <= k * beat <= EASY_MAX_GAP] or [1]
    free_at = [0.0] * lanes
    notes = []
    step = 0
    while step * beat < length:
        t = step * beat
        free = [lane for lane in range(lanes) if free_at[lane] <= t] or list(range(lanes))
        lane = rng.choice(free)
        end = t + beat if rng.random() < 0.1 else None
        notes.append((lane, t, end, 1))
        free_at[lane] = (end or t) + beat
        step += max(rng.choice(gaps), 2 if end else 1)
    return notes


def make_demo_chart(bpm, bars, seed, easy=False, lanes=4):
    rng = random.Random(seed)
    beat = 60 / bpm
    if easy:
        return make_easy_chart(rng, beat, bars * 4 * beat, lanes), bars * 4 * beat
    free_at = [0.0] * lanes
    notes = []
    for step in range(bars * 8):
        t = step * beat / 2
        on_beat = step % 2 == 0
        if rng.random() > (0.75 if on_beat else 0.35):
            continue
        free = [lane for lane in range(lanes) if free_at[lane] <= t]
        for lane in rng.sample(free, min(2 if on_beat and rng.random() < 0.15 else 1, len(free))):
            end = t + beat * rng.choice((1, 2)) if on_beat and rng.random() < 0.15 else None
            notes.append((lane, t, end, 1 if on_beat else 2))
            free_at[lane] = (end or t) + beat / 2
    return notes, bars * 4 * beat


def add_click(samples, at, freq, volume, length=0.03):
    first = int(at * SAMPLE_RATE)
    for i in range(int(length * SAMPLE_RATE)):
        if first + i >= len(samples):
            break
        t = i / SAMPLE_RATE
        value = math.sin(2 * math.pi * freq * t) * math.exp(-t * 120) * volume
        samples[first + i] = max(-32767, min(32767, samples[first + i] + int(value * 32767)))


def make_demo_audio(notes, bpm, length):
    samples = array.array("h", bytes(2 * int((length + 1) * SAMPLE_RATE)))
    beat = 60 / bpm
    for i in range(int(length / beat) + 1):
        add_click(samples, i * beat, 1500 if i % 4 == 0 else 1000, 0.5)
    for t in sorted({n[1] for n in notes}):
        add_click(samples, t, 2400, 0.25, length=0.015)
    path = os.path.join(tempfile.gettempdir(), "streamdeck_rhythm_demo.wav")
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(samples.tobytes())
    return path


class Game:
    def __init__(self, deck, chart, lanes, od, args):
        self.deck = deck
        self.notes = [Note(*n) for n in chart]
        self.lanes = [Lane([n for n in self.notes if n.lane == i]) for i in range(lanes)]
        self.key_lane, self.shown_key = key_layout(lanes)
        self.od = od
        self.windows = scoring.hit_windows(od)
        # Holds are judged twice: once on press, once on release
        self.score = scoring.ScoreKeeper(sum(2 if n.is_hold else 1 for n in self.notes))
        self.approach = args.approach
        self.offset = args.offset / 1000
        self.ease = EASINGS[args.easing]
        self.start = None
        self.lock = threading.Lock()
        self.last_result = None
        self.frame_cache = {}
        self.sent = [None] * KEY_COUNT
        self.strip_sent = None
        self.key_writes = 0
        self.key_write_time = 0.0
        self.size = deck.key_image_format()["size"][0]
        self.strip_font = ImageFont.load_default(size=40)
        self.button_font = ImageFont.load_default(size=28)
        self.quit_taps = []
        self.quit = False

    def song_time(self, at=None):
        return (at or time.perf_counter()) - self.start - self.offset

    def on_key(self, deck, key, pressed):
        stamp = time.perf_counter()
        if self.start is None:
            return
        t = self.song_time(stamp)
        if self.key_lane[key] is None:
            return
        lane = self.lanes[self.key_lane[key]]
        with self.lock:
            if not pressed:
                if lane.holding is not None and lane.hold_key == key:
                    self.release(lane, t)
                return
            if lane.holding is not None:
                return
            note = lane.current()
            if note is None:
                return
            if note.is_hold:
                self.press_hold(lane, note, key, t)
                return
            result = scoring.result_for(self.windows, t - note.time)
            if result is not None:
                self.judge_head(lane, note, result, t - note.time, t)

    def press_hold(self, lane, note, key, t):
        # Grabbing is allowed from the press's miss window until the release's MEH window closes
        if t > note.end and t - note.end > self.windows[MEH]:
            return
        if t - note.time < -self.windows[MISS]:
            return
        note.holding = True
        lane.holding = note
        lane.hold_key = key
        if note.head is None:
            result = scoring.result_for(self.windows, t - note.time)
            if result is not None:
                self.judge_head(lane, note, result, t - note.time, t)

    def release(self, lane, t):
        note = lane.holding
        note.holding = False
        lane.holding = None
        lane.hold_key = None
        result = scoring.result_for(self.windows, (t - note.end) / scoring.RELEASE_LENIENCE)
        if result is not None:
            self.judge_tail(lane, note, result, t)
        self.settle_body(note, note.tail not in (None, MISS))

    def judge_head(self, lane, note, result, error, t):
        note.head = result
        note.error = error
        self.record(lane, result, t)

    def judge_tail(self, lane, note, result, t):
        # A missed press or an early let-go caps the release at MEH
        if is_hit(result) and scoring.is_better(result, MEH) and (not is_hit(note.head) or note.broken):
            result = MEH
        note.tail = result
        self.record(lane, result, t)

    def settle_body(self, note, tail_hit):
        if note.body_done:
            return
        note.body_done = True
        if not tail_hit:
            note.broken = True
            self.score.combo_break()

    def record(self, lane, result, t):
        self.score.add(result)
        self.last_result = result
        lane.flash = (result, t)

    def advance(self, t):
        with self.lock:
            for lane in self.lanes:
                for i in range(lane.first, len(lane.notes)):
                    note = lane.notes[i]
                    if note.time > t:
                        break
                    if note.head is None and t - note.time > self.windows[MEH]:
                        self.judge_head(lane, note, MISS, None, t)
                    late = note.is_hold and note.tail is None
                    if late and (t - note.end) / scoring.RELEASE_LENIENCE > self.windows[MEH]:
                        if note.holding:
                            note.holding = False
                            lane.holding = None
                            lane.hold_key = None
                        self.judge_tail(lane, note, MISS, t)
                        self.settle_body(note, False)
                while lane.first < len(lane.notes) and lane.notes[lane.first].done:
                    lane.first += 1

    def key_states(self, t):
        with self.lock:
            states = [("unused",) if lane is None else None for lane in self.key_lane]
            for lane, key in zip(self.lanes, self.shown_key):
                flash = None
                if lane.flash and t - lane.flash[1] < FLASH_TIME:
                    flash = lane.flash[0]
                note, following = lane.upcoming(2)
                second = self.overlay(following, t)
                if lane.holding is not None:
                    states[key] = ("drain", self.drain_pixels(lane.holding, t), True, second)
                elif note is not None and note.head is not None:
                    states[key] = ("drain", self.drain_pixels(note, t), False, second)
                elif note is not None and note.time - self.approach <= t:
                    states[key] = ("note", self.box_size(note, t), note.snap, note.is_hold, flash, second)
                elif flash:
                    states[key] = ("flash", flash)
            return states

    def box_size(self, note, t):
        progress = min(1.0, max(0.0, 1 - (note.time - t) / self.approach))
        return self.step(self.ease(progress) * self.size)

    def step(self, pixels):
        # Even steps keep boxes centered and send the device far fewer images
        return round(pixels / SIZE_STEP) * SIZE_STEP

    def overlay(self, note, t):
        # The next note in the lane, drawn over the current one when their approaches overlap
        if note is None or note.time - self.approach > t:
            return None
        return self.box_size(note, t), note.is_hold

    def drain_pixels(self, note, t):
        remaining = min(1.0, max(0.0, (note.end - t) / (note.end - note.time)))
        return self.step(remaining * self.size)

    def render(self, state):
        if state in self.frame_cache:
            return self.frame_cache[state]
        if len(self.frame_cache) > FRAME_CACHE_LIMIT:
            self.frame_cache.clear()
        image = PILHelper.create_key_image(self.deck)
        draw = ImageDraw.Draw(image)
        s = self.size
        kind = state[0] if state else None
        if kind == "unused":
            draw.rectangle((0, 0, s - 1, s - 1), fill=UNUSED_COLOR)
        elif kind == "flash":
            draw.rectangle((0, 0, s - 1, s - 1), fill=RESULT_COLORS[state[1]])
        elif kind == "drain":
            _, filled, held, second = state
            if filled > 0:
                draw.rectangle((0, s - filled, s - 1, s - 1), fill=HOLD_COLOR if held else LOOSE_HOLD_COLOR)
            self.draw_second(draw, second)
        elif kind == "note":
            _, side, snap, is_hold, flash, second = state
            color = HOLD_COLOR if is_hold else SNAP_COLORS.get(snap, OTHER_SNAP_COLOR)
            edge = RESULT_COLORS[flash] if flash else (HOLD_COLOR if is_hold else OUTLINE_COLOR)
            draw.rectangle((2, 2, s - 3, s - 3), outline=edge, width=4)
            if side > 0:
                lo = (s - side) // 2
                box = (lo, lo, lo + side - 1, lo + side - 1)
                if is_hold:
                    draw.rectangle(box, outline=color, width=min(10, side // 2))
                else:
                    draw.rectangle(box, fill=color)
            self.draw_second(draw, second)
        frame = PILHelper.to_native_key_format(self.deck, image)
        self.frame_cache[state] = frame
        return frame

    def draw_second(self, draw, second):
        if second is None or second[0] <= 0:
            return
        side, is_hold = second
        lo = (self.size - side) // 2
        hi = lo + side - 1
        # A hollow frame, so the note being hit stays visible through it
        draw.rectangle((lo - 2, lo - 2, hi + 2, hi + 2), outline="black", width=2)
        draw.rectangle((lo, lo, hi, hi), outline=SECOND_HOLD_COLOR if is_hold else SECOND_COLOR, width=min(SECOND_WIDTH, side // 2))

    def on_touch(self, deck, event, value):
        left, _, right, _ = QUIT_BUTTON
        if event != TouchscreenEventType.SHORT or not left <= value["x"] <= right:
            return
        now = time.perf_counter()
        with self.lock:
            if self.quit_taps and now - self.quit_taps[-1] > QUIT_TAP_GAP:
                self.quit_taps = []
            self.quit_taps.append(now)
            if len(self.quit_taps) >= QUIT_TAPS:
                self.quit = True

    def recent_taps(self):
        with self.lock:
            if self.quit_taps and time.perf_counter() - self.quit_taps[-1] <= QUIT_TAP_GAP:
                return len(self.quit_taps)
            return 0

    def draw_strip(self, text, taps):
        if (text, taps) == self.strip_sent:
            return
        self.strip_sent = (text, taps)
        image = PILHelper.create_touchscreen_image(self.deck)
        draw = ImageDraw.Draw(image)
        left, top, right, bottom = QUIT_BUTTON
        draw.text((left / 2, image.height / 2), text, font=self.strip_font, fill="white", anchor="mm")
        draw.rounded_rectangle(QUIT_BUTTON, radius=12, outline=(220, 60, 60), width=3, fill=(70, 15, 15) if taps else "black")
        middle = (left + right) / 2
        draw.text((middle, top + 28), "QUIT", font=self.button_font, fill="white", anchor="mm")
        # One dot per tap needed; filled ones show taps so far
        for i in range(QUIT_TAPS):
            x = middle + (i - (QUIT_TAPS - 1) / 2) * 22
            dot = (x - 6, bottom - 22, x + 6, bottom - 10)
            draw.ellipse(dot, fill=(220, 60, 60) if i < taps else None, outline=(220, 60, 60), width=2)
        native = PILHelper.to_native_touchscreen_format(self.deck, image)
        with self.deck:
            self.deck.set_touchscreen_image(native, 0, 0, image.width, image.height)

    def update_keys(self, t):
        for key, state in enumerate(self.key_states(t)):
            if state == self.sent[key]:
                continue
            frame = self.render(state)
            began = time.perf_counter()
            with self.deck:
                self.deck.set_key_image(key, frame)
            self.key_write_time += time.perf_counter() - began
            self.key_writes += 1
            self.sent[key] = state

    def run(self, audio_path):
        last = max(n.end or n.time for n in self.notes)
        lead = max(LEAD_IN, self.approach - self.notes[0].time + 0.5)
        pygame.mixer.music.load(audio_path)
        self.start = time.perf_counter() + lead
        playing = False
        try:
            while True:
                if not playing and time.perf_counter() >= self.start:
                    pygame.mixer.music.play()
                    playing = True
                t = self.song_time()
                if t > last + 1.5:
                    break
                if self.quit:
                    print("\nQuit from the touch strip.")
                    break
                self.advance(t)
                self.update_keys(t)
                with self.lock:
                    text = f"{self.last_result or 'READY'}   {self.score.combo}x   {self.score.accuracy * 100:.2f}%"
                self.draw_strip(text, self.recent_taps())
                time.sleep(0.002)
        except KeyboardInterrupt:
            print("\nStopped early.")
        pygame.mixer.music.stop()
        self.run_time = time.perf_counter() - self.start


def is_hit(result):
    return result is not None and result != MISS


def describe_windows(od):
    windows = scoring.hit_windows(od)
    return f"OD {od:g}: " + "  ".join(f"{r} ±{windows[r] * 1000:.1f}" for r in RESULTS) + " ms"


def print_results(game):
    score = game.score
    errors = [n.error * 1000 for n in game.notes if is_hit(n.head) and n.error is not None]
    print()
    print("  ".join(f"{r} {score.counts[r]}" for r in RESULTS))
    print(f"Accuracy {score.accuracy * 100:.2f}%   Max combo {score.max_combo}/{score.total}   Score {score.score:,}   Rank {score.rank}")
    if len(errors) >= 2:
        mean = statistics.mean(errors)
        print(f"Hit error: mean {mean:+.1f} ms, spread (stdev) {statistics.stdev(errors):.1f} ms")
        print(f"  Positive mean = you hit late. Try --offset {game.offset * 1000 + mean:.0f}")
    if game.key_writes:
        per_write = game.key_write_time / game.key_writes * 1000
        print(f"Key image writes: {game.key_writes} in {game.run_time:.1f} s, {per_write:.2f} ms each")
        print(f"  That's a ceiling of about {1000 / per_write:.0f} key images per second")


def find_charts():
    charts = []
    try:
        charts += osu.list_lazer_charts()
    except Exception as error:
        print(f"Couldn't read the osu!lazer library ({error}). Exported .osz files still work.")
    charts += osu.list_osz_charts(MAP_FOLDERS)
    unique = {}
    for chart in charts:
        unique.setdefault(chart.label().lower(), chart)
    return sorted(unique.values(), key=lambda c: (c.artist.lower(), c.title.lower(), c.od, c.version.lower()))


def choose_chart():
    charts = find_charts()
    playable = [c for c in charts if c.mode == 3 and MIN_LANES <= c.keys <= MAX_LANES]
    if not playable:
        print(f"No osu!mania {MIN_LANES}K-{MAX_LANES}K charts found in osu!lazer or in these folders:")
        for folder in MAP_FOLDERS:
            print("  " + folder)
        print("Or run with --demo for a random chart.")
        raise SystemExit(1)
    skipped = len(charts) - len(playable)
    for i, chart in enumerate(playable, 1):
        print(f"{i:3}. {chart.keys}K  {chart.label()}  (OD {chart.od:g}, {chart.note_count} notes)")
    if skipped:
        print(f"     ({skipped} other charts skipped: only mania {MIN_LANES}K-{MAX_LANES}K is supported)")
    while True:
        try:
            pick = input("Pick a chart number (q to quit): ").strip()
        except EOFError:
            raise SystemExit
        if pick.lower() == "q":
            raise SystemExit
        if pick.isdigit() and 1 <= int(pick) <= len(playable):
            chart = playable[int(pick) - 1]
            print(f"Loading {chart.label()}")
            notes, audio = osu.load_chart(chart)
            return notes, audio, chart.keys, chart.od


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="play a random chart instead of an osu! map")
    parser.add_argument("--easy", action="store_true", help="demo only: 1 to 3 single notes per second")
    parser.add_argument("--bpm", type=float, default=110, help="demo only")
    parser.add_argument("--bars", type=int, default=16, help="demo only")
    parser.add_argument("--seed", type=int, default=1, help="demo only")
    parser.add_argument("--keys", type=int, default=4, choices=range(MIN_LANES, MAX_LANES + 1), help="demo only")
    parser.add_argument("--od", type=float, help="override the chart's OD; lower is more forgiving")
    parser.add_argument("--approach", type=float, default=0.5, help="seconds a box takes to fill; lower is faster")
    parser.add_argument("--easing", choices=EASINGS, default="linear")
    parser.add_argument("--offset", type=float, default=0, help="ms; raise it if you keep hitting late")
    args = parser.parse_args()

    if args.demo:
        chart, length = make_demo_chart(args.bpm, args.bars, args.seed, args.easy, args.keys)
        audio = make_demo_audio(chart, args.bpm, length)
        lanes, od = args.keys, DEMO_OD
    else:
        chart, audio, lanes, od = choose_chart()
    if args.od is not None:
        od = args.od

    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.mixer.init()
    # Lets the library find hidapi.dll next to this script
    os.add_dll_directory(HERE)
    decks = [d for d in DeviceManager().enumerate() if d.deck_type() == "Stream Deck +"]
    if not decks:
        raise SystemExit("No Stream Deck+ found. Is it plugged in?")
    deck = decks[0]
    deck.open()
    try:
        deck.reset()
        deck.set_brightness(80)
        # The library only checks for presses 20 times a second by default
        deck.set_poll_frequency(1000)
        game = Game(deck, chart, lanes, od, args)
        deck.set_key_callback(game.on_key)
        deck.set_touchscreen_callback(game.on_touch)
        print(f"{len(chart)} notes. {describe_layout(lanes)}")
        print(describe_windows(od))
        game.run(audio)
        print_results(game)
    finally:
        with deck:
            deck.reset()
            deck.close()


if __name__ == "__main__":
    main()
