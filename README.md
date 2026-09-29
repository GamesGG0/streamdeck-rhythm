# streamdeck-rhythm

A rhythm game for Elgato Stream Decks. Boxes grow on the keys, and you press a key when its box fills. It plays osu!mania 4K to 8K charts from your osu!lazer library, with osu!lazer's timing windows and scoring.

It works with any Stream Deck that has screens on its keys, which is every model except the Stream Deck Pedal:

| Stream Deck | Charts | How to stop a song early |
|---|---|---|
| Mini | 4K-6K | QUIT key (4K and 5K), or Ctrl+C |
| Original / MK.2 | 4K-8K | QUIT key |
| Neo | 4K-8K | Either touch button |
| + (Plus) | 4K-8K | QUIT on the touch strip |
| XL | 4K-8K | QUIT key |
| + XL | 4K-8K | QUIT on the touch strip |
| Studio | 4K-8K | QUIT key |

It has been played on a Stream Deck+. The other models were tested with the Stream Deck library's simulated devices, not real hardware.

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

- `Play.bat` lists the osu!mania charts your Stream Deck has room for, from your osu!lazer library and any `.osz` files in lazer's `exports` folder or in `maps\`.
- `Play Demo.bat` plays an easy random chart with a metronome.
- To stop a song early, press QUIT 3 times in a row. Where QUIT is depends on the model (see the table above).
- The Stream Deck+ and + XL show your last result, combo, accuracy and misses on the touch strip. The Neo shows them on its small screen.
- When the song finishes, the keys show your stats, score and max combo. Press any key to finish.
- Closing the window resets the Stream Deck.

How lanes map to keys: the lanes go on the bottom row, centered. If a chart has more lanes than the deck has columns, they split across the bottom two rows, left half on the upper row. Unused keys are gray.

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
| `--deck N` | Which Stream Deck to use, if more than one is plugged in. |
| `--debug` | Also prints how fast key images were sent. |

## Code

| File | What it does |
|---|---|
| `rhythm.py` | Gameplay, the song loop, the results screen and the command line |
| `device.py` | Finds the Stream Deck, lays lanes out on its keys, resets it afterwards |
| `render.py` | Draws the keys, the touch strip and the Neo's screen |
| `scoring.py` | osu!lazer's mania judgements and scoring |
| `osu.py` | Reads charts from `.osz` files and the osu!lazer library |
| `lazer.py` | Reads osu!lazer's database to find charts and their songs |
| `demo.py` | Random practice charts with a metronome |

## License

MIT, see [LICENSE](LICENSE). The scoring is ported from osu!lazer, which is also MIT; its notice is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), along with the libraries the game uses.

This project isn't affiliated with or endorsed by ppy (osu!) or Elgato (Stream Deck).
