#!/usr/bin/env python3
"""
stem_stripper.py — strip drums, bass and vocals out of samples, keep the rest.

For every audio file in an INCOMING folder:
  1. Run Demucs (htdemucs) stem separation and keep only the "other" stem
     (everything that isn't drums, bass or vocals).
  2. Export it as 24-bit WAV into the OUTPUT folder as "<name>_other.wav".
  3. Move the untouched original into the ARCHIVE folder.

The original is only archived after the export has landed safely, so a failed
run never loses a file.

Usage:
  python3 stem_stripper.py --incoming ~/Samples/Incoming \
                           --output   ~/Samples/Instrumental \
                           --archive  ~/Samples/Archive
  # keep running and process anything that shows up:
  python3 stem_stripper.py ... --watch
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}
DEFAULT_MODEL = "htdemucs"
KEEP_STEM = "other"

log = logging.getLogger("stem_stripper")


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def find_audio_files(folder: Path) -> list[Path]:
    """Audio files directly inside `folder` (not recursive), skipping hidden files."""
    return sorted(
        p for p in folder.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def unique_path(path: Path) -> Path:
    """Return `path`, or `name (2).ext`, `name (3).ext`... if it already exists."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def is_stable(path: Path, wait_seconds: float) -> bool:
    """True if the file size hasn't changed over `wait_seconds` (i.e. it's done copying)."""
    try:
        before = path.stat().st_size
        time.sleep(wait_seconds)
        after = path.stat().st_size
    except FileNotFoundError:
        return False
    return before == after and after > 0


# ---------------------------------------------------------------------------
# Separation
# ---------------------------------------------------------------------------

def pick_device(requested: str) -> str:
    """Resolve 'auto' to mps (Apple Silicon GPU), cuda or cpu."""
    if requested != "auto":
        return requested
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def separate_other_stem(src: Path, work_dir: Path, model: str, device: str) -> Path:
    """
    Run Demucs on `src` and return the path of the rendered "other" stem (24-bit WAV).
    Raises RuntimeError if Demucs fails or the stem isn't produced.
    """
    cmd = [
        sys.executable, "-m", "demucs",
        "-n", model,
        "--two-stems", KEEP_STEM,      # -> "other" + "no_other"; we keep "other"
        "--int24",                      # 24-bit WAV output
        "-d", device,
        "-o", str(work_dir),
        "--filename", "{stem}.{ext}",
        str(src),
    ]
    env = os.environ.copy()
    # Some ops aren't implemented on Apple's GPU yet; let them fall back to CPU.
    env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    log.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-15:])
        raise RuntimeError(f"Demucs failed (exit {result.returncode}):\n{tail}")

    stem = work_dir / model / f"{KEEP_STEM}.wav"
    if not stem.exists():
        raise RuntimeError(f"Demucs finished but {stem} was not created")
    return stem


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def process_file(src: Path, output_dir: Path, archive_dir: Path,
                 model: str, device: str, dry_run: bool = False,
                 separator=separate_other_stem) -> Path | None:
    """Separate one file, export the result, archive the original. Returns the export path."""
    dest = unique_path(output_dir / f"{src.stem}_{KEEP_STEM}.wav")
    archived = unique_path(archive_dir / src.name)

    if dry_run:
        log.info("[dry run] %s -> %s  (original -> %s)", src.name, dest, archived)
        return None

    log.info("Separating %s ...", src.name)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="stem_stripper_") as tmp:
        stem = separator(src, Path(tmp), model, device)
        # Export first...
        shutil.move(str(stem), str(dest))
    # ...archive only once the export is safely on disk.
    shutil.move(str(src), str(archived))
    log.info("Done in %.1fs: %s  (original archived)", time.monotonic() - started, dest.name)
    return dest


def run_once(incoming: Path, output_dir: Path, archive_dir: Path, model: str, device: str,
             dry_run: bool = False, stable_seconds: float = 0.0,
             skip: set[Path] | None = None, separator=separate_other_stem) -> tuple[int, int]:
    """Process everything currently in `incoming`. Returns (succeeded, failed)."""
    skip = skip if skip is not None else set()
    ok = failed = 0
    for src in find_audio_files(incoming):
        if src in skip:
            continue
        if stable_seconds and not is_stable(src, stable_seconds):
            log.debug("Still copying, will retry: %s", src.name)
            continue
        try:
            process_file(src, output_dir, archive_dir, model, device, dry_run, separator)
            ok += 1
            if dry_run:
                skip.add(src)  # nothing moved, so don't re-report it every watch cycle
        except Exception as exc:  # keep going with the rest of the batch
            log.error("Failed on %s: %s", src.name, exc)
            skip.add(src)  # don't retry endlessly in watch mode; original stays put
            failed += 1
    return ok, failed


def check_demucs_installed() -> None:
    try:
        import demucs  # noqa: F401
    except ImportError:
        sys.exit(
            "Demucs isn't installed in this Python.\n"
            "Install it with:  python3 -m pip install -r requirements.txt\n"
            "(see README.md for the full setup)"
        )
    if shutil.which("ffmpeg") is None:
        log.warning("ffmpeg not found on PATH — MP3/M4A/AAC input may fail. "
                    "Install with: brew install ffmpeg")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Strip drums, bass and vocals from samples using Demucs; "
                    "export the remaining instrumentation and archive the originals.")
    p.add_argument("--incoming", required=True, type=Path, help="Folder to pull audio files from")
    p.add_argument("--output", required=True, type=Path, help="Folder for the exported stems")
    p.add_argument("--archive", required=True, type=Path, help="Folder to move originals into")
    p.add_argument("--watch", action="store_true",
                   help="Keep running and process new files as they arrive")
    p.add_argument("--interval", type=float, default=5.0,
                   help="Seconds between folder checks in --watch mode (default 5)")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="Demucs model: htdemucs (default, fast) or htdemucs_ft (slower, a bit cleaner)")
    p.add_argument("--device", default="auto", choices=["auto", "mps", "cpu", "cuda"],
                   help="Processing device (default auto: Apple GPU if available)")
    p.add_argument("--dry-run", action="store_true", help="Show what would happen, change nothing")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    incoming = args.incoming.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    archive_dir = args.archive.expanduser().resolve()

    if not incoming.is_dir():
        log.error("Incoming folder doesn't exist: %s", incoming)
        return 2
    if len({incoming, output_dir, archive_dir}) < 3:
        log.error("Incoming, output and archive must be three different folders")
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        check_demucs_installed()
    device = pick_device(args.device)
    log.info("Model %s on %s | in: %s | out: %s | archive: %s",
             args.model, device, incoming, output_dir, archive_dir)

    if not args.watch:
        ok, failed = run_once(incoming, output_dir, archive_dir, args.model, device, args.dry_run)
        log.info("Finished: %d processed, %d failed", ok, failed)
        return 1 if failed else 0

    log.info("Watching %s (Ctrl+C to stop)", incoming)
    skip: set[Path] = set()
    try:
        while True:
            # In watch mode, wait for each file to stop growing before touching it.
            run_once(incoming, output_dir, archive_dir, args.model, device,
                     args.dry_run, stable_seconds=2.0, skip=skip)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
