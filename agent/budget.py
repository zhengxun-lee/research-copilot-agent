"""Reservation accounting: interrupted or unreported requests retain their reservation."""
from dataclasses import asdict
import json
import time

from agent.runtime import BudgetExceeded


class BudgetControls:
    def budget_snapshot(self):
        ctx = self.last_run
        if ctx is None:
            return {'limits': asdict(self.budget), 'used': {}}
        elapsed = self._task.get('finished_at', time.monotonic()) - ctx.started_at
        if self._task.get('suspended_at') is not None:
            elapsed = self._task['suspended_at'] - ctx.started_at
        return {'limits': asdict(self.budget), 'used': {
            'steps': ctx.steps, 'llm_calls': ctx.llm_calls, 'tool_calls': ctx.tool_calls,
            'tokens': ctx.tokens, 'cost': ctx.cost, 'seconds': max(0, elapsed),
            'retries': ctx.retries, 'recoveries': ctx.recoveries,
            'estimated_usage': ctx.estimated_usage}}

    def _budget_event(self):
        snapshot = self.budget_snapshot()
        self._emit('budget.updated', **snapshot)
        if self._task.get('conserve'):
            return
        for name, value in snapshot['used'].items():
            limit = snapshot['limits'].get('max_' + name)
            if isinstance(value, (int, float)) and limit and value >= limit * self.budget.warning_ratio:
                self._task['conserve'] = True
                self._emit('budget.warning', resource=name, **snapshot)
                self._emit('recovery.applied', strategy='budget_conservation', resource=name)
                return

    def _consume(self, resource):
        try:
            self.last_run.consume(resource)
        except BudgetExceeded:
            self._emit('budget.exceeded', resource=resource, **self.budget_snapshot())
            raise
        self._budget_event()

    def _reserve_request(self, payload):
        ctx, budget = self.last_run, self.budget
        # UTF-8 bytes plus framing allowance is a conservative local estimate,
        # not a provider tokenizer. Real usage replaces it when returned.
        prompt = len(json.dumps({'messages': payload.get('messages'), 'tools': payload.get('tools')},
                                ensure_ascii=False).encode('utf-8')) + 1024
        output = budget.max_output_tokens
        if self._task.get('conserve'):
            output = min(output, 512)
        if budget.max_tokens is not None:
            output = min(output, budget.max_tokens - ctx.tokens - prompt)
        input_cost = prompt * budget.input_price_per_million / 1_000_000
        if budget.max_cost is not None:
            remaining = budget.max_cost - ctx.cost - input_cost
            output = min(output, int(remaining * 1_000_000 / budget.output_price_per_million))
        if output < 1:
            self._emit('budget.exceeded', resource='tokens_or_cost', **self.budget_snapshot())
            raise BudgetExceeded('Token or cost budget cannot fund another request')
        cost = input_cost + output * budget.output_price_per_million / 1_000_000
        ctx.tokens += prompt + output
        ctx.cost += cost
        ctx.estimated_usage = True
        reservation = {'tokens': prompt + output, 'cost': cost, 'output': output}
        self._budget_event()
        return reservation

    def _settle_request(self, response, reservation):
        usage = getattr(response, 'usage', None)
        def field(name):
            value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        prompt, completion = field('prompt_tokens'), field('completion_tokens')
        if prompt is not None and completion is not None:
            total = field('total_tokens')
            total = max(total or 0, prompt + completion)
            self.last_run.tokens += total - reservation['tokens']
            actual_cost = (prompt * self.budget.input_price_per_million +
                           completion * self.budget.output_price_per_million) / 1_000_000
            self.last_run.cost = max(0, self.last_run.cost + actual_cost - reservation['cost'])
            self._task['unreported_requests'] = self._task.get('unreported_requests', 1) - 1
            self.last_run.estimated_usage = self._task['unreported_requests'] > 0
        self._budget_event()
        self._save()
        for resource in ('tokens', 'cost'):
            limit = getattr(self.budget, 'max_' + resource)
            if limit is not None and getattr(self.last_run, resource) >= limit:
                self._emit('budget.exceeded', resource=resource, **self.budget_snapshot())
                raise BudgetExceeded(f'{resource} budget exhausted')
