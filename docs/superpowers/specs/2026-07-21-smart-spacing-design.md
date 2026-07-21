# Smart Dictation Boundaries — Design

**Date:** 2026-07-21
**Status:** Approved (design)

## Problem

Each dictation is transcribed and injected independently with no leading/trailing
space, so back-to-back dictations collide: `"…sentence."` + `"and…"` →
`"…sentence.and…"`. Reading the character before the cursor to fix this is not
reliably possible on Wayland (no universal API; AT-SPI fails in terminals/browsers;
clipboard hacks are destructive). Instead, the daemon manages spacing from **its
own** previous output.

## Approach

The daemon remembers the text it last injected and when. Before injecting a new
dictation it inserts a separating space and (when the previous chunk ended a
sentence) capitalizes the new first letter. State is dropped after an idle timeout,
so a quick sequence of dictations is treated as continuous, while a dictation after
a long gap starts fresh.

## Components

### 1. Pure function `format_segment(new_text, prev_text)` (`src/dictate/textproc.py`)

- `prev_text` empty → return `new_text` unchanged (first dictation / fresh start;
  no stray leading space at the beginning).
- else: `sep = "" if prev_text[-1].isspace() else " "`; if `prev_text.rstrip()`
  ends with `.`, `!`, or `?`, capitalize `new_text`'s first character; return
  `sep + new_text`.

### 2. Config (`src/dictate/config.py`)

- `smart_spacing: bool = True` — master toggle.
- `smart_spacing_reset_seconds: int = 30` — idle window after which remembered
  state is dropped.

### 3. Daemon wiring (`src/dictate/daemon.py`)

- `DictationDaemon.__init__` gains `clock=time.monotonic` (injectable for tests)
  and state `self._last_text = ""`, `self._last_time = 0.0`.
- In `_stop_and_transcribe`, after a non-empty transcript and **before** injection,
  compute the effective previous text: `""` if `smart_spacing` is off, or if the
  idle window elapsed (`clock() - _last_time > reset_seconds`); otherwise
  `_last_text`. Inject `format_segment(text, effective_prev)`.
- Update `_last_text` and `_last_time` **only after a successful injection** (so
  "no speech" and failed injections never corrupt the boundary state).

## Behaviour

```
"hello world"   → "hello world"     (first: unchanged)
"this is next." → " this is next."  (space added)
"and more"      → " And more"       (space + capital; prev ended ".")
```
→ `hello world this is next. And more`

A dictation more than `smart_spacing_reset_seconds` after the previous one is
treated as a fresh start (no leading space, no forced capital).

## Limitation

State tracks the daemon's own output, not the actual field. Dictating into a
different field within the idle window can add a stray leading space or one
unexpected capital — never a missing space. The idle reset bounds this to rapid
field-switching only.

## Testing (TDD; keep the suite green)

- `format_segment`: first-chunk unchanged; space inserted mid-word; capital after
  `. ! ?`; no capital after non-terminal char; no double space when prev ends in
  space.
- Daemon: two sequential `toggle`s inject the second with a leading space;
  capitalization after a sentence; idle beyond the reset window starts fresh
  (fake clock); `smart_spacing = false` injects raw; state not updated on empty
  transcript or injection failure.

## Out of scope

- Reading the real cursor/field context (infeasible on Wayland).
- Grammar beyond inter-segment spacing + sentence-start capitalization.
