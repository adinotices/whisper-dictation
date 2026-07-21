from dictate.commands import parse_utterance


def test_plain_text_is_single_text_action():
    assert parse_utterance("hello there") == [("text", "hello there")]


def test_inline_new_line_splits_and_emits_shift_enter():
    assert parse_utterance("line one new line line two") == [
        ("text", "line one"),
        ("key", "shift_enter"),
        ("text", "line two"),
    ]


def test_new_paragraph_emits_two_shift_enters():
    assert parse_utterance("a paragraph new paragraph another") == [
        ("text", "a paragraph"),
        ("key", "shift_enter"),
        ("key", "shift_enter"),
        ("text", "another"),
    ]


def test_trailing_enter_submits():
    assert parse_utterance("send this press enter") == [
        ("text", "send this"),
        ("key", "enter"),
    ]


def test_trailing_bare_enter_submits():
    assert parse_utterance("send this enter") == [
        ("text", "send this"),
        ("key", "enter"),
    ]


def test_bare_enter_only_is_just_the_key():
    assert parse_utterance("enter") == [("key", "enter")]


def test_mid_utterance_enter_stays_literal():
    # "enter" not at the end is treated as ordinary text, never a submit.
    assert parse_utterance("press enter to continue") == [
        ("text", "press enter to continue"),
    ]


def test_whisper_punctuation_and_casing_around_command_still_matches():
    # Whisper renders spoken "new line" mid-sentence with caps/periods.
    assert parse_utterance("Line one. New line. Line two.") == [
        ("text", "Line one."),
        ("key", "shift_enter"),
        ("text", "Line two."),
    ]


def test_leading_new_line_has_no_empty_text_chunk():
    assert parse_utterance("new line hello") == [
        ("key", "shift_enter"),
        ("text", "hello"),
    ]


def test_new_line_then_trailing_enter():
    assert parse_utterance("hello new line world enter") == [
        ("text", "hello"),
        ("key", "shift_enter"),
        ("text", "world"),
        ("key", "enter"),
    ]
