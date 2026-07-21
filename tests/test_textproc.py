from dictate.textproc import format_segment


def test_first_chunk_unchanged():
    assert format_segment("hello world", "") == "hello world"


def test_space_inserted_mid_word():
    assert format_segment("this is next.", "hello world") == " this is next."


def test_capital_after_sentence_end():
    assert format_segment("and more", "this is next.") == " And more"


def test_capital_after_question_and_exclamation():
    assert format_segment("yes", "really?") == " Yes"
    assert format_segment("go", "now!") == " Go"


def test_no_capital_after_non_terminal():
    assert format_segment("the store", "I went to the") == " the store"


def test_no_double_space_when_prev_ends_in_space():
    assert format_segment("more", "done. ") == "More"


def test_capitalizing_non_letter_start_is_noop():
    assert format_segment("42 apples", "count?") == " 42 apples"
