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
WHISPER_MODEL="${WHISPER_MODEL:-base.en}"
VOICE="${VOICE:-en_US-lessac-medium}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
PKG_DIR="$ROOT/packaging"        # deb metadata, systemd unit, launcher, default config
REQ_DIR="$ROOT/requirements"     # declared dependency manifests (see docs/DEPENDENCIES.md)
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
    $(sed -e 's/#.*//' "$REQ_DIR/python-runtime.txt" | tr -d '\r' | xargs) >/dev/null

step "Fetching models (piper voice, whisper $WHISPER_MODEL, silero VAD, ECAPA speaker)"
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

# ECAPA-TDNN speaker embedding, so only the enrolled voice can wake Gideon.
# WeSpeaker's ONNX export, not SpeechBrain's checkpoint: SpeechBrain needs
# PyTorch, which would multiply the size of this package, while this runs under
# the onnxruntime already vendored for the VAD. Pinned by SHA for the same
# reason the VAD is - a silently swapped embedder is a silently opened door.
ECAPA_URL="https://huggingface.co/Wespeaker/wespeaker-ecapa-tdnn512-LM/resolve/main/voxceleb_ECAPA512_LM.onnx"
ECAPA_SHA="d71b85d9b48058ef68004f04f1b78acebefb9dfcf542e19b976a12a5ad1f10b0"
mkdir -p "$OPT/models/speaker"
curl -fsSL -o "$OPT/models/speaker/ecapa_tdnn512_lm.onnx" "$ECAPA_URL"
echo "$ECAPA_SHA  $OPT/models/speaker/ecapa_tdnn512_lm.onnx" | sha256sum -c - >/dev/null \
  || { echo "!! ecapa_tdnn512_lm.onnx checksum mismatch - refusing to package" >&2; exit 1; }

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
# Bytecode from a developer's own interpreter is dead weight here and actively
# misleading for hotkey/ and ui/, which are executed by the SYSTEM python: the
# .pyc left behind by a local test run is for neither that interpreter nor the
# vendored one.
find "$OPT/app/gideon" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
# gideon/hotkey/* is executed by the SYSTEM python (it needs python3-evdev,
# which is not in the vendored runtime), so it ships as readable scripts here
# rather than as an importable part of the app.
chmod 0755 "$OPT/app/gideon/hotkey"/*.py
# gideon/ui/* is the same story: GTK and PyGObject are apt packages, not part of
# the vendored closure, so the tray indicator is executed by the system python.
chmod 0755 "$OPT/app/gideon/ui"/*.py
install -m644 "$PKG_DIR/config/config.toml" "$STAGE/etc/gideon/config.toml"
install -m755 "$PKG_DIR/launcher/gideon.launcher" "$STAGE/usr/bin/gideon"
install -m644 "$PKG_DIR/systemd/gideon.service" "$STAGE/usr/lib/systemd/user/gideon.service"
install -m644 "$PKG_DIR/systemd/gideon-ui.service" "$STAGE/usr/lib/systemd/user/gideon-ui.service"
install -m644 "$ROOT/README.md" "$STAGE/usr/share/doc/$PKG/README.md" 2>/dev/null || true

INSTALLED_KB=$(du -sk "$STAGE" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" -e "s/@SIZE@/$INSTALLED_KB/" \
    "$PKG_DIR/debian/control" > "$STAGE/DEBIAN/control"
install -m755 "$PKG_DIR/debian/postinst" "$STAGE/DEBIAN/postinst"
install -m755 "$PKG_DIR/debian/prerm"    "$STAGE/DEBIAN/prerm"
install -m644 "$PKG_DIR/debian/conffiles" "$STAGE/DEBIAN/conffiles"

step "Building .deb"
OUT="$BUILD/${PKG}_${VERSION}_${ARCH}.deb"
fakeroot dpkg-deb --build -Zzstd -z19 "$STAGE" "$OUT" >/dev/null
printf '\n\033[1;32m✓ %s  (%s)\033[0m\n' "$OUT" "$(du -h "$OUT" | cut -f1)"
echo "  installed size: $((INSTALLED_KB/1024)) MB"
echo "  install with:   sudo apt install $OUT"
