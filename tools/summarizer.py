from __future__ import annotations

from tools.base import BaseTool
from retrievers.utils import split_sentences, STOPWORDS, tokenize


class SummarizerTool(BaseTool):
    cost_per_call = 0.0
    side_effects = False
    idempotent = True
    name = "summarizer"
    description = "Summarize a given text into a shorter version."
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to summarize."
            },
            "max_sentences": {
                "type": "integer",
                "description": "Maximum number of sentences in the summary.",
                "default": 3
            }
        },
        "required": ["text"]
    }

    MAX_SENTENCES = 20

    # Scoring weight constants (exposed for tuning).
    POSITION_BONUS_FIRST = 0.15
    LENGTH_BONUS_MAX = 0.2
    LENGTH_BONUS_NORM = 200          # characters at which length bonus saturates
    DIVERSITY_BONUS_FACTOR = 0.1
    TAIL_PENALTY_THRESHOLD = 12      # characters below which a single-sentence tail is penalized
    TAIL_PENALTY_FACTOR = 0.15

    def run(self, **kwargs) -> str:
        text = kwargs.get("text", "").strip()
        max_sentences = kwargs.get("max_sentences", 3)

        if not text:
            return "Error: 'text' is required."

        if not isinstance(max_sentences, int) or isinstance(max_sentences, bool) or max_sentences <= 0:
            return "Error: 'max_sentences' must be a positive integer."

        max_sentences = min(max_sentences, self.MAX_SENTENCES)
        summary = self._summarize(text, max_sentences)
        return summary

    def _summarize(self, text: str, max_sentences: int) -> str:
        sentences = split_sentences(text)
        if not sentences:
            return "Error: no valid text to summarize."
        if len(sentences) <= max_sentences:
            return " ".join(sentences)
        sentence_scores = self._score_sentences(sentences)
        ranked = sorted(enumerate(sentence_scores), key=lambda x: x[1], reverse=True)[:max_sentences]
        top_indices = sorted(i for i, _ in ranked)
        return " ".join(sentences[i] for i in top_indices)

    def _score_sentences(self, sentences: list[str]) -> list[float]:
        global_freq: dict[str, int] = {}
        tokenized: list[list[str]] = []
        for sentence in sentences:
            tokens = [t for t in tokenize(sentence) if t not in STOPWORDS]
            tokenized.append(tokens)
            for token in tokens:
                global_freq[token] = global_freq.get(token, 0) + 1

        if not global_freq:
            return [1.0 for _ in sentences]

        # Normalise raw TF scores to [0, 1] so bonus terms have predictable weight.
        max_freq = max(global_freq.values())
        norm_freq = {token: count / max_freq for token, count in global_freq.items()}

        scores: list[float] = []
        total_sentences = len(sentences)
        for index, tokens in enumerate(tokenized):
            if not tokens:
                scores.append(self.DIVERSITY_BONUS_FACTOR)
                continue
            base = sum(norm_freq[token] for token in tokens) / len(tokens)
            position_bonus = self.POSITION_BONUS_FIRST if index == 0 else 0.0
            length_bonus = min(len(sentences[index]) / self.LENGTH_BONUS_NORM, self.LENGTH_BONUS_MAX)
            diversity_bonus = len(set(tokens)) / max(len(tokens), 1) * self.DIVERSITY_BONUS_FACTOR
            tail_penalty = (
                self.TAIL_PENALTY_FACTOR
                if index == total_sentences - 1 and len(sentences[index]) < self.TAIL_PENALTY_THRESHOLD
                else 0.0
            )
            scores.append(base + position_bonus + length_bonus + diversity_bonus - tail_penalty)
        return scores
