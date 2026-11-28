"""Minimal local semantic router — no external dependencies, uses hash-based encoding."""

from semantic_router.route import Route
from semantic_router.routers import RouteChoice, SemanticRouter

__all__ = ["Route", "RouteChoice", "SemanticRouter"]
