"""Speaker verification: is this Gideon's owner talking, or somebody else?

Wake matching is done on the transcript, so anyone in the room who says "hey
gideon" is heard. This module answers the separate question of *who* said it,
by embedding the utterance with an ECAPA-TDNN and comparing it against the
voiceprint enrolled by `gideon --enroll`.

Two things are worth knowing before touching this file:

- **No torch.** The upstream model ships as ONNX, so it runs under the same
  onnxruntime already vendored for the VAD. That also means the 80-bin log-mel
  front end torchaudio would normally provide has to be reproduced here in
  numpy, and it has to be reproduced *exactly*: the network was trained on
  Kaldi's `fbank` and mismatched features do not degrade the embedding
  gracefully, they make it meaningless. `fbank()` below is a port of
  kaldi-compliance fbank with the settings recorded in the model's config.yaml
  (25 ms Povey window, 10 ms shift, 80 mel bins, dither off, int16-scaled input).
- **Cosine, not distance.** The -LM checkpoint is trained with large-margin
  fine-tuning, so embeddings are compared with cosine similarity and the
  threshold is an absolute number, not a percentile.
"""
from __future__ import annotations
import logging
from pathlib import Path
import numpy as np

log = logging.getLogger("gideon.speaker")

SAMPLE_RATE = 16000
NUM_MEL_BINS = 80
FRAME_LENGTH = 400          # 25 ms @ 16 kHz
FRAME_SHIFT = 160           # 10 ms @ 16 kHz
FFT_SIZE = 512              # next power of two above FRAME_LENGTH
PREEMPH = 0.97
LOW_FREQ = 20.0
EPS = np.float32(1.1920928955078125e-07)   # Kaldi's log floor (FLT_EPSILON)

# Shortest utterance worth embedding. Anything below this is accepted unscored
# (see Verifier.check), so the floor is a hole and wants to be as low as the
# model tolerates. Measured against a 5-phrase enrollment: at 0.85 s the owner
# scores 0.72 and two impostors 0.07-0.08; at 0.55 s, 0.69 against 0.07/-0.02;
# at 0.35 s the owner falls to 0.46, close enough to the 0.45 threshold to start
# rejecting its own speaker. 0.4 s is the compromise - comfortably discriminative,
# and shorter than any real utterance of "hey gideon" (0.6-0.9 s measured).
MIN_SPEECH_S = 0.4


def _mel(f):
    return 1127.0 * np.log(1.0 + f / 700.0)


def _mel_banks() -> np.ndarray:
    """Kaldi's triangular mel filterbank: (NUM_MEL_BINS, FFT_SIZE//2)."""
    num_fft_bins = FFT_SIZE // 2          # Kaldi drops the Nyquist bin
    bin_width = SAMPLE_RATE / FFT_SIZE
    high_freq = SAMPLE_RATE / 2.0
    mel_low, mel_high = _mel(LOW_FREQ), _mel(high_freq)
    delta = (mel_high - mel_low) / (NUM_MEL_BINS + 1)

    fft_mel = _mel(np.arange(num_fft_bins) * bin_width)
    banks = np.zeros((NUM_MEL_BINS, num_fft_bins), dtype=np.float32)
    for i in range(NUM_MEL_BINS):
        left = mel_low + i * delta
        centre, right = left + delta, left + 2 * delta
        rising = (fft_mel - left) / (centre - left)
        falling = (right - fft_mel) / (right - centre)
        w = np.where(fft_mel <= centre, rising, falling)
        banks[i] = np.where((fft_mel > left) & (fft_mel < right), w, 0.0)
    return banks


def _povey_window() -> np.ndarray:
    n = np.arange(FRAME_LENGTH)
    hann = 0.5 - 0.5 * np.cos(2 * np.pi * n / (FRAME_LENGTH - 1))
    return np.power(hann, 0.85).astype(np.float32)


_BANKS = _mel_banks()
_WINDOW = _povey_window()


def fbank(audio: np.ndarray) -> np.ndarray:
    """float32 mono in [-1, 1] -> (frames, 80) log-mel, mean-normalised over time.

    Mirrors torchaudio.compliance.kaldi.fbank(dither=0, snip_edges=True) followed
    by the per-utterance CMN that WeSpeaker applies before the network.
    """
    x = audio.astype(np.float32) * 32768.0     # Kaldi works in int16 units
    n_frames = 1 + (len(x) - FRAME_LENGTH) // FRAME_SHIFT
    if n_frames < 1:
        return np.zeros((0, NUM_MEL_BINS), dtype=np.float32)

    idx = np.arange(FRAME_LENGTH) + FRAME_SHIFT * np.arange(n_frames)[:, None]
    frames = x[idx]                                        # (frames, 400)
    frames -= frames.mean(axis=1, keepdims=True)           # remove_dc_offset
    # Kaldi pre-emphasises with the frame's own first sample duplicated, so the
    # filter never reaches back across the frame boundary.
    shifted = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
    frames = frames - PREEMPH * shifted
    frames *= _WINDOW

    power = np.abs(np.fft.rfft(frames, n=FFT_SIZE)[:, :FFT_SIZE // 2]) ** 2
    feats = np.log(np.maximum(power.astype(np.float32) @ _BANKS.T, EPS))
    return (feats - feats.mean(axis=0, keepdims=True)).astype(np.float32)


class SpeakerModel:
    """ECAPA-TDNN embedder. Loading is lazy at construction, like STT/VAD."""

    def __init__(self, model_path):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        log.info("loading speaker model from %s", model_path)
        self._s = ort.InferenceSession(str(model_path), sess_options=opts,
                                       providers=["CPUExecutionProvider"])

    def embed(self, audio: np.ndarray) -> np.ndarray | None:
        """Return a unit-norm 192-d embedding, or None if the audio is too short."""
        if len(audio) < MIN_SPEECH_S * SAMPLE_RATE:
            return None
        feats = fbank(audio)
        if len(feats) < 10:
            return None
        emb = self._s.run(None, {"feats": feats[None, :, :]})[0][0]
        norm = float(np.linalg.norm(emb))
        if norm == 0.0:
            return None
        return (emb / norm).astype(np.float32)

    def warm(self) -> None:
        self.embed(np.zeros(int(SAMPLE_RATE), dtype=np.float32))


def score(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two unit-norm embeddings."""
    return float(np.dot(a, b))


class Verifier:
    """Owns the model, the voiceprint, and the fail-open policy.

    Constructing one never raises: a missing model or a missing voiceprint
    leaves the verifier `disabled`, which accepts every utterance and reports
    why through `.reason`. The daemon must keep answering its owner even when
    this subsystem is broken; the alternative is a bad download silently
    turning Gideon off.
    """

    def __init__(self, model_path, voiceprint_path, threshold: float):
        self.threshold = threshold
        self.enabled = False
        self.reason = ""
        self._model = None
        self._print = None

        if not Path(voiceprint_path).is_file():
            self.reason = "not enrolled - run: gideon --enroll"
            log.warning("speaker verification OFF: %s", self.reason)
            return
        if not Path(model_path).is_file():
            self.reason = f"model missing: {model_path}"
            log.warning("speaker verification OFF: %s", self.reason)
            return
        try:
            self._print = load_voiceprint(voiceprint_path)
            self._model = SpeakerModel(model_path)
        except Exception as exc:                     # noqa: BLE001 - never fatal
            self.reason = f"load failed: {exc}"
            log.warning("speaker verification OFF: %s", self.reason)
            return
        self.enabled = True
        self.reason = f"enrolled, threshold {threshold:.2f}"

    def check(self, audio: np.ndarray) -> tuple[bool, float]:
        """Return (accepted, similarity). Disabled or unscorable audio accepts.

        Audio too short to embed is accepted rather than rejected: a clipped
        segment says nothing about who spoke, and refusing it would make the
        wake phrase on its own - the shortest possible utterance - unusable.
        """
        if not self.enabled:
            return True, 0.0
        try:
            emb = self._model.embed(audio)
        except Exception as exc:                     # noqa: BLE001
            log.warning("speaker embed failed, accepting: %s", exc)
            return True, 0.0
        if emb is None:
            return True, 0.0
        sim = score(emb, self._print)
        return sim >= self.threshold, sim

    def warm(self) -> None:
        if self._model is not None:
            self._model.warm()


def save_voiceprint(path, embeddings) -> np.ndarray:
    """Average unit-norm embeddings into one voiceprint and write it."""
    centroid = np.mean(np.stack(embeddings), axis=0)
    centroid /= np.linalg.norm(centroid)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, centroid.astype(np.float32))
    return centroid


def load_voiceprint(path) -> np.ndarray:
    emb = np.load(Path(path)).astype(np.float32)
    if emb.shape != (192,):
        raise ValueError(f"voiceprint has shape {emb.shape}, expected (192,)")
    return emb / np.linalg.norm(emb)
