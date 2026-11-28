from __future__ import annotations

import json
import os
import time
import math
import logging
import threading
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote as urllib_unquote


ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
MAX_BODY_BYTES = 128 * 1024

# ---------------------------------------------------------------------------
# Load config.yaml before importing config-backed modules (must be early).
# flake8: noqa: E402
# ---------------------------------------------------------------------------
from config_loader import load_project_config

load_project_config(ROOT_DIR)

from agent.core import Agent
from agent.observability import TraceStore, metrics
from agent.debugging import fork_checkpoint
from agent import CheckpointStore
from web_runtime import attach_inspector, inspector_status, is_active, launch
from config import (
    KNOWLEDGE_BASE_PATH,
    RETRIEVAL_MODE,
    WEB_CORS_ORIGIN,
    WEB_HOST,
    WEB_PORT,
    print_config_summary,
    validate_config,
)
from llm.prompts import build_system_prompt
from retrievers.loader import load_knowledge_base
from tools.registry import ToolRegistry


logger = logging.getLogger(__name__)


TRACE_STORE = TraceStore(Path(os.environ.get('RESEARCH_COPILOT_STATE_DIR', ROOT_DIR / 'data' / 'checkpoints')) / 'traces.sqlite3')

from model_settings import ModelSettings
MODEL_SETTINGS = ModelSettings(ROOT_DIR / 'config.local.yaml')


def create_agent() -> Agent:
    registry = ToolRegistry()
    system_prompt = build_system_prompt(registry.get_tool_specs())
    agent = attach_inspector(Agent(system_prompt=system_prompt, tool_registry=registry,
                                  checkpoint_store=CheckpointStore(Path(os.environ.get('RESEARCH_COPILOT_STATE_DIR', ROOT_DIR / 'data' / 'checkpoints'))), trace_store=TRACE_STORE,
                                  streaming=os.environ.get('RESEARCH_COPILOT_STREAMING', '1') != '0',
                                  stream_usage=os.environ.get('RESEARCH_COPILOT_STREAM_USAGE', '1') != '0'))
    MODEL_SETTINGS.apply(agent)
    return agent


class AgentSessionStore:
    def __init__(self, max_sessions: int = 32):
        self.max_sessions = max(1, max_sessions)
        self._sessions: dict[str, Agent] = {}
        self._lock = threading.Lock()

    def create(self) -> tuple[str, Agent]:
        """Create a new session (convenience wrapper around :meth:`get_or_create`)."""
        return self.get_or_create(session_id=None)

    def get_or_create(self, session_id: Optional[str] = None) -> tuple[str, Agent]:
        """Return the session identified by *session_id*, or create a new one.

        The entire lookup-or-create operation is performed under the lock so
        that concurrent callers never exceed *max_sessions*.
        """
        with self._lock:
            if session_id:
                agent = self._sessions.get(session_id)
                if agent is not None:
                    # Move to end (LRU ordering).
                    self._sessions.pop(session_id, None)
                    self._sessions[session_id] = agent
                    return session_id, agent

            # --- create new session ---
            session_id = uuid.uuid4().hex
            agent = create_agent()
            if len(self._sessions) >= self.max_sessions:
                oldest_id = next((key for key, value in self._sessions.items() if not is_active(value)), None)
                if oldest_id is None:
                    raise ValueError('All session slots have active tasks')
                self._sessions.pop(oldest_id, None)
            self._sessions[session_id] = agent
            return session_id, agent

    def find(self, session_id):
        with self._lock:
            agent = self._sessions.get(session_id)
            if agent is None:
                raise ValueError('Unknown session; restore the checkpoint in a new session')
            return agent

    def has_active_run(self, run_id, exclude=None):
        with self._lock:
            return any(agent is not exclude and getattr(agent,'last_run',None)
                       and agent.last_run.run_id==run_id and is_active(agent)
                       for agent in self._sessions.values())

    def reset(self, session_id: Optional[str] = None) -> tuple[str, Agent]:
        if session_id:
            with self._lock:
                if session_id in self._sessions and is_active(self._sessions[session_id]):
                    raise ValueError('Cancel the active task before resetting')
                self._sessions.pop(session_id, None)
        return self.create()

    def delete(self, session_id: Optional[str] = None) -> bool:
        if not session_id:
            return False
        with self._lock:
            if session_id in self._sessions and is_active(self._sessions[session_id]):
                raise ValueError('Cancel the active task before deleting')
            return self._sessions.pop(session_id, None) is not None


SESSION_STORE = AgentSessionStore()


def build_kb_stats_from_items(items: list[dict]) -> dict:
    documents: dict[str, dict] = {}
    for item in items:
        doc_id = item.get("doc_id") or item.get("source_path") or item.get("title") or "unknown"
        title = str(item.get("title") or "Untitled")
        document = documents.setdefault(
            doc_id,
            {
                "doc_id": doc_id,
                "title": title,
                "source": str(item.get("source_rel_path") or item.get("source_path") or "unknown"),
                "chunks": 0,
                "pages": set(),
            },
        )
        document["chunks"] += 1
        # Prefer a real title over "Untitled" set by an earlier item.
        if document["title"] == "Untitled" and title != "Untitled":
            document["title"] = title
        page_number = item.get("page_number")
        if page_number is None:
            page_number = item.get("page")
        if page_number is not None:
            document["pages"].add(page_number)

    normalized_docs = []
    for document in documents.values():
        pages = document.pop("pages")
        document["page_count"] = len(pages)
        normalized_docs.append(document)

    normalized_docs.sort(key=lambda doc: doc["title"].lower())
    return {
        "exists": True,
        "knowledge_base_path": KNOWLEDGE_BASE_PATH,
        "retrieval_mode": RETRIEVAL_MODE,
        "chunk_count": len(items),
        "document_count": len(normalized_docs),
        "documents": normalized_docs,
    }


def _empty_kb_stats(error: str = "") -> dict:
    result = {
        "exists": False,
        "knowledge_base_path": KNOWLEDGE_BASE_PATH,
        "retrieval_mode": RETRIEVAL_MODE,
        "chunk_count": 0,
        "document_count": 0,
        "documents": [],
    }
    if error:
        result["error"] = error
    return result


def get_kb_stats() -> dict:
    try:
        items = load_knowledge_base()
    except FileNotFoundError:
        return _empty_kb_stats()
    except Exception:
        logger.exception("Failed to load knowledge base from %s", KNOWLEDGE_BASE_PATH)
        return _empty_kb_stats("Knowledge base is corrupt or unreadable. Rebuild with `python3 -m ingest`.")
    return build_kb_stats_from_items(items)


def get_document_chunks(doc_id: str, limit: int = 50, offset: int = 0) -> dict:
    """Return a snippet of chunks for *doc_id* for the in-UI document browser.

    The full chunk text is included (truncated by the caller) but the
    response is bounded so the API never streams the entire knowledge base
    through the wire.
    """
    if not doc_id or not isinstance(doc_id, str):
        return {"exists": False, "error": "doc_id is required"}
    try:
        items = load_knowledge_base()
    except FileNotFoundError:
        return {"exists": False, "doc_id": doc_id, "error": "knowledge base not built"}
    except Exception:
        logger.exception("Failed to load knowledge base for document browse")
        return {"exists": False, "error": "knowledge base unreadable"}
    matches = [item for item in items if item.get("doc_id") == doc_id]
    if not matches:
        return {"exists": False, "doc_id": doc_id, "error": "document not found"}
    matches.sort(key=lambda item: item.get("chunk_index", 0))
    truncated = []
    for item in matches[offset:offset + limit]:
        truncated.append({
            "chunk_id": item.get("chunk_id"),
            "chunk_index": item.get("chunk_index"),
            "page_number": item.get("page_number") if item.get("page_number") is not None else item.get("page"),
            "title": item.get("title"),
            "content": item.get("content", ""),
            "prev_chunk_id": item.get("prev_chunk_id"),
            "next_chunk_id": item.get("next_chunk_id"),
        })
    return {
        "exists": True,
        "doc_id": doc_id,
        "title": matches[0].get("title"),
        "source": matches[0].get("source_rel_path") or matches[0].get("source_path"),
        "chunk_count": len(matches),
        "returned": len(truncated),
        "limit": limit,
        "offset": offset,
        "chunks": truncated,
    }


class ResearchCopilotHandler(SimpleHTTPRequestHandler):
    server_version = "ResearchCopilotWeb/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, fmt, *args):
        # Only format the message when INFO-level logging is enabled so we
        # don't waste cycles on every HTTP request in production.
        if logger.isEnabledFor(logging.INFO):
            logger.info("%s - %s", self.address_string(), fmt % args)

    def end_headers(self):
        if urlparse(self.path).path.startswith('/api/settings/'):
            self.send_header('Cache-Control','no-store')
        elif not urlparse(self.path).path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Frame-Options','DENY')
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def _local_settings_access(self):
        import ipaddress
        if not ipaddress.ip_address(self.client_address[0]).is_loopback:
            raise PermissionError('模型设置只允许本机访问')
        host=self.headers.get('Host','')
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}',f'[::1]:{self.server.server_port}'}
        if host not in allowed:
            raise PermissionError('无效的本机 Host')
        origin=self.headers.get('Origin')
        if origin and origin != 'http://'+host:
            raise PermissionError('拒绝跨站配置请求')
        if self.headers.get('Sec-Fetch-Site') in ('cross-site','same-site'):
            raise PermissionError('拒绝跨站配置请求')

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/settings/models':
            try:
                self._local_settings_access()
                self._send_json(MODEL_SETTINGS.public())
            except PermissionError as exc:self._send_json({'error':str(exc)},status=403)
            return
        if parsed.path in {'/api/traces','/api/traces/detail','/api/traces/export'}:
            query=parse_qs(parsed.query)
            run_id=query.get('run_id',[''])[0]
            if parsed.path=='/api/traces':
                self._send_json({'runs':TRACE_STORE.runs(query.get('q',[''])[0])})
            elif parsed.path=='/api/traces/export':
                body=TRACE_STORE.export(run_id).encode('utf-8')
                self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            else:
                events=TRACE_STORE.all_events(run_id)
                self._send_json({'run_id':run_id,'events':events,'metrics':metrics(events),'checkpoints':TRACE_STORE.checkpoints(run_id),'replay_mode':'offline'})
            return
        if parsed.path=='/api/events':
            query=parse_qs(parsed.query)
            try:
                agent=SESSION_STORE.find(query.get('session_id',[''])[0])
                after=max(0,int(self.headers.get('Last-Event-ID') or query.get('after',['0'])[0]))
            except (ValueError,TypeError) as exc:
                self._send_json({'error':str(exc)},status=HTTPStatus.BAD_REQUEST);return
            attach_inspector(agent)
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-cache');self.end_headers()
            deadline=time.monotonic()+25
            try:
                while time.monotonic()<deadline:
                    agent._inspector.wait(after,1)
                    state=inspector_status(agent,after);after=state['cursor']
                    frame='id: '+str(after)+'\nevent: runtime\ndata: '+json.dumps(state,ensure_ascii=False)+'\n\n'
                    self.wfile.write(frame.encode('utf-8'));self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):pass
            return
        if parsed.path == '/api/tasks/status':
            try:
                query = parse_qs(parsed.query)
                agent = SESSION_STORE.find(query.get('session_id', [''])[0])
                after = max(0, int(query.get('after', ['0'])[0]))
                self._send_json(inspector_status(agent, after))
            except (ValueError, TypeError) as exc:
                self._send_json({'error': str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == '/api/config/public':
            from web_runtime import hybrid_retrieval_unavailable
            from api_config import SIMPLE_MODEL_API_KEY, COMPLEX_MODEL_API_KEY
            from config import RETRIEVAL_ENABLE_EMBEDDING, RETRIEVAL_TOP_K, MAX_STEPS, MAX_MEMORY_TURNS
            self._send_json({
                'models': {role:p['model_name'] for role,p in MODEL_SETTINGS.public()['profiles'].items()},
                'api_configured': bool(SIMPLE_MODEL_API_KEY or COMPLEX_MODEL_API_KEY) if MODEL_SETTINGS.revision==0 else any(p['key_configured'] for role,p in MODEL_SETTINGS.public()['profiles'].items() if role in ('simple','complex','default')),
                'retrieval': {'mode': RETRIEVAL_MODE, 'embedding_enabled': RETRIEVAL_ENABLE_EMBEDDING,
                              'hybrid_available': not bool(hybrid_retrieval_unavailable()),
                              'hybrid_unavailable_reason': hybrid_retrieval_unavailable(),
                              'top_k': RETRIEVAL_TOP_K},
                'agent': {'max_steps': MAX_STEPS, 'max_memory_turns': MAX_MEMORY_TURNS, 'context_window': 32768,
                          'router_enabled': MODEL_SETTINGS.public()['router_enabled']},
                'capabilities': {'pdf_upload': True, 'token_streaming': os.environ.get('RESEARCH_COPILOT_STREAMING', '1') != '0',
                                 'structured_retrieval_events': False, 'retrieval_search': True,
                                 'structured_traces': True, 'runtime_sse': True, 'trace_replay': True, 'read_only_debug_branches': True},
            })
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return
        if parsed.path == "/api/kb/stats":
            self._send_json(get_kb_stats())
            return
        if parsed.path.startswith("/api/kb/document/"):
            doc_id = urllib_unquote(parsed.path[len("/api/kb/document/"):])
            if not doc_id or doc_id in {".", ".."}:
                self._send_json({"error": "Invalid doc_id."}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                offset = int(parse_qs(parsed.query).get('offset', ['0'])[0])
                if offset < 0 or offset > 1_000_000:
                    raise ValueError('Invalid offset')
                self._send_json(get_document_chunks(doc_id, offset=offset))
            except ValueError:
                self._send_json({'error': 'Invalid document offset'}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/api/settings/models/unlock','/api/settings/models/reveal','/api/settings/models'):
            try:
                self._local_settings_access()
                if self.headers.get('X-Requested-With')!='research-copilot' or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise PermissionError('配置请求需要同源授权头')
                payload=self._read_json_body()
                if parsed.path.endswith('/unlock'):result=MODEL_SETTINGS.unlock()
                elif parsed.path.endswith('/reveal'):result=MODEL_SETTINGS.reveal(payload,self.headers.get('X-Config-Token',''))
                else:result=MODEL_SETTINGS.save(payload,self.headers.get('X-Config-Token',''))
                self._send_json(result)
            except PermissionError as exc:self._send_json({'error':str(exc)},status=403)
            except ValueError as exc:self._send_json({'error':str(exc)},status=400)
            except Exception:self._send_json({'error':'配置保存失败，请检查文件权限或配置格式'},status=500)
            return
        if parsed.path == '/api/kb/delete':
            from ingest.web_import import delete_document, ImportBusy
            try:
                origin = self.headers.get('Origin')
                if ((origin and urlparse(origin).netloc != self.headers.get('Host'))
                        or self.headers.get('Sec-Fetch-Site') == 'cross-site'
                        or self.headers.get('Content-Type', '').split(';')[0] != 'application/json'):
                    self._send_json({'error': 'Cross-origin deletion rejected'}, status=403)
                    return
                payload = self._read_json_body()
                self._send_json(delete_document(payload.get('doc_id'), KNOWLEDGE_BASE_PATH))
            except ImportBusy as exc:
                self._send_json({'error': str(exc)}, status=409)
            except FileNotFoundError:
                self._send_json({'error': '文档已不存在，请刷新列表。'}, status=404)
            except ValueError as exc:
                self._send_json({'error': str(exc)}, status=400)
            except Exception:
                self._send_json({'error': '删除失败，请检查本地存储权限。'}, status=500)
            return
        if parsed.path == '/api/kb/import':
            from ingest.web_import import import_uploaded_pdf, MAX_PDF_BYTES, ImportBusy
            try:
                origin = self.headers.get('Origin')
                if origin and urlparse(origin).netloc != self.headers.get('Host'):
                    self._send_json({'error':'Cross-origin upload rejected'}, status=403)
                    return
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/pdf':
                    self._send_json({'error':'请上传 PDF 文件。'}, status=415)
                    return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_PDF_BYTES:
                    self._send_json({'error':'PDF 大小须为 1 字节至 20 MiB。'}, status=413)
                    return
                self.connection.settimeout(60)
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('上传未完成，请重试。')
                name = urllib_unquote(parse_qs(parsed.query).get('filename', ['document.pdf'])[0])
                result = import_uploaded_pdf(data, name, KNOWLEDGE_BASE_PATH)
                self._send_json(result, status=201)
            except ImportBusy as exc:
                self._send_json({'error':str(exc)},status=409)
            except (ValueError, TimeoutError) as exc:
                self._send_json({'error':str(exc)},status=400)
            except Exception:
                logger.error('PDF import failed; inspect local storage and PDF parser')
                self._send_json({'error':'文档入库失败，请检查本地存储后重试。'},status=500)
            return
        if parsed.path=='/api/traces/branch':
            try:
                payload=self._read_json_body()
                session_id,agent=SESSION_STORE.create()
                run_id=fork_checkpoint(agent,TRACE_STORE,payload.get('run_id'),payload.get('checkpoint_id'),
                    arguments=payload.get('arguments'),model=payload.get('model'),pressure=payload.get('pressure'))
                self._send_json({'session_id':session_id,'run_id':run_id,'state':'paused',
                    'messages':agent.trace.redact(agent.memory.messages),'execution_mode':'new_execution_requires_resume'},status=HTTPStatus.CREATED)
            except (ValueError,TypeError) as exc:
                self._send_json({'error':str(exc)},status=HTTPStatus.BAD_REQUEST)
            except Exception:
                logger.error('Branch creation failed; local persistence unavailable')
                self._send_json({'error':'Branch creation failed; check local trace/checkpoint storage.'},status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == '/api/retrieval/search':
            try:
                from retrievers import search
                payload = self._read_json_body()
                query, mode, top_k = payload.get('query'), payload.get('mode', 'keyword'), payload.get('top_k', 3)
                if not isinstance(query, str) or not query.strip() or len(query) > 2000:
                    raise ValueError('Query must contain 1–2000 characters')
                if mode not in {'keyword', 'semantic', 'vector', 'hybrid'}:
                    raise ValueError('Unknown retrieval mode')
                if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
                    raise ValueError('top_k must be an integer from 1 to 10')
                started = time.monotonic()
                results = search(query.strip(), top_k=top_k, mode=mode)
                fields = ('doc_id', 'title', 'chunk_id', 'chunk_index', 'page_number', 'page',
                          'content', 'prev_chunk_id', 'next_chunk_id')
                safe_results = []
                for result in results[:top_k]:
                    score = result.get('score')
                    safe_results.append({
                        'item': {key: value for key, value in result['item'].items() if key in fields},
                        'score': score if isinstance(score, (int, float)) and math.isfinite(score) else None,
                        'mode': result.get('mode', mode), 'fallback_reason': result.get('fallback_reason'),
                    })
                self._send_json({'query': query.strip(), 'requested_mode': mode, 'results': safe_results,
                                 'duration_ms': round((time.monotonic() - started) * 1000, 2)})
            except (ValueError, TypeError) as exc:
                self._send_json({'error': str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except FileNotFoundError:
                self._send_json({'error': 'Knowledge base not built. Run python3 -m ingest.'}, status=HTTPStatus.CONFLICT)
            except Exception:
                logger.exception('Playground retrieval failed')
                self._send_json({'error': 'Retrieval failed. Check knowledge base and embedding configuration.'}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith('/api/tasks/'):
            try:
                payload = self._read_json_body()
                action = parsed.path.rsplit('/', 1)[-1]
                if action == 'start':
                    session_id, agent = SESSION_STORE.get_or_create(payload.get('session_id'))
                else:
                    session_id = payload.get('session_id')
                    agent = SESSION_STORE.find(session_id)
                if action == 'pause':
                    agent.pause()
                elif action == 'cancel':
                    agent.cancel()
                elif action == 'restore':
                    if is_active(agent):
                        raise ValueError('Cancel current task before restoring')
                    if SESSION_STORE.has_active_run(payload.get('run_id',''),exclude=agent):
                        raise ValueError('This run is already owned by another active session; fork a branch instead')
                    agent.restore(payload.get('run_id', ''))
                else:
                    launch(agent, action, payload, prepare=MODEL_SETTINGS.apply)
                self._send_json({'session_id': session_id}, status=HTTPStatus.ACCEPTED)
            except (ValueError, TypeError, FileNotFoundError) as exc:
                self._send_json({'error': str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                logger.exception('Task control failed')
                self._send_json({'error': str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/session":
            session_id, _agent = SESSION_STORE.create()
            self._send_json({"session_id": session_id})
            return
        if parsed.path == "/api/session/reset":
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                session_id, _agent = SESSION_STORE.reset(payload.get("session_id"))
            except ValueError as exc:
                self._send_json({'error': str(exc)}, status=HTTPStatus.CONFLICT)
                return
            self._send_json({"session_id": session_id})
            return
        if parsed.path == "/api/session/delete":
            try:
                payload = self._read_json_body()
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                deleted = SESSION_STORE.delete(payload.get("session_id"))
            except ValueError as exc:
                self._send_json({'error': str(exc)}, status=HTTPStatus.CONFLICT)
                return
            self._send_json({"deleted": deleted})
            return
        if parsed.path == "/api/chat":
            self._handle_chat()
            return
        self._send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def _handle_chat(self):
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        message = str(payload.get("message") or "").strip()
        if not message:
            self._send_json({"error": "Message is required."}, status=HTTPStatus.BAD_REQUEST)
            return
        if len(message) > 10000:
            self._send_json({"error": "Message is too long."}, status=HTTPStatus.BAD_REQUEST)
            return

        session_id, agent = SESSION_STORE.get_or_create(payload.get("session_id"))
        if is_active(agent):
            self._send_json({'error': 'An active task exists; use task controls', 'session_id': session_id}, status=HTTPStatus.CONFLICT)
            return
        try:
            answer = agent.run(message)
        except Exception as exc:
            logger.exception("Chat request failed")
            # Reset the corrupted session so the next request gets a clean agent.
            new_session_id, _agent = SESSION_STORE.reset(session_id)
            self._send_json(
                {"error": f"Agent failed: {exc}", "session_id": new_session_id},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        route_decision = agent.last_route_decision
        self._send_json({
            "session_id": session_id,
            "answer": answer,
            "model": route_decision.model_name if route_decision else "",
            "route": route_decision.route_name if route_decision else "",
        })

    def _read_json_body(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length header is required.")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length.") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("Request body is too large.")
        raw_body = self.rfile.read(length)
        if not raw_body:
            return {}
        try:
            body_text = raw_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Request body is not valid UTF-8.") from exc
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self):
        if urlparse(self.path).path.startswith('/api/settings/'):return
        allowed_origin = WEB_CORS_ORIGIN.strip()
        if not allowed_origin:
            return

        request_origin = self.headers.get("Origin")
        # Wildcard is convenient but incompatible with credentialed requests; we
        # refuse credentials when wildcard is configured so the browser cannot
        # be tricked into sending them.
        if allowed_origin == "*":
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Credentials", "false")
            return
        # Support comma-separated origins (e.g. "http://localhost:3000, http://127.0.0.1:3000").
        allowed_origins = {o.strip() for o in allowed_origin.split(",") if o.strip()}
        if request_origin and request_origin in allowed_origins:
            self.send_header("Access-Control-Allow-Origin", request_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Credentials", "true")


def run(host: str = "127.0.0.1", port: int = 7860):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")
    validate_config()
    print_config_summary()
    if not WEB_DIR.exists():
        raise RuntimeError(f"Web assets not found: {WEB_DIR}")
    server = ThreadingHTTPServer((host, port), ResearchCopilotHandler)
    print(f"Research Copilot Web is running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nInterrupted. Bye!")
    finally:
        server.server_close()


if __name__ == "__main__":
    run(host=WEB_HOST, port=WEB_PORT)
