#!/usr/bin/env bash
# Run Gideon straight from the build tree - no .deb, no sudo, no system install.
#
# It reuses the vendored runtime and models that packaging/build-deb.sh staged in
# build/stage, but runs YOUR working copy in src/ so edits take effect immediately.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGE="$ROOT/build/stage/opt/gideon"

if [ ! -x "$STAGE/python/bin/python3" ]; then
  echo "Build tree missing. Run:  ./packaging/build-deb.sh" >&2
  exit 1
fi

# sounddevice dlopen()s the system PortAudio; it is the one thing not vendored.
# Only the paths that actually open a device need it - --selftest does not.
NEEDS_AUDIO=1
for a in "$@"; do
  case "$a" in --selftest) NEEDS_AUDIO=0 ;; esac
done
if [ "$NEEDS_AUDIO" = 1 ] && ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
  cat >&2 <<'MSG'
Missing PortAudio - Gideon cannot open the microphone or speakers without it:

    sudo apt install libportaudio2

The .deb declares this as a dependency, so a real install pulls it in
automatically; only this run-from-source path needs it installed by hand.
Meanwhile ./run-local.sh --selftest works without it.
MSG
  exit 1
fi

export GIDEON_HOME="$STAGE"
export GIDEON_CONFIG="${GIDEON_CONFIG:-$ROOT/packaging/config.toml}"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export GIDEON_SRC="$ROOT/src"

# src/ first, so the working copy wins over the staged copy of the app.
exec "$STAGE/python/bin/python3" -E -s -c '
import os, sys, runpy
home = os.environ["GIDEON_HOME"]
# working copy first, so edits in src/ shadow the staged app/
sys.path[:0] = [os.environ["GIDEON_SRC"], os.path.join(home,"lib"), os.path.join(home,"app")]
sys.argv[0] = "gideon"
runpy.run_module("gideon", run_name="__main__", alter_sys=True)
' "$@"
