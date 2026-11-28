import json
import time
import pytest
from agent.context import ContextMemory, ContextStore, count_tokens
from agent.runtime import BudgetExceeded


def memory(tmp_path, window=6000):
    events=[]
    mem=ContextMemory('protected system', ContextStore(tmp_path/'context.sqlite'), window,
                      emit=lambda name, **data: events.append((name,data)))
    return mem,events


def test_long_history_offloads_and_can_be_recovered_after_reopen(tmp_path):
    mem,events=memory(tmp_path)
    scope=mem.scope
    for i in range(40):
        mem.add_user_message(f'Historical fact {i}: unique-pin-{i}')
        mem.add_assistant_message('detail '*80)
    mem.add_user_message('What was unique-pin-0?')
    assembled=mem.assemble(mem.messages, output_tokens=500)
    assert sum(count_tokens(m) for m in assembled)+count_tokens([])+1024+500 <= 6000
    hits=json.loads(mem.recall('unique-pin-0'))
    assert hits
    ref=hits[0]['id']
    mem.store.close()
    restored,_=memory(tmp_path);restored.scope=scope
    assert 'unique-pin-0' in restored.recall(ref=ref)
    assert any(name=='context.offloaded' for name,_ in events)


def test_large_tool_output_preserves_pairs_and_original(tmp_path):
    mem,_=memory(tmp_path)
    mem.add_user_message('inspect evidence')
    mem.add_assistant_message(tool_calls=[{'id':'call','type':'function','function':{'name':'search_knowledge','arguments':'{}'}}])
    original='START '+('evidence '*10000)+' END'
    mem.add_tool_message('call', original)
    assembled=mem.assemble(mem.messages, output_tokens=500)
    result=next(m for m in assembled if m['role']=='tool')
    assert result['tool_call_id']=='call'
    assert 'context:' in result['content']
    refs=json.loads(mem.recall('START'))
    record=mem.store.get(mem.scope,refs[0]['id'])
    assert record['body']['content']==original
    assert mem.last_assembly['categories']['rag']>0
    assert len(mem.messages[-1]['content'])<1000


def test_pinned_and_historical_constraints_are_not_dropped(tmp_path):
    mem,_=memory(tmp_path)
    mem.pin('Use citations')
    mem.add_user_message('必须保留数据来源 A')
    mem.add_assistant_message('confirmed')
    for i in range(12):
        mem.add_user_message(str(i));mem.add_assistant_message('x'*500)
    mem.add_user_message('new question')
    text=json.dumps(mem.assemble(mem.messages, output_tokens=500),ensure_ascii=False)
    assert '必须保留数据来源 A' in text and 'Use citations' in text


def test_protected_overflow_fails_without_truncating_user(tmp_path):
    mem,_=memory(tmp_path,2000)
    mem.add_user_message('x'*4000)
    with pytest.raises(BudgetExceeded):mem.assemble(mem.messages,output_tokens=100)
    assert mem.messages[-1]['content']=='x'*4000


def test_archive_is_session_scoped(tmp_path):
    first,_=memory(tmp_path);second,_=memory(tmp_path)
    ref=first.store.put(first.scope,{'content':'private alpha'},'history',20,.5)
    assert second.store.search(second.scope,'private')==[]
    with pytest.raises(ValueError):second.recall(ref=ref)


def test_composition_is_additive_and_provenance_persists(tmp_path):
    mem,_=memory(tmp_path);mem.add_user_message('question')
    mem.assemble(mem.messages,[{'name':'tool'}],500)
    snapshot=mem.last_assembly
    assert sum(snapshot['categories'].values())==snapshot['used']+snapshot['reserved']
    for fragment in snapshot['fragments']:
        assert mem.store.get(mem.scope,fragment['ref'])['history']


def test_orphan_and_missing_results_are_rejected(tmp_path):
    mem,_=memory(tmp_path)
    with pytest.raises(BudgetExceeded):
        mem.assemble([{'role':'system','content':'s'},{'role':'tool','tool_call_id':'bad','content':'x'}])


def test_repeated_user_text_is_not_evicted_from_active_turn(tmp_path):
    mem,_=memory(tmp_path,4000)
    for i in range(10):
        mem.add_user_message('same user question')
        mem.add_assistant_message(str(i)*600)
    mem.add_user_message('same user question')
    mem.assemble(mem.messages,output_tokens=100)
    assert mem.messages[-1]=={'role':'user','content':'same user question'}
