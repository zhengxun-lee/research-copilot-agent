# 配置与数据

## 配置文件

Web 与对话 CLI 使用 `load_project_config()`，在导入模型和检索模块前依次读取：

1. `config.yaml`：可提交的默认值，凭据通过环境变量引用。
2. `config.local.yaml`：可选私有覆盖，适合 API Key、本地地址和个人偏好。

```bash
cp config.yaml config.local.yaml
```

只修改需要覆盖的字段即可。YAML 非空值覆盖已有环境变量；空字符串/null 表示不注入新值，
不是“清空上层配置”。`${OPENAI_API_KEY}` 会读取当前环境，同样支持旧配置的裸变量名。
`.env` 不自动读取；如采用环境模板，可在启动前执行 `set -a; source .env; set +a`。

本地覆盖文件被 Git 忽略，不应作为共享配置或示例上传。
通用库导入与 `python -m ingest` 不自动应用项目 YAML，调用方应在导入前配置环境或显式传参。

## 模型配置

| 字段 | 环境变量 | 行为 |
| --- | --- | --- |
| `api.model_name` | `MODEL_NAME` | 关闭路由时使用的模型 |
| `api.api_key` / `base_url` | `OPENAI_API_KEY` / `OPENAI_BASE_URL` | 默认模型连接 |
| `api.simple.*` | `SIMPLE_MODEL_*` | 简单任务模型；Key/地址缺省时继承默认连接 |
| `api.complex.*` | `COMPLEX_MODEL_*` | 复杂任务模型；Key/地址缺省时继承默认连接 |
| `api.embedding.*` | `EMBEDDING_MODEL_NAME` / `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` | 向量检索连接，Key 不自动继承聊天模型 |

路由器按任务特征选择配置；模型是否支持推理输出、工具调用及 Usage 取决于供应商。
模型升级/降级仍受执行预算与已配置模型档位限制，不代表可以自动选择任意模型。

## 检索

| `retrieval.mode` | 实现 | 外部依赖 |
| --- | --- | --- |
| `keyword` | BM25 关键词检索 | 无 API |
| `semantic` | BLAKE2b 哈希近似匹配 | 无 API；不等同于真实语义 Embedding |
| `vector` | OpenAI-compatible Embedding | 需要 `enable_embedding: true` 与有效 Embedding 配置 |
| `hybrid` | BM25、哈希及可选向量通道的加权 RRF | 仅启用的向量通道需要 API |

`top_k` 控制默认返回量，`neighbors` 控制相邻片段扩展，候选数量分别由 hybrid/vector 配置控制。
向量模式在 Embedding 被禁用时可能回退到本地匹配；回退信息不应被解释为向量检索已经成功。

## 流式选项

```bash
export RESEARCH_COPILOT_STREAMING=0   # Web 使用兼容的非流式模式
export RESEARCH_COPILOT_STREAM_USAGE=0 # 不发送 include_usage 选项
```

Python 调用可通过 `Agent(..., streaming=False)` 关闭。`LLMClient.chat()` 默认仍为非流式；
传入 `stream=True` 才启用协议聚合。部分输出之后不会自动重发请求。

## 数据落盘

- 知识库默认 `data/knowledge_base.json`，可由 `knowledge.base_path` 指定。
- Web 上传 PDF 保存在知识库 JSON 同级的 `uploads/`。
- 普通 Agent 的 Context / Trace 默认为 `data/context.sqlite3`、`data/traces.sqlite3`。
- Web 的 Checkpoint / Context / Trace 默认位于 `data/checkpoints/`。
- `RESEARCH_COPILOT_STATE_DIR` 可覆盖 Runtime 状态目录；它不改变知识库或上传目录。
- `data/`、`artifacts/` 与本地配置不提交。若将数据路径改到其他目录，应自行加入忽略规则。

Trace 会脱敏常见凭据和注册的敏感字面量；原始私有 Checkpoint 可能包含任务材料，不能作为公开导出文件。
本地脱敏并非通用 DLP。不要将 HTTP 服务无保护地暴露到公网。

## 执行预算

执行预算位于各模型编辑页内部，是所有模型共享的任务预算。点击“保存本地预算偏好”保存到当前浏览器，下一个新任务生效；它不修改服务端配置文件。
费用上限必须配套填写输入/输出单价，币种与供应商报价一致。
API 未返回真实 Usage 时保留预留估算；取消请求不代表费用已经结算为零。
`max_memory_turns` 仅保留旧 Memory 接口兼容，当前 Agent 使用 `ContextMemory` 的窗口预算。


## 网页模型设置

进入“设置 → 模型连接”。关闭自动路由时只显示默认模型；开启后显示快速、深度和向量模型。
选择“编辑”修改模型名称、接口地址和密钥，点击“保存配置”写入本机。返回列表保留草稿，离开设置页清空未保存修改。
保存配置不测试模型连通性，也不调用模型。

- 密钥留空保留原值；输入新值则替换。支持 ASCII Key，拒绝空白和中文引号。
- “移除”明确禁用该档凭据；快速/深度模型可选择“使用默认密钥”。
- 常规接口只返回星号掩码。眼睛按钮通过独立接口按需读取原值，支持显示、隐藏和修改。
- 退出编辑时遮蔽密钥；离开设置时清空明文和草稿。密钥不写入浏览器持久化存储。
- 接口地址禁止内嵌凭据、查询参数与片段；远端地址必须使用 HTTPS，本机可使用 HTTP。

模型保存使用私有临时文件、fsync 与原子替换，保留非模型配置；`config.local.yaml` 的 POSIX 权限为 `0600`。
文件未加密，备份也应按敏感资料保护。`api_key_mode` 记录 set / clear / inherit，重启后保留清除与继承语义。
聊天配置应用于下一次新任务，不修改正在执行、暂停或等待确认的 Run；向量客户端保存后需要重启服务。
Windows 尚无文件 ACL 实现，网页保存默认禁用，可使用本地配置文件。

设置接口仅允许 loopback 客户端与匹配的本机 Host，校验 Origin / Fetch Metadata；写入和密钥查看要求专用请求头与短期 nonce，界面无需手动授权。
查看密钥还校验配置版本，并消费一次性 nonce。响应禁止缓存，不开放跨域读取。
这些控制适用于可信本机环境，不能替代多用户身份认证；不要将管理端口公开暴露。

| 接口 | 用途 |
| --- | --- |
| `GET /api/settings/models` | 模型摘要与脱敏密钥 |
| `POST /api/settings/models/unlock` | 前端自动申请操作 nonce |
| `POST /api/settings/models` | 校验版本并保存完整模型配置 |
| `POST /api/settings/models/reveal` | 按需读取一个档位的有效密钥 |
