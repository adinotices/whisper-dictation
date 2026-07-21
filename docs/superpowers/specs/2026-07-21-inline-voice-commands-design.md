# Inline Voice Commands — Design

**Date:** 2026-07-21
**Status:** Approved (design)

## Problem

Dictation can only produce text; there is no way to insert line breaks or submit a
field by voice. The user wants to do this **inline, in a single utterance/key** —
partway through speaking say "new line" and get a line break, and end an utterance
with "enter" to submit — without a separate command mode.

## Key insight (resolves the "lost second half" concern)

Recording is one continuous capture; nothing is transcribed, parsed, or injected
until the key is released. So the **entire** transcript (all text + commands) is in
memory before any key is pressed. No spoken text is ever lost to a mid-utterance
key press. The only residual risk is a *submit* (Enter) in a submit-on-Enter field
(chat boxes) sending early — which we contain by design (below).

## Commands

| Spoken phrase        | Emits                       | Where allowed        |
|----------------------|-----------------------------|----------------------|
| "new line"           | Shift+Enter ×1              | anywhere, inline     |
| "new paragraph"      | Shift+Enter ×2              | anywhere, inline     |
| "enter" / "press enter" | Enter (true submit)      | **end of utterance only** |

- **Shift+Enter** inserts a *literal line break* in both editors and chat apps
  (Claude, Slack) and never submits — so inline "new line" is safe everywhere.
- **Enter** is a true submit. It is honored **only as the final word(s)** of the
  utterance, so there is never spoken text after a submit to lose. A mid-utterance
  "enter" is treated as the literal word.

## Approach

Rule-based, local, LLM-free parsing (snappy). A single transcript string is parsed
into an ordered list of actions: `("text", str)` and `("key", "enter"|"shift_enter")`.
The daemon injects each action in order, replacing today's single text injection.

## Components

### 1. Parser `parse_utterance(text) -> list[Action]` (`src/dictate/commands.py`)

- Word-tokenize. Match commands on a normalized form of each word
  (`word.strip(".,!?;:").lower()`) so Whisper's punctuation/casing doesn't block a
  match; text chunks preserve original words.
- **Trailing enter first:** if the last normalized word is `enter`, drop it; if the
  word before it is `press`, drop that too; remember to append an `("key","enter")`
  at the very end.
- **Inline scan** of the remaining words:
  - `new line` → flush current text buffer, emit `("key","shift_enter")`.
  - `new paragraph` → flush, emit `("key","shift_enter")` twice.
  - otherwise accumulate the original word into the text buffer.
- Flush joins buffered words with single spaces and strips; empty chunks are not
  emitted. Append the trailing Enter action last if flagged.
- `[("text", text)]` for a plain transcript with no commands.

### 2. Key injection `inject_key(key, method=None, runner=...)` (`src/dictate/inject.py`)

Maps `enter`→Return, `shift_enter`→Shift+Return. Tries `wtype` then `ydotool`
(clipboard cannot press keys). Commands:
- wtype: `wtype -k Return` / `wtype -M shift -k Return -m shift`
- ydotool: `ydotool key 28:1 28:0` / `ydotool key 42:1 28:1 28:0 42:0`

### 3. Config (`src/dictate/config.py`)

- `voice_commands: bool = True` — master toggle. Off → transcript injected verbatim.

### 4. Daemon wiring (`src/dictate/daemon.py`)

`_stop_and_transcribe`, after a non-empty transcript:
- If `voice_commands` off → today's single-injection path (with smart spacing).
- Else parse into actions and inject in order:
  - Apply smart-spacing boundary (`format_segment`) to the **first text action only**;
    inner text chunks (after a key press, i.e. a new line) inject as-is.
  - Text actions → `injector`; key actions → `key_injector`.
  - On any injection `RuntimeError`, notify and abort (leave boundary state
    untouched, as today).
- Update boundary state **after success**: if the last injected action was text, set
  `_last_text` to it; if it was a key (Enter/Shift+Enter), the field is now a new
  line or a fresh field, so **reset** `_last_text = ""`. Always stamp `_last_time`.

## Behaviour

```
"line one new line line two"          → "line one" [S-Enter] "line two"
"a paragraph new paragraph another"   → "a paragraph" [S-Enter][S-Enter] "another"
"send this press enter"               → "send this" [Enter]
"enter"                               → [Enter]
"no commands here"                    → "no commands here"   (unchanged)
```

## Tradeoff (accepted)

Literal dictation of the words "new line", "new paragraph", or a trailing "enter"
triggers the command. This is the intended one-key inline design; `voice_commands`
can be disabled for pure prose.

## Testing (TDD; keep the suite green)

- Parser: plain text unchanged; inline "new line" splits + shift_enter; "new
  paragraph" → two shift_enters; trailing "enter" and "press enter" → Enter; bare
  "enter" → Enter only; mid-utterance "enter" stays literal text; Whisper
  punctuation/casing around a command still matches ("New line." mid-sentence);
  disabled → single text action.
- inject_key: builds correct wtype/ydotool argv; falls back wtype→ydotool; raises
  when neither available.
- Daemon: multi-action sequence injects text and keys in order; smart spacing on
  first chunk only; boundary state resets after a trailing key; injection failure
  mid-sequence aborts and leaves state untouched; `voice_commands=false` injects raw.

## Out of scope

- Tab/backspace/other keys (can be added to the command table later).
- Reading the real field/cursor context (infeasible on Wayland).
- A separate/modal command mode.
