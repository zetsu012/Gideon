# `src/gideon/cli/enroll.py`

**`gideon --enroll`: records the owner's voiceprint.** Five varied phrases are read aloud,
each endpointed by the same Silero VAD the daemon uses, embedded with ECAPA-TDNN, and
averaged into `~/.config/gideon/voiceprint.npy`. Until this runs, `speech/speaker.py`
fails open and anybody can wake Gideon.

## Why the prompts are varied

A voiceprint built from one sentence repeated five times encodes that sentence as much as
the voice. The prompt list spans different vowels, a digit sequence and a long sentence on
purpose.

## The daemon owns the microphone

Enrolling while Gideon is running is impossible, not merely inadvisable: the daemon holds
the capture stream. That is detected up front with a control-socket ping and explained as
a three-line stop/enroll/start recipe, rather than surfacing as a PortAudio error.

## Outlier rejection

After averaging, any take scoring below 0.35 against the centroid is dropped and the count
is reported. That take is a cough, a clipped word, or somebody else in the room — averaging
it in would quietly widen the door for everyone. At least `MIN_ACCEPTED` (3) usable
recordings must survive, or nothing is written.

The final line prints the closest-match floor next to the configured accept threshold, so
a marginal enrollment is visible at the moment it happens rather than as mysterious
rejections a week later.

| | |
|---|---|
| Imports | `core/config`, `audio/capture`, `speech/vad`, `speech/speaker`, `ipc/control`, `__main__.segments` |
| Imported by | `__main__` (lazily, only for `--enroll`) |
| Writes | `~/.config/gideon/voiceprint.npy` |
| Exit codes | `0` written · `1` too few/inconsistent takes · `2` model missing or daemon running · `130` aborted |
