# "Hey Gideon" often didn't wake him

*Fixed: 2026-08-29. Touches `src/gideon/nlu/wake.py`, `src/gideon/speech/stt.py`,
`src/gideon/core/config.py`, `packaging/config/config.toml`.*

## The symptom

You'd say "hey Gideon" and nothing would happen. Not every time — often enough to be
annoying, rarely enough that it was hard to pin down. Speaking more clearly didn't
reliably help.

## What was actually going on

Two separate problems, stacked on top of each other. That's why it felt random.

### Problem 1: Whisper writes down the wrong word

Gideon doesn't use a wake-word detector. He transcribes *everything* he hears into
text, then checks whether that text starts with "hey gideon". So the wake phrase is
only as good as the transcription.

And Whisper, the speech-to-text model, does not write "Gideon". It writes **"get in"**.
Consistently. At every model size — tiny, base, small. Making the model bigger does not
fix it.

Why? Whisper isn't just recognising sounds, it's also predicting *likely English*.
"Gideon" is a rare name. "Get in" is a common phrase. When the audio is ambiguous —
and a name it barely knows is always ambiguous — it picks the likelier words. It is
confidently writing down something you didn't say.

### Problem 2: the matcher compared spellings

The old code handled this with a hand-written list of every wrong transcription anyone
had personally run into:

```
"hey gideon", "hey get in", "hey guidion", "hey giddy on",
"hi gideon", "hi get in", "a gideon", "hey kidding", "hike it in"
```

Two things wrong with that.

**It only covers what you've already seen.** Whisper has effectively infinite ways to
mangle a rare name. Every new one meant discovering it, then adding it to the list by
hand. The list could never catch up.

**It compared letters, not sounds.** The matcher used `difflib`, which measures how
similar two strings *look*. But "sounds like Gideon" is the only thing that actually
matters here, and letter-similarity is a poor stand-in for it. Measured against
"hey gideon", with the cutoff set at 80%:

| What Whisper wrote | Letter similarity | Woke him up? |
|---|---|---|
| `hey gideon` | 100% | yes |
| `ok gideon` | 74% | **no** |
| `hey the on` | 70% | **no** |
| `hey good` | 67% | **no** |

Those bottom three are all recognisably *you saying his name*. The matcher threw them
out because the spellings didn't line up.

There was a third, quieter version of the same bug: the matcher only ever looked at the
first N words, where N was the word count of the phrase it was testing. "hey gideon" is
two words, so it only ever examined the first two words. But "hey giddy on" is three.
That mishearing could never match a two-word phrase — which is exactly why somebody had
to add "hey giddy on" to the list as its own entry.

## The fix: compare sounds instead

### The idea

Whisper's mistakes are not random. It substitutes a phrase built from **roughly the same
mouth movements**. And the mouth movements that carry a word are mostly the **consonants** —
vowels are the mushy, variable part, and they're what gets misheard.

So: throw the vowels away, and treat similar consonants as interchangeable. Whatever
survives is the word's *skeleton*.

### How it's built

Every consonant gets a number, and **consonants made the same way in your mouth get the
same number** (`nlu/wake.py`):

| Consonants | Number | Why they group |
|---|---|---|
| b f p v | 1 | all made with the lips |
| c g j k q s x z | 2 | all made at the back/middle |
| d t | 3 | same tongue position, one just voiced |
| l | 4 | |
| m n | 5 | both nasal |
| r | 6 | |
| h | 7 | |
| w y | 8 | |

Vowels get nothing at all — they're deleted.

So `"hey gideon"` becomes: `h`→7, `e`→gone, `y`→8, `g`→2, `i`→gone, `d`→3, `e`→gone,
`o`→gone, `n`→5.

**`78235`**

Now put the mishearings through the same grinder:

| What Whisper wrote | Skeleton |
|---|---|
| hey gideon | `78235` |
| hey get in | `78235` |
| hey guidion | `78235` |
| hey kidin | `78235` |
| hey kidding | `782352` |
| hey giddy on | `782385` |

They collapse onto the same string, or near enough. **The mishearings now match
automatically — nobody has to list them.** Including ones nobody has hit yet, which is
the real win.

### The guard that stops false alarms

There's an obvious hole. `"get in the car"` has that same consonant frame. So does
`"let me get in touch"`. Sound-matching on its own would have Gideon interrupting
ordinary conversation constantly.

So a candidate has to **open with a word that looks like a greeting** — "hey", "hi",
"ok", "a". "Get in the car" starts with "get", which isn't one, so it's rejected before
the skeleton is ever consulted.

This is load-bearing. If someone removes that guard because it looks redundant, Gideon
starts waking up at random.

### Picking the cutoff with measurements

The similarity cutoff was tested against 19 real ways the phrase gets transcribed and
19 ordinary sentences, rather than guessed:

| Cutoff | Missed wakes | False wakes |
|---|---|---|
| 0.80 | 0 / 19 | 3 / 19 — `they didn't say`, `a good idea`, `can you get me a coffee` |
| **0.84** | **1 / 19** (`hey the on`) | **0 / 19** |

0.84 is the setting. Losing `hey the on` — a badly degraded transcription — is the price
of never waking up during a normal conversation.

## The three smaller fixes that came with it

**Sliding window.** The matcher now checks windows of one word either side of the
expected length, so a three-word mishearing of a two-word phrase gets a fair test.

**Whisper is told the name exists.** `speech/stt.py` now passes `initial_prompt="Hey
Gideon."` and `hotwords="Gideon"`. This nudges the decoder to consider the rare name
instead of rewriting it. It doesn't solve the problem alone — the skeleton is still
doing the heavy lifting — but it's free at runtime and removes some mishearings at the
source.

**Bigger speech model.** The default went from `tiny.en` (the smallest Whisper there is,
39M parameters) to `base.en`. This is unrelated to the wake phrase — it's the fix for
"sometimes my words generally aren't picked up right", especially when you're quiet,
far from the mic, or there's background noise.

Measured on this machine, for 2 seconds of audio:

| Model | Time | Size |
|---|---|---|
| `tiny.en` | 0.22–0.26 s | 75 MB |
| `base.en` | 0.37–0.40 s | 141 MB |

About 0.15 s slower on a round trip that takes roughly 0.9 s.

## What this changed about the config

`wake_phrases` **means something different now.** It used to be a list of *mishearings
of the name*. It's now a list of *ways to address him*:

```toml
wake_phrases = ["hey gideon", "hi gideon", "ok gideon", "a gideon", "gideon"]
```

Nine entries became five, and the five are all things a person would actually say.

**If Gideon mishears his name in a new way, do not add it here** — that's the matcher's
job now, and if the matcher isn't catching it, adding a patch to this list hides a real
regression. Add an entry only for a genuinely new *greeting*.

## A trap that cost time

Changing the defaults in `core/config.py` had **no effect on the running Gideon**, and
the selftest failed in a way that made no sense.

The cause: `Config.load()` **does not merge config files**. It checks `$GIDEON_CONFIG`,
then `~/.config/gideon/config.toml`, then `/etc/gideon/config.toml`, and the *first file
that exists wins entirely*. A user config file existed and still had the old phrase list
and `tiny.en` in it, so it was the whole configuration — the new defaults were never
consulted.

**If you change a default and nothing happens, check `~/.config/gideon/config.toml`
first.** That file was updated as part of this fix. `/etc/gideon/config.toml` still holds
the old values; it's shadowed by the user file so it's harmless, but the two disagree.

## What stops this regressing

`gideon --selftest` now asserts three things:

- eight real mishearings (`hey get in`, `hey guidion`, `hey giddy on`, `hey kidin`,
  `hi get in`, `ok gideon`, `hey kidding`, `gideon`) **still wake him**
- six ordinary sentences (`get in the car`, `let me get in touch`, `they didn't say`,
  `a good idea`, `hey there how are you`, `what time is it`) **do not**
- the leftover text handed to the brain is clean — `"hey get in there"` yields the query
  `"there"`, not `"in there"`

That second list is the canary. If someone loosens the matcher or drops the greeting
guard, those are what break first, and nothing else in the daemon would notice Gideon
had started answering the room.

## Known limitation

`"hey kitten"` reduces to the same skeleton as `"hey gideon"`, so it would wake him.
Accepted on purpose: it's a rare thing to say, it still has to pass speaker verification,
and tightening the cutoff enough to exclude it also throws out real mishearings. It's
noted in the `wake.py` docstring so nobody "discovers" it later and over-corrects.

## The option we didn't take (yet)

Swapping Whisper for **NVIDIA Parakeet TDT 0.6B** was considered. It's attractive: there
are ONNX builds that need no PyTorch, so Gideon's "everything is vendored into the .deb"
rule would survive, and being a non-autoregressive model it has a much weaker pull toward
rewriting rare names into common phrases — which is the root cause here.

Deferred because it's a much larger model (a big .deb increase and unmeasured CPU
latency on an always-on daemon), and the cheap fixes above may well be enough. If it's
revisited, the swap is clean: `STT` only exposes `transcribe()` and `warm()`, so it's a
new class behind the same two methods plus a config key — the same shape as the
`llm/__init__.build()` provider factory.
