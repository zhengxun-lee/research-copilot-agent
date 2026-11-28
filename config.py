"""Central configuration — all runtime settings are read from environment variables
with sensible defaults, so no config file is required.

Call :func:`validate_config` at startup to surface misconfiguration early."""

import os
import sys

# ---------------------------------------------------------------------------
# Shared env-var helpers (also used by api_config)
# ---------------------------------------------------------------------------

_KNOWN_RETRIEVAL_MODES = {"hybrid", "semantic", "vector", "keyword"}


def safe_str_env(var_name: str, default: str = "") -> str:
    value = os.getenv(var_name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def safe_int_env(var_name: str, default: int, min_value: int = 1) -> int:
    raw = os.getenv(var_name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(min_value, value)


def safe_bool_env(var_name: str, default: bool = False) -> bool:
    raw = os.getenv(var_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------

KNOWLEDGE_BASE_PATH = safe_str_env("KNOWLEDGE_BASE_PATH", "data/knowledge_base.json")

# Retrieval settings
RETRIEVAL_MODE = safe_str_env("RETRIEVAL_MODE", "keyword").lower()

RETRIEVAL_HYBRID_CANDIDATES = safe_int_env("RETRIEVAL_HYBRID_CANDIDATES", 12, min_value=1)
RETRIEVAL_ENABLE_EMBEDDING = safe_bool_env("RETRIEVAL_ENABLE_EMBEDDING", default=False)
RETRIEVAL_VECTOR_CANDIDATES = safe_int_env("RETRIEVAL_VECTOR_CANDIDATES", 48, min_value=1)
RETRIEVAL_VECTOR_BATCH_SIZE = safe_int_env("RETRIEVAL_VECTOR_BATCH_SIZE", 32, min_value=1)
RETRIEVAL_TOP_K = safe_int_env("RETRIEVAL_TOP_K", 3, min_value=1)
RETRIEVAL_NEIGHBORS = safe_int_env("RETRIEVAL_NEIGHBORS", 1, min_value=0)
MAX_STEPS = safe_int_env("MAX_STEPS", 5, min_value=1)

# Memory settings
MAX_MEMORY_TURNS = safe_int_env("MAX_MEMORY_TURNS", 10, min_value=1)

# Model routing settings
MODEL_ROUTER_ENABLED = safe_bool_env("MODEL_ROUTER_ENABLED", default=True)

# Web server settings
WEB_HOST = safe_str_env("WEB_HOST", "127.0.0.1")
WEB_PORT = safe_int_env("WEB_PORT", 7860, min_value=1)
WEB_CORS_ORIGIN = safe_str_env("WEB_CORS_ORIGIN", "")


def validate_config(quiet: bool = False) -> list[str]:
    """Validate critical configuration at startup.  Returns the list of issues.

    When ``quiet`` is False (the default for CLI/Web entry points), each issue
    is printed to stderr with an actionable hint so a first-time user knows
    exactly what to do.  When ``quiet`` is True (e.g. inside a test that has
    already stubbed config) the function stays silent.
    """
    from api_config import EMBEDDING_API_KEY, OPENAI_API_KEY  # deferred to avoid partial-init cycles

    issues = []
    hints = []

    if not OPENAI_API_KEY:
        msg = "OPENAI_API_KEY is not set"
        fix = "  → Set the environment variable, e.g.: export OPENAI_API_KEY=sk-..."
        issues.append(msg)
        hints.append(fix)
        if not quiet:
            print(f"[config] {msg}\n{fix}", file=sys.stderr)

    if RETRIEVAL_MODE not in _KNOWN_RETRIEVAL_MODES:
        msg = f"Unknown RETRIEVAL_MODE={RETRIEVAL_MODE!r}"
        fix = (
            f"  → Valid modes: {', '.join(sorted(_KNOWN_RETRIEVAL_MODES))}. "
            "Will fall back to 'keyword' at search time."
        )
        issues.append(msg)
        hints.append(fix)
        if not quiet:
            print(f"[config] {msg}\n{fix}", file=sys.stderr)

    if RETRIEVAL_ENABLE_EMBEDDING and RETRIEVAL_MODE in {"vector", "hybrid"}:
        if not EMBEDDING_API_KEY:
            msg = (
                f"RETRIEVAL_ENABLE_EMBEDDING=true and RETRIEVAL_MODE={RETRIEVAL_MODE}, "
                "but EMBEDDING_API_KEY is empty"
            )
            fix = (
                "  → Set EMBEDDING_API_KEY in config.yaml or environment, "
                "or set RETRIEVAL_ENABLE_EMBEDDING=false to use the local semantic retriever."
            )
            issues.append(msg)
            hints.append(fix)
            if not quiet:
                print(f"[config] {msg}\n{fix}", file=sys.stderr)

    if not issues and not quiet:
        print("[config] validation OK", file=sys.stderr)
    elif issues and not quiet:
        print(
            f"[config] {len(issues)} issue(s) found. The agent may not work until fixed:",
            file=sys.stderr,
        )
        for issue, hint in zip(issues, hints):
            print(f"  ✗ {issue}\n{hint}", file=sys.stderr)

    return issues


def print_config_summary() -> None:
    """Print a short human-readable summary of the active configuration.

    Used by the CLI ``/config`` command and the Web startup banner to give
    the user a quick "what is the system actually using" snapshot.
    """
    from api_config import (
        COMPLEX_MODEL_NAME,
        EMBEDDING_MODEL_NAME,
        MODEL_NAME,
        OPENAI_BASE_URL,
        SIMPLE_MODEL_NAME,
    )

    api_key_set = bool(os.environ.get("OPENAI_API_KEY"))
    print("[config summary]")
    print(f"  default model    : {MODEL_NAME}")
    print(f"  simple  route    : {SIMPLE_MODEL_NAME}")
    print(f"  complex route    : {COMPLEX_MODEL_NAME}")
    print(f"  embedding model  : {EMBEDDING_MODEL_NAME}")
    print(f"  base url         : {OPENAI_BASE_URL}")
    print(f"  api key set      : {'yes' if api_key_set else 'NO'}")
    print(f"  retrieval mode   : {RETRIEVAL_MODE}")
    print(f"  embedding on     : {RETRIEVAL_ENABLE_EMBEDDING}")
    print(f"  max steps        : {MAX_STEPS}")
    print(f"  memory turns     : {MAX_MEMORY_TURNS}")
    print(f"  knowledge base   : {KNOWLEDGE_BASE_PATH}")
