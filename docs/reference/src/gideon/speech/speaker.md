# `src/gideon/speech/speaker.py`

**Speaker verification: not *what* was said, but *who* said it.** Wake detection is
transcript matching, so it fires for anyone in the room who says "hey gideon". This file
answers the other half of the question by embedding the utterance with an ECAPA-TDNN and
comparing it against the voiceprint written by `gideon --enroll`.

## Why WeSpeaker ONNX, not SpeechBrain

SpeechBrain's ECAPA is the better-known checkpoint, but it needs PyTorch — several hundred
megabytes vendored into a `.deb` that is currently a fraction of that. WeSpeaker publishes
the same architecture as a 24 MB ONNX export, which runs under the `onnxruntime` already
vendored for the VAD. **Speaker verification therefore adds no Python dependency at all.**
`scripts/build-deb.sh` pins it by SHA-256 and aborts on mismatch, exactly as it does for
Silero: a silently swapped embedder is a silently opened door.

The checkpoint is the `-LM` (large-margin fine-tuned) variant, which is why comparison is
plain cosine similarity against an absolute threshold rather than a calibrated score.

## The fbank front end is load-bearing

The network was trained on **Kaldi's** `fbank`, which torchaudio would normally supply.
Without torch, `fbank()` reproduces it in numpy, and it has to be exact: mismatched
features do not degrade the embedding gracefully, they make it meaningless — and
meaningless embeddings still return confident-looking numbers. The settings come from the
model's own `config.yaml`: 80 mel bins, 25 ms Povey window, 10 ms shift, dither off,
input scaled to int16 units, per-utterance mean normalisation over time.

Details that are easy to get wrong and silent when wrong: Kaldi drops the Nyquist FFT bin
(`FFT_SIZE // 2`, not `+ 1`); pre-emphasis happens **after** DC removal and **before**
windowing, using the frame's own first sample so the filter never reaches across a frame
boundary; the log floor is `FLT_EPSILON`, not an arbitrary small number.

Because a broken port cannot be caught by reading it, `--selftest` asserts the property
only a correct one produces — two utterances from one voice score far apart from noise —
and the build was validated against three synthetic speakers before landing: same-voice
pairs scored 0.51–0.85, cross-voice pairs −0.22–0.21.

## `MIN_SPEECH_S` is a hole, and is sized accordingly

Audio too short to embed is **accepted**, not rejected: a clipped segment says nothing
about who spoke, and refusing it would make the wake phrase — the shortest utterance there
is — unusable. That makes the floor a way in, so it is set as low as the model tolerates.
Measured against a 5-phrase enrollment: 0.85 s → owner 0.72 vs impostors 0.07–0.08;
0.55 s → 0.69 vs 0.07/−0.02; 0.35 s → owner 0.46, close enough to the 0.45 threshold to
start rejecting its own speaker. **0.4 s** is the compromise, and is shorter than any real
utterance of "hey gideon" (0.6–0.9 s measured).

## `Verifier` fails open, loudly

Constructing a `Verifier` never raises. A missing voiceprint, a missing model file or a
load failure leaves it `disabled`, which accepts every utterance and reports why through
`.reason` — surfaced as the **Voice lock** row in the health panel. This is deliberate: a
failed model download must not silently turn the assistant off for its owner. The strict
alternative is `speaker_verify = false`'s opposite and is not offered; users who want it
can raise `speaker_threshold`.

`check()` also swallows a mid-flight embedding failure and accepts, for the same reason.

## Public surface

| | |
|---|---|
| `fbank(audio)` | float32 mono → `(frames, 80)` CMN log-mel |
| `SpeakerModel.embed(audio)` | unit-norm 192-d embedding, or `None` if too short |
| `Verifier.check(audio)` | `(accepted, similarity)`; accepts when disabled |
| `score(a, b)` | cosine similarity of two unit-norm embeddings |
| `save_voiceprint` / `load_voiceprint` | the `(192,)` float32 centroid on disk |

| | |
|---|---|
| Imports | `numpy`, `onnxruntime` (lazily) |
| Imported by | `__main__`, `cli/enroll` |
| Model | `$GIDEON_MODELS/speaker/ecapa_tdnn512_lm.onnx` (~24 MB) |
| Voiceprint | `~/.config/gideon/voiceprint.npy` |
| Config | `speaker_verify`, `speaker_threshold`, `speaker_verify_followup` |
