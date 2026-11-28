"""Real socket / SDK integration against an explicitly test-only protocol fixture."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS
from http.client import HTTPConnection
from urllib.parse import urlparse

import web_app
from agent.core import Agent
from agent.observability import TraceStore
from test_web_app import http_server, _post_json
from web_runtime import attach_inspector


def test_sdk_http_stream_reaches_web_sse_and_persistent_trace(http_server, monkeypatch, tmp_path):
    release = threading.Event()
    received = []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            def send(data):
                self.wfile.write(('data: '+json.dumps(data)+'\n\n').encode());self.wfile.flush()
            send({'id':'fixture','choices':[{'index':0,'delta':{'content':'test-only HTTP output '*60},'finish_reason':None}]})
            release.wait(4)
            send({'id':'fixture','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})
            send({'choices':[],'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}})
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
    provider=ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=provider.serve_forever,daemon=True).start()
    store=TraceStore(tmp_path/'trace.sqlite')
    agent=attach_inspector(Agent('system',trace_store=store))
    agent.model_router.route=lambda _:NS(route_name='simple',model_name='test-fixture',confidence=1,reason='test',api_key='test-only',base_url=f'http://127.0.0.1:{provider.server_port}/v1')
    monkeypatch.setattr(web_app,'create_agent',lambda:agent)
    monkeypatch.setattr(web_app,'TRACE_STORE',store)
    conn=None
    try:
        code,payload=_post_json(http_server,'/api/tasks/start',{'message':'protocol test'})
        assert code==202
        url=urlparse(http_server);conn=HTTPConnection(url.hostname,url.port,timeout=5)
        conn.request('GET','/api/events?session_id='+payload['session_id'])
        response=conn.getresponse()
        snapshot=None
        for _ in range(80):
            line=response.readline().decode()
            if line.startswith('data: '):
                frame=json.loads(line[6:])
                if frame.get('partial_output',{} ) and frame['partial_output'].get('content'):
                    snapshot=frame;break
        assert snapshot and snapshot['running']
        assert snapshot['metrics']['ttft_ms'] is not None
        assert received[0]['stream'] and received[0]['stream_options']['include_usage']
        release.set()
        for _ in range(80):
            line=response.readline().decode()
            if line.startswith('data: '):
                frame=json.loads(line[6:])
                if not frame['running'] and frame['state']=='completed':break
        assert frame['state']=='completed'
        assert frame['metrics']['input_tokens']==10
        assert frame['metrics']['output_tokens']==20
        assert agent.last_run.tokens==30
        assert any(e['name']=='llm.stream.accepted' for e in store.all_events(agent.last_run.run_id))
    finally:
        release.set()
        if conn:conn.close()
        provider.shutdown();provider.server_close()
