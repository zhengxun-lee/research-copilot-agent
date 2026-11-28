# 开发与维护

## 从源码开发

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm ci
```

Node 版本以 `package.json` 的 engines 为准。日常运行 Python Web / CLI 不要求 Node。
当前分发与启动说明面向源码检出目录，不将 Python wheel 描述为带完整 Web 数据目录的独立部署包。

```bash
python -m pytest
npm test
npm run check
npm run build:console
```

`npm run check` 检查所有维护中的 Web / 图表源码；vendor 不重复做语法审计。
构建只打包图表，并复制官方 Geist 字体、许可证和项目 Logo；不覆盖业务 JS。
提交前端源码修改时，应同步提交需要变化的静态产物，确保 Python 服务可直接启动。

## 测试边界

- Python 测试使用临时 Runtime 目录，避免污染真实 Trace 与 Checkpoint。
- LLM 协议 fixture 和生成的测试 PDF 仅用于自动化测试；不进入生产 UI。
- `tests/test_streaming_http.py` 用真实 socket + OpenAI SDK 对接测试协议服务，不代表线上模型验证。
- Node 测试使用 JSDOM，覆盖页面初始化、原生文件选择入口、流式 DOM 身份、浅色初始化、密钥显隐和状态投影。
- DOM 测试不能替代真实浏览器布局、截图、GPU 性能或文件选择对话框验收。
- 历史查询、存储与分支通过 API 测试，Web 交互通过工作台和回答执行详情测试。

联网验证需提供本地凭据，使用真实供应商并记录 Usage / 时延来源；不要把测试 fixture 的数值写成产品基准。

## 扩展工具

在 `tools/` 实现 `BaseTool` 的名称、参数、描述与执行方法，通过 ToolRegistry 注册。
明确声明 `side_effects`、`idempotent` 和保守调用费用；未知工具默认按可能有副作用处理。
需要幂等保证的工具应实现并由下游验证 `run_idempotent`。不要把自动重试视为适用于所有 I/O。

工具应通过 Runtime 边界调用，不从流式 Delta 回调直接执行。Schema 修改后补充有效/非法参数、确认、取消和中断测试。

## 事件与 Hook

观察执行使用 Event Bus；控制执行使用 Middleware / Hooks。事件应带 Run 归属，并避免将密钥放入可见数据。
新增关键持久化订阅时，应验证失败后确实阻止调度。普通订阅需要隔离异常，不能拖垮执行。

## 文档维护规则

- README：用户定位、真实能力、最短启动路径和重要限制。
- configuration：配置语义、继承与数据路径。
- architecture：模块职责、数据流和一致性边界。
- methods：已实现方法、既有理论来源与证据边界。
- benchmarks：可复现口径与原始测量，不放营销指标。
- 当前设计参考位于 `design-reference/`，不作为当前产品功能说明。

不把逐次验收结果、临时进程 PID、个人目录和对话记录追加到 README。
不要为暂未实现的特性加入无行为按钮，也不要使用演示数据冒充任务或检索结果。

## 目录与提交范围

`web/` 是运行时前端；`frontend/` 仅保留需要打包的图表入口，两者职责不同。
`routing/` 使用本仓库的 `semantic_router/`，两者均为运行依赖。
当前使用的 Stitch 参考放在 `design-reference/`，历史模板不保留，不由 HTTP 服务提供，不进入 Python 分发包。
静态图表、字体、公式资源及其许可证需要随源码提交，确保启动时不依赖 npm 或公共 CDN。

`data/`、`config.local.yaml`、`.local-backups/`、`artifacts/`、虚拟环境和依赖目录均不提交。
清理缓存使用 `make clean`，不清空论文、运行记录、凭据或备份。历史 Git 提交不重写。

## 发布前

检查 `git diff --check`、测试、配置模板和资源许可证，并在真实浏览器验证导入/流式输出/知识库、模型编辑和密钥显隐。
确认不提交 PDF、SQLite、私有配置或 Trace。服务默认保持本机监听；公共部署需要额外的认证与隔离设计。
项目整体许可证仍需维护者明确选择，不能用第三方资源许可证代替。
