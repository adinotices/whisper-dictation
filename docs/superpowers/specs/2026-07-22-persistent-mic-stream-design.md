# Persistent Mic Stream — Design

**Date:** 2026-07-22
**Status:** Approved (design)

## Problem

Each `Recorder.start()` spawns a brand-new `pw-record` process. Measured directly
(`pw-record --verbose`, and separately by watching WAV file growth): the PipeWire
capture stream takes **~45–100ms** after process spawn to reach `streaming` state,
during which no audio is captured. Push-to-talk users start speaking the instant
they feel the key go down, so this window silently clips the start of speech —
confirmed as the cause of two observed incidents ("This is a test" → "s a test";
"this is a test" → "hissest").

Toggle mode (Super+D) is less affected in practice since users tend to glance for
the "🎙 Listening…" notification before speaking, but the underlying gap exists
there too.

## Approach

Stop spawning a process per recording. Keep **one `pw-record` process, opened
lazily on the first `start()` call, alive for the rest of the daemon's life**
(same "warm" philosophy already used for the Whisper model). It streams raw PCM
(`--raw -`, no WAV header) continuously to stdout. A background reader thread
drains stdout in a loop:

- While a recording is active: append chunks to an in-memory buffer.
- While idle: read and discard, so idle memory usage stays flat and the process
  never blocks on a full stdout pipe.

Because the stream negotiation (the ~50–100ms cost) only happens once per daemon
lifetime — at the first press — every subsequent press starts capturing with
**zero** startup latency: the stream is already in `streaming` state, we're just
flipping a flag on when to keep vs. drop incoming chunks.

User-accepted tradeoff (see prior discussion): the very first PTT press after a
daemon (re)start can still exhibit the original clipping, since that's when the
stream negotiation happens. All subsequent presses in that daemon's lifetime are
latency-free. The mic is inactive (process not spawned) until that first press —
it does not go "hot" merely because the daemon is running.

## Components (`src/dictate/audio.py`)

- `build_stream_cmd(mic_source) -> list[str]` — `pw-record --rate 16000 --channels 1
  --format s16 --raw -` (+ `--target` if set). Replaces `build_pw_record_cmd` (which
  wrote directly to a WAV file path — no longer used).
- `Recorder`:
  - `start(out_path)`: spawns the stream process on first call only (or after the
    previous one died); resets the buffer; sets `recording = True`.
  - `stop()`: sets `recording = False`, snapshots and clears the buffer, writes it
    to `out_path` as a proper WAV file (`wave` module: 1 channel, 16-bit, 16000 Hz).
    The stream process is **not** killed — it stays warm for the next `start()`.
  - Reader thread: `stdout.read(chunk_size)` in a loop; on EOF (process died) marks
    the recorder so the next `start()` respawns a fresh process instead of hanging
    forever on a dead stream.
  - A lock guards the buffer/flag since the reader thread and `start`/`stop` (called
    from the daemon's socket-handling thread) touch shared state concurrently.
- Daemon shutdown (`main()`'s existing `finally`/SIGTERM path) terminates the
  persistent process so it isn't orphaned when the daemon exits.

## Out of scope

- Eliminating the first-press latency entirely (would need waiting for the
  `--verbose` "streaming" marker before the daemon is considered ready, or
  spawning at daemon startup — user explicitly chose lazy warm-on-first-use).
- A ring-buffer pre-roll (unnecessary once the stream is persistent — there's no
  gap left to pre-roll across).

## Testing (TDD)

- `build_stream_cmd`: shape with/without `mic_source`.
- `Recorder`: first `start()` spawns exactly one process; a second `start()`/`stop()`
  cycle does **not** spawn a second process (reuses the warm stream); `stop()`
  writes exactly the bytes read while `recording` was true (chunks read before
  `start()` or after `stop()` are excluded); a dead stream (EOF from reader) is
  respawned on the next `start()`; `close()`/shutdown terminates the process.
