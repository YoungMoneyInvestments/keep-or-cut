"""Judge verdict parsing — truncated JSON must not zero the board."""
from keep_or_cut.judge import _parse_verdict


def test_parse_complete_json():
    score, reason = _parse_verdict('{"score": 8, "reasoning": "solid answer"}')
    assert score == 8
    assert "solid" in reason


def test_parse_score_only_json():
    score, reason = _parse_verdict('{"score": 7}')
    assert score == 7


def test_parse_truncated_reasoning():
    # Matches live failure: score present, reasoning string cut mid-way.
    text = '{"score": 6, "reasoning": "It correctly captures all four transcript points with accurate timestamps in a skimmable heading/bullet format, but it invents an unsupported specific ("If it worked Claude '
    score, reason = _parse_verdict(text)
    assert score == 6
    assert reason


def test_parse_garbage():
    score, reason = _parse_verdict("no json here")
    assert score == 0
    assert "unparseable" in reason
