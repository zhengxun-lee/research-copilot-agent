# Context Engine 本地基准

```bash
mkdir -p artifacts
python scripts/benchmark_context.py > artifacts/context-benchmark.json
```

两个固定场景：长对话，以及附带大工具返回值的长对话。两种实现分别为固定轮数 Memory 与 ContextMemory。
不需要模型 Key，不发起模型请求；输入是显式合成的测试负载。

| 输出字段 | 含义 |
| --- | --- |
| estimated_prompt_tokens | 同一 UTF-8 保守估算器测得的活动上下文开销 |
| key_retention | 指定测试信息是否出现在当前上下文；0/1，不是通用信息保留率 |
| archived_key_recoverable | 是否能经档案查询恢复指定信息 |
| elapsed_ms | 本地一次运行耗时，包含初始化与 SQLite 操作 |
| live_model_task_success | null；没有测量真实模型任务成功率 |

正式实验应记录 commit、Python/依赖版本、机器、配置、采样次数与波动，并单独进行真实任务评价。
新的输出默认写入忽略提交的 `artifacts/`，避免将临时结果混入已审阅基准。
