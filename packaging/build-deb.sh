#!/usr/bin/env bash
# Build a fully self-contained gideon_*.deb.
#
# The package vendors its own relocatable CPython, so it does not care whether
# the target runs Ubuntu 24.04 (python3.12) or 26.04 (python3.14). Models and
# wheels are baked in: installing needs apt only, and first run needs no network.
set -euo pipefail

PKG=gideon
VERSION="${VERSION:-0.1.0}"
ARCH=amd64
PYVER=3.12
WHISPER_MODEL="${WHISPER_MODEL:-tiny.en}"
VOICE="${VOICE:-en_US-lessac-medium}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
BUILD="${BUILD_DIR:-$ROOT/build}"
STAGE="$BUILD/stage"
OPT="$STAGE/opt/gideon"

need() { command -v "$1" >/dev/null || { echo "!! missing required tool: $1" >&2; exit 1; }; }
need uv; need dpkg-deb; need fakeroot; need curl; need sha256sum
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

rm -rf "$STAGE"
mkdir -p "$OPT"/{lib,app,models/piper,models/whisper,models/vad} \
         "$STAGE"/DEBIAN "$STAGE"/usr/bin "$STAGE"/usr/lib/systemd/user \
         "$STAGE"/etc/gideon "$STAGE"/usr/share/doc/$PKG

step "Vendoring CPython $PYVER (relocatable)"
uv python install "$PYVER" >/dev/null
PYBIN="$(uv python find "$PYVER")"
PYROOT="$(dirname "$(dirname "$PYBIN")")"
# -L dereferences: uv's tree contains symlinks that must not escape the package.
cp -aL "$PYROOT" "$OPT/python"
# Trim what a headless daemon will never use.
rm -rf "$OPT/python/lib/python$PYVER"/{test,idlelib,tkinter,ensurepip,turtledemo} \
       "$OPT/python/lib/python$PYVER"/lib2to3 "$OPT/python/share" 2>/dev/null || true
find "$OPT/python" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

step "Installing Python dependencies (CPU-only, no CUDA)"
# Resolve the real dependency closure, then prune. Hand-pinning a --no-deps list
# breaks whenever an upstream adds a transitive dep (e.g. huggingface-hub/httpx).
uv pip install --python "$OPT/python/bin/python3" --target "$OPT/lib" \
    faster-whisper onnxruntime sounddevice piper-tts >/dev/null

step "Fetching models (piper voice, whisper $WHISPER_MODEL, silero VAD)"
PYTHONPATH="$OPT/lib" "$OPT/python/bin/python3" - "$OPT" "$VOICE" "$WHISPER_MODEL" <<'PY'
import sys, pathlib
opt, voice, wmodel = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
from piper.download_voices import download_voice
download_voice(voice, opt / "models" / "piper")
from huggingface_hub import snapshot_download
snapshot_download(f"Systran/faster-whisper-{wmodel}",
                  local_dir=opt / "models" / "whisper" / wmodel)
PY
# Silero VAD, pinned to v4 (the h/c LSTM-state interface gideon.vad implements).
# Taken from upstream rather than from the openwakeword wheel: openwakeword 0.6
# stopped bundling models, so that source silently disappears on version bumps.
SILERO_URL="https://raw.githubusercontent.com/snakers4/silero-vad/v4.0/files/silero_vad.onnx"
SILERO_SHA="a35ebf52fd3ce5f1469b2a36158dba761bc47b973ea3382b3186ca15b1f5af28"
curl -fsSL -o "$OPT/models/vad/silero_vad.onnx" "$SILERO_URL"
echo "$SILERO_SHA  $OPT/models/vad/silero_vad.onnx" | sha256sum -c - >/dev/null \
  || { echo "!! silero_vad.onnx checksum mismatch - refusing to package" >&2; exit 1; }

# Drop packages pulled in for features this daemon never touches:
#   scipy/sklearn - only reached via openwakeword, which v0.1 does not use
#   hf_xet    - Xet transfer backend; models are already baked in, HF is offline
# NOTE: av stays. faster_whisper/audio.py imports it unconditionally at package
# import time, even though we feed transcribe() numpy arrays and never decode.
PRUNE_MB_BEFORE=$(du -sm "$OPT/lib" | cut -f1)
for junk in scipy scipy.libs sklearn hf_xet; do
    rm -rf "$OPT/lib/$junk" "$OPT/lib/${junk}-"*.dist-info
done
echo "    pruned $((PRUNE_MB_BEFORE - $(du -sm "$OPT/lib" | cut -f1))) MB of unused dependencies"

rm -rf "$OPT/models/whisper/$WHISPER_MODEL/.cache"

step "Stripping binaries"
find "$OPT/lib" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OPT/lib" "$OPT/python" -name '*.so*' -type f -print0 2>/dev/null \
  | xargs -0 -r strip --strip-unneeded 2>/dev/null || true

step "Staging application"
cp -a "$ROOT/src/gideon" "$OPT/app/gideon"
# gideon/hotkey/* is executed by the SYSTEM python (it needs python3-evdev,
# which is not in the vendored runtime), so it ships as readable scripts here
# rather than as an importable part of the app.
chmod 0755 "$OPT/app/gideon/hotkey"/*.py
install -m644 "$HERE/config.toml" "$STAGE/etc/gideon/config.toml"
install -m755 "$HERE/gideon.launcher" "$STAGE/usr/bin/gideon"
install -m644 "$HERE/gideon.service" "$STAGE/usr/lib/systemd/user/gideon.service"
install -m644 "$ROOT/README.md" "$STAGE/usr/share/doc/$PKG/README.md" 2>/dev/null || true

INSTALLED_KB=$(du -sk "$STAGE" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" -e "s/@SIZE@/$INSTALLED_KB/" \
    "$HERE/debian/control" > "$STAGE/DEBIAN/control"
install -m755 "$HERE/debian/postinst" "$STAGE/DEBIAN/postinst"
install -m755 "$HERE/debian/prerm"    "$STAGE/DEBIAN/prerm"
install -m644 "$HERE/debian/conffiles" "$STAGE/DEBIAN/conffiles"

step "Building .deb"
OUT="$BUILD/${PKG}_${VERSION}_${ARCH}.deb"
fakeroot dpkg-deb --build -Zzstd -z19 "$STAGE" "$OUT" >/dev/null
printf '\n\033[1;32m✓ %s  (%s)\033[0m\n' "$OUT" "$(du -h "$OUT" | cut -f1)"
echo "  installed size: $((INSTALLED_KB/1024)) MB"
echo "  install with:   sudo apt install $OUT"
