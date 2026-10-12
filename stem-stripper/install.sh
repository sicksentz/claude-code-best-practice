#!/bin/bash
# One-shot installer for Stem Stripper on macOS.
#   - cleans up earlier broken download attempts (only if they're clones of this repo)
#   - downloads/updates the stem-stripper branch into ~/stem-stripper-repo
#   - builds the Python environment and installs Demucs
#   - runs the self-checks and creates ~/StemTest test folders
# Safe to run again any time; it picks up where it left off.

set -euo pipefail

REPO_URL="https://github.com/sicksentz/claude-code-best-practice.git"
BRANCH="stem-stripper"
REPO_DIR="$HOME/stem-stripper-repo"
TOOL_DIR="$REPO_DIR/stem-stripper"
TEST_DIR="$HOME/StemTest"

say()  { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }
ok()   { printf "    \033[32m✓ %s\033[0m\n" "$1"; }
warn() { printf "    \033[33m! %s\033[0m\n" "$1"; }
die()  { printf "\n\033[1;31mSTOPPED: %s\033[0m\n" "$1"; exit 1; }

# --- 1. Clean up earlier attempts ------------------------------------------
say "Cleaning up earlier attempts"
for old in "$HOME/stem-stripper" "$HOME/stem-stripper-download"; do
  [ -e "$old" ] || continue
  if git -C "$old" remote get-url origin 2>/dev/null | grep -q "claude-code-best-practice"; then
    # Move to the Trash rather than rm: works even if files inside are owned by
    # root (moving only needs write access to $HOME), and it's recoverable.
    mkdir -p "$HOME/.Trash"
    mv "$old" "$HOME/.Trash/$(basename "$old")-old-$(date +%Y%m%d-%H%M%S)"
    ok "Moved $old to the Trash (it was an old download of this repo)"
  else
    warn "Left $old alone — it isn't a download of this repo, so I won't delete it"
  fi
done

# --- 2. Find Python 3.11 / 3.12 --------------------------------------------
say "Looking for Python"
PY=""
for cand in python3.11 python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.11; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
[ -n "$PY" ] || die "Python 3.11 not found. Run:  brew install python@3.11   then run this installer again."
ok "Using $PY"

if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg found"
elif command -v brew >/dev/null 2>&1; then
  say "Installing ffmpeg (needed for MP3/M4A files)"
  brew install ffmpeg && ok "ffmpeg installed"
else
  warn "ffmpeg not found and Homebrew isn't installed — WAV/AIFF will work, MP3/M4A may not"
fi

# --- 3. Download or update the code ----------------------------------------
say "Getting the code"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
  git -C "$REPO_DIR" checkout --quiet "$BRANCH"
  git -C "$REPO_DIR" pull --quiet --ff-only origin "$BRANCH"
  ok "Updated $REPO_DIR"
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$REPO_DIR" \
    || die "Download failed. If GitHub asked for a login, the repo is private — tell Claude."
  ok "Downloaded to $REPO_DIR"
fi
[ -f "$TOOL_DIR/stem_stripper.py" ] || die "Downloaded, but $TOOL_DIR/stem_stripper.py is missing."

# --- 4. Python environment + Demucs ----------------------------------------
cd "$TOOL_DIR"
if [ -x .venv/bin/python ] && .venv/bin/python -c "import sys" 2>/dev/null; then
  ok "Python environment already exists"
else
  say "Creating Python environment"
  rm -rf .venv
  "$PY" -m venv .venv
  ok "Created .venv"
fi

if [ "${SKIP_PIP:-0}" != "1" ]; then
  say "Installing Demucs + PyTorch (a few minutes the first time)"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  ok "Packages installed"
fi

# --- 5. Self-checks --------------------------------------------------------
say "Running checks"
.venv/bin/python -m unittest discover -s tests >/dev/null 2>&1 \
  && ok "Pipeline tests passed" \
  || die "Tests failed — run: cd \"$TOOL_DIR\" && .venv/bin/python -m unittest discover -s tests -v"

if [ "${SKIP_PIP:-0}" != "1" ]; then
  .venv/bin/python -c "import demucs, torch; print('    \033[32m✓ Demucs ready | Apple GPU:', torch.backends.mps.is_available(), '\033[0m')" \
    || die "Demucs didn't import. Send Claude a screenshot of this window."
fi

# --- 6. Test folders -------------------------------------------------------
mkdir -p "$TEST_DIR/Incoming" "$TEST_DIR/Instrumental" "$TEST_DIR/Archive"
ok "Test folders ready in $TEST_DIR"

cat <<EOF

$(printf "\033[1;32mAll set.\033[0m")

Next:
  1. Copy 3–5 samples (copies, not originals) into:  $TEST_DIR/Incoming
       open "$TEST_DIR/Incoming"
  2. Run it:
       cd "$TOOL_DIR" && .venv/bin/python stem_stripper.py --incoming ~/StemTest/Incoming --output ~/StemTest/Instrumental --archive ~/StemTest/Archive

EOF
