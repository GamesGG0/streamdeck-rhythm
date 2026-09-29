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
- The touch strip shows your last result, combo, accuracy and misses.
- Tap QUIT on the touch strip three times to stop a song early.
- When the song finishes, the keys show your stats, score and max combo. Press any key to finish.
- Closing the window resets the Stream Deck.

How lanes map to keys:

| Keys | Layout |
|---|---|
| 4K | One lane per bottom-row key. The top row is grayed out. |
| 5K-8K | The left half of the lanes are on the top row, the right half on the bottom row. Unused keys are gray. |

What the keys show:

- Tap notes are red boxes and hold notes are purple boxes, all outlined in white.
- After you hit a hold note, the key fills purple and drains; let go when it's empty.
- Boxes in front of a note are the next notes in that lane. From the back, stacked notes go bright, slightly dark, darker, then repeat, so each one stands apart. The note you're about to hit is always bright.
- How fast boxes fill follows each song's BPM (1.5 beats). `--approach` overrides it.
- Your result for each note fades out on its key. MISS is shown in red.

## Options

Run `rhythm.py` directly for these:

| Option | What it does |
|---|---|
| `--offset MS` | Shifts timing; the results suggest a value. |
| `--od N` | Overrides the chart's OD. Lower is more forgiving. |
| `--approach S` | How many seconds a box takes to fill. By default it follows the song's BPM. |
| `--demo --keys N --easy` | A random chart with N lanes. |
