"""Runtime configuration. Paths are resolved against GIDEON_HOME (set by the launcher)."""
from __future__ import annotations
import os, tomllib
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path(os.environ.get("GIDEON_HOME", "/opt/gideon"))
MODELS = Path(os.environ.get("GIDEON_MODELS", HOME / "models"))
CONFIG_PATHS = [
    Path(os.environ["GIDEON_CONFIG"]) if "GIDEON_CONFIG" in os.environ else None,
    Path(os.path.expanduser("~/.config/gideon/config.toml")),
    Path("/etc/gideon/config.toml"),
]


@dataclass
class Config:
    # audio
    sample_rate: int = 16000
    frame: int = 512                # silero v4 window @16k
    input_device: str | None = None
    output_device: str | None = None

    # vad / endpointing
    vad_threshold: float = 0.5
    speech_start_frames: int = 3    # ~96 ms of speech to open a segment
    silence_end_ms: int = 700       # trailing silence that closes a segment
    max_segment_s: float = 15.0
    pre_roll_ms: int = 300          # audio kept from before the trigger

    # stt
    whisper_model: str = "tiny.en"
    whisper_compute: str = "int8"
    whisper_threads: int = 4

    # wake
    # Whisper reliably renders "Gideon" as "get in" - the name collapses onto a
    # far more common English phrase, and this does NOT improve with tiny -> base
    # -> small. The variants below are therefore load-bearing, not padding.
    # All require a "hey"-style prefix: bare "get in" would fire on ordinary speech.
    wake_phrases: tuple[str, ...] = (
        "hey gideon", "hey get in", "hey guidion", "hey giddy on",
        "hi gideon", "hi get in", "a gideon", "hey kidding", "hike it in",
    )
    wake_fuzz: float = 0.80         # difflib ratio floor; raised because the
                                    # variant list now covers the real mishearings

    # speaker verification
    # Wake matching is transcript matching: it cannot tell WHO spoke, so without
    # this any visitor who says "hey gideon" is served. An ECAPA-TDNN embeds the
    # utterance and it is accepted only if it resembles the voiceprint written by
    # `gideon --enroll`. Deliberately fail-open: with no voiceprint enrolled the
    # daemon behaves exactly as it did before, warns once, and shows a degraded
    # health row - a failed model download must not silently mute the assistant.
    speaker_verify: bool = True
    # Cosine similarity floor against the enrolled centroid. Measured on this
    # checkpoint with a 4-utterance enrollment: the owner scores 0.66 on a bare
    # "hey gideon" and 0.81-0.85 on a full sentence, while two other speakers
    # saying the same words score -0.22 to 0.13. The gap is wide, so 0.45 sits
    # far from both sides and leaves room for mic and room noise, which compress
    # the owner's score more than a synthetic test can show. Raise towards 0.60
    # for a stricter door at the cost of the occasional repeated wake phrase.
    speaker_threshold: float = 0.45
    # Verification costs one embedding (~20 ms) per candidate utterance, so it
    # only runs where it buys something. The follow-up window is deliberately
    # NOT gated by default: it opens only after an already-verified turn.
    speaker_verify_followup: bool = False

    # conversation
    # Seconds after a reply during which Gideon answers without the wake phrase.
    # Long enough for a real follow-up, short enough that background talk in the
    # room does not get treated as a question.
    followup_window_s: float = 8.0

    # Push-to-talk: a unix socket the hotkey listener sends "wake" to, so a key
    # press arms the *running* daemon instead of starting a second one. Set
    # control_socket = false to disable the socket entirely.
    control_socket: bool = True
    # How long a key press stays armed. Longer than the follow-up window: the
    # press comes *before* the sentence, so it has to cover the pause while the
    # user gathers their thought.
    hotkey_window_s: float = 10.0

    # tier 1 brain (optional; absent Ollama degrades to canned replies)
    llm_enabled: bool = True
    # Where Tier 1 answers come from: "ollama" (local, the default and the only
    # one that keeps Gideon fully offline), "cerebras" or "openrouter". A cloud
    # provider sends your transcribed speech off this machine, so it is never a
    # default and the daemon logs it at every startup. Set with `gideon --provider`.
    llm_provider: str = "ollama"
    # The model id at that provider (e.g. "llama3.1-8b",
    # "meta-llama/llama-3.3-70b-instruct"). Ignored when llm_provider = "ollama",
    # which uses llm_model below. They are separate settings so that switching
    # providers back and forth does not lose either choice - and because the
    # local model stays configured as the fallback when the cloud is unreachable.
    cloud_model: str = ""
    cloud_timeout: float = 12.0
    llm_url: str = "http://127.0.0.1:11434"
    # Must be a NON-reasoning model. qwen3/deepseek-r1 spend their whole token
    # budget thinking before answering, which costs 15-20 s on a laptop CPU.
    # Measured on an i7-1165G7: 1b averages 0.5 s on simple questions and 1.7 s on
    # harder ones, against 2.0 s / 4.3 s for 3b, with the same answers correct.
    # For speech, the latency matters more than 3b's slightly better wording.
    llm_model: str = "llama3.2:1b"
    llm_timeout: float = 30.0

    # tts
    voice: str = "en_US-lessac-medium"
    speak_greeting_on_start: bool = True

    log_level: str = "INFO"

    @classmethod
    def load(cls) -> "Config":
        data: dict = {}
        for p in CONFIG_PATHS:
            if p and p.is_file():
                with p.open("rb") as fh:
                    data = tomllib.load(fh)
                break
        known = {f for f in cls.__dataclass_fields__}
        flat = {k: v for k, v in data.items() if k in known}
        for section in data.values():
            if isinstance(section, dict):
                flat.update({k: v for k, v in section.items() if k in known})
        if "wake_phrases" in flat:
            flat["wake_phrases"] = tuple(flat["wake_phrases"])
        return cls(**flat)

    @property
    def voice_path(self) -> Path:
        return MODELS / "piper" / f"{self.voice}.onnx"

    @property
    def vad_path(self) -> Path:
        return MODELS / "vad" / "silero_vad.onnx"

    @property
    def speaker_path(self) -> Path:
        return MODELS / "speaker" / "ecapa_tdnn512_lm.onnx"

    @property
    def voiceprint_path(self) -> Path:
        return Path(os.path.expanduser("~/.config/gideon/voiceprint.npy"))

    @property
    def whisper_dir(self) -> Path:
        return MODELS / "whisper" / self.whisper_model
