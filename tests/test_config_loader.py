"""Test the config-loader env-var resolution logic, especially the edge cases
that previously caused unresolved references to become literal strings."""

import os

from config_loader import _BARE_ENV_RE, _ENV_REF_RE, _resolve_env_vars


def test_resolves_dollar_brace_reference():
    os.environ["TEST_VAR_A"] = "resolved-value"
    try:
        result = _resolve_env_vars("${TEST_VAR_A}")
        assert result == "resolved-value"
    finally:
        del os.environ["TEST_VAR_A"]


def test_returns_empty_for_unresolved_dollar_brace_reference():
    assert "NONEXISTENT_VAR_XYZ" not in os.environ
    result = _resolve_env_vars("${NONEXISTENT_VAR_XYZ}")
    assert result == "", f"Expected '' but got {result!r}"


def test_resolves_bare_env_var_name():
    os.environ["TEST_VAR_B"] = "bare-value"
    try:
        result = _resolve_env_vars("TEST_VAR_B")
        assert result == "bare-value"
    finally:
        del os.environ["TEST_VAR_B"]


def test_returns_empty_for_unresolved_bare_env_var_name():
    assert "NONEXISTENT_BARE_VAR" not in os.environ
    result = _resolve_env_vars("NONEXISTENT_BARE_VAR")
    assert result == "", f"Expected '' but got {result!r}"


def test_passes_through_literal_values():
    result = _resolve_env_vars("deepseek-chat")
    assert result == "deepseek-chat"


def test_passes_through_yaml_boolean_strings():
    assert _resolve_env_vars("False") == "False"
    assert _resolve_env_vars("True") == "True"


def test_passes_through_numeric_values():
    assert _resolve_env_vars("12") == "12"
    assert _resolve_env_vars("0") == "0"


def test_does_not_match_lowercase_bare_words():
    result = _resolve_env_vars("simple")
    assert result == "simple"


def test_handles_mixed_dollar_brace_and_literal():
    os.environ["TEST_MIXED"] = "middle"
    try:
        result = _resolve_env_vars("prefix-${TEST_MIXED}-suffix")
        assert result == "prefix-middle-suffix"
    finally:
        del os.environ["TEST_MIXED"]


def test_mixed_reference_returns_empty_for_missing_var():
    assert "NONEXISTENT_MIXED" not in os.environ
    result = _resolve_env_vars("prefix-${NONEXISTENT_MIXED}-suffix")
    assert result == "prefix--suffix"


def test_bare_env_re_matches_typical_names():
    assert _BARE_ENV_RE.match("OPENAI_API_KEY")
    assert _BARE_ENV_RE.match("MODEL_NAME")
    assert _BARE_ENV_RE.match("MAX_STEPS")


def test_bare_env_re_rejects_lowercase():
    assert not _BARE_ENV_RE.match("simple")
    assert not _BARE_ENV_RE.match("false")


def test_bare_env_re_rejects_dollar_brace():
    assert not _BARE_ENV_RE.match("${OPENAI_API_KEY}")


def test_dollar_brace_re_matches_references():
    assert _ENV_REF_RE.search("prefix${VAR_NAME}suffix")
    assert _ENV_REF_RE.search("${ONLY_BRACED}")


def test_dollar_brace_re_does_not_match_bare():
    assert not _ENV_REF_RE.search("OPENAI_API_KEY")


def test_project_configuration_applies_optional_local_override(tmp_path, monkeypatch):
    from config_loader import load_project_config
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('WEB_PORT', raising=False)
    (tmp_path / 'config.yaml').write_text('api:\n  api_key: "${OPENAI_API_KEY}"\nweb:\n  port: 7860\n')
    (tmp_path / 'config.local.yaml').write_text('api:\n  api_key: "unit-local-key"\nweb:\n  port: 9876\n')
    load_project_config(tmp_path)
    assert os.environ['OPENAI_API_KEY'] == 'unit-local-key'
    assert os.environ['WEB_PORT'] == '9876'


def test_project_configuration_without_local_file_uses_environment(tmp_path, monkeypatch):
    from config_loader import load_project_config
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-env-key')
    (tmp_path / 'config.yaml').write_text('api:\n  api_key: "${OPENAI_API_KEY}"\n')
    load_project_config(tmp_path)
    assert os.environ['OPENAI_API_KEY'] == 'unit-env-key'


def test_gui_profile_values_are_literal_not_environment_references(tmp_path, monkeypatch):
    from config_loader import load_project_config
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('MODEL_NAME', '')
    monkeypatch.setenv('OPENAI_API_KEY_MODE', '')
    monkeypatch.delenv('UNIT_LITERAL_KEY', raising=False)
    (tmp_path / 'config.yaml').write_text('api: {}')
    (tmp_path / 'config.local.yaml').write_text('api:\n  api_key_mode: set\n  api_key: UNIT_LITERAL_KEY\n  model_name: UPPERCASE_MODEL\n')
    load_project_config(tmp_path)
    assert os.environ['OPENAI_API_KEY'] == 'UNIT_LITERAL_KEY'
    assert os.environ['MODEL_NAME'] == 'UPPERCASE_MODEL'
