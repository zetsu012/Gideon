# `src/gideon/speech/stt.py`

**Speech-to-text via faster-whisper (CTranslate2), CPU, int8.**

`STT(model_dir, compute_type="int8", threads=4)` loads the model at construction — the
expensive step, a few seconds. `transcribe(audio) -> str` takes a float32 numpy array and
returns joined, stripped text. `warm()` runs one second of silence through it so the first
real utterance does not pay the lazy-init cost.

## Transcribe options, and why each

| Option | Reason |
|---|---|
| `language="en"` | skips language detection, which costs a pass over the audio |
| `beam_size=1` | greedy. Beam search buys accuracy this pipeline cannot spend latency on |
| `vad_filter=False` | `speech/vad.py` already endpointed the segment; doing it twice would clip |
| `condition_on_previous_text=False` | each utterance is independent; prevents drift and looping |
| `no_speech_threshold=0.6` | drops segments Whisper thinks are silence |

## Load-bearing consequence

Because wake detection is transcript matching (`nlu/wake.py`), **Whisper runs on every
VAD-gated segment**, not only after a trigger. That is the cost of not needing a trained
wake-word model, and it is what sets `tiny.en` as the default size.

The model directory is a HuggingFace snapshot baked into the package; `HF_HUB_OFFLINE=1`
is exported by the launcher so nothing reaches the network at load time.

| | |
|---|---|
| Imports | `numpy`, `faster_whisper` (deferred to `__init__`) |
| Imported by | `__main__` |
| Model | `$GIDEON_MODELS/whisper/tiny.en/` (~75 MB) |
