# streamdeck-rhythm

A rhythm game for Elgato Stream Decks. A box grows on a key, and you press the key when the box fills up.

It plays osu!mania songs from your osu!lazer game, and scores you the same way osu! does.

## What you need

- A Windows PC
- Any Stream Deck with screens on its keys (every model except the Stream Deck Pedal)
- [Python 3](https://www.python.org/downloads/)
- osu!lazer with some osu!mania maps (optional, there's a practice mode without it)

## Setup

Do this once.

1. Open a command prompt in this folder and run these two lines:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
2. Download `hidapi-win.zip` from the [hidapi releases page](https://github.com/libusb/hidapi/releases). Open it, and copy `x64\hidapi.dll` into this folder.

## Playing

1. Quit the Stream Deck app (right-click its icon by the clock, then Quit).
2. Double-click **`Play.bat`** and type the number of a song.
   Or double-click **`Play Demo.bat`** for an easy practice song.
3. Press a key when its box fills up.

When the song ends, your stats show on the keys. Press any key to finish.

## What you'll see

| On the key | What it means |
|---|---|
| Red box | Tap the key when it's full |
| Purple box | Hold the key when it's full, and let go when the purple bar runs out |
| Smaller boxes on top | The next notes on that key |
| Gray key | Not used in this song |
| PERFECT, GREAT... | How well you hit the note (MISS is red) |

## Controls

| | How |
|---|---|
| Stop a song early | Press QUIT 3 times in a row (see below) |
| Change the volume | Turn a dial (press it to mute), or start with a volume like `Play.bat --volume 50` |

Where QUIT is:

| Stream Deck | QUIT | Dials for volume |
|---|---|---|
| + and + XL | On the touch strip | Yes |
| Neo | Either touch button | No |
| Mini | A QUIT key (or Ctrl+C for 6-key songs) | No |
| Original, MK.2, XL | A QUIT key in the top-right corner | No |
| Studio | A QUIT key in the top-right corner | Yes |

Volume starts at 80%.

## Options

Type these after `Play.bat` in a command prompt, for example `Play.bat --volume 50 --offset -15`.

| Option | What it does |
|---|---|
| `--volume 50` | Music volume, from 0 to 100 |
| `--offset -15` | Fixes timing if you're always early or late. After each song, the game suggests a number. |
| `--od 0` | Makes timing more forgiving. Lower is easier. |
| `--approach 0.8` | How many seconds a box takes to fill. Normally it matches the song's speed. |
| `--deck 2` | Which Stream Deck to use, if you have more than one |

`Play Demo.bat` also takes `--keys 6`, for a practice song with that many lanes (4 to 8).

## Good to know

- It has been tested on a Stream Deck+. Other models were tested with simulated devices.
- Closing the window resets the Stream Deck.
- Songs that don't fit your Stream Deck aren't listed. The Mini fits up to 6 lanes, the rest up to 8.

## For developers

| File | What it does |
|---|---|
| `rhythm.py` | Gameplay, the song loop, the results screen and the options |
| `device.py` | Finds the Stream Deck and places lanes on its keys |
| `render.py` | Draws the keys, the touch strip and the Neo's screen |
| `scoring.py` | osu!lazer's timing windows and scoring |
| `osu.py` | Reads songs from `.osz` files and from osu!lazer |
| `lazer.py` | Reads osu!lazer's database to find songs |
| `demo.py` | The practice songs |

`--debug` prints how fast images were sent to the keys.

## License

MIT, see [LICENSE](LICENSE). The scoring is based on osu!lazer's code, which is also MIT; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This project isn't made or endorsed by ppy (osu!) or Elgato (Stream Deck).
