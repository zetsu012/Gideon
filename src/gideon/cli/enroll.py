"""`gideon --enroll`: record the owner's voiceprint.

Wake matching cannot tell who is speaking, so this is what makes "hey gideon"
personal. The user reads a handful of prompts, each one is endpointed by the
same VAD the daemon uses, embedded with ECAPA-TDNN, and the averaged embedding
is written to ~/.config/gideon/voiceprint.npy.

Enrolling with the daemon running is fine to *ask* for but impossible to do:
the daemon owns the microphone. That case is detected up front and explained,
rather than surfacing as a PortAudio error.
"""
from __future__ import annotations
import logging
import numpy as np

from ..core.config import Config
from ..audio.capture import Microphone
from ..speech.vad import VAD
from ..speech import speaker as spk
from ..ipc.control import send as control_send

log = logging.getLogger("gideon.enroll")

# Varied phonetically on purpose: a voiceprint built from one repeated sentence
# encodes that sentence as much as the voice.
PROMPTS = (
    "Hey Gideon, are you listening to me?",
    "The quick brown fox jumps over the lazy dog.",
    "Please turn the kitchen lights off at nine.",
    "One, two, three, four, five, six, seven, eight.",
    "I would like to know what the weather is doing today.",
)

# A single utterance is a weak print; five is enough to average out one bad
# take without making enrollment a chore.
MIN_ACCEPTED = 3


def _record(mic: Microphone, vad: VAD, cfg: Config) -> np.ndarray | None:
    """Capture one endpointed utterance, or None if nothing was said."""
    from .. import __main__ as daemon
    vad.reset()
    mic.drain()
    for audio in daemon.segments(mic, vad, cfg):
        return audio
    return None


def enroll(cfg: Config) -> int:
    if not cfg.speaker_path.exists():
        print(f"The speaker model is missing:\n    {cfg.speaker_path}\n\n"
              "Rebuild the package (./scripts/build-deb.sh) to fetch it.")
        return 2
    if cfg.control_socket and control_send("ping"):
        print("Gideon is already running and holds the microphone.\n\n"
              "Stop it first, enroll, then start it again:\n"
              "    systemctl --user stop gideon\n"
              "    gideon --enroll\n"
              "    systemctl --user start gideon")
        return 2

    print("Enrolling your voice. Gideon will then answer you and ignore everyone else.\n"
          "Read each line out loud, normally, from where you usually stand.\n"
          f"Press Ctrl-C to abort. ({len(PROMPTS)} phrases)\n")

    model = spk.SpeakerModel(cfg.speaker_path)
    vad = VAD(cfg.vad_path, cfg.sample_rate)
    embeddings: list[np.ndarray] = []

    try:
        with Microphone(cfg.sample_rate, cfg.frame, cfg.input_device) as mic:
            for i, prompt in enumerate(PROMPTS, 1):
                print(f"  [{i}/{len(PROMPTS)}] say:  {prompt}")
                audio = _record(mic, vad, cfg)
                if audio is None:
                    print("        ...nothing heard, skipping")
                    continue
                emb = model.embed(audio)
                if emb is None:
                    print("        ...too short, skipping")
                    continue
                embeddings.append(emb)
                print(f"        ok ({len(audio) / cfg.sample_rate:.1f}s)")
    except KeyboardInterrupt:
        print("\naborted - nothing was written")
        return 130

    if len(embeddings) < MIN_ACCEPTED:
        print(f"\nOnly {len(embeddings)} usable recording(s); {MIN_ACCEPTED} are needed.\n"
              "Check the microphone and try again.")
        return 1

    # A take that disagrees with the rest is a cough, a clipped word or someone
    # else in the room. Averaging it in would quietly widen the door for
    # everybody, so drop it and say so.
    centroid = np.mean(np.stack(embeddings), axis=0)
    centroid /= np.linalg.norm(centroid)
    kept = [e for e in embeddings if spk.score(e, centroid) >= 0.35]
    if len(kept) < len(embeddings):
        print(f"\nDiscarded {len(embeddings) - len(kept)} inconsistent recording(s).")
    if len(kept) < MIN_ACCEPTED:
        print("The recordings disagree with each other too much to build a "
              "voiceprint. Try again somewhere quieter.")
        return 1

    spk.save_voiceprint(cfg.voiceprint_path, kept)
    spread = min(spk.score(e, centroid) for e in kept)
    print(f"\nVoiceprint written to {cfg.voiceprint_path}"
          f"\n  {len(kept)} recordings, closest-match floor {spread:.2f}, "
          f"accept threshold {cfg.speaker_threshold:.2f}")
    print("\nRestart Gideon to use it:\n    systemctl --user restart gideon")
    return 0
