<p align="center">
  <img src="logo.png" width="360" alt="Research Copilot Agent" />
</p>

<h1 align="center">Research Copilot Agent</h1>
<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>
<p align="center">A local AI research workspace for paper retrieval, streaming answers, and controllable agent execution.</p>

Research Copilot Agent brings a PDF knowledge base, OpenAI-compatible models, and tool calling into one research workflow. Import papers, ask questions, and inspect the agent's actual tool results, execution state, resource usage, and errors alongside its answers.

Built for **individual research and single-process deployment in trusted private environments**, with a localhost-only server by default.

## Features

- **PDF knowledge base** — Import PDFs in the browser or in batches through the CLI. Content deduplication, page references, chunks, and neighboring-chunk relationships are built during ingestion.
- **One research workspace** — Ask questions, retrieve evidence, and call tools in one conversation. Stream Markdown, code, and math; copy answers or export them as Markdown.
- **Multiple retrieval channels** — BM25, local hash-based approximate matching, optional embedding retrieval, and weighted Reciprocal Rank Fusion (RRF).
- **Model routing** — Select simple or complex model profiles using local rules and a lightweight router, without an additional LLM routing request.
- **Controllable execution** — An explicit state machine, pause and resume at safe boundaries, cancellation, tool approval, and checkpoints.
- **Execution budgets** — Limits for steps, tokens, estimated cost, elapsed time, LLM requests, and tool calls, with strategy adjustments near budget limits.
- **Dynamic context** — Assemble a token-budgeted working set, offload lower-priority history and large tool results to SQLite, and retrieve them through `recall_context`.
- **Observability** — An Event Bus, hooks and middleware, structured traces, provider-reported usage, and client-measured streaming latency, exposed through live execution details.

Built-in tools provide knowledge retrieval, restricted mathematical calculation, and extractive text summarization. The runtime also registers the context recall tool.

## Quick start

Requires Python 3.9+. Node.js is only needed for frontend development; the repository includes the static assets required to run the app. The interface uses a light theme.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python web_app.py
```

Open **http://127.0.0.1:7860**. Under **设置 → 模型连接** (Settings → Model connections), configure a model name, API endpoint, and API key.

Default, Simple, Complex, and Embedding profiles can be configured separately. With automatic routing disabled, the list shows the default model; enabling routing reveals the other profiles. Click **编辑** (Edit), then save. Updated chat profiles apply to the next new task.

Keys are masked by default, with an eye button to reveal, hide, and edit them. Configuration is stored locally with POSIX permissions of `0600`; the file is not encrypted. See the [model and credential settings guide](docs/configuration.md#网页模型设置).

On Windows, activate the environment with `.venv\Scripts\activate`. Browser-based model saving requires POSIX file permissions; on Windows, configure models through the local configuration file.

To configure models manually, create **`config.local.yaml`**. For example, with DeepSeek:

```yaml
api:
  model_name: deepseek-chat
  api_key: "YOUR_API_KEY"
  base_url: https://api.deepseek.com
  simple:
    model_name: deepseek-chat
    api_key: ""
    base_url: https://api.deepseek.com
  complex:
    model_name: deepseek-reasoner
    api_key: ""
    base_url: https://api.deepseek.com
```

Other OpenAI-compatible Chat Completions providers can be used by changing both the model names and endpoint. Check the provider's streaming tool-call compatibility. Local configuration is ignored by Git; keep real credentials out of tracked files.

Restart the service after changing retrieval settings, embedding connections, or other server configuration.

### Research a paper

1. Open **知识库** (Knowledge base) and click **导入论文 PDF** (Import papers).
2. Confirm that the papers appear in the document list. Filter by title or delete documents as needed.
3. Ask a question in the workspace. Explicitly request a search of imported papers when you need local evidence.
4. Expand **执行详情** (Execution details) below the answer to inspect tool results, runtime state, and budgets. Copy or export the completed answer.

Each PDF is limited to **20 MiB / 500 pages**. Scanned documents require OCR before import. Encrypted, damaged, and textless files produce explicit errors.

You can name a paper in your question, but retrieval is not strictly isolated to that document. Verify the model's citations against the source.

### CLI

```bash
python main.py

# Import a directory of PDFs
python -m ingest --pdf-dir data/pdfs --output data/knowledge_base.json
```

Interactive commands: `/help`, `/config`, `/route`, `/reset`, `/clear`, and `exit`.

Specify paths explicitly for batch ingestion. Avoid concurrent Web and CLI writes to the same knowledge-base file.

## Configuration and operating limits

- Web and conversational CLI entry points load `config.yaml`, then optional overrides from `config.local.yaml`. Nonempty values override earlier settings.
- YAML supports `${ENV_NAME}` references. Creating a `.env` file **does not load it automatically**. See the [configuration guide](docs/configuration.md).
- BM25 is the default and needs no embedding key. The `semantic` mode uses local hash-based matching, not a pretrained semantic model.
- Web responses stream by default. Set `RESEARCH_COPILOT_STREAMING=0` for non-streaming compatibility, or `RESEARCH_COPILOT_STREAM_USAGE=0` if the provider does not support the streaming usage option.
- Pausing takes effect at safe boundaries. Cancellation blocks subsequent tool dispatch and attempts to close the client connection; it cannot guarantee that the provider stops generating or charging.
- Traces and checkpoints can persist, but the Web session registry is in memory. Restarting the server does not automatically restore the entire browser workspace.
- Public-facing deployment requires additional authentication, tenant isolation, and cross-process write coordination. Background ingestion queues and OCR are not included.

The workspace displays execution details alongside answers. Historical trace queries, exports, and controlled execution branches are available through backend APIs.

## Project structure

```text
agent/               Runtime, context, budgets, recovery, checkpoints, traces
llm/                 Model client, streaming aggregation, prompts
routing/             Simple/complex routing and profile selection
semantic_router/     Local lightweight implementation used by the router
retrievers/          BM25, hash-based, vector, and hybrid retrieval
tools/               Tool definitions, registry, validation, context recall
ingest/              PDF parsing, chunking, indexing, browser imports
web/                 Frontend and static assets served directly by Python
frontend/            Source entry point for the bundled chart library
scripts/             Frontend builds, syntax checks, context benchmark
tests/               Python and Node automated tests
docs/                Architecture, configuration, methods, development
design-reference/    Current Stitch design reference; not a runtime dependency
web_app.py           HTTP server entry point
web_runtime.py       Web task supervision and SSE event history
main.py              Conversational CLI entry point
config.yaml          Tracked default configuration
config.local.yaml    Private local overrides, excluded from Git
```

## Development and validation

```bash
python -m pip install -e ".[dev]"
python -m pytest

# Node.js is required only for frontend work; see package.json for versions
npm ci
npm test
npm run check
npm run build:console
```

Tests cover the runtime, context offloading and recall, streaming text and tool-call aggregation, cancellation and timeouts, budget accounting, traces, PDF imports, and frontend interactions.

Protocol fixtures and synthetic documents are used only in tests. They do not supply product runtime data. Automated tests require no real API key; live provider verification incurs provider charges.

Run the reproducible local context benchmark:

```bash
mkdir -p artifacts
python scripts/benchmark_context.py > artifacts/context-benchmark.json
```

The benchmark measures estimated active-context size, retention and recovery of specified information, and local execution time on controlled workloads. It does not measure real-model task success.

## Documentation

The detailed guides are currently written in Chinese.

- [Configuration](docs/configuration.md) — Models, retrieval, private configuration, and storage.
- [Architecture](docs/architecture.md) — Module boundaries, data flow, runtime constraints, and frontend organization.
- [Theory and methods](docs/methods.md) — Context working sets, budgets, streaming tool safety, and the evidence supporting design claims.
- [Development](docs/development.md) — Tests, extensions, asset builds, and release checks.
- [Benchmark guide](docs/benchmarks/README.md) — Reproduction, measurement definitions, and interpretation.

## Third-party assets and licensing

Geist fonts use the SIL Open Font License, Apache ECharts uses Apache-2.0, and KaTeX uses MIT. Their LICENSE / NOTICE files are included with the static assets.

A project-wide license has not yet been specified. Third-party licenses do not grant a license to this project's own code.
