from llm.client import LLMClient
from routing import ComplexityModelRouter


def test_semantic_router_imports_as_package():
    import semantic_router

    assert "SemanticRouter" in semantic_router.__all__


def test_model_router_sends_simple_question_to_small_model():
    router = ComplexityModelRouter(
        simple_model="cheap-model",
        simple_api_key="cheap-key",
        simple_base_url="https://cheap.example.com",
        complex_model="expensive-model",
    )

    decision = router.route("What is RAG?")

    assert decision.route_name == "simple"
    assert decision.model_name == "cheap-model"
    assert decision.api_key == "cheap-key"
    assert decision.base_url == "https://cheap.example.com"


def test_model_router_sends_complex_question_to_large_model():
    router = ComplexityModelRouter(
        simple_model="cheap-model",
        complex_model="expensive-model",
        complex_api_key="expensive-key",
        complex_base_url="https://expensive.example.com",
    )

    decision = router.route("帮我实现完整功能并补充测试，比较方案优缺点，然后给出落地计划。")

    assert decision.route_name == "complex"
    assert decision.model_name == "expensive-model"
    assert decision.api_key == "expensive-key"
    assert decision.base_url == "https://expensive.example.com"


def test_model_router_can_be_disabled():
    router = ComplexityModelRouter(
        enabled=False,
        simple_model="cheap-model",
        complex_model="expensive-model",
        default_model="base-model",
    )

    decision = router.route("帮我实现完整功能并补充测试。")

    assert decision.route_name == "disabled"
    assert decision.model_name == "base-model"
    assert decision.enabled is False


def test_llm_client_accepts_per_request_model():
    class FakeCompletions:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return "ok"

    class FakeClient:
        def __init__(self):
            self.chat = type("Chat", (), {})()
            self.chat.completions = FakeCompletions()

    fake_client = FakeClient()
    client = LLMClient(api_key="test-key", base_url="https://example.com")
    client._clients[("test-key", "https://example.com")] = fake_client

    result = client.chat(messages=[{"role": "user", "content": "hello"}], model_name="chosen-model")

    assert result == "ok"
    assert fake_client.chat.completions.kwargs["model"] == "chosen-model"


def test_llm_client_accepts_per_request_api_profile(monkeypatch):
    created = []

    class FakeCompletions:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return "ok"

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, max_retries=None):
            assert max_retries == 0
            self.api_key = api_key
            self.base_url = base_url
            self.chat = type("Chat", (), {})()
            self.chat.completions = FakeCompletions()
            created.append(self)

    monkeypatch.setattr("llm.client.OpenAI", FakeOpenAI)
    client = LLMClient(api_key="default-key", base_url="https://default.example.com")

    result = client.chat(
        messages=[{"role": "user", "content": "hello"}],
        model_name="chosen-model",
        api_key="route-key",
        base_url="https://route.example.com",
    )

    assert result == "ok"
    assert created[-1].api_key == "route-key"
    assert created[-1].base_url == "https://route.example.com"
    assert created[-1].chat.completions.kwargs["model"] == "chosen-model"


def test_llm_client_allows_route_profile_without_default_key(monkeypatch):
    created = []

    class FakeCompletions:
        def create(self, **kwargs):
            return kwargs["model"]

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None, max_retries=None):
            assert max_retries == 0
            self.api_key = api_key
            self.base_url = base_url
            self.chat = type("Chat", (), {})()
            self.chat.completions = FakeCompletions()
            created.append(self)

    monkeypatch.setattr("llm.client.OpenAI", FakeOpenAI)
    client = LLMClient(api_key="", base_url="https://default.example.com")

    result = client.chat(
        messages=[{"role": "user", "content": "hello"}],
        model_name="route-model",
        api_key="route-key",
        base_url="https://route.example.com",
    )

    assert result == "route-model"
    assert created[-1].api_key == "route-key"
