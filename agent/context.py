"""Token-estimated working sets and durable, session-scoped context paging."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from uuid import uuid4

from agent.memory import Memory
from agent.runtime import BudgetExceeded


def count_tokens(value):
    """Conservative UTF-8 estimate, including message framing; not provider billing."""
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8')) + 12


class ContextStore:
    def __init__(self, path):
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS fragments (scope TEXT, id TEXT, body TEXT, source TEXT, tokens INTEGER, importance REAL, history TEXT, created REAL, PRIMARY KEY(scope,id))')
        try:
            self.db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS fragment_fts USING fts5(scope UNINDEXED, ref UNINDEXED, body)')
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False
        self.db.commit()
        if str(path) != ':memory:':
            Path(path).chmod(0o600)

    def put(self, scope, body, source, tokens, importance, operation='offloaded'):
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True)
        ref = hashlib.sha256(raw.encode()).hexdigest()[:24]
        with self.lock, self.db:
            old = self.db.execute('SELECT history,created FROM fragments WHERE scope=? AND id=?', (scope, ref)).fetchone()
            history = json.loads(old[0]) if old else []
            history.append({'operation': operation, 'timestamp': time.time(), 'source':source, 'tokens':tokens, 'importance':importance})
            if self.fts and not old:
                self.db.execute('INSERT INTO fragment_fts VALUES (?,?,?)', (scope, ref, raw))
            self.db.execute('INSERT OR REPLACE INTO fragments VALUES (?,?,?,?,?,?,?,?)',
                            (scope, ref, raw, source, tokens, importance, json.dumps(history[-100:]), old[1] if old else time.time()))
        return ref

    def get(self, scope, ref):
        with self.lock:
            row = self.db.execute('SELECT body,source,tokens,importance,history FROM fragments WHERE scope=? AND id=?', (scope, ref)).fetchone()
        if row is None:
            raise ValueError('Context reference not found in this session')
        return dict(id=ref, body=json.loads(row[0]), source=row[1], tokens=row[2], importance=row[3], history=json.loads(row[4]))

    def search(self, scope, query, limit=5):
        # Parameterized local full-text scan; no embedding API, dependency or SQL interpolation.
        terms = set(re.findall(r'\w+', query.lower()))
        if not terms:
            return []
        with self.lock:
            rows = []
            if self.fts:
                expression = ' OR '.join('"'+term+'"' for term in sorted(terms)[:12])
                rows = self.db.execute('SELECT f.id,f.body,f.source,f.tokens,f.importance FROM fragments f JOIN fragment_fts x ON f.scope=x.scope AND f.id=x.ref WHERE fragment_fts MATCH ? AND f.scope=? LIMIT 100', (expression,scope)).fetchall()
            if not rows:
                rows = self.db.execute('SELECT id,body,source,tokens,importance FROM fragments WHERE scope=?', (scope,)).fetchall()
        hits = []
        for ref, body, source, tokens, importance in rows:
            score = sum(term in body.lower() for term in terms)
            if score:
                hits.append(dict(id=ref, source=source, tokens=tokens, importance=importance,
                                 score=score, excerpt=body[:160]))
        return sorted(hits, key=lambda item: (-item['score'], -int(item['source'].startswith('tool:') or item['source']=='history_turn'), -item['importance']))[:limit]

    def clone_scope(self, source, target, before=None):
        with self.lock, self.db:
            rows=self.db.execute('SELECT id,body,source,tokens,importance,history,created FROM fragments WHERE scope=? AND created<=?',(source,before if before is not None else time.time())).fetchall()
            for ref,body,origin,tokens,importance,history,created in rows:
                if before is not None:
                    eligible=[item for item in json.loads(history) if item['timestamp']<=before]
                    if eligible:
                        origin=eligible[-1].get('source',origin)
                        importance=eligible[-1].get('importance',importance)
                        tokens=eligible[-1].get('tokens',tokens)
                    history=json.dumps(eligible)
                self.db.execute('INSERT OR IGNORE INTO fragments VALUES (?,?,?,?,?,?,?,?)',(target,ref,body,origin,tokens,importance,history,created))
                if self.fts:self.db.execute('INSERT INTO fragment_fts VALUES (?,?,?)',(target,ref,body))

    def close(self):
        self.db.close()


class ContextMemory(Memory):
    def __init__(self, system_prompt, store, window_tokens=32768, emit=None, counter=count_tokens):
        super().__init__(system_prompt)
        if window_tokens < 128:
            raise ValueError('Context window must be at least 128 estimated tokens')
        self.store, self.window_tokens, self.counter = store, window_tokens, counter
        self.scope = uuid4().hex
        self.emit = emit or (lambda *args, **kwargs: None)
        self.last_assembly = None
        self.pinned = []
        self.pressure = False

    def _enforce_limit(self):
        pass  # Working-set selection replaces fixed turn-count eviction.

    def pin(self, instruction):
        if instruction not in self.pinned:
            self.pinned.append(instruction)

    def assemble(self, messages, tools=None, output_tokens=2048, phase='llm', task_state=None):
        if output_tokens >= self.window_tokens:
            raise BudgetExceeded('Output reservation exceeds context window')
        messages = deepcopy(messages)
        pending = set()
        for message in messages:
            if message['role'] == 'tool':
                ref = message.get('tool_call_id')
                if ref not in pending:
                    raise BudgetExceeded('Orphan tool result in context')
                pending.remove(ref)
            else:
                if pending:
                    raise BudgetExceeded('Incomplete tool-call batch in context')
                calls = message.get('tool_calls', [])
                pending = {call['id'] for call in calls}
                if len(pending) != len(calls):
                    raise BudgetExceeded('Duplicate tool-call IDs in context')
        if pending:
            raise BudgetExceeded('Missing tool results in context')
        system = [m for m in messages if m['role'] in {'system', 'developer'}]
        if self.pinned:
            system.append({'role': 'system', 'content': 'Persistent user constraints:\n'+'\n'.join(self.pinned)})
        if task_state:
            system.append({'role': 'system', 'content': 'Runtime state (not user evidence): '+json.dumps(task_state)})
        turns = []
        for message in messages:
            if message['role'] in {'system', 'developer'}:
                continue
            if message['role'] == 'user' or not turns:
                turns.append([])
            turns[-1].append(message)
        if not turns:
            turns = [[]]
        categories = dict(system=sum(self.counter(m) for m in system), user_task=0, history=0, tool_definitions=self.counter(tools or []),
                          tool_results=0, rag=0, output_reserve=output_tokens, framing=1024)
        remaining = self.window_tokens - output_tokens - categories['framing'] - categories['tool_definitions']
        # Always keep the active user task. Compress observations, never tool-call metadata.
        current = turns[-1]
        for message in current:
            if message['role'] == 'tool' and self.counter(message) > max(512, remaining//4):
                original = deepcopy(message)
                source = 'tool:'+str(message.get('tool_call_id'))
                ref = self.store.put(self.scope, original, source, self.counter(original), .7, 'offloaded_and_previewed:extractive_prefix')
                prefix = str(message.get('content', ''))[:256]
                message['content'] = f'[Extractive preview; original offloaded: context:{ref}; use recall_context to read original]\n{prefix}'
                for active in self.messages:
                    if active == original:
                        active['content'] = message['content']
                self.emit('context.compressed', ref=ref, method='extractive_prefix', original_tokens=self.counter(original), active_tokens=self.counter(message))
                self.emit('context.offloaded', ref=ref, source=source, original_tokens=self.counter(original), active_tokens=self.counter(message))
        mandatory = system + current
        remaining -= sum(self.counter(m) for m in mandatory)
        if remaining < 0:
            self.emit('context.overflow', window=self.window_tokens, required=self.window_tokens-remaining)
            raise BudgetExceeded('Protected context exceeds window; task/instructions were not truncated')
        query = ' '.join(str(m.get('content','')) for m in current if m['role']=='user').lower()
        terms = set(re.findall(r'\w+', query))
        candidates = []
        for index, turn in enumerate(turns[:-1]):
            text = json.dumps(turn, ensure_ascii=False).lower()
            protected = any(m['role']=='user' and re.search(r'必须|禁止|始终|不得|always|never|must', str(m.get('content','')), re.I) for m in turn)
            relevance = sum(term in text for term in terms)
            candidates.append((protected, relevance, index, turn))
        selected, seen, refs, evicted = [], set(), [], []
        for protected, relevance, index, turn in sorted(candidates, key=lambda row: row[:3], reverse=True):
            raw = json.dumps(turn, sort_keys=True, ensure_ascii=False)
            tokens = sum(self.counter(m) for m in turn)
            if raw not in seen and tokens <= remaining and (protected or not self.pressure):
                selected.append((index, turn)); remaining -= tokens;seen.add(raw)
            elif protected:
                raise BudgetExceeded('Persistent user constraints exceed context window; explicit task reduction required')
            else:
                ref = self.store.put(self.scope, turn, 'history_turn', tokens, min(1, .2+relevance*.1))
                refs.append(ref)
                evicted.append(turn)
                self.emit('context.offloaded', ref=ref, source='history_turn', original_tokens=tokens)
        counts = {}
        for turn in evicted:
            key = json.dumps(turn, sort_keys=True, ensure_ascii=False)
            counts[key] = counts.get(key, 0) + 1
        active_system, active_turns = [], []
        for message in self.messages:
            if message['role'] in {'system','developer'}:
                active_system.append(message)
            else:
                if message['role']=='user' or not active_turns:
                    active_turns.append([])
                active_turns[-1].append(message)
        retained=[]
        for index, turn in enumerate(active_turns):
            key=json.dumps(turn, sort_keys=True, ensure_ascii=False)
            if index != len(active_turns)-1 and counts.get(key,0):
                counts[key]-=1
            else:
                retained.extend(turn)
        self.messages = active_system + retained
        assembled = system + [m for _, turn in sorted(selected) for m in turn] + current
        # Persisted index references are available through scoped search, not large index dumps.
        for message in assembled:
            role = message['role']
            if role in {'system','developer'}: continue
            category = 'history'
            if message in current:
                category = 'user_task' if role=='user' else 'tool_results' if role=='tool' else 'history'
                if role=='tool':
                    call_id=message.get('tool_call_id')
                    if any(c['id']==call_id and c.get('function',{}).get('name')=='search_knowledge' for m in current for c in m.get('tool_calls',[])):
                        category='rag'
            categories[category] += self.counter(message)
        # Envelope accounting uses the same authoritative estimator as selection.
        used = sum(categories.values()) - output_tokens
        if used+output_tokens > self.window_tokens:
            raise BudgetExceeded('Context envelope exceeds window')
        provenance=[]
        for message in assembled:
            source = ('tool:'+str(message.get('tool_call_id'))) if message['role']=='tool' else message['role']
            ref=self.store.put(self.scope, message, source, self.counter(message), 1 if message in system+current else .5, 'assembled')
            provenance.append(dict(ref=ref, source=source, tokens=self.counter(message), importance=1 if message in system+current else .5))
        self.last_assembly=dict(window=self.window_tokens, used=used, reserved=output_tokens, estimated=True,
                                categories=categories, fragments=provenance, offloaded=refs, phase=phase)
        self.emit('context.assembled', **self.last_assembly)
        return assembled

    def recall(self, query='', ref=None, offset=0, length=2000):
        if ref is None:
            hits = self.store.search(self.scope, query)
            self.emit('context.searched', query=query, matches=len(hits))
            return json.dumps(hits, ensure_ascii=False)
        record = self.store.get(self.scope, ref.removeprefix('context:'))
        raw = json.dumps(record['body'], ensure_ascii=False)
        self.store.put(self.scope, record['body'], record['source'], record['tokens'], record['importance'], 'restored')
        self.emit('context.restored', ref=record['id'], source=record['source'], offset=offset, length=min(length,len(raw)-offset))
        return json.dumps(dict(ref=record['id'], source=record['source'], total_chars=len(raw), offset=offset,
                               content=raw[offset:offset+length], provenance=self.store.get(self.scope, record['id'])['history'][-5:]), ensure_ascii=False)
