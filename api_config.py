"""Per-model API profiles — keys, base URLs, and model names for the simple,
complex, and embedding routes.  Every value can be set via environment variable."""

from config import safe_str_env
from model_settings import resolved_api_key


# Default chat model profile.
MODEL_NAME = safe_str_env("MODEL_NAME", "deepseek-chat")
OPENAI_API_KEY = resolved_api_key("OPENAI_API_KEY")
OPENAI_BASE_URL = safe_str_env("OPENAI_BASE_URL", "https://api.deepseek.com")

# Simple route: cheaper/smaller model profile.
SIMPLE_MODEL_NAME = safe_str_env("SIMPLE_MODEL_NAME", "deepseek-chat")
SIMPLE_MODEL_API_KEY = resolved_api_key("SIMPLE_MODEL_API_KEY", OPENAI_API_KEY)
SIMPLE_MODEL_BASE_URL = safe_str_env("SIMPLE_MODEL_BASE_URL", OPENAI_BASE_URL)

# Complex route: stronger/more expensive model profile.
COMPLEX_MODEL_NAME = safe_str_env("COMPLEX_MODEL_NAME", "deepseek-reasoner")
COMPLEX_MODEL_API_KEY = resolved_api_key("COMPLEX_MODEL_API_KEY", OPENAI_API_KEY)
COMPLEX_MODEL_BASE_URL = safe_str_env("COMPLEX_MODEL_BASE_URL", OPENAI_BASE_URL)

# Embedding profile used by optional vector retrieval.
# NOTE: EMBEDDING_API_KEY defaults to the empty string (not OPENAI_API_KEY)
# because the embedding provider is typically different from the chat provider
# (e.g. OpenAI for embeddings vs DeepSeek for chat).  Set it explicitly via
# the EMBEDDING_API_KEY env var or config.yaml's api.embedding.api_key.
EMBEDDING_MODEL_NAME = safe_str_env("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
EMBEDDING_API_KEY = resolved_api_key("EMBEDDING_API_KEY")
EMBEDDING_BASE_URL = safe_str_env("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
