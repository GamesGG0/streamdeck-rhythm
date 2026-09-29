"""Reads osu!mania charts from .osz packages and from osu!lazer's library."""

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass

import lazer

HOLD_TYPE = 128


@dataclass
class ChartInfo:
    source: tuple  # ("osz", package path, member) or ("lazer", chart path, audio path)
    artist: str
    title: str
    version: str
    mode: int
    keys: int
    od: float
    note_count: int

    def label(self):
        return f"{self.artist} - {self.title} [{self.version}]"


def parse_sections(text):
    sections = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], [])
        elif current is not None:
            current.append(line)
    return sections


def key_values(lines):
    values = {}
    for line in lines:
        key, sep, value = line.partition(":")
        if sep:
            values[key.strip()] = value.strip()
    return values


def decode(raw):
    return raw.decode("utf-8-sig", errors="replace")


def audio_filename(sections):
    return key_values(sections.get("General", [])).get("AudioFilename", "")


def chart_info(source, text):
    sections = parse_sections(text)
    general = key_values(sections.get("General", []))
    meta = key_values(sections.get("Metadata", []))
    difficulty = key_values(sections.get("Difficulty", []))
    return ChartInfo(
        source=source,
        artist=meta.get("Artist", "?"),
        title=meta.get("Title", "?"),
        version=meta.get("Version", "?"),
        mode=int(general.get("Mode", "0")),
        keys=round(float(difficulty.get("CircleSize", "0"))),
        od=float(difficulty.get("OverallDifficulty", "5")),
        note_count=len(sections.get("HitObjects", [])),
    )


def list_osz_charts(folders):
    charts = []
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(".osz"):
                continue
            path = os.path.join(folder, name)
            try:
                with zipfile.ZipFile(path) as package:
                    for member in package.namelist():
                        if member.lower().endswith(".osu"):
                            charts.append(chart_info(("osz", path, member), decode(package.read(member))))
            except zipfile.BadZipFile:
                print(f"Skipping {name}: not a valid .osz")
    return charts


def list_lazer_charts():
    charts = []
    for files in lazer.beatmap_sets():
        for name, path in files.items():
            if not name.endswith(".osu") or not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                text = decode(f.read())
            audio = files.get(audio_filename(parse_sections(text)).lower())
            if audio and os.path.exists(audio):
                charts.append(chart_info(("lazer", path, audio), text))
    return charts


def red_points(sections):
    # Uninherited timing points set the BPM; inherited ones only change scroll speed
    points = []
    for line in sections.get("TimingPoints", []):
        fields = line.split(",")
        beat_length = float(fields[1])
        uninherited = len(fields) < 7 or fields[6] == "1"
        if uninherited and beat_length > 0:
            points.append((float(fields[0]), beat_length))
    return sorted(points)


def main_bpm(points, last_ms):
    """The BPM that lasts longest before the last note, which is what osu! shows as a map's BPM."""
    totals = {}
    for i, (time_ms, beat_length) in enumerate(points):
        if time_ms > last_ms:
            break
        start = 0 if i == 0 else time_ms
        end = min(points[i + 1][0], last_ms) if i + 1 < len(points) else last_ms
        key = round(beat_length, 3)
        totals[key] = totals.get(key, 0) + max(0, end - start)
    if not totals:
        return None
    return round(60000 / max(totals, key=totals.get), 2)


def load_chart(info):
    """Returns (notes, audio_path, bpm) with notes as (lane, time, end) in seconds; end is None for taps."""
    kind, path, extra = info.source
    if kind == "osz":
        with zipfile.ZipFile(path) as package:
            sections = parse_sections(decode(package.read(extra)))
            wanted = audio_filename(sections).lower()
            member = {m.lower(): m for m in package.namelist()}.get(wanted)
            if member is None:
                raise SystemExit(f"{info.label()}: audio file '{wanted}' is missing from the .osz")
            audio_path = temp_audio_path(member)
            with open(audio_path, "wb") as f:
                f.write(package.read(member))
    else:
        with open(path, "rb") as f:
            sections = parse_sections(decode(f.read()))
        # Lazer's stored files have no extension, which the audio player needs
        audio_path = temp_audio_path(audio_filename(sections))
        shutil.copyfile(extra, audio_path)

    notes = []
    for line in sections.get("HitObjects", []):
        fields = line.split(",")
        x, time_ms, kind_bits = int(fields[0]), int(fields[2]), int(fields[3])
        lane = min(info.keys - 1, max(0, x * info.keys // 512))
        end = None
        if kind_bits & HOLD_TYPE:
            end = int(fields[5].split(":")[0]) / 1000
        notes.append((lane, time_ms / 1000, end))
    notes.sort(key=lambda n: n[1])
    last_ms = max((n[2] or n[1] for n in notes), default=0) * 1000
    return notes, audio_path, main_bpm(red_points(sections), last_ms)


def temp_audio_path(filename):
    return os.path.join(tempfile.gettempdir(), "streamdeck_rhythm_song" + os.path.splitext(filename)[1].lower())
