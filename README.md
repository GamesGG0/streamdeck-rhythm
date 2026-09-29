# streamdeck-rhythm

A rhythm game for the Elgato Stream Deck+. Boxes grow on the keys, and you press a key when its box fills. It plays osu!mania 4K to 8K charts from your osu!lazer library, with osu!lazer's timing windows and scoring.

## Setup (Windows)

1. Install Python 3 (tested with 3.14).
2. In this folder, create a virtual environment and install the libraries:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
3. Download `hidapi-win.zip` from the [hidapi releases](https://github.com/libusb/hidapi/releases) and put its `x64\hidapi.dll` in this folder.
4. Quit the Stream Deck app, so the game can take over the device.

## Playing

- `Play.bat` lists the osu!mania 4K-8K charts in your osu!lazer library, and any `.osz` files in lazer's `exports` folder or in `maps\`.
- `Play Demo.bat` plays an easy random chart with a metronome.
- Tap QUIT on the touch strip three times to stop a song early.

How lanes map to keys:

| Keys | Layout |
|---|---|
| 4K | One lane per column. Notes show on the bottom row, and either key in a column hits. |
| 5K-8K | The left half of the lanes are on the top row, the right half on the bottom row. Unused keys are gray. |

What the keys show:

- A note's color is its rhythm: red is on the beat, blue a half beat, pink a third, yellow a quarter.
- Hold notes are purple rings. After you hit one, the key fills purple and drains; let go when it's empty.
- A white frame inside a note is the next note in that lane.

## Options

Run `rhythm.py` directly for these:

| Option | What it does |
|---|---|
| `--offset MS` | Shifts timing; the results suggest a value. |
| `--od N` | Overrides the chart's OD. Lower is more forgiving. |
| `--approach S` | How many seconds a box takes to fill. The default is 0.5. |
| `--demo --keys N --easy` | A random chart with N lanes. |
