<p align="center">
  <img src="logo.png" width="360" alt="Research Copilot Agent" />
</p>

<h1 align="center">Research Copilot Agent</h1>
<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>
<p align="center">面向本地论文研究的 AI 工作台：资料检索、流式回答与可控的 Agent 执行。</p>

Research Copilot Agent 将 PDF 知识库、OpenAI-compatible 模型和工具调用放在同一条研究流程中。
你可以导入论文、直接提问；Agent 按需检索资料或调用工具，执行状态、预算和异常可在 Inspector 中检查。

项目面向**个人研究与可信私有环境中的单进程部署**，默认仅监听本机。

## 能做什么

- **论文入库**：浏览器导入 PDF，按内容去重，建立页码、片段和相邻关系；也可用 CLI 批量建库。
- **统一研究入口**：一个对话入口完成提问、按需检索与工具调用；支持流式 Markdown、代码与公式，结果可导出 Markdown。
- **多通道检索**：BM25、本地哈希近似匹配、可选 Embedding 向量检索，以及加权 RRF 融合。
- **模型路由**：依据本地规则与轻量路由器选择 simple / complex 模型配置，不额外调用模型进行路由。
- **可控执行**：显式状态机、安全节点暂停/恢复、取消、工具确认和 Checkpoint。
- **资源管理**：步数、Token、估算费用、时长、模型与工具调用次数预算；接近上限时收缩策略。
- **动态上下文**：按预算组装工作集，将低优先级历史和大工具结果卸载到 SQLite，通过 `recall_context` 恢复。
- **运行可观测性**：Event Bus、Hook/Middleware、结构化 Trace、真实 Usage 与客户端流式延迟；Web Inspector 实时更新。

默认工具包括知识检索、受限数学计算和抽取式文本总结。上下文恢复工具由 Runtime 注册。

## 快速开始

需要 Python 3.9+。应用启动不需要 Node.js；前端静态资源已包含在仓库中。界面统一使用浅色主题。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python web_app.py
```

打开 **http://127.0.0.1:7860**，在 **设置 → 模型连接** 中配置模型名称、接口地址与 API Key。
默认模型、快速模型（Simple）、深度模型（Complex）与向量模型（Embedding）可分别设置。
关闭自动路由时显示默认模型，开启后显示其余档位。点击“编辑”修改连接，保存后用于下一次新任务。
密钥支持掩码展示、眼睛按钮显隐与替换；保存到权限为 `0600` 的本机文件，未加密。
完整规则见[模型与密钥设置](docs/configuration.md#网页模型设置)。

Windows 使用 `.venv\Scripts\activate` 激活虚拟环境；网页模型保存仅支持具备 POSIX 文件权限的系统，Windows 请使用本地配置文件。

手动配置时，新建 **`config.local.yaml`** 并填写供应商信息。下面是 DeepSeek 示例：

```yaml
api:
  model_name: deepseek-chat
  api_key: "你的 API Key"
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

也可使用其他 OpenAI-compatible Chat Completions 服务，但应同时修改模型名与地址，并确认其流式工具调用兼容性。
本地配置已被 Git 忽略；不要将真实凭据写入受版本控制的文件。

网页保存的聊天模型配置下一次新任务生效；修改检索、向量连接或其他服务端配置后需要重启。

### 完成一次论文研究

1. 进入 **知识库**，点击“导入论文 PDF”。
2. 在文档列表确认论文已导入，可按标题筛选或删除。
3. 在工作台直接提问；需要本地依据时，明确要求检索已导入论文。
4. 展开回答下方的“执行详情”检查实际工具结果、状态和预算；回答完成后可复制或导出。

单个 PDF 限制为 20 MiB / 500 页。扫描件需要先做 OCR；加密、损坏或没有文字的文件会明确报错。
提问时可指定论文题目，当前不提供强制单篇文档检索隔离；仍需核对模型引用是否正确。

### CLI

```bash
python main.py
# 批量导入本地 PDF
python -m ingest --pdf-dir data/pdfs --output data/knowledge_base.json
```

交互命令：`/help`、`/config`、`/route`、`/reset`、`/clear`、`exit`。
批量导入时显式指定路径；Web 和 CLI 使用同一个知识库文件时，不要并行写入。

## 配置与运行边界

- Web / 对话 CLI 先加载 `config.yaml`，再加载可选的 `config.local.yaml`；后加载的非空值覆盖默认值。
- YAML 支持 `${ENV_NAME}` 引用；单纯创建 `.env` **不会自动加载**。完整说明见 [配置指南](docs/configuration.md)。
- 默认使用 BM25，不需要 Embedding Key；`semantic` 是本地哈希近似匹配，不等同于预训练语义模型。
- 默认请求流式返回。供应商不支持时可设置 `RESEARCH_COPILOT_STREAMING=0`；不支持流式 Usage 选项时设置 `RESEARCH_COPILOT_STREAM_USAGE=0`。
- 暂停发生在安全节点；取消会阻止后续工具调度，并尽力关闭客户端连接，不能保证供应商停止生成或计费。
- Trace / Checkpoint 可持久化，但 Web 会话注册表仍在进程内，重启后不自动恢复整个浏览器工作区。
- 当前没有公共部署所需的身份认证、租户隔离、跨进程写锁、后台导入队列与 OCR。

回答内可查看执行详情；历史查询、轨迹导出和受控分支由底层 API 提供。

## 项目结构

```text
agent/               Runtime、上下文、预算、恢复、Checkpoint、Trace
llm/                 模型客户端、流式协议聚合与 Prompt
routing/             simple / complex 路由与模型配置选择
semantic_router/     当前路由器依赖的本地轻量实现
retrievers/          BM25、哈希、向量与混合检索
tools/               工具定义、注册、校验与上下文恢复
ingest/              PDF 解析、切分、建库与 Web 导入
web/                 可直接由 Python 服务的前端与静态资源
frontend/            需要打包的第三方图表源码入口
scripts/             前端构建、语法检查与上下文基准
tests/               Python / Node 自动化测试
docs/                架构、配置、方法设计与开发说明
design-reference/    当前 Stitch 设计参考；不进入运行时
web_app.py           HTTP 服务入口
web_runtime.py       Web 任务监督与 SSE 事件历史
main.py              对话 CLI 入口
config.yaml          可提交的默认配置
config.local.yaml    私有覆盖配置（不提交）
```

## 开发与验证

```bash
python -m pip install -e ".[dev]"
python -m pytest

# 仅修改前端或重建资源时需要 Node.js，版本要求见 package.json
npm ci
npm test
npm run check
npm run build:console
```

自动化测试覆盖 Runtime、上下文换入换出、流式内容与工具参数聚合、取消/超时、预算结算、Trace、PDF 导入和前端交互。
测试中的模型协议 fixture 与合成文档只用于测试，不用于伪造产品运行效果。测试不要求真实 API Key；联网验证会产生供应商费用。

可复现上下文基准：

```bash
mkdir -p artifacts
python scripts/benchmark_context.py > artifacts/context-benchmark.json
```

该基准使用受控本地负载，输出估算上下文占用、指定信息保留/恢复情况和本地耗时；不测量真实模型任务成功率。

## 文档

- [配置指南](docs/configuration.md)：模型、检索、私有配置与数据存储。
- [系统架构](docs/architecture.md)：模块边界、数据流、执行约束与前端组织。
- [理论与方法设计](docs/methods.md)：Working Set 上下文、预算、流式工具安全，以及创新主张的证据边界。
- [开发指南](docs/development.md)：测试、扩展、资源构建与发布检查。
- [基准说明](docs/benchmarks/README.md)：可复现运行方式、测量口径与结果解释。

## 第三方资源与许可

Geist 字体使用 SIL OFL，Apache ECharts 使用 Apache-2.0，KaTeX 使用 MIT；相应 LICENSE / NOTICE 随静态资源保留。
本仓库尚未指定项目整体许可证，第三方资源许可证不自动授予本项目代码的使用许可。
