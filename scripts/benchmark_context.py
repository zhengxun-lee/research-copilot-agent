"""Controlled local workload, not a live-model task-success benchmark."""
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.context import ContextMemory, ContextStore, count_tokens
from agent.memory import Memory


def benchmark():
    rows=[]
    for scenario in ('long_dialogue', 'large_observation'):
        with tempfile.TemporaryDirectory() as directory:
            for strategy in ('fixed_turns', 'working_set'):
                started=time.perf_counter()
                mem=(Memory('system',10) if strategy=='fixed_turns' else
                     ContextMemory('system',ContextStore(Path(directory)/(strategy+'.sqlite')),8000))
                mem.add_user_message('Project telescope codeword: MARBLE-EXACT-731')
                mem.add_assistant_message('recorded')
                for i in range(40):
                    mem.add_user_message(f'Unrelated question {i}')
                    mem.add_assistant_message('Background text. '*70)
                mem.add_user_message('Recall the codeword for Project telescope')
                if scenario=='large_observation':
                    mem.add_assistant_message(tool_calls=[{'id':'c','type':'function','function':{'name':'search_knowledge','arguments':'{}'}}])
                    mem.add_tool_message('c','Evidence '*12000)
                messages=mem.get_messages() if strategy=='fixed_turns' else mem.assemble(mem.messages,output_tokens=500)
                raw=json.dumps(messages)
                retention=int('MARBLE-EXACT-731' in raw)
                recall_retention=None
                if strategy=='working_set':
                    hits=json.loads(mem.recall('telescope'))
                    recall_retention=int(any('MARBLE-EXACT-731' in mem.recall(ref=hit['id']) for hit in hits))
                rows.append(dict(scenario=scenario,strategy=strategy,estimated_prompt_tokens=sum(count_tokens(m) for m in messages),
                                 key_retention=retention,archived_key_recoverable=recall_retention,
                                 elapsed_ms=(time.perf_counter()-started)*1000,live_model_task_success=None))
                if strategy=='working_set':mem.store.close()
    return {'method':'deterministic synthetic fixtures; measured local execution, no provider calls',
            'token_counter':'UTF-8 conservative estimate', 'rows':rows,
            'limitations':'Latency includes initialization and SQLite writes; no statistical significance or live-model success claim.'}

if __name__=='__main__':
    print(json.dumps(benchmark(),indent=2))
