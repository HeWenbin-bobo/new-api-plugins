# WorkBuddy Panel Video

用于 **New API** 的任务插件，把 **WorkBuddy2API Panel** 的视频能力接入 OpenAI Video 风格的异步任务接口。

这是基于 Hub 版插件为 Panel 协议专门适配的独立插件，不是 New API 或 WorkBuddy 官方发布包。

## 版本

`1.1.0`

## 支持模型

- `minimax-video-h3`
- `kling-video-v3`

模型是否可用、分辨率与时长限制取决于 Panel 及其上游。MiniMax 实测接受 `768P` / `2K`，不接受 `720P`；不要把此经验外推为所有模型的永久限制。

## 协议适配

| 操作 | Panel 接口 |
|---|---|
| 创建视频任务 | `POST /v1/videos/generations` |
| 查询任务 | `GET /v1/videos/{task_id}` |
| 获取成品 | 使用任务完成响应中的 COS 签名直链 |

插件会：

1. 给裸模型名补上 `cn:` 前缀（Panel 的模型命名约定；Kling 的真实任务未实测）；
2. 固定 `wait=false`，使 New API 负责轮询；
3. 从顶层 `url`、`data.data[0].url` 或 `data.videos[0].url` 读取完成后的签名直链；
4. 下载 COS 视频时不携带 Panel API key；
5. 复用上游任务状态映射、用量字段和 MP4 artifact 投影。

**Panel 与 Hub 不是同一套接口。** Hub 使用 `POST /v1/videos` 和 `/content` 下载；不要把 Hub 的插件直接改个 Base URL 用于 Panel。

## 安装

### 1. 前置条件

- New API 已验证版本：`v1.0.0-rc.48`。
- Panel 已启用视频媒体能力。
- 已确认 `POST /v1/videos/generations` 存在。空参数应返回 400 参数校验，而不是 404。

### 2. 安装插件

将 `plugin.js` 作为 New API 的自定义 Task Plugin 上传/安装，插件 key 为：

```text
workbuddy-panel-video
```

版本为 `1.1.0`。数据库中的 `source` 必须是**完整 JS 源码**，不能只存 `file:///...` 路径。安装后检查运行日志没有 `compile task plugin` 错误。

### 3. 创建渠道

- 渠道类型：`Task Plugin (61)`
- Base URL：`http://wb2api-panel.local:7863`（或你的 Panel HTTP(S) 地址，不可嵌入凭据、查询参数或片段）
- 插件：`workbuddy-panel-video`
- 模型：`minimax-video-h3,kling-video-v3`
- abilities：按你的用户分组配置

若 Panel 与 New API 在同一台主机，可以将 `wb2api-panel.local` 映射到 `127.0.0.1`。不建议为了绕过 SSRF 而开放任意私有 IP。

### 4. SSRF 与 COS 白名单

插件的 `allowedHosts` 只包含本次实测的腾讯云 COS 域名；`buildContentRequest` 也会在插件内再次强制校验：只允许该域名的 HTTPS 绝对地址，拒绝其他主机、非默认端口、用户名密码及相对地址。`allowedHosts` 声明不能替代代码级校验。

```text
aigc-output-video-1326893053.cos.ap-guangzhou.myqcloud.com
```

如果 New API 开启了媒体下载的域名白名单，还需要允许该 COS 域名。Panel 的本地域名/端口也应按实际部署加入。不要全局关闭 SSRF，也不要向 COS 转发 Panel API key。

如果上游 COS 域名改变，需要同步更新 `plugin.js` 的 `CONTENT_HOSTS` 和 New API 的媒体下载白名单。

## 离线测试

```bash
npm test
npm run check
```

测试不连接 New API、Panel 或 COS，不使用真实凭据，不产生视频生成费用。覆盖 Panel 提交参数、模型前缀、任务查询、结果地址白名单、COS 鉴权隔离、Range 请求及响应渲染。

## 最小验证

```http
POST /v1/videos
Authorization: Bearer <NEW_API_TOKEN>
Content-Type: application/json

{
  "model": "minimax-video-h3",
  "prompt": "a small bird perched on a green leaf, gentle camera movement",
  "seconds": 5,
  "resolution": "768P"
}
```

然后轮询 New API 返回的公开任务 ID：

```http
GET /v1/videos/{task_id}
```

完成后下载：

```http
GET /v1/videos/{task_id}/content
```

应返回 `video/mp4`，且文件第 4–7 字节为 `ftyp`。

**真实视频可能产生费用。** 先用单模型、单入口、短时长测试；不要一开始就跑所有模型/入口的回退组合。

## 已验证范围

2026-11-05，在 New API rc.48 + 升级后的 Panel 上：

- MiniMax H3、5 秒、768P 任务成功完成；
- 从 COS 签名直链下载 MP4；
- New API `/content` 返回 HTTP 200、759,484 字节、`video/mp4`；
- `ftyp` 文件签名校验通过。

没有在本次适配中额外创建 Kling 测试任务，因此不声称 Kling 已完成同样的实测。

## 安全说明

- 仓库不包含 API key、Token、真实任务 ID、签名 URL、账号配置或测试视频。
- `ctx.apiKey` 只用于访问 Panel，不应转发到 COS。
- 保持 New API 的私有 IP 禁止策略，按域名精确放行。
- 视频直链通常有时效，请通过 New API 下载并自行保存需要的成品。
- Panel 的任务查询与限流策略由其实现决定；插件不绕过账号或限流。

## 文件

- `plugin.js`：完整插件源码。
- `package.json`：包信息和离线测试、JS 语法检查命令。
- `tests/plugin.test.js`：离线契约与安全测试。
- `README.md`：安装、协议与安全说明。
- `CHANGELOG.md`：版本记录。
- `.gitignore`：排除本地配置、密钥、日志与媒体产物。

## 维护提示

修改源码后，需让 New API 重新编译插件。数据库直改不一定触发热重载；可通过正规插件管理接口激活，或在维护窗口重启 master。不要误以为更新了文件就自动更新了运行时。
