"""Smoke tests for the CLI ``/help``, ``/config``, ``/route`` commands.

These are tested by importing ``main`` and asserting that the helper
functions produce stable output.  The interactive readline loop is not
exercised here because it requires a TTY.
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest


def test_help_command_prints_command_list():
    from main import _print_help

    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_help()
    output = buf.getvalue()
    for cmd in ("/help", "/config", "/route", "/reset", "/quit"):
        assert cmd in output


def test_config_command_prints_active_settings(capsys):
    from main import _print_config

    _print_config()
    out = capsys.readouterr().out
    assert "config summary" in out
    assert "default model" in out
    assert "simple  route" in out
    assert "complex route" in out
    assert "api key set" in out


def test_route_command_handles_no_decision(capsys):
    """Without a prior run, /route should print a friendly hint."""
    from main import _print_route

    class _FakeAgent:
        last_route_decision = None

    _print_route(_FakeAgent())
    out = capsys.readouterr().out
    assert "尚无路由" in out or "no route" in out.lower()


def test_route_command_prints_decision(capsys):
    from main import _print_route
    from types import SimpleNamespace

    decision = SimpleNamespace(
        route_name="complex",
        model_name="deepseek-reasoner",
        reason="code or traceback detected",
        confidence=0.95,
        enabled=True,
    )

    class _FakeAgent:
        last_route_decision = decision

    _print_route(_FakeAgent())
    out = capsys.readouterr().out
    assert "complex" in out
    assert "deepseek-reasoner" in out
    assert "code or traceback" in out
    assert "0.950" in out


def test_print_banner_includes_model_info(capsys, monkeypatch):
    """The startup banner should always show the active model + route."""
    from main import _print_banner

    class _FakeAgent:
        class model_router:
            @staticmethod
            def route(_text):
                from types import SimpleNamespace
                return SimpleNamespace(
                    route_name="simple",
                    model_name="deepseek-chat",
                    base_url="https://api.deepseek.com",
                )

    _print_banner(_FakeAgent())
    out = capsys.readouterr().out
    assert "deepseek-chat" in out
    assert "simple" in out
