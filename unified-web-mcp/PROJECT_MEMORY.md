# 项目开发记忆

> 本文件记录 unified-web-mcp 的设计决策、踩过的坑和验证状态，供后续接手的人（或 AI）快速恢复上下文。
> 最后更新：2026-10-30

---

## 1. 这个项目解决什么

多个网页搜索/抓取服务各有各的 Key、各自的 SDK、各自的失败方式。客户端（Claude Code / WorkBuddy / Codex / DSH）如果各自适配一遍，逻辑会漂移。

**做法**：一个本地 stdio MCP 网关，对外只暴露 3 个稳定工具，对内按优先级回退：

```text
unified_web_search / unified_web_fetch
        ↓
   router（超时、冷却、错误分类、结果归一化）
        ↓
free ──→ minimax ──→ deepseek
 │
 ├─ 搜索：anysearch → bing → duckduckgo → searxng
 └─ 抓取：direct  → anysearch → jina
```

关键取舍：**回退只看「错误与可用性」，不看结果相关性**。曾考虑做质量评分再决定是否换引擎，否决了——不可靠、不可解释、还会带来额外延迟。

---

## 2. 目录职责

| 路径 | 职责 |
|---|---|
| `src/index.js` | MCP 入口、工具注册、生命周期、凭据脱敏出口 |
| `src/router.js` | 路由核心：独立 search/fetch 链路、per-attempt 超时、总 deadline、冷却、错误分类 |
| `src/config.js` | 配置校验与默认值注入（含 free 内部引擎默认链） |
| `src/errors.js` | `ProviderError`（带 retryable/status）与 `InputError` |
| `src/http.js` | DNS 校验/固定、公共地址判定、有界响应读取 |
| `src/providers/free.js` | 免费引擎集合（AnySearch / Bing / DuckDuckGo / SearXNG / 直连 / Jina） |
| `src/providers/minimax.js` | 上游 MCP 客户端（懒连接、连接超时、关闭有界） |
| `src/providers/deepseek.js` | 官方 Search/Fetch REST |
| `scripts/smoke.js` | 真实链路自检，不经 MCP，直接打 router |

---

## 3. 关键设计决策

### 3.1 错误分类决定是否回退

- 网络错误 / 超时 / 401 / 402 / 403 / 408 / 413 / 429 / 5xx → 可回退
- `ProviderError.retryable === false`（例如目标页面 404）→ **立即停止，不触发付费回退**
- `InputError`（参数不合法）→ 不回退
- 调用方 abort → 不回退、不写冷却

这条不是理论洁癖：目标页 404 是「有效结果」，继续换付费服务既浪费钱也不会变好。

### 3.2 空搜索结果是成功

空数组不等于失败。默认不回退，除非显式打开 `server.fallbackOnEmptySearch`。否则一次正常「无结果」会连带打穿所有付费渠道。

### 3.3 异常响应形状必须报错

早期 `normalizeMiniMaxSearch` / `normalizeDeepSeekSearch` 把「字段缺失或类型错误」也当成空数组，导致本应回退的故障被当成「查无结果」。现在只接受**显式的空数组**，形状不对就抛可重试错误。

### 3.4 DNS rebinding 防护（免费直连抓取）

`assertPublicUrl()` 只做早期检查，真正的防护在**连接层**：undici `Agent` 的 `connect.lookup` 里重新解析并校验，返回已验证地址给 socket，同时保留 Host/SNI。重定向逐跳复验。

**边界必须说清**：这只覆盖免费直连抓取。AnySearch / Jina / MiniMax / DeepSeek 的抓取发生在对方服务器，其出网策略不归本网关管。

### 3.5 MiniMax 上游生命周期

三个坑，都已修：

1. **连接可能永远不返回** → `connectTimeoutMs`（默认 15s）
2. **关闭时等未完成的连接会挂死** → `closeTimeoutMs`（默认 5s）+ 迟到连接的补救关闭
3. **一个调用方 abort 不能拖垮共享连接** → 内部连接用自己的 controller，调用方只做「可中断等待」

### 3.6 凭据边界

- Key 只存 `config.json`；`config.example.json` 的 Key 字段必须**留空**
- 出口统一脱敏：错误信息、attempts、status 都不含 Key
- 上游 stderr 设为 `ignore`，避免绕过网关的脱敏

> 曾经示例配置用 `REPLACE_WITH_*` 非空占位符，结果接收方看到付费渠道「已配置」却调用即失败。改成空字符串后，未填 Key 的渠道就是 `configured: false`。

---

## 4. 验证状态（截至 2026-10-30）

| 项目 | 状态 |
|---|---|
| 自动化测试 | **85/85 通过** |
| MCP 握手 | legacy + modern 双模式通过 |
| 真实 MCP 调用 | 搜索/抓取通过 |
| AnySearch | 搜索 + 抓取实测通过（匿名额度） |
| Jina Reader | 抓取实测通过 |
| MiniMax | 真实搜索通过 |
| DeepSeek | 充值后搜索 + 抓取通过 |
| Bing | 可达，但**相关性不稳定**（多次出现无关结果） |
| DuckDuckGo | **当前网络不可达**，按可重试故障降级 |
| SearXNG | 仅模拟测试，需配置实例后实测 |
| WorkBuddy 5.9.3 | 实机通过：Trust、3/3 工具、真实任务返回 `free/anysearch` + `free/direct` |
| Codex / DSH | **未验证** |
| 依赖审计 | npm 官方源 0 漏洞 |

---

## 5. 已知限制

- 免费搜索引擎的质量会随查询波动；不要期待稳定的相关性。
- 直连抓取只做 HTTP 请求与正文提取，**不执行 JavaScript**。
- SearXNG 需实例开启 `format=json`，很多公共实例不支持。
- MiniMax 默认用 `uvx` 动态拉包，该依赖不在 `package-lock.json`，也不在 `npm audit` 范围内。
- 抓取到的网页内容是**不可信数据**，可能含提示注入。

---

## 6. 明确未做（避免重复讨论）

- HTTP 传输 / 多客户端共享服务
- 响应缓存
- 自动修改客户端配置
- DSH 原生 provider bundle
- 质量/相关性感知路由
- New API 作为搜索网关（New API 是模型中继，不路由 `/v1/tools/search`；MiniMax 只有 MCP 接口，无法中转）

---

## 7. 分发包规则

产物：`unified-web-mcp-package/unified-web-mcp-0.1.0.zip`

**必排除**：`config.json`、`node_modules/`、`docs/`、开发中间产物
**必包含**：`src/`、`scripts/`、`test/`、`package.json`、`package-lock.json`、`README.md`、`INSTALL_NOTICE.md`、`AI_SETUP_PROMPT.md`、`config.example.json`、`.gitignore`

打包后必做三件事：
1. `npm test` 全绿
2. 用真实 Key 值扫描包内全部文本，确认零命中
3. 解压到全新目录跑 `npm ci && npm test`，再验一次 `createGateway` 只有 free 为 `configured: true`

---

## 8. 踩坑记录

| 现象 | 根因 | 处理 |
|---|---|---|
| 后台 shell 空转一整天 | `until [ -f report.md ]` 等的文件从未生成，父进程退出后子进程成孤儿 | 改用命令退出码判断，不轮询文件 |
| `rm -rf .superpowers` 报 Device busy | 目录内容已删空，句柄仍被占用 | 用 PowerShell `Remove-Item` 清空目录 |
| 测试中断言「截断后返回」 | 安全策略改为「超限拒绝」 | 测试按新契约更新，而非放松实现 |
| WorkBuddy 实机自动化点不中按钮 | Windows DPI 缩放 + Electron 焦点 | 用 CDP（`--remote-debugging-port`）结构化操作，不盲点坐标 |
