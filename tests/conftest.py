import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_storage(tmp_path, monkeypatch):
    """Test executions must never seed production trace/context history."""
    monkeypatch.setenv('RESEARCH_COPILOT_STATE_DIR', str(tmp_path / 'runtime'))
    web_module = sys.modules.get('web_app')
    if web_module is not None:
        from agent.observability import TraceStore
        store = TraceStore(tmp_path / 'runtime' / 'web-traces.sqlite3')
        monkeypatch.setattr(web_module, 'TRACE_STORE', store)
        yield
        store.db.close()
    else:
        yield
