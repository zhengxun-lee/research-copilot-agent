from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRouteDecision:
    """The result of routing a user question to a model profile.

    Attributes
    ----------
    route_name:
        ``"simple"``, ``"complex"``, or ``"disabled"``.
    model_name:
        The concrete model name to use for the LLM call.
    api_key:
        The API key for the selected profile.
    base_url:
        The base URL for the selected profile.
    confidence:
        Router confidence in [0, 1].
    reason:
        Human-readable explanation for the routing decision.
    enabled:
        ``False`` when the model router was disabled via config.
    """
    route_name: str
    model_name: str
    api_key: str = ""
    base_url: str = ""
    confidence: float = 0.0
    reason: str = ""
    enabled: bool = True
