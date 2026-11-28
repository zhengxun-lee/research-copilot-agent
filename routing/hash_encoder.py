import math
from typing import List

from retrievers.utils import hash_token_index, hash_token_sign, tokenize


class HashingEncoder:
    """Dependency-free dense encoder used to keep semantic-router local and cheap."""

    def __init__(self, dimensions: int = 384):
        self.name = "research-copilot-hashing-encoder"
        self.type = "local_hash"
        self.dimensions = dimensions

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return tokenize(text)

    def _encode_one(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        tokens = self._tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            vector[hash_token_index(token, self.dimensions)] += hash_token_sign(token)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def __call__(self, docs: List[str]) -> List[List[float]]:
        return [self._encode_one(doc) for doc in docs]
