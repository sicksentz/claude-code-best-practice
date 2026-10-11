# Stem Stripper

Drop samples in a folder, get back just the instrumentation — no drums, no bass, no vocals.

For each audio file in your **Incoming** folder, the script:

1. Runs [Demucs](https://github.com/facebookresearch/demucs) (`htdemucs`) stem separation — the same four-way split Ableton Live 12.3 does (drums / bass / vocals / other).
2. Keeps only the **other** stem and exports it as a **24-bit WAV** to your **Output** folder as `<name>_other.wav`.
3. Moves the untouched original into your **Archive** folder.

The original is archived only *after* the export is safely written, so a failed run never loses a file — it just stays in Incoming and the error is logged.

> **Why not Ableton itself?** Live's stem separation is a right-click menu action with no documented scripting API, so driving it would mean brittle click-automation. Demucs runs headless, so this can run in the background while you work.

## Setup (macOS, one time)

```bash
brew install python@3.11 ffmpeg
cd ~/stem-stripper                      # wherever you put this folder
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The first real run downloads the Demucs model (~80 MB) to `~/.cache/torch`.

## Use

```bash
# Process everything in Incoming once
.venv/bin/python stem_stripper.py \
  --incoming ~/Music/Samples/Incoming \
  --output   ~/Music/Samples/Instrumental \
  --archive  ~/Music/Samples/Archive

# Preview without touching anything
.venv/bin/python stem_stripper.py ... --dry-run

# Keep running and process new files as they land
.venv/bin/python stem_stripper.py ... --watch
```

| Option | Default | What it does |
|--------|---------|--------------|
| `--watch` | off | Keep checking Incoming; waits for each file to finish copying first |
| `--interval` | `5` | Seconds between checks in watch mode |
| `--model` | `htdemucs` | `htdemucs_ft` is ~4x slower but a little cleaner |
| `--device` | `auto` | Uses the Apple Silicon GPU (`mps`) when available, else CPU |
| `--dry-run` | off | Print the plan, move nothing |
| `-v` | off | Debug logging |

Supported input: `.wav .aif .aiff .mp3 .flac .m4a .ogg .aac`. Output is 44.1 kHz / 24-bit WAV. Names never collide — an existing file gets `name (2).wav` instead of being overwritten.

## Run automatically at login

Edit the paths in `com.sentz.stem-stripper.plist`, then:

```bash
cp com.sentz.stem-stripper.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.sentz.stem-stripper.plist
tail -f ~/Library/Logs/stem-stripper.log
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests swap Demucs for a fake separator and cover the file handling: export + archive, skipping non-audio and macOS `._` files, no-overwrite naming, failures leaving originals in place, and dry runs.
