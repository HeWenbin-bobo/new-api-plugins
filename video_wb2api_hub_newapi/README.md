# WorkBuddy Video Hub

将 new-api 的 OpenAI Video 请求转发到 **workbuddy2api-hub**，使用 `minimax-video-h3` 或 `kling-video-v3` 生成视频。

**本插件仅适用于 Hub 版，不兼容接口不同的 wb2api Panel 版。**

- 对外接口：`POST /v1/videos`、`GET /v1/videos/{id}`、`GET /v1/videos/{id}/content`
- 上游接口：WorkBuddy `POST /v1/videos`、`GET /v1/videos/{id}` 及其签名内容地址
- 支持 JSON 文生视频、JSON 图片 URL 图生视频、multipart 图片上传
- 无需修改 new-api 或 workbuddy2api-hub 源码，无第三方运行依赖

需要支持 **Task Plugin API v1 / `openai_video`** 的 new-api 版本。旧版若没有任务插件管理入口，需要先升级。接口契约以 new-api 当前官方文档为准：<https://github.com/QuantumNous/new-api/tree/main/docs/plugin-api>。

## 1. 准备 WorkBuddy

1. 启动 workbuddy2api-hub，默认端口为 `8788`。
2. 在看板中启用**媒体能力/媒体模块**，并确认可用模型目录包含 `minimax-video-h3` 和 `kling-video-v3`。
3. 在看板「设置」中创建 API Key，并确保该 Key 的模型限制和出口配置允许此视频模型。

插件向上游提交的地址是 `{Base URL}/v1/videos`，因此 new-api 渠道中的 Base URL 不要带 `/v1`。

## 2. 上传插件

在 new-api 使用 root 管理员账号：

1. 打开任务插件管理页。
2. 上传本目录的 [`plugin.js`](./plugin.js)，保存并激活。
3. 插件 key 为 `workbuddy-video-hub`，版本为 `1.2.0`。

后续修改源码时请递增 `meta.version` 后上传新版本；new-api 不接受同 key、同版本但内容不同的源码。

## 3. 创建渠道

| 配置项 | 值 |
|---|---|
| 渠道类型 | `Task Plugin`（任务插件，类型 61） |
| 插件 | `workbuddy-video-hub` |
| Base URL | WorkBuddy 地址，例如 `http://wb-proxy:8788` |
| 密钥 | **WorkBuddy 看板创建的 API Key**，不是 new-api 客户端令牌 |
| 模型 | `minimax-video-h3`、`kling-video-v3` |

Base URL 按 new-api 实际运行环境填写：

- 两个服务同一 Docker Compose 网络：优先用服务名，如 `http://wb-proxy:8788`。
- new-api 在容器内：`127.0.0.1` 指向 new-api 容器自身，**不是宿主机**。
- new-api 直接运行在宿主机，WorkBuddy 也监听本机：才使用 `http://127.0.0.1:8788`。

按需为模型配置 new-api 计费。插件只上报秒数、分辨率和 WorkBuddy credit 等用量事实，不自行计算价格。

## 4. 调用

以下示例中的 `NEW_API_BASE_URL` 不带末尾 `/v1`，`NEW_API_KEY` 是调用 new-api 的客户端令牌。不要把真实密钥提交到源码或日志。

### 文生视频（JSON）

```bash
curl -X POST "$NEW_API_BASE_URL/v1/videos" \
  -H "Authorization: Bearer $NEW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-video-h3",
    "prompt": "一只猫在阳光下的窗边伸懒腰，镜头缓慢推进",
    "seconds": 5,
    "size": "1280x720"
  }'
```

提交成功后，从响应中取得 new-api 返回的任务 `id`：

```bash
curl "$NEW_API_BASE_URL/v1/videos/$VIDEO_ID" \
  -H "Authorization: Bearer $NEW_API_KEY"
```

### 图生视频（图片 URL）

`input_reference` 可传公网 HTTP(S) 图片地址或 data URL：

```bash
curl -X POST "$NEW_API_BASE_URL/v1/videos" \
  -H "Authorization: Bearer $NEW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kling-video-v3",
    "prompt": "人物自然转头，头发随微风轻动",
    "input_reference": "https://example.com/input.png",
    "seconds": 5
  }'
```

### 图生视频（本地上传）

```bash
curl -X POST "$NEW_API_BASE_URL/v1/videos" \
  -H "Authorization: Bearer $NEW_API_KEY" \
  -F "model=kling-video-v3" \
  -F "prompt=镜头缓慢推进，主体自然运动" \
  -F "seconds=5" \
  -F "input_reference=@./input.png"
```

插件通过 new-api 的文件引用机制将上传图片转为 data URL 后交给 WorkBuddy，解码前图片上限为 **8 MiB**。文件字段仅支持 `input_reference`；上传文件时不要同时传图片 URL。

### 下载视频

任务状态变为 `completed` 后：

```bash
curl -L "$NEW_API_BASE_URL/v1/videos/$VIDEO_ID/content" \
  -H "Authorization: Bearer $NEW_API_KEY" \
  -o result.mp4
```

new-api 通过 `GET /v1/videos/{id}/content` 代理下载。插件按上游任务 ID + 渠道密钥请求 WorkBuddy 内容路由，利用其「签名或 API Key」双重鉴权——即使签名 URL 过期（有效期约 1 小时），仍可用渠道密钥取回 WorkBuddy 保留期内的产物。分段读取的 `Range`/条件请求头会被转发，但是否真正返回 `206`/分段取决于 WorkBuddy 是否实现（当前其下载端返回完整 200 响应）。

## 请求与状态说明

- `prompt` 必填；`seconds` 必须为正数，也兼容 `duration` 输入并统一转换为 `seconds`。
- 支持 WorkBuddy 已有的 `size`、`resolution`、`last_image`、`reference_images` 等 JSON 字段，具体可用范围由 WorkBuddy 模型目录决定。
- `queued` / `pending` → 排队；`submitted` / `processing` / `in_progress` / `running` → 处理中；`completed` / `succeeded` → 成功；失败、拒绝、取消及丢失 → 失败。
- 签名 URL 过期、WorkBuddy 重启导致任务数据不可用、媒体模块关闭或 Key 权限不足，都可能使轮询/下载失败，请先检查 WorkBuddy 看板与日志。

## 离线测试

```bash
npm test
node --check plugin.js
```

测试使用 Node.js 内置测试框架，不需要安装依赖，不连接 new-api 或 WorkBuddy，不使用真实凭据，也不会产生视频生成费用。覆盖请求转换、multipart 文件占位、鉴权、轮询、状态映射、签名下载、Range 请求及响应渲染。
