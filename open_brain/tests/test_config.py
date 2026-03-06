"""Tests for config module."""

from open_brain import config


def test_dsn_reader():
    dsn = config.dsn("reader")
    assert "ob_reader" in dsn
    assert "open_brain_test" in dsn


def test_dsn_writer():
    dsn = config.dsn("writer")
    assert "ob_writer" in dsn


def test_estimate_tokens():
    assert config.estimate_tokens("hello world") == 2  # 2 * 1.3 = 2.6 -> int = 2
    assert config.estimate_tokens("one two three four five") == 6  # 5 * 1.3 = 6.5 -> 6


def test_agent_validation():
    # Dynamic agents: get_valid_agents returns list (may be empty if no projects registered)
    agents = config.get_valid_agents()
    assert isinstance(agents, list)
    # is_valid_agent accepts reasonable strings in open mode
    assert config.is_valid_agent("myagent")
    assert config.is_valid_agent("agent-1")
    assert not config.is_valid_agent("")
    assert not config.is_valid_agent("a" * 31)  # too long


def test_embedding_dimension():
    assert config.EMBEDDING_DIMENSION == 384
