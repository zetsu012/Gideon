"""Gideon daemon: mic -> VAD endpointing -> Whisper -> wake match -> Piper."""
from __future__ import annotations
import argparse, collections, json, logging, shutil, signal, socket, sys, tempfile, time
from pathlib import Path
import numpy as np

from .core.config import Config
from .core import state as st
from .core.state import StatusBus
from .audio.capture import Microphone
from .speech.vad import VAD
from .speech.stt import STT
from .speech.tts import TTS
from .nlu import wake
from .ipc.control import Control, send as control_send, status as control_status
from .nlu.brain import Brain
from .llm.client import LLM

log = logging.getLogger("gideon")
_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    log.info("signal %s received, shutting down", signum)


def segments(mic: Microphone, vad: VAD, cfg: Config, on_speech=None):
    """Yield float32 utterances delimited by silence.

    `on_speech(True)` fires the moment VAD opens a segment and `on_speech(False)`
    when it closes. The UI needs that leading edge: an indicator that only lit up
    after the sentence ended would always be one beat behind the speaker.
    """
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
                if on_speech is not None:
                    on_speech(True)
                buf = list(pre_roll)
                silence_run = 0
            continue

        buf.append(frame)
        silence_run = 0 if voiced else silence_run + 1
        if silence_run >= end_frames or len(buf) >= max_frames:
            audio = np.concatenate(buf)
            active, speech_run, buf = False, 0, []
            if on_speech is not None:
                on_speech(False)
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
    ap.add_argument("--ui", nargs=argparse.REMAINDER,
                    help="start the tray indicator (remaining args go to it)")
    ap.add_argument("--setup-key", action="store_true", dest="setup_key",
                    help="wire up a keyboard key as push-to-talk, nothing else")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    cfg = Config.load()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s", stream=sys.stderr)

    # The indicator is a separate process on the system python and needs no
    # models, so it short-circuits everything below.
    if args.ui is not None:
        from .cli import ui as ui_mod
        return ui_mod.launch(args.ui)

    # Setup runs before the model check: diagnosing a broken install is exactly
    # what it is for, so it must not be blocked by one.
    if args.setup or args.setup_key:
        from .cli import setup as setup_mod
        return setup_mod.setup(cfg) if args.setup else setup_mod.setup_key(cfg)

    # Everything below reports into the bus; the tray icon and HUD are a view
    # of it. Built first so even a failure during model loading is visible.
    bus = StatusBus()
    bus.start()

    missing = [p for p in (cfg.vad_path, cfg.voice_path, cfg.whisper_dir) if not p.exists()]
    for path in (cfg.vad_path, cfg.voice_path, cfg.whisper_dir):
        if not path.exists():
            log.error("missing model: %s", path)
    if missing:
        return 2

    tts = TTS(cfg.voice_path, cfg.output_device)
    bus.health_set("tts", True, f"piper {cfg.voice}")
    if args.say:
        tts.say(args.say)
        return 0

    stt = STT(cfg.whisper_dir, cfg.whisper_compute, cfg.whisper_threads)
    vad = VAD(cfg.vad_path, cfg.sample_rate)
    bus.health_set("vad", True, "silero v4")
    t0 = time.time()
    stt.warm()
    log.info("models ready in %.1fs", time.time() - t0)
    bus.health_set("stt", True, f"whisper {cfg.whisper_model} ({cfg.whisper_compute})")

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
        probe_bus = StatusBus()
        # A scratch path, never the real one: --selftest must be safe to run
        # while the daemon is up, and binding the live socket would hijack it.
        probe_path = Path(tempfile.mkdtemp(prefix="gideon-selftest-")) / "control.sock"
        probe_sock = Control(path=probe_path, window_s=5.0, bus=probe_bus)
        assert probe_sock.start(), "control socket failed to bind"
        try:
            assert control_send(path=probe_sock.path), "control socket did not answer"
            assert probe_sock.consume(), "wake did not arm the daemon"
            assert not probe_sock.consume(), "arm was not one-shot"
            # The tray and the HUD are only ever as truthful as this feed, so
            # the selftest proves the whole path: a state change made on the
            # pipeline's side must arrive as JSON on a subscriber's socket.
            snap = control_status(path=probe_sock.path)
            assert snap and snap["health"]["control"]["ok"], "status query failed"
            feed = socket.socket(socket.AF_UNIX)
            feed.settimeout(3.0)
            feed.connect(str(probe_sock.path))
            feed.sendall(b"subscribe\n")
            lines = feed.makefile("rb")
            assert json.loads(lines.readline())["type"] == "status", "no initial snapshot"
            probe_bus.set_state(st.LISTENING)
            pushed = json.loads(lines.readline())
            assert pushed["state"] == st.LISTENING, pushed
            feed.close()
            # A second daemon must decline the socket AND leave it alone: the
            # loser unlinking it on exit would strand the running daemon with a
            # socket no key, tray or setup check could ever reach again.
            loser = Control(path=probe_path, window_s=5.0)
            assert not loser.start(), "a second daemon took over a live socket"
            loser.close()
            assert probe_path.exists(), "a second daemon deleted the live socket"
            assert control_send("ping", path=probe_path), "the owner stopped answering"
        finally:
            probe_sock.close()
            probe_bus.close()
            shutil.rmtree(probe_path.parent, ignore_errors=True)
        log.info("control socket + status feed OK (%s)", probe_sock.path)

        pcm, sr = tts.synth("Self test passed.")
        log.info("selftest OK (vad+stt+tts+router loaded, %d samples @ %d Hz synthesised)",
                 len(pcm), sr)
        return 0

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    llm = LLM(cfg.llm_url, cfg.llm_model, cfg.llm_timeout) if cfg.llm_enabled else None
    if llm is None:
        bus.health_set("llm", True, "disabled in config - canned replies")
    elif llm.available():
        log.info("local LLM ready: %s", cfg.llm_model)
        bus.health_set("llm", True, f"ollama {cfg.llm_model}")
    else:
        # Not an error: a missing Ollama is a supported configuration. It is
        # still worth showing, because "why are the answers canned" is exactly
        # the question the health panel exists to answer.
        bus.health_set("llm", False, f"ollama unreachable at {cfg.llm_url} - canned replies")
    brain = Brain(llm)

    # A push-to-talk key talks to this socket, and so does the tray UI; without
    # it the daemon is exactly as it was, wake-phrase only and invisible.
    ctrl = Control(window_s=cfg.hotkey_window_s, bus=bus) if cfg.control_socket else None
    if ctrl is not None:
        ctrl.start()
    else:
        bus.health_set("control", False, "disabled in config (control_socket = false)")

    with Microphone(cfg.sample_rate, cfg.frame, cfg.input_device) as mic:
        bus.health_set("mic", True, f"{cfg.input_device or 'default device'} "
                                    f"@ {cfg.sample_rate} Hz")
        if cfg.speak_greeting_on_start:
            mic.muted.set(); tts.say("Gideon is online."); mic.drain(); mic.muted.clear()
        log.info("listening for %r", cfg.wake_phrases[0])

        # After a reply Gideon stays open for a follow-up, so a conversation does
        # not require repeating the wake phrase for every single sentence.
        follow_until = 0.0

        bus.set_state(st.IDLE)

        def on_speech(active: bool) -> None:
            # Only leave the resting state; whether the daemon returns to idle
            # or to the follow-up window is decided below, once the transcript
            # says what this utterance actually was.
            if active:
                bus.set_state(st.LISTENING)
            elif bus.state == st.LISTENING:
                bus.set_state(st.THINKING)

        for audio in segments(mic, vad, cfg, on_speech):
            t = time.time()
            text = stt.transcribe(audio)
            resting = st.FOLLOWUP if time.time() < follow_until else st.IDLE
            if not text:
                bus.set_state(resting)
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
                bus.heard(text, "ignored")
                bus.set_state(resting)
                continue

            kind = ("key" if keyed and not matched else
                    "follow" if (in_window and not matched) else "wake")
            log.info("[%.2fs] %s %r", time.time() - t, kind.upper(), text)
            bus.heard(text, kind)

            if query.strip().lower() in ("stop", "never mind", "nevermind",
                                         "cancel", "that's all", "thanks"):
                follow_until = 0.0
                if llm is not None:
                    llm.reset()
                bus.windows(follow_until=0.0)
                bus.set_state(st.SPEAKING)
                bus.spoke("Okay.")
                mic.muted.set()
                try: tts.say("Okay.")
                finally:
                    time.sleep(0.15); mic.drain(); mic.muted.clear()
                bus.set_state(st.IDLE)
                continue

            bus.set_state(st.THINKING)
            reply = brain.respond(query, awaiting_followup=in_window)
            bus.spoke(reply)
            bus.set_state(st.SPEAKING)
            mic.muted.set()
            try:
                tts.say(reply)
            finally:
                time.sleep(0.15)   # let the tail of playback clear the room
                mic.drain(); mic.muted.clear()
            follow_until = time.time() + cfg.followup_window_s
            # Order matters: publish the deadline before the state, or the bus
            # ticker can see FOLLOWUP with a stale (already expired) deadline
            # and snap it straight back to idle.
            bus.windows(follow_until=follow_until)
            bus.set_state(st.FOLLOWUP)
            if args.once:
                break

    if ctrl is not None:
        ctrl.close()
    bus.close()
    log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
