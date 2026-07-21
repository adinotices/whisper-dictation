"""Rule-based, LLM-free parsing of a dictation transcript into an ordered list
of actions: ``("text", str)`` and ``("key", "enter" | "shift_enter")``.

Recording is one continuous capture, so the whole transcript is known before any
key is pressed — no spoken text can be lost to a mid-utterance key. A true submit
("enter") is therefore only honored as the final word(s) of the utterance.
"""

Action = tuple[str, str]

_PUNCT = ".,!?;:"


def _norm(word: str) -> str:
    return word.strip(_PUNCT).lower()


def parse_utterance(text: str) -> list[Action]:
    words = text.split()
    if not words:
        return []

    # Peel a trailing "enter" / "press enter" off the end first, so a submit can
    # only ever be the last action and never strand spoken text after it.
    trailing_enter = False
    if words and _norm(words[-1]) == "enter":
        words = words[:-1]
        if words and _norm(words[-1]) == "press":
            words = words[:-1]
        trailing_enter = True

    actions: list[Action] = []
    buffer: list[str] = []

    def flush() -> None:
        chunk = " ".join(buffer).strip()
        if chunk:
            actions.append(("text", chunk))
        buffer.clear()

    i = 0
    while i < len(words):
        cur = _norm(words[i])
        nxt = _norm(words[i + 1]) if i + 1 < len(words) else ""
        if cur == "new" and nxt == "line":
            flush()
            actions.append(("key", "shift_enter"))
            i += 2
            continue
        if cur == "new" and nxt == "paragraph":
            flush()
            actions.append(("key", "shift_enter"))
            actions.append(("key", "shift_enter"))
            i += 2
            continue
        buffer.append(words[i])
        i += 1
    flush()

    if trailing_enter:
        actions.append(("key", "enter"))
    return actions
