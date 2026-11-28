"""Bounded recovery policy shared by LLM, tools, and retrieval."""
import ast
from enum import Enum
import json
import re


class ErrorKind(str, Enum):
    TIMEOUT = 'timeout'
    RATE_LIMIT = 'rate_limit'
    TRANSIENT = 'transient_api'
    CONTEXT = 'context_overflow'
    ARGUMENTS = 'invalid_arguments'
    EMPTY = 'empty_retrieval'
    TOOL = 'tool_failure'
    PERMANENT = 'permanent'
    LOOP = 'tool_loop'


class RuntimeFailure(RuntimeError):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


def classify(error, operation='llm'):
    if isinstance(error, RuntimeFailure):
        return error.kind
    status = getattr(error, 'status_code', None)
    text = str(error).lower()
    if status == 429 or 'rate limit' in text or 'too many requests' in text:
        return ErrorKind.RATE_LIMIT
    if isinstance(error, TimeoutError) or 'timed out' in text or 'timeout' in text:
        return ErrorKind.TIMEOUT
    if any(word in text for word in ('context_length', 'context length', 'maximum context', 'too many tokens')):
        return ErrorKind.CONTEXT
    if isinstance(error, (TypeError, ValueError)) and operation == 'tool':
        return ErrorKind.ARGUMENTS
    if status in {500, 502, 503, 504} or any(word in text for word in (
            'connection reset', 'connection refused', 'connection error', 'server error', 'overloaded', 'service unavailable')):
        return ErrorKind.TRANSIENT
    return ErrorKind.TOOL if operation == 'tool' else ErrorKind.PERMANENT


def repair_json(raw):
    """Only safe syntax repair; never invent missing values."""
    if len(raw) > 100_000:
        return None
    text = re.sub(r',\s*([}\]])', r'\1', raw.strip())
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError, RecursionError):
            return None
    return value if isinstance(value, dict) else None


def correct_arguments(name, arguments):
    result = dict(arguments)
    if name == 'search_knowledge':
        if isinstance(result.get('query'), str):
            result['query'] = result['query'].strip()
        top_k = result.get('top_k')
        if isinstance(top_k, str) and top_k.strip().isdigit():
            result['top_k'] = min(10, max(1, int(top_k)))
    return result


def rewrite_query(query):
    # Deterministic broadening, preserving terms instead of hallucinating synonyms.
    terms = re.findall(r'[\w\u4e00-\u9fff]+', query)
    stopwords = {'please', 'find', 'search', 'the', 'a', 'an', 'about', '告诉我', '请问'}
    rewritten = ' '.join(term for term in terms if term.lower() not in stopwords)
    return rewritten or query.strip()
