from __future__ import annotations

import logging
import re
import threading
from typing import Optional, Tuple

from api_config import (
    COMPLEX_MODEL_API_KEY,
    COMPLEX_MODEL_BASE_URL,
    COMPLEX_MODEL_NAME,
    MODEL_NAME,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    SIMPLE_MODEL_API_KEY,
    SIMPLE_MODEL_BASE_URL,
    SIMPLE_MODEL_NAME,
)
from config import MODEL_ROUTER_ENABLED
from routing.catalog import MODEL_ROUTE_SPECS
from routing.decision import ModelRouteDecision

logger = logging.getLogger(__name__)


class ComplexityModelRouter:
    """Route simple requests to a cheap model and complex requests to a stronger model."""

    DEFAULT_THRESHOLD = 0.22
    COMPLEX_KEYWORDS = {
        "architecture", "design", "implement", "implementation",
        "debug", "traceback", "refactor", "optimize", "benchmark", "evaluate",
        "compare", "tradeoff", "trade-off", "prove", "proof", "derive",
        "multi-step", "step by step", "root cause", "edge case", "test",
        "production", "pipeline", "strategy", "analysis", "analyze",
        "架构", "设计", "实现", "完整", "调试", "报错", "修复", "优化",
        "比较", "权衡", "证明", "推导", "多步", "根因", "边界情况",
        "测试", "方案", "落地", "详细分析", "评估", "重构",
    }
    SIMPLE_KEYWORDS = {
        "what is", "define", "explain briefly", "quickly", "short answer",
        "translate", "summarize briefly", "calculate", "一句话", "简单解释",
        "是什么", "定义", "翻译", "简短", "概括", "计算",
    }

    def __init__(
        self,
        enabled: bool = MODEL_ROUTER_ENABLED,
        simple_model: str = SIMPLE_MODEL_NAME,
        simple_api_key: str = SIMPLE_MODEL_API_KEY,
        simple_base_url: str = SIMPLE_MODEL_BASE_URL,
        complex_model: str = COMPLEX_MODEL_NAME,
        complex_api_key: str = COMPLEX_MODEL_API_KEY,
        complex_base_url: str = COMPLEX_MODEL_BASE_URL,
        default_model: str = MODEL_NAME,
        default_api_key: str = OPENAI_API_KEY,
        default_base_url: str = OPENAI_BASE_URL,
        threshold: float = DEFAULT_THRESHOLD,
    ):
        self.enabled = enabled
        self.simple_model = simple_model
        self.simple_api_key = simple_api_key
        self.simple_base_url = simple_base_url
        self.complex_model = complex_model
        self.complex_api_key = complex_api_key
        self.complex_base_url = complex_base_url
        self.default_model = default_model
        self.default_api_key = default_api_key
        self.default_base_url = default_base_url
        self.threshold = threshold
        self._semantic_router = None
        self._semantic_router_error: Optional[str] = None
        self._semantic_router_lock = threading.Lock()

    def route(self, text: str) -> ModelRouteDecision:
        if not self.enabled:
            return ModelRouteDecision(
                route_name="disabled",
                model_name=self.default_model,
                api_key=self.default_api_key,
                base_url=self.default_base_url,
                reason="model router disabled",
                enabled=False,
            )

        text = (text or "").strip()
        if not text:
            return self._decision("simple", 1.0, "empty input fallback")

        rule_route, rule_confidence, rule_reason = self._rule_route(text)
        if rule_route == "complex" and rule_confidence >= 0.75:
            return self._decision(rule_route, rule_confidence, rule_reason)

        semantic_route, semantic_confidence = self._semantic_route(text)
        if semantic_route and semantic_confidence >= self.threshold:
            return self._decision(
                semantic_route,
                semantic_confidence,
                "semantic-router route",
            )

        if rule_route:
            return self._decision(rule_route, rule_confidence, rule_reason)
        return self._decision("simple", 0.0, "default simple fallback")

    def _decision(
        self,
        route_name: str,
        confidence: float,
        reason: str,
    ) -> ModelRouteDecision:
        model, api_key, base_url = self._resolve_for_route(route_name)
        return ModelRouteDecision(
            route_name=route_name,
            model_name=model,
            api_key=api_key,
            base_url=base_url,
            confidence=confidence,
            reason=reason,
            enabled=self.enabled,
        )

    def _resolve_for_route(self, route_name: str) -> tuple[str, str, str]:
        """Return (model_name, api_key, base_url) for *route_name*."""
        attrs = {
            "complex": (self.complex_model, self.complex_api_key, self.complex_base_url),
            "simple":  (self.simple_model,  self.simple_api_key,  self.simple_base_url),
        }
        return attrs.get(route_name, (self.default_model, self.default_api_key, self.default_base_url))

    def _rule_route(self, text: str) -> Tuple[Optional[str], float, str]:
        lowered = text.lower()
        line_count = sum(1 for line in text.splitlines() if line.strip())
        has_code = bool(
            "```" in text
            or re.search(r"\b(class|def|async def|function)\s+\w+", lowered)
            or "traceback" in lowered
        )
        complex_hits = [kw for kw in self.COMPLEX_KEYWORDS if kw in lowered]
        simple_hits = [kw for kw in self.SIMPLE_KEYWORDS if kw in lowered]

        if has_code:
            return "complex", 0.95, "code or traceback detected"
        if len(text) >= 220 or line_count >= 6:
            return "complex", 0.9, "long or multi-line request"
        if len(complex_hits) >= 2:
            return "complex", 0.85, "multiple complex-task signals"
        if complex_hits and len(text) >= 90:
            return "complex", 0.8, "complex-task keyword with enough context"
        if self._looks_like_multi_part_request(text):
            return "complex", 0.78, "multi-part request"
        if simple_hits and len(text) <= 120 and not complex_hits:
            return "simple", 0.82, "simple-task keyword"
        if len(text) <= 80 and not complex_hits:
            return "simple", 0.65, "short request"
        return None, 0.0, ""

    def _looks_like_multi_part_request(self, text: str) -> bool:
        separators = ["，", ",", "；", ";", "然后", "并且", "同时", "and then"]
        return sum(1 for sep in separators if sep in text) >= 2

    def _semantic_route(self, text: str) -> Tuple[Optional[str], float]:
        router = self._get_semantic_router()
        if router is None:
            return None, 0.0
        try:
            choice = router(text)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("semantic-router model routing failed: %s", exc)
            return None, 0.0
        route_name = getattr(choice, "name", None)
        confidence = getattr(choice, "similarity_score", None) or 0.0
        if route_name not in {"simple", "complex"}:
            return None, 0.0
        return route_name, float(confidence)

    def _get_semantic_router(self):
        if self._semantic_router is not None or self._semantic_router_error is not None:
            return self._semantic_router
        with self._semantic_router_lock:
            # Double-check under lock — another thread may have initialized while we waited.
            if self._semantic_router is not None or self._semantic_router_error is not None:
                return self._semantic_router
            try:
                from routing.hash_encoder import HashingEncoder
                from semantic_router import Route, SemanticRouter

                router = SemanticRouter(
                    encoder=HashingEncoder(),
                    routes=[],
                    top_k=4,
                    aggregation="mean",
                )
                routes = [
                    Route(
                        name=spec.name,
                        utterances=spec.utterances,
                        description=spec.description,
                    )
                    for spec in MODEL_ROUTE_SPECS
                ]
                router.add(routes)
                self._semantic_router = router
            except Exception as exc:  # pragma: no cover - depends on optional package state
                self._semantic_router_error = str(exc)
                logger.warning("semantic-router unavailable, using rule router: %s", exc)
        return self._semantic_router
