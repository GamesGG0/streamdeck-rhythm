"""Random practice charts with a metronome, for playing without an osu! map."""

import array
import math
import os
import random
import tempfile
import wave

EASY_MIN_GAP = 1 / 3  # easy charts: at most 3 notes per second
EASY_MAX_GAP = 1.2  # and roughly at least 1
SAMPLE_RATE = 44100


def make_chart(bpm, bars, seed, lanes, easy=False):
    """Returns (notes, length) with notes as (lane, time, end) in seconds, like osu.load_chart."""
    rng = random.Random(seed)
    beat = 60 / bpm
    length = bars * 4 * beat
    if easy:
        return easy_notes(rng, beat, length, lanes), length
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
            notes.append((lane, t, end))
            free_at[lane] = (end or t) + beat / 2
    return notes, length


def easy_notes(rng, beat, length, lanes):
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
        notes.append((lane, t, end))
        free_at[lane] = (end or t) + beat
        step += max(rng.choice(gaps), 2 if end else 1)
    return notes


def make_audio(notes, bpm, length):
    """Writes a metronome with a tick on every note to a temporary WAV file and returns its path."""
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


def add_click(samples, at, freq, volume, length=0.03):
    first = int(at * SAMPLE_RATE)
    for i in range(int(length * SAMPLE_RATE)):
        if first + i >= len(samples):
            break
        t = i / SAMPLE_RATE
        value = math.sin(2 * math.pi * freq * t) * math.exp(-t * 120) * volume
        samples[first + i] = max(-32767, min(32767, samples[first + i] + int(value * 32767)))
