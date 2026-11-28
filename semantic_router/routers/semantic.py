"""Semantic router implementation — cosine-similarity nearest-neighbour over utterance vectors."""

import math
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Union

from semantic_router.route import Route


@dataclass(frozen=True)
class RouteChoice:
    name: Optional[str] = None
    similarity_score: Optional[float] = None


class SemanticRouter:
    """Minimal semantic router used by the research copilot model router."""

    def __init__(
        self,
        encoder: Callable[[List[str]], List[List[float]]],
        routes: Optional[List[Route]] = None,
        top_k: int = 4,
        aggregation: str = "mean",
    ):
        if aggregation not in {"mean", "max", "sum"}:
            raise ValueError("aggregation must be one of: mean, max, sum")
        self.encoder = encoder
        self.routes: List[Route] = []
        self.top_k = max(1, top_k)
        self.aggregation = aggregation
        self._utterance_vectors: List[List[float]] = []
        self._utterance_routes: List[str] = []
        if routes:
            self.add(routes)

    def add(self, routes: Union[Route, Iterable[Route]]):
        if isinstance(routes, Route):
            routes = [routes]
        routes = list(routes)
        utterances: List[str] = []
        route_names: List[str] = []
        for route in routes:
            utterances.extend(route.utterances)
            route_names.extend([route.name] * len(route.utterances))
        if utterances:
            self._utterance_vectors.extend(self.encoder(utterances))
            self._utterance_routes.extend(route_names)
        self.routes.extend(routes)

    def __call__(self, text: str) -> RouteChoice:
        if not self._utterance_vectors or not text.strip():
            return RouteChoice()

        query_vectors = self.encoder([text])
        if not query_vectors:
            return RouteChoice()
        query_vector = query_vectors[0]
        ranked = sorted(
            (
                (route_name, self._cosine(query_vector, vector))
                for route_name, vector in zip(self._utterance_routes, self._utterance_vectors)
            ),
            key=lambda item: item[1],
            reverse=True,
        )[: self.top_k]

        route_scores: Dict[str, List[float]] = {}
        for route_name, score in ranked:
            route_scores.setdefault(route_name, []).append(score)
        if not route_scores:
            return RouteChoice()

        best_route, best_score = max(
            (
                (route_name, self._aggregate(scores))
                for route_name, scores in route_scores.items()
            ),
            key=lambda item: item[1],
        )
        route = self._route_by_name(best_route)
        if route and route.score_threshold is not None and best_score < route.score_threshold:
            return RouteChoice()
        return RouteChoice(name=best_route, similarity_score=best_score)

    def _aggregate(self, scores: List[float]) -> float:
        if self.aggregation == "max":
            return max(scores)
        if self.aggregation == "sum":
            return sum(scores)
        return sum(scores) / len(scores)

    def _route_by_name(self, name: str) -> Optional[Route]:
        for route in self.routes:
            if route.name == name:
                return route
        return None

    def _cosine(self, left: List[float], right: List[float]) -> float:
        # Vectors from encoders may not be normalized — compute full cosine.
        if not left or not right or len(left) != len(right):
            return 0.0
        numerator = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)
