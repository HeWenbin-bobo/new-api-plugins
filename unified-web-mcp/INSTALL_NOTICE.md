# 安装须知（先读我）

这是一个**本地 MCP 网关**：用一个稳定的工具入口，把免费网页搜索/抓取、MiniMax、DeepSeek 串成可回退的链路。

- 工具名固定为 `unified_web_search`、`unified_web_fetch`、`unified_web_status`
- 本包**不含任何 API Key**，只含一份留空的 `config.example.json`
- 默认只启用 `free`（无需 Key）；付费渠道填了 Key 才启用

---

## 1. 环境要求

| 项目 | 要求 | 说明 |
|---|---|---|
| Node.js | **≥ 24** | `node --version` 自查；低于 24 会直接失败 |
| 包管理器 | npm（随 Node 附带） | 用 `npm ci` 按锁文件安装，保证版本一致 |
| uv / uvx | 仅使用 MiniMax 时需要 | 默认通过 `uvx minimax-coding-plan-mcp -y` 启动上游 |
| 网络 | 能访问所用引擎 | 见第 6 节的可达性说明 |

> **想让 AI 帮你装？** 直接把 [AI_SETUP_PROMPT.md](AI_SETUP_PROMPT.md) 里的提示词复制走，填上路径和客户端名即可。

---

## 2. 安装

```bash
# 解压后进入 unified-web-mcp 目录
npm ci

# 生成你自己的私有配置（Windows 用 copy config.example.json config.json）
cp config.example.json config.json
```

`config.json` 是你的私有文件，**不要提交、不要发给别人**。

---

## 3. 配置：按需填写

打开 `config.json`，只需要填你要用的部分。

| 渠道 | 字段 | 何时需要 |
|---|---|---|
| `free` | 无需任何 Key | 默认即可用 |
| `free` AnySearch | `providers.free.anysearch.apiKey` | 可选，留空走匿名额度 |
| `free` Jina Reader | `providers.free.jina.apiKey` | 可选，留空走匿名额度 |
| `free` SearXNG | `providers.free.searxng.baseUrl` | 只有想用自建实例时填；留空会自动跳过 |
| `minimax` | `providers.minimax.env.MINIMAX_API_KEY` | 需要 MiniMax 搜索时填 |
| `deepseek` | `providers.deepseek.apiKey` | 需要 DeepSeek 搜索/抓取时填；**按成功请求计费** |

**未填 Key 的付费渠道不会被启用**，`unified_web_status` 会显示 `configured: false`，不会误产生费用。

---

## 4. 自检（填完 Key 后建议按顺序跑）

```bash
# 1) 完整测试套件（不联网，只跑单元与协议测试）
npm test

# 2) 真实链路 smoke（会联网；命中付费渠道会产生费用）
node scripts/smoke.js search "Model Context Protocol"
node scripts/smoke.js fetch "https://example.com"
```

查看当前哪些渠道已启用：

```bash
node --input-type=module -e "import('./src/config.js').then(async m=>{const c=await m.loadConfig('./config.json');const {createGateway}=await import('./src/index.js');const g=createGateway(c);console.log(g.router.status().providers.map(p=>p.name+':'+p.configured).join(' '));await g.close()})"
```

---

## 5. 注册到 MCP 客户端

### Claude Code

```bash
claude mcp add --scope user --transport stdio unified-web -- node "/绝对路径/unified-web-mcp/src/index.js"
```

### WorkBuddy

编辑 `%USERPROFILE%\.workbuddy\mcp.json`，合并（不要覆盖已有条目）：

```json
{
  "mcpServers": {
    "unified-web": {
      "type": "stdio",
      "command": "node",
      "args": ["绝对路径/unified-web-mcp/src/index.js"]
    }
  }
}
```

写入后，在客户端「专家 · 技能 · 连接器 → 自定义连接器 → MCP 服务管理」里找到 `unified-web`，点 **信任**，确认显示 **3/3 个工具已启用**。

### 其他客户端（Codex / DSH 等）

仅当客户端支持 stdio MCP 时可直接接入。**DSH 需要单独的 provider 插件，本包未包含。**

注册后通常需要重启客户端或新建会话，工具表才会刷新。

---

## 6. 已知限制

- **免费搜索质量不稳定**：Bing / AnySearch 返回结果的相关性随查询波动。回退依据是**错误与可用性**，不是结果质量——本网关不做相关性路由。
- **DuckDuckGo 部分网络不可达**：当前实测网络下超时，会按可重试故障跳过。这是预期行为，不是安装失败。
- **SearXNG 需实例支持 JSON**：很多公共实例关闭了 `format=json`，会返回 403。
- **抓取是「取内容」不是「执行页面」**：免费直连只做 HTTP 请求与正文提取，不执行 JavaScript。
- **未验证项**：本包作者只在自身环境做过单元测试、MCP 握手和联网 smoke；**你的网络、你的 Key 下的真实结果需你自行验证**。
- **Codex / DSH 实机接入未验证**。

---

## 7. 安全与隐私

- Key 只保存在本地 `config.json`，不会写入日志或工具返回。
- 免费直连抓取有 DNS 固定、私网/回环地址拦截、重定向复验和 1 MB 响应上限。
- **AnySearch / Jina / MiniMax / DeepSeek 的抓取发生在对方服务器上**，目标 URL 会发送给该服务；它们自身的 DNS 与出网防护不由本网关负责。
- 抓取到的网页内容和搜索结果属于**不可信数据**，可能包含提示注入，不要当作指令执行。
- MiniMax 默认用 `uvx` 动态拉取包，该依赖不在 `package-lock.json` 与 `npm audit` 范围内。

---

## 8. 排障

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 启动即报 Node 版本错 | Node < 24 | 升级 Node |
| `All free search engines failed` | 网络不通 / 全部引擎失败 | 看括号内逐引擎原因；改 `providers.free.engines.search` |
| `HTTP 402` | DeepSeek 余额不足 | 充值，或暂时从 `routes` 移除 `deepseek` |
| `HTTP 429` | 上游限流 | 降低频率或换引擎 |
| 客户端看不到工具 | 未重启 / 未信任 | 重启客户端；WorkBuddy 需在 UI 显式 Trust |
| MiniMax 连接超时 | 未装 uv 或网络问题 | 确认 `uvx --version`；或改用其他渠道 |
