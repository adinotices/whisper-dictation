_SENTENCE_END = ".!?"


def format_segment(new_text: str, prev_text: str) -> str:
    """Join a new dictation onto the daemon's previous output.

    - No previous text (first dictation / fresh start): return new_text unchanged,
      so there is never a stray leading space at the beginning.
    - Otherwise prepend a single separating space unless the previous output
      already ended in whitespace, and capitalize new_text's first character when
      the previous output ended a sentence (. ! ?).
    """
    if not prev_text:
        return new_text
    separator = "" if prev_text[-1].isspace() else " "
    stripped = prev_text.rstrip()
    if stripped and stripped[-1] in _SENTENCE_END:
        new_text = new_text[:1].upper() + new_text[1:]
    return separator + new_text
