"""Gideon daemon: mic -> VAD endpointing -> Whisper -> wake match -> Piper."""
from __future__ import annotations
import argparse, collections, logging, signal, sys, time
import numpy as np

from .core.config import Config
from .audio.capture import Microphone
from .speech.vad import VAD
from .speech.stt import STT
from .speech.tts import TTS
from .nlu import wake
from .ipc.control import Control, send as control_send
from .nlu.brain import Brain
from .llm.client import LLM

log = logging.getLogger("gideon")
_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    log.info("signal %s received, shutting down", signum)


def segments(mic: Microphone, vad: VAD, cfg: Config):
    """Yield float32 utterances delimited by silence."""
    frames_per_s = cfg.sample_rate / cfg.frame
    end_frames = max(1, int(cfg.silence_end_ms / 1000 * frames_per_s))
    max_frames = int(cfg.max_segment_s * frames_per_s)
    pre_roll = collections.deque(maxlen=max(1, int(cfg.pre_roll_ms / 1000 * frames_per_s)))

    buf: list[np.ndarray] = []
    speech_run = silence_run = 0
    active = False

    for frame in mic.frames():
        if _stop:
            return
        p = vad(frame)
        voiced = p >= cfg.vad_threshold

        if not active:
            pre_roll.append(frame)
            speech_run = speech_run + 1 if voiced else 0
            if speech_run >= cfg.speech_start_frames:
                active = True
                buf = list(pre_roll)
                silence_run = 0
            continue

        buf.append(frame)
        silence_run = 0 if voiced else silence_run + 1
        if silence_run >= end_frames or len(buf) >= max_frames:
            audio = np.concatenate(buf)
            active, speech_run, buf = False, 0, []
            pre_roll.clear()
            vad.reset()
            if len(audio) >= cfg.sample_rate * 0.3:   # ignore sub-300ms blips
                yield audio


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gideon", description="Always-on local voice assistant")
    ap.add_argument("--once", action="store_true", help="handle a single utterance then exit")
    ap.add_argument("--say", metavar="TEXT", help="speak TEXT and exit (audio smoke test)")
    ap.add_argument("--selftest", action="store_true", help="load all models, verify, exit")
    ap.add_argument("--setup", action="store_true",
                    help="check the install, start the daemon, offer to wire up a key")
    ap.add_argument("--setup-key", action="store_true", dest="setup_key",
                    help="wire up a keyboard key as push-to-talk, nothing else")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = Config.load()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s", stream=sys.stderr)

    # Setup runs before the model check: diagnosing a broken install is exactly
    # what it is for, so it must not be blocked by one.
    if args.setup or args.setup_key:
        from .cli import setup as setup_mod
        return setup_mod.setup(cfg) if args.setup else setup_mod.setup_key(cfg)

    for path in (cfg.vad_path, cfg.voice_path, cfg.whisper_dir):
        if not path.exists():
            log.error("missing model: %s", path)
            return 2

    tts = TTS(cfg.voice_path, cfg.output_device)
    if args.say:
        tts.say(args.say)
        return 0

    stt = STT(cfg.whisper_dir, cfg.whisper_compute, cfg.whisper_threads)
    vad = VAD(cfg.vad_path, cfg.sample_rate)
    t0 = time.time()
    stt.warm()
    log.info("models ready in %.1fs", time.time() - t0)

    if args.selftest:
        matched, rest = wake.match("hey gideon are you there", cfg.wake_phrases, cfg.wake_fuzz)
        assert matched and rest == "are you there", (matched, rest)
        b = Brain(None)                                  # no LLM: must not raise
        assert b.respond("") in ("Yes?", "I'm here.", "Go ahead."), "ack failed"
        assert b.respond("hello").startswith(("Hi", "Hello", "Hey")), "greeting failed"
        probe = LLM(cfg.llm_url, cfg.llm_model, cfg.llm_timeout)
        log.info("local LLM: %s", "ready (%s)" % cfg.llm_model if probe.available()
                 else "not available - canned replies will be used")
        # Push-to-talk round trip: bind, send "wake" the way the hotkey
        # listener does, and confirm the daemon would treat the next utterance
        # as a query.
        probe_sock = Control(window_s=5.0)
        assert probe_sock.start(), "control socket failed to bind"
        try:
            assert control_send(path=probe_sock.path), "control socket did not answer"
            assert probe_sock.consume(), "wake did not arm the daemon"
            assert not probe_sock.consume(), "arm was not one-shot"
        finally:
            probe_sock.close()
        log.info("control socket OK (%s)", probe_sock.path)

        pcm, sr = tts.synth("Self test passed.")
        log.info("selftest OK (vad+stt+tts+router loaded, %d samples @ %d Hz synthesised)",
                 len(pcm), sr)
        return 0

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    llm = LLM(cfg.llm_url, cfg.llm_model, cfg.llm_timeout) if cfg.llm_enabled else None
    if llm is not None and llm.available():
        log.info("local LLM ready: %s", cfg.llm_model)
    brain = Brain(llm)

    # A push-to-talk key talks to this socket; without it the daemon is exactly
    # as it was, wake-phrase only.
    ctrl = Control(window_s=cfg.hotkey_window_s) if cfg.control_socket else None
    if ctrl is not None:
        ctrl.start()

    with Microphone(cfg.sample_rate, cfg.frame, cfg.input_device) as mic:
        if cfg.speak_greeting_on_start:
            mic.muted.set(); tts.say("Gideon is online."); mic.drain(); mic.muted.clear()
        log.info("listening for %r", cfg.wake_phrases[0])

        # After a reply Gideon stays open for a follow-up, so a conversation does
        # not require repeating the wake phrase for every single sentence.
        follow_until = 0.0

        for audio in segments(mic, vad, cfg):
            t = time.time()
            text = stt.transcribe(audio)
            if not text:
                continue

            # The key was pressed while this was being said: no wake phrase
            # needed, the whole utterance is the query.
            keyed = ctrl.consume() if ctrl is not None else False
            in_window = keyed or time.time() < follow_until
            matched, rest = wake.match(text, cfg.wake_phrases, cfg.wake_fuzz)
            if matched:
                query = rest
            elif in_window:
                query = text          # key press or follow-up window
            else:
                log.info("[%.2fs] ---- %r", time.time() - t, text)
                continue

            log.info("[%.2fs] %s %r", time.time() - t,
                     "KEY" if keyed and not matched else
                     "FOLLOW" if (in_window and not matched) else "WAKE", text)

            if query.strip().lower() in ("stop", "never mind", "nevermind",
                                         "cancel", "that's all", "thanks"):
                follow_until = 0.0
                if llm is not None:
                    llm.reset()
                mic.muted.set()
                try: tts.say("Okay.")
                finally:
                    time.sleep(0.15); mic.drain(); mic.muted.clear()
                continue

            reply = brain.respond(query, awaiting_followup=in_window)
            mic.muted.set()
            try:
                tts.say(reply)
            finally:
                time.sleep(0.15)   # let the tail of playback clear the room
                mic.drain(); mic.muted.clear()
            follow_until = time.time() + cfg.followup_window_s
            if args.once:
                break

    if ctrl is not None:
        ctrl.close()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
