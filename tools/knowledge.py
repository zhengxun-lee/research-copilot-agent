from __future__ import annotations

from tools.base import BaseTool
from retrievers import search, format_results
from retrievers.loader import get_chunk_index
from config import RETRIEVAL_NEIGHBORS, RETRIEVAL_TOP_K


class KnowledgeSearchTool(BaseTool):
    retrieval_mode = None
    cost_per_call = 0.0
    side_effects = False
    idempotent = True
    name = "search_knowledge"
    description = "Search the local knowledge base for relevant information."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query for retrieving knowledge."
            },
            "top_k": {
                "type": "integer",
                "description": "Number of relevant chunks to retrieve.",
                "default": RETRIEVAL_TOP_K
            }
        },
        "required": ["query"]
    }

    def _attach_neighbor_context(self, results: list[dict], max_neighbors: int = 1) -> list[dict]:
        if not results or max_neighbors <= 0:
            return results
        by_chunk_id = get_chunk_index()
        enriched = []
        for result in results:
            item = dict(result["item"])
            prev_contents = []
            next_contents = []
            prev_id = item.get("prev_chunk_id")
            next_id = item.get("next_chunk_id")
            hops = 0
            while prev_id and hops < max_neighbors:
                prev_item = by_chunk_id.get(prev_id)
                if prev_item is None:
                    break
                prev_contents.append(prev_item.get("content", ""))
                prev_id = prev_item.get("prev_chunk_id")
                hops += 1
            hops = 0
            while next_id and hops < max_neighbors:
                next_item = by_chunk_id.get(next_id)
                if next_item is None:
                    break
                next_contents.append(next_item.get("content", ""))
                next_id = next_item.get("next_chunk_id")
                hops += 1
            prev_content = " ".join(reversed([c for c in prev_contents if c])).strip()
            next_content = " ".join([c for c in next_contents if c]).strip()
            if prev_content:
                item["prev_content"] = prev_content
            if next_content:
                item["next_content"] = next_content
            enriched.append({"item": item, "score": result["score"]})
        return enriched

    def run_strict(self, **kwargs):
        from agent.recovery import RuntimeFailure, ErrorKind
        query = kwargs.get('query', '')
        if not isinstance(query, str) or not query.strip():
            raise RuntimeFailure(ErrorKind.ARGUMENTS, 'query must be a non-empty string')
        top_k = kwargs.get('top_k', RETRIEVAL_TOP_K)
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise RuntimeFailure(ErrorKind.ARGUMENTS, 'top_k must be an integer')
        mode = kwargs.get('mode') or self.retrieval_mode
        results = search(query.strip(), top_k=min(10, max(1, top_k)), mode=mode)
        if not results:
            raise RuntimeFailure(ErrorKind.EMPTY, 'No knowledge matched this query')
        return format_results(self._attach_neighbor_context(results, RETRIEVAL_NEIGHBORS))

    def run(self, **kwargs) -> str:
        query = kwargs.get("query", "").strip()
        if not query:
            return "Error: 'query' is required."
        top_k = kwargs.get("top_k", RETRIEVAL_TOP_K)
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            return "Error: 'top_k' must be an integer."
        top_k = min(max(1, top_k), 10)
        try:
            results = search(query, top_k=top_k, mode=self.retrieval_mode)
        except FileNotFoundError:
            return "Knowledge base not found. Build it first with `python3 -m ingest`."
        except Exception as exc:
            return f"Error: failed to search knowledge base. {exc}"
        enriched_results = self._attach_neighbor_context(results, max_neighbors=RETRIEVAL_NEIGHBORS)
        return format_results(enriched_results)
