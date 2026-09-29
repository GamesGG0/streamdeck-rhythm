"""Stream Deck rhythm game: osu!mania 4K to 8K charts played on the deck's keys."""

import argparse
import os
import statistics
import threading
import time

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from StreamDeck.Devices.StreamDeck import TouchscreenEventType

import demo
import device
import osu
import render
import scoring
from scoring import GOOD, GREAT, MEH, MISS, OK, PERFECT, RESULTS

MAP_FOLDERS = [os.path.join(os.environ.get("APPDATA", ""), "osu", "exports"), os.path.join(device.HERE, "maps")]
DEMO_OD = 5
LEAD_IN = 2.0
RESULT_TEXT_TIME = 0.5  # how long a hit's result takes to fade off its key
RESULTS_GRACE = 1.0  # seconds the stats ignore presses, so a late tap doesn't skip them
QUIT_TAP_GAP = 0.6  # most seconds allowed between quit presses
APPROACH_BEATS = 1.5  # a box takes this many beats of the song's main BPM to fill
APPROACH_MIN = 0.3
APPROACH_MAX = 1.0
DEFAULT_APPROACH = 0.5  # when a chart's BPM can't be worked out
MAX_STACK = 4  # most notes shown at once on one key

EASINGS = {
    "linear": lambda p: p,
    "quad_in": lambda p: p * p,
    "cubic_in": lambda p: p * p * p,
    "expo_in": lambda p: 0.0 if p <= 0 else 2 ** (10 * p - 10),
    "expo_out": lambda p: 1.0 if p >= 1 else 1 - 2 ** (-10 * p),
}


class Note:
    def __init__(self, lane, time_, end=None):
        self.lane = lane
        self.time = time_
        self.end = end
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
        self.label = None  # (result, song time)

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


class Game:
    def __init__(self, deck, chart, lanes, od, approach, args):
        self.deck = deck
        self.approach = approach
        self.notes = [Note(*n) for n in chart]
        self.lanes = [Lane([n for n in self.notes if n.lane == i]) for i in range(lanes)]
        self.layout = device.make_layout(deck, lanes)
        self.art = render.KeyArt(deck)
        self.panel = render.StatusPanel(deck) if deck.is_touch() or device.has_screen(deck) else None
        self.windows = scoring.hit_windows(od)
        # Holds are judged twice: once on press, once on release
        self.score = scoring.ScoreKeeper(sum(2 if n.is_hold else 1 for n in self.notes))
        self.offset = args.offset / 1000
        self.ease = EASINGS[args.easing]
        self.start = None
        self.lock = threading.Lock()
        self.last_result = None
        self.sent = [None] * deck.key_count()
        self.key_writes = 0
        self.key_write_time = 0.0
        self.quit_taps = []
        self.quit = False
        self.results_since = None
        self.results_done = False

    def song_time(self, at=None):
        return (at or time.perf_counter()) - self.start - self.offset

    def on_key(self, deck, key, pressed):
        stamp = time.perf_counter()
        if self.results_since is not None:
            if pressed:
                self.dismiss_results(stamp)
            return
        # Keys past the screen keys are the Neo's touch buttons, which quit
        if key == self.layout.quit_key or key >= len(self.layout.key_lane):
            if pressed:
                self.quit_press(stamp)
            return
        if self.start is None or self.layout.key_lane[key] is None:
            return
        t = self.song_time(stamp)
        lane = self.lanes[self.layout.key_lane[key]]
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

    def on_touch(self, deck, event, value):
        if event != TouchscreenEventType.SHORT:
            return
        if self.results_since is not None:
            self.dismiss_results(time.perf_counter())
        elif self.panel.hits_quit(value["x"]):
            self.quit_press(time.perf_counter())

    def quit_press(self, now):
        with self.lock:
            if self.quit_taps and now - self.quit_taps[-1] > QUIT_TAP_GAP:
                self.quit_taps = []
            self.quit_taps.append(now)
            if len(self.quit_taps) >= render.QUIT_TAPS:
                self.quit = True

    def recent_quit_presses(self):
        with self.lock:
            if self.quit_taps and time.perf_counter() - self.quit_taps[-1] <= QUIT_TAP_GAP:
                return len(self.quit_taps)
            return 0

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
        lane.label = (result, t)

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
        # Each is None, ("unused",), ("quit", presses), ("label", label), ("drain", filled, held, stack, label)
        # or ("note", side, is_hold, stack, label); stacks list (side, is_hold, place) and labels (result, fade step)
        quit_state = ("quit", self.recent_quit_presses())
        with self.lock:
            states = [("unused",) if lane is None else None for lane in self.layout.key_lane]
            if self.layout.quit_key is not None:
                states[self.layout.quit_key] = quit_state
            for lane, key in zip(self.lanes, self.layout.shown_key):
                label = None
                if lane.label and t - lane.label[1] < RESULT_TEXT_TIME:
                    fade = max(0.0, t - lane.label[1]) / RESULT_TEXT_TIME
                    label = (lane.label[0], int(fade * render.RESULT_TEXT_STEPS))
                note, *following = lane.upcoming(MAX_STACK)
                stack = self.stack(following, t)
                if lane.holding is not None:
                    states[key] = ("drain", self.drain_pixels(lane.holding, t), True, stack, label)
                elif note is not None and note.head is not None:
                    states[key] = ("drain", self.drain_pixels(note, t), False, stack, label)
                elif note is not None and note.time - self.approach <= t:
                    states[key] = ("note", self.box_size(note, t), note.is_hold, stack, label)
                elif label:
                    states[key] = ("label", label)
            return states

    def box_size(self, note, t):
        progress = min(1.0, max(0.0, 1 - (note.time - t) / self.approach))
        return self.art.box_pixels(self.ease(progress))

    def stack(self, notes, t):
        # Later notes in the lane whose approach has started, drawn in front of the current one.
        # Their place in the stack picks the shade, so neighbours never match.
        shown = []
        for place, note in enumerate(notes, start=1):
            if note is None or note.time - self.approach > t:
                break
            shown.append((self.box_size(note, t), note.is_hold, place))
        return tuple(shown)

    def drain_pixels(self, note, t):
        return self.art.drain_pixels(min(1.0, max(0.0, (note.end - t) / (note.end - note.time))))

    def update_keys(self, t):
        for key, state in enumerate(self.key_states(t)):
            if state == self.sent[key]:
                continue
            frame = self.art.frame(state)
            began = time.perf_counter()
            with self.deck:
                self.deck.set_key_image(key, frame)
            self.key_write_time += time.perf_counter() - began
            self.key_writes += 1
            self.sent[key] = state

    def run(self, audio_path):
        if self.deck.touch_key_count():
            for key in range(self.deck.key_count(), self.deck.key_count() + self.deck.touch_key_count()):
                self.deck.set_key_color(key, *render.QUIT_COLOR)
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
                # Keep going until the music itself has finished, not just the notes
                if t > last + 1.5 and not (playing and pygame.mixer.music.get_busy()):
                    break
                if self.quit:
                    print("\nQuit early.")
                    break
                self.advance(t)
                self.update_keys(t)
                if self.panel:
                    with self.lock:
                        stats = (self.last_result or "READY", self.score.combo, self.score.accuracy * 100, self.score.counts[MISS])
                    self.panel.show_stats(*stats, self.recent_quit_presses())
                time.sleep(0.002)
        except KeyboardInterrupt:
            print("\nStopped early.")
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()  # lets go of the song file
        self.run_time = time.perf_counter() - self.start

    def show_results(self):
        """Shows the stats on the keys until a key is pressed or the strip tapped."""
        tiles = result_tiles(self.score, self.deck.key_count())
        with self.deck:
            for key in range(self.deck.key_count()):
                self.deck.set_key_image(key, self.art.tile(tiles[key]) if key < len(tiles) else self.art.frame(None))
        if self.panel:
            self.panel.show_message("Press any key to finish")
        self.results_since = time.perf_counter()
        print("Press any Stream Deck key to finish.")
        try:
            while not self.results_done:
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass

    def dismiss_results(self, stamp):
        # Ignore presses right away, so a late tap from the song doesn't skip the stats
        if stamp - self.results_since >= RESULTS_GRACE:
            self.results_done = True


def result_tiles(score, key_count):
    """What each results key shows, as a list of (label, value) rows; two rows share a key."""
    count = lambda r: (r, str(score.counts[r]))
    combo = ("MAX COMBO", f"{score.max_combo}/{score.total}")
    points = ("SCORE", f"{score.score:,}")
    rank = ("RANK", score.rank)
    accuracy = ("ACCURACY", f"{score.accuracy * 100:.2f}%")
    if key_count >= 10:
        return [[count(r)] for r in RESULTS] + [[accuracy], [rank], [combo], [points]]
    if key_count >= 8:
        return [[count(PERFECT)], [count(GREAT)], [count(GOOD)], [count(OK), count(MEH)],
                [count(MISS)], [combo], [points], [rank, accuracy]]
    return [[count(PERFECT), count(GREAT)], [count(GOOD), count(OK)], [count(MEH), count(MISS)],
            [combo], [points], [rank, accuracy]]


def approach_for(bpm):
    if not bpm:
        return DEFAULT_APPROACH
    return min(APPROACH_MAX, max(APPROACH_MIN, APPROACH_BEATS * 60 / bpm))


def is_hit(result):
    return result is not None and result != MISS


def describe_windows(od):
    windows = scoring.hit_windows(od)
    return f"OD {od:g}: " + "  ".join(f"{r} ±{windows[r] * 1000:.1f}" for r in RESULTS) + " ms"


def print_results(game, debug):
    score = game.score
    errors = [n.error * 1000 for n in game.notes if is_hit(n.head) and n.error is not None]
    print()
    print("  ".join(f"{r} {score.counts[r]}" for r in RESULTS))
    print(f"Accuracy {score.accuracy * 100:.2f}%   Max combo {score.max_combo}/{score.total}   Score {score.score:,}   Rank {score.rank}")
    if len(errors) >= 2:
        mean = statistics.mean(errors)
        print(f"Hit error: mean {mean:+.1f} ms, spread (stdev) {statistics.stdev(errors):.1f} ms")
        print(f"  Positive mean = you hit late. Try --offset {game.offset * 1000 + mean:.0f}")
    if debug and game.key_writes:
        per_write = game.key_write_time / game.key_writes * 1000
        print(f"Key image writes: {game.key_writes} in {game.run_time:.1f} s, {per_write:.2f} ms each")


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


def choose_chart(most_lanes):
    charts = find_charts()
    playable = [c for c in charts if c.mode == 3 and device.MIN_LANES <= c.keys <= most_lanes]
    if not playable:
        print(f"No osu!mania {device.MIN_LANES}K-{most_lanes}K charts found in osu!lazer or in these folders:")
        for folder in MAP_FOLDERS:
            print("  " + folder)
        print("Or run with --demo for a random chart.")
        raise SystemExit(1)
    for i, chart in enumerate(playable, 1):
        print(f"{i:3}. {chart.keys}K  {chart.label()}  (OD {chart.od:g}, {chart.note_count} notes)")
    skipped = len(charts) - len(playable)
    if skipped:
        print(f"     ({skipped} other charts skipped: this deck plays osu!mania {device.MIN_LANES}K-{most_lanes}K)")
    while True:
        try:
            pick = input("Pick a chart number (q to quit): ").strip()
        except EOFError:
            raise SystemExit from None
        if pick.lower() == "q":
            raise SystemExit
        if pick.isdigit() and 1 <= int(pick) <= len(playable):
            chart = playable[int(pick) - 1]
            print(f"Loading {chart.label()}")
            notes, audio, bpm = osu.load_chart(chart)
            return notes, audio, chart.keys, chart.od, bpm


def pick_deck(number):
    decks = device.find_decks()
    if not decks:
        raise SystemExit("No Stream Deck with screen keys found. Is it plugged in?")
    if not 1 <= number <= len(decks):
        raise SystemExit(f"There's no deck {number}; {len(decks)} found.")
    if len(decks) > 1:
        for i, deck in enumerate(decks, 1):
            print(f"  Deck {i}: {deck.deck_type()}")
        print("  (Use --deck N to pick another.)")
    deck = decks[number - 1]
    rows, cols = deck.key_layout()
    print(f"Using a {deck.deck_type()} ({cols}x{rows} keys, up to {device.max_lanes(deck)}K).")
    return deck


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="play a random chart instead of an osu! map")
    parser.add_argument("--easy", action="store_true", help="demo only: 1 to 3 single notes per second")
    parser.add_argument("--bpm", type=float, default=110, help="demo only")
    parser.add_argument("--bars", type=int, default=16, help="demo only")
    parser.add_argument("--seed", type=int, default=1, help="demo only")
    parser.add_argument("--keys", type=int, default=4, choices=range(device.MIN_LANES, device.MAX_LANES + 1), help="demo only")
    parser.add_argument("--deck", type=int, default=1, help="which Stream Deck to use, if several are plugged in")
    parser.add_argument("--od", type=float, help="override the chart's OD; lower is more forgiving")
    parser.add_argument("--approach", type=float, help="seconds a box takes to fill; by default it follows the song's BPM")
    parser.add_argument("--easing", choices=EASINGS, default="linear")
    parser.add_argument("--offset", type=float, default=0, help="ms; raise it if you keep hitting late")
    parser.add_argument("--debug", action="store_true", help="also print how fast key images were sent")
    args = parser.parse_args()

    deck = pick_deck(args.deck)
    most_lanes = device.max_lanes(deck)
    if args.demo:
        if args.keys > most_lanes:
            raise SystemExit(f"A {deck.deck_type()} has room for up to {most_lanes}K.")
        chart, length = demo.make_chart(args.bpm, args.bars, args.seed, args.keys, args.easy)
        audio = demo.make_audio(chart, args.bpm, length)
        lanes, od, bpm = args.keys, DEMO_OD, args.bpm
    else:
        chart, audio, lanes, od, bpm = choose_chart(most_lanes)
    if args.od is not None:
        od = args.od
    approach = args.approach if args.approach is not None else approach_for(bpm)

    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.mixer.init()
    deck.open()
    close_handler = device.reset_on_console_close(deck)
    try:
        deck.reset()
        deck.set_brightness(80)
        # The library only checks for presses 20 times a second by default
        deck.set_poll_frequency(1000)
        game = Game(deck, chart, lanes, od, approach, args)
        deck.set_key_callback(game.on_key)
        if deck.is_touch():
            deck.set_touchscreen_callback(game.on_touch)
        print(f"{len(chart)} notes. {device.describe_layout(deck, game.layout, lanes)}")
        print(device.describe_quit(deck, game.layout))
        print(describe_windows(od))
        print(f"Note speed: boxes fill in {approach:.2f} s" + (f" ({bpm:g} BPM)" if bpm else ""))
        game.run(audio)
        print_results(game, args.debug)
        game.show_results()
    finally:
        device.reset_deck(deck)
        del close_handler


if __name__ == "__main__":
    main()
