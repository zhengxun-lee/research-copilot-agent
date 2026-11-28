"""Minimal YAML config loader — reads config.yaml and maps its values into
os.environ so the existing config.py / api_config.py modules work unchanged.

Imports nothing from the project, so it can be called before any config-backed
modules are evaluated."""

from __future__ import annotations

import os
import re
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# Map config.yaml dot-paths to environment variable names.
# Keys not in this table are silently ignored (forward-compatible).
_YAML_PATH_TO_ENV = {
    # ── API ───────────────────────────────────────────────────
    "api.model_name": "MODEL_NAME",
    "api.api_key": "OPENAI_API_KEY",
    "api.base_url": "OPENAI_BASE_URL",
    "api.simple.model_name": "SIMPLE_MODEL_NAME",
    "api.simple.api_key": "SIMPLE_MODEL_API_KEY",
    "api.simple.base_url": "SIMPLE_MODEL_BASE_URL",
    "api.complex.model_name": "COMPLEX_MODEL_NAME",
    "api.complex.api_key": "COMPLEX_MODEL_API_KEY",
    "api.complex.base_url": "COMPLEX_MODEL_BASE_URL",
    "api.embedding.model_name": "EMBEDDING_MODEL_NAME",
    "api.embedding.api_key": "EMBEDDING_API_KEY",
    "api.embedding.base_url": "EMBEDDING_BASE_URL",
    "api.api_key_mode": "OPENAI_API_KEY_MODE",
    "api.simple.api_key_mode": "SIMPLE_MODEL_API_KEY_MODE",
    "api.complex.api_key_mode": "COMPLEX_MODEL_API_KEY_MODE",
    "api.embedding.api_key_mode": "EMBEDDING_API_KEY_MODE",
    # ── Retrieval ─────────────────────────────────────────────
    "retrieval.mode": "RETRIEVAL_MODE",
    "retrieval.enable_embedding": "RETRIEVAL_ENABLE_EMBEDDING",
    "retrieval.hybrid_candidates": "RETRIEVAL_HYBRID_CANDIDATES",
    "retrieval.vector_candidates": "RETRIEVAL_VECTOR_CANDIDATES",
    "retrieval.vector_batch_size": "RETRIEVAL_VECTOR_BATCH_SIZE",
    "retrieval.top_k": "RETRIEVAL_TOP_K",
    "retrieval.neighbors": "RETRIEVAL_NEIGHBORS",
    # ── Agent ─────────────────────────────────────────────────
    "agent.max_steps": "MAX_STEPS",
    "agent.max_memory_turns": "MAX_MEMORY_TURNS",
    "agent.model_router_enabled": "MODEL_ROUTER_ENABLED",
    # ── Knowledge ─────────────────────────────────────────────
    "knowledge.base_path": "KNOWLEDGE_BASE_PATH",
    # ── Web ───────────────────────────────────────────────────
    "web.host": "WEB_HOST",
    "web.port": "WEB_PORT",
    "web.cors_origin": "WEB_CORS_ORIGIN",
}


def _flatten(data: dict, prefix: str = "") -> dict[str, object]:
    """Recursively flatten a nested dict into dot-separated keys."""
    result: dict[str, object] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, full_key))
        else:
            result[full_key] = value
    return result


_ENV_REF_RE = re.compile(r"\$\{([^}]+)\}")
_BARE_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")


def _resolve_env_vars(value: str) -> str:
    """Replace ``${VAR_NAME}`` or bare ``VAR_NAME`` with env-var values.

    Returns the empty string when *value* is clearly an env-var reference
    but the referenced variable does not exist.  This lets the caller treat
    the value as "not set" and fall back to application defaults.
    """

    # 1. ${VAR_NAME}
    def _replace(match: re.Match) -> str:
        varname = match.group(1)
        return os.environ.get(varname, "")

    resolved = _ENV_REF_RE.sub(_replace, value)
    # If the original value was a pure ${...} reference that resolved to
    # nothing, signal "not set" so callers don't inject a literal.
    if _ENV_REF_RE.fullmatch(value) and not resolved:
        return ""

    # 2. bare VAR_NAME (only if it looks like an env-var name and exists)
    resolved_stripped = resolved.strip()
    if _BARE_ENV_RE.match(resolved_stripped) and resolved_stripped in os.environ:
        return os.environ[resolved_stripped]
    # If the original value was a bare env-var name that doesn't exist,
    # signal "not set".
    if _BARE_ENV_RE.match(value.strip()):
        return ""

    return resolved


def load_config(path: Path) -> None:
    """Read *path* (YAML) and inject its values into os.environ.

    - Does nothing if the file is missing, unreadable, or invalid.
    - YAML values ALWAYS take precedence (this is the single config source).
    - Empty-string values are treated as "not set" — env var is *not*
      populated with an empty string.
    """
    if yaml is None:
        import sys

        print(
            "Warning: pyyaml is not installed — config.yaml will not be loaded.",
            file=sys.stderr,
        )
        return
    if not path.exists():
        import sys

        print(
            f"Warning: config file not found at {path} — using environment defaults.",
            file=sys.stderr,
        )
        return
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        import sys

        print(
            f"Warning: cannot read config file {path}: {exc}",
            file=sys.stderr,
        )
        return
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        import sys

        print(
            f"Warning: invalid YAML in config file {path} ({type(exc).__name__}); check formatting.",
            file=sys.stderr,
        )
        return
    if not isinstance(data, dict):
        import sys

        print(
            f"Warning: config file {path} does not contain a YAML mapping at the top level.",
            file=sys.stderr,
        )
        return

    flat = _flatten(data)
    for yaml_path, value in flat.items():
        env_name = _YAML_PATH_TO_ENV.get(yaml_path)
        if env_name is None:
            continue
        # YAML null → skip (treat as "use default").
        if value is None:
            continue
        str_value = str(value).strip()
        # Empty string means "use default" — don't pollute os.environ.
        if not str_value:
            continue
        # GUI-managed profiles store literal values, including uppercase model/key names.
        profile_path, _, field = yaml_path.rpartition(".")
        literal_profile = (
            profile_path == "api" or profile_path.startswith("api.")
        ) and flat.get(profile_path + ".api_key_mode") in {"set", "clear", "inherit"}
        if not (literal_profile and field in {"model_name", "base_url", "api_key"}):
            str_value = _resolve_env_vars(str_value)
        os.environ[env_name] = str_value


def load_project_config(root: Path) -> None:
    """Load the tracked defaults, then an optional private local override."""
    root = Path(root)
    load_config(root / "config.yaml")
    local = root / "config.local.yaml"
    if local.exists():
        load_config(local)
