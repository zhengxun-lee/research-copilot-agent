"""Smoke tests for the new validate_config + print_config_summary outputs."""

import io
import sys
from pathlib import Path

import config as config_module
from config import print_config_summary, validate_config


def test_validate_config_quiet_returns_issues(capsys):
    """``quiet=True`` should suppress stderr noise while still returning issues."""
    issues = validate_config(quiet=True)
    # May or may not have issues depending on environment; just check the contract.
    assert isinstance(issues, list)


def test_validate_config_prints_to_stderr_when_missing_api_key(monkeypatch, capsys):
    """Missing OPENAI_API_KEY should be reported with an actionable hint."""
    import api_config

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(api_config, "OPENAI_API_KEY", "", raising=False)
    issues = validate_config(quiet=False)
    captured = capsys.readouterr()
    assert "OPENAI_API_KEY" in captured.err
    assert issues
    assert any("OPENAI_API_KEY" in issue for issue in issues)


def test_validate_config_reports_unknown_retrieval_mode(monkeypatch, capsys):
    monkeypatch.setattr(config_module, "RETRIEVAL_MODE", "magic", raising=False)
    issues = validate_config(quiet=False)
    captured = capsys.readouterr()
    assert "magic" in captured.err
    assert "keyword" in captured.err  # mention of valid fallback
    assert any("retrieval" in issue.lower() for issue in issues)


def test_print_config_summary_runs_without_error(capsys):
    """print_config_summary must never raise — it pulls from live config."""
    print_config_summary()
    captured = capsys.readouterr()
    assert "config summary" in captured.out.lower()
    assert "default model" in captured.out.lower()
    assert "knowledge base" in captured.out.lower()
