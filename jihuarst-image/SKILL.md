---
name: jihuarst-image
description: Use when 用户要求使用 jihuarst 生成或编辑图片、需要上传参考图做图生图/局部重绘/多图融合，或指定 gpt-image-2.6-sunburst / gpt-image-2.6-exact / gpt-image-2.6-flare / gpt-image-2.5 / gpt-image-2.5-flare / gpt-image-2 / hunyuan-image-alpha / hunyuan-image-alpha-edit 出图，或需要生成 SVG、GIF、传递 2.6 新参数，或在多个 jihuarst API 地址之间自动切换完成出图。
---

# jihuarst 生图 / 改图

使用 OpenAI 兼容接口出图，运行与离线测试均只依赖 Python 3.9+ 标准库。

两种模式，按是否传参考图自动选择：

| 模式 | 触发条件 | 端点 | 传输格式 |
|---|---|---|---|
| 文生图 | 不传 `-r` | `POST /v1/images/generations` | JSON |
| 参考图改图 | 传 `-r`（1 张或多张） | `POST /v1/images/edits` | multipart/form-data |

## 调用

在技能目录中运行（Windows 用 `python`，其他系统可用 `python3`）：

```bash
# 纯文生图
python scripts/generate.py "详细图片描述提示词" -o "output.png"

# 单张参考图改图
python scripts/generate.py "把背景改成蓝色，保持人物不变" -r photo.png -o out.png

# 多图参考融合（字段自动用 image[]）
python scripts/generate.py "把这两张图的产品合成到同一张海报里" -r a.png -r b.png -o out.png

# 局部重绘（mask 透明区域为可编辑区域，仅限单张参考图）
# 注意：prompt 要写明"遮罩外保持原样"，否则上游可能整体重绘
python scripts/generate.py "把圈出的区域换成一只猫，遮罩外保持原样" -r photo.png -m mask.png -o out.png

# 指定尺寸 / 质量 / 一次出 4 张（会写成 out-1.png … out-4.png）
python scripts/generate.py "一颗苹果" --size 1536x1024 --quality high -n 4 -o out.png

# 只要某个模型或某个入口（调试用）
python scripts/generate.py "测试" --model gpt-image-2.5 --base-url https://api.jihuarst.top --json

# 2.6：SVG 配置，--svg 接受任意非 null JSON（字符串、布尔值、对象等）
python scripts/generate.py "生成流程图" --model gpt-image-2.6-exact --svg true -o diagram.svg

# 2.6：GIF 帧参数；frame_count 是单个 GIF 内的帧数，不是返回图片张数
python scripts/generate.py "让云层缓慢移动" --model gpt-image-2.6-exact \
  --frame-count 8 --frame-duration-ms 100 -o animation.gif

# 2.6：本地标注图用于 edits，JSON 标注可用于 generations 或 edits
python scripts/generate.py "按标注修改" -r photo.png --markup annotation.png \
  --model gpt-image-2.6-exact -o edited.png
python scripts/generate.py "按标注修改" --markup-json '{"layer":1}' \
  --model gpt-image-2.6-exact -o edited.png
```

也可从任意工作目录用脚本绝对路径调用。成功后会打印实际使用的 URL、模型、端点，以及上游重写后的提示词。

## 参数

| 参数 | 类型 | 实际发送 / 客户端行为 |
|---|---|---|
| `prompt` | 字符串 | 文生图写入 JSON `prompt`；改图写入 multipart 文本字段 |
| `-o, --output` | 本地路径 | 不进入 API 请求；默认 `jihuarst-image.png`，`-n>1` 时加 `-1/-2…` 后缀 |
| `-r, --ref IMAGE` | 本地文件 | 单张作为 multipart `image` 上传，多张分别作为 `image[]` 上传；提供后切换至 edits，可重复使用 |
| `-m, --mask` | 本地 PNG | 作为 multipart `mask` 上传；仅允许单张参考图，透明处为待编辑区域，与两种 markup 输入互斥 |
| `--size` | `auto` 或 `宽x高` | 原样透传 `size`；网关实际生效范围见下方实测表 |
| `--quality` | `low` / `medium` / `high` / `auto` | 原样透传 `quality` |
| `--input-fidelity` | `low` / `high` | 仅 edits 请求发送 `input_fidelity` |
| `--output-format` | `png` / `jpeg` / `webp` / `svg` / `gif` | 发送 `output_format`；`svg` / `gif` 仅限 2.6 并选择 2.6 链，普通光栅格式不改变模型链；显式旧模型与矢量格式组合在请求前失败 |
| `--complexity` | `low` / `medium` / `high` | 仅 `gpt-image-2.6-*`；原样发送 `complexity` |
| `--svg` | 任意非 null JSON | 仅 `gpt-image-2.6-*`；generations 保留原生 JSON 类型，edits 序列化为紧凑 JSON 文本字段 `svg`；宽松输入是网关兼容扩展 |
| `--frame-count` | 整数 2–16 | 仅 `gpt-image-2.6-*`；发送 `frame_count`，表示单个 GIF 内的帧数，不增加 `data` 图片条目数 |
| `--frame-duration-ms` | 整数，至少 20 | 仅 `gpt-image-2.6-*`；发送 `frame_duration_ms`；非法值在请求前拒绝 |
| `--markup IMAGE` | 本地图片 | 仅 `gpt-image-2.6-*` edits；作为独立 multipart 文件 `markup` 上传，与 `--markup-json`、`--mask` 互斥且必须提供 `-r` |
| `--markup-json JSON` | 任意非 null JSON | 仅 `gpt-image-2.6-*`；generations 保留原生 JSON 类型，edits 序列化为紧凑 JSON 文本字段 `markup`；与本地 `--markup`、`--mask` 互斥，可不带 `-r` |
| `-n, --count` | 整数 1–10，默认 1 | 发送整数 `n`；实际交付张数在本地校验 |
| `--timeout` | 正有限秒数，默认 180 | 仅控制客户端单次请求等待，不进入 API 请求；零、负数、NaN 和无穷大在请求前拒绝 |
| `--model` / `--base-url` | 模型 ID / 网关地址 | 限定候选范围；不扩展回退链 |
| `--json` | CLI 开关 | 不进入 API 请求；成功时向 stdout 输出本地交付摘要 |

### 参数边界与后处理

- 脚本固定请求 `response_format=url`，优先取得较小的 JSON 响应再下载图片，避免依赖数 MiB 的内嵌 base64 JSON；这是 Jihuarst 部署特定的兼容选择，不是 OpenAI GPT Image 官方合同，官方接口返回 base64。解析器仍兼容 `b64_json`、data URL 和 HTTP(S) 图片 URL。接口支持某字段不代表所选网关、模型会实现其语义。
- `background` 和透明背景后处理**不是当前 CLI 参数**。需要透明背景时，应对成功保存的 PNG 另行做本地透明化处理，不得将其描述为上游直接交付。`--output-format` 只转发格式请求并保存上游实际返回的字节，不做本地格式转换；旧网关曾忽略 JPG/WebP 字段，最新请求因图片 URL 下载失败而不能确认当前格式语义。
- 提示词、遮罩、模型与尺寸最终由上游解释；客户端验证文件数量、格式和保存结果，不保证构图、风格或遮罩外像素绝不变动。
- `complexity`、`svg`、`frame_count`、`frame_duration_ms` 和两种 markup 输入只能与 `gpt-image-2.6-sunburst`、`gpt-image-2.6-exact`、`gpt-image-2.6-flare` 一起使用；`--output-format svg|gif` 同样受此限制。这是客户端的保守路由策略，不是 New API 的通用模型限制。显式选择非 2.6 模型会在请求前失败；未指定 `--model` 时，提供这些 2.6 选项后每个 URL 就只尝试这三个 2.6 模型，不会把参数发给旧模型。
- `--svg` 和 `--markup-json` 不假设网关的具体对象结构：按已确认的设计，客户端接受任意非 null JSON，作为宽松兼容扩展原样转发。OpenAI 官方 `svg` 是包含 `model`、`reasoning` 的结构化配置，不是任意 JSON；官方 generations schema 不包含 `markup`，因此 generations 的 `--markup-json` 同样是 Jihuarst/New API 兼容扩展。New API 的 `json.RawMessage` 只证明值可以转发，不证明任意形状符合上游语义。multipart 中的 JSON 字段统一紧凑编码；`complexity`、`frame_count`、`frame_duration_ms` 使用十进制文本，generations 请求则保留原生 JSON 类型。
- `frame_count=2..16` 和 `frame_duration_ms>=20` 采用官方输入范围，并在付费请求前校验。官方还定义默认 9 帧、默认 200 ms、帧时长取整至 10 ms 及编码上限 655350 ms；客户端不复制这些上游变换或额外上限。官方 markup 是 edits 的透明 PNG，叠加首图，方向校正后尺寸一致，且不能与 mask 同用；本地文件/JSON 与 mask 的互斥由客户端提前拒绝。
- SVG 与 GIF 按上游返回的字节原样保存到用户指定的输出路径。SVG 只做有界根标签识别，**不会清理、转义、渲染或执行 SVG，也不会获取其引用的资源**；不得把保存成功描述为 SVG 已安全消毒或已视觉验收。客户端不会自动转换文件格式。
- 提示词、数量、参考图、遮罩、2.6 参数与 markup 在付费请求前校验；参考图、遮罩和本地 markup 必须存在、非空且各不超过 64 MiB。输出目录在交付阶段创建，文件系统写入或恢复错误会触发后续选定组合，不作为输入错误提前终止。真实配置文件留在本地，不能进入文档、归档或命令参数。

## API Key

Key 保存在技能根目录的 `config.json`；将 `config.example.json` 复制为该文件并填写自己的 key：

```json
{"api_key": ""}
```

各客户端副本的 `config.json` 是**独立文件**，不存在"自动同源"——复制目录时请一并复制同一把 key。

不要在日志、回复或命令参数中显示 key。脚本始终从自身上一级的 `config.json` 读取，因此复制整个技能目录即可使用。除首选的 HTTP 入口外，其余默认回退地址均使用 HTTPS。

## 强制回退顺序

**URL 优先，模型其次。** 在当前 URL 上依次尝试全部模型，全部失败后切换到下一 URL：

默认每个 URL 的 GPT 模型顺序为：`gpt-image-2.6-sunburst` → `gpt-image-2.6-exact` → `gpt-image-2.6-flare` → `gpt-image-2.5` → `gpt-image-2.5-flare` → `gpt-image-2`，随后按模式追加一个混元模型。

| 尝试 | Base URL | 模型数 |
| -- | --- | --- |
| 1-7 | `http://222.211.75.198:3000` | 6 个 GPT 模型 + 当前模式的混元模型 |
| 8-14 | `https://gz-api.jihuarst.top:8443` | 同上 |
| 15-21 | `https://api.jihuarst.top` | 同上 |
| 22-28 | `https://sg-api.jihuarst.top` | 同上 |

提供任一 2.6 新参数且未指定 `--model` 时，每个 URL 只尝试前三个 2.6 模型，默认共 12 个组合；显式 `--model` / `--base-url` 仍严格限定候选范围。

模型链按模式分流：**不传 `-r` 的文生图**末位追加 `hunyuan-image-alpha`；**传 `-r` 的改图**末位追加 `hunyuan-image-alpha-edit`。混元 `-edit` 是上游目录标记的 `image-to-image` 模型，**只能与参考图一起用于 edits 模式**，因此不会进入默认文生图回退链；反之 `hunyuan-image-alpha` 标记为 `text-to-image`，不进入默认改图链。显式 `--model` 指定时跳过该分流（只试这一个模型），便于调试。

新入口的 `/v1/models` 已确认包含这两个混元模型 ID；模式依据上游目录标签与[混元接入文档](https://github.com/dingminhua/dsh-connect-workbuddy/blob/main/docs/IMAGE_GEN.md)。2026-11-04 已在新入口分别完成一次 `hunyuan-image-alpha` 文生图和一次 `hunyuan-image-alpha-edit` 单参考图改图，均成功返回并保存 1792×1344 PNG。下方尺寸、质量、透明背景等参数实测结论仍仅来自三个旧 GPT Image 模型，不外推到混元或 2.6 模型。

2026-11-09 的只读目录检查确认 `https://api.jihuarst.top/v1/models` 包含三个 `gpt-image-2.6-*` ID；`gpt-image-2.6-exact` 是该目录的模型 ID，不称为 OpenAI 官方模型枚举。New API `v1.0.0-rc.49` 及 PR #8208 提供 `complexity`、`svg`、`frame_count`、`frame_duration_ms`、`markup` 的转发契约，其中本地 `markup` 是 edits 的独立 multipart 文件；`output_format` 在 New API 中早于该 PR 存在。这些是**目录与接口契约证据，不代表每次客户端交付均成功**。当前 OpenAI OpenAPI 与 Python SDK 对 edits SVG 的定义存在版本冲突，客户端只验证 SVG 字节保存，不宣称 edits SVG 已获上游支持。

同日固定该 HTTPS 入口逐模型执行一次基础付费文生图测试：`gpt-image-2.5` 和 `gpt-image-2` 成功交付 1536x1024 PNG，其余六个模型的客户端未保存图片。三个 2.6 模型在 85–141 秒后观察为 `RemoteDisconnected`；`gpt-image-2.5-flare` 为同类异常，`hunyuan-image-alpha` 为 18 秒后的同类异常，`hunyuan-image-alpha-edit` 为 TLS EOF。默认等待上限已经是 180 秒；这些异常发生在读取响应阶段，不是 Python `socket.timeout`，现有证据不能确定断开发生在哪一层，也不能改判为客户端等待超时。用户随后提供的渠道记录和手动直连报告显示：三个 2.6 模型均返回 HTTP 200 和有效 b64_json 图片，直连耗时 102–119 秒；混元文生图及改图也成功返回有效图片，改图直连耗时 9 秒。该报告证明上游能够完成生成，不自动证明客户端路径已恢复；本轮客户端未重试或切换入口，失败请求可能已产生费用。

同日随后对全部八个模型各执行一次**单参考图 edits** 付费测试，仍固定该入口、单模型、1536x1024、low，使用同一本地生成的 64x64 PNG 和默认 180 秒等待，不重试。四项成功交付 1536x1024 PNG：`gpt-image-2.6-exact`（1,493,038 字节，SHA-256 `03be70591bfca4009d069aacd827ab530942f97cadb7ffde21d63bec8a9a57fe`）、`gpt-image-2.5`（1,640,153 字节，SHA-256 `06eb5713a873c7f939b808774431115346f81f3d2ce5bf87512c94df3ce4039a`）、`hunyuan-image-alpha`（858,080 字节，SHA-256 `ad9a3ad310491a714ee8630b5683501cbfdb1f5392cb11c688b8d19d118f0ba8`）和 `hunyuan-image-alpha-edit`（930,214 字节，SHA-256 `974c8ad8cf2fb8f3130ed766d172061c67fbd4af75defbff5a26af8df4fc076d`）。四项未保存图片：`gpt-image-2.6-sunburst` 与 `gpt-image-2.6-flare` 为 `RemoteDisconnected`，`gpt-image-2.5-flare` 为响应 JSON 截断（`JSONDecodeError`），`gpt-image-2` 为 TLS EOF。文件大小、SHA-256、PNG 签名和尺寸已独立复核；运行器因存在失败项以退出码 1 结束。本轮只覆盖单图 edits，不覆盖多图、mask、SVG/GIF/markup；未验收视觉质量或实际费用，失败请求仍可能已生成并计费。

- 本轮测试完成后，用户补充提供 new-api HTTP 200 日志及独立直连结果：sunburst、flare 的 base64 JSON 响应约 2.7–2.9 MiB，指定 `response_format=url` 后三个 2.6 模型均返回 270–429 字节的 JSON 和图片 URL。这证明该部署可避开大 base64 响应，但不把 `RemoteDisconnected` 直接解释成客户端主动断开或 256 MiB 读取上限触发。生产脚本随后将 generations 与 edits 的默认请求格式改为 `url`，保留旧 base64 响应解析、URL 下载安全限制和默认 180 秒超时；未把 2–3 MiB 误判为超过客户端上限。修改后仅对 sunburst 和 flare 各进行一次单图 edits 真实复测，两项均未再出现 `RemoteDisconnected`，但仍未完整交付：sunburst 在 33.0 秒后的图片 URL 下载阶段失败；flare 在 49.9 秒返回 3 个图片条目，与 `n=1` 不符而被严格数量校验拒绝。两项均无本地文件，未重试。原始响应未落盘，下载错误细节又被归一，现有日志不足以进一步定位 sunburst 的下载失败原因。

## 2026-11-09 完整验证矩阵

随后按用户明确的全量验证授权，继续使用同一 HTTPS 入口和显式单模型，不扩大回退范围，且每项只启动一次。输入仅为本地生成的 64x64 PNG，不上传私人文件；没有可靠单价，失败请求也可能已产生费用。所有产物、完整响应和诊断记录保存在忽略的 `.omc/artifacts/`，不进入归档或公开状态。

最新默认 URL 模式下，七个 generations 请求均 HTTP 200 且各有一个 `data` 条目；本地完整交付仅 `hunyuan-image-alpha` 一项：1536x1024 PNG，2,022,259 字节，SHA-256 `0e08546dd5e5b2cf2bf20893fe3ed7fa64fa0a6b1915805be578665edf301e9b`。六个 GPT 模型的 URL 主机为 `img.hud.im`，其中五项下载 HTTP 403，flare 为 180 秒 URLError/超时；均没有本地文件。

最新八模型单图 edits 均 HTTP 200 且各有一个条目。`hunyuan-image-alpha` 与 `hunyuan-image-alpha-edit` 分别交付 1536x1024 PNG（1,441,819 / 838,126 字节，SHA-256 `ce53af2896ddf7fa1b10aee584e11918143588a2d1c617b94462f78427ef4446` / `0ca34001d2bc9da2e729670bdd155a47134e977a474cc64ce335e79ead9284ee`）；六个 GPT 模型下载均失败（五次 HTTP 403，sunburst 为 180 秒 URLError）。此前 flare 一次 `n=1` 返回三条目的现象没有复现，仍保留严格数量校验，不为通过而截断额外条目。

三个 2.6 模型的 `complexity=low`、exact 的 SVG 和 GIF 请求均 HTTP 500，网关报告 `auto` 分组没有可用渠道；本地 markup 文件与 JSON markup 两项也为相同 HTTP 500。已离线核对实际请求包含 `complexity`、`output_format=svg|gif`、帧参数、JSON `svg` / `markup` 和独立 multipart `markup` 文件，但这只证明客户端编码，不证明上游参数语义；这些项目均无产物，也未验收 SVG/GIF 或标注效果。

其他真实路径结果：

| 案例 | 观察结果 | 完整本地交付 |
| --- | --- | --- |
| `n=2`，2.5 | 生成 HTTP 200，恰好两条目；下载一次超时、一次 403 | 无，两张均未保存 |
| 多图 edits，2.5 | 96.9 秒 `RemoteDisconnected`，无 HTTP 状态 | 无 |
| 单图 mask，2.5 | 生成 HTTP 200，下载 403 | 无，未验证遮罩语义 |
| `input_fidelity=high`，exact | 生成 HTTP 200，下载超时 | 无 |
| `size=2048x2048`、`quality=medium`，2.5 | 生成 HTTP 200，下载 403 | 无，不能验证实际尺寸/质量 |
| 强制 b64 generations，2.5 | 私有诊断请求覆盖 response_format；有效内嵌图片 | PNG 1536x1024，1,093,349 字节，SHA-256 `90fdff797430fb99ff7248d39d0a74a07431fb876cabd8294b68d6eae5a9ab4b` |
| 强制 b64 edits，2.5 | 私有诊断请求覆盖 response_format；有效内嵌图片 | PNG 1536x1024，1,083,623 字节，SHA-256 `24770c1c08900268be795251f35c8b9d9e3644367b0021b64e46acc7d899a2cd` |
| `output_format=jpeg`，2.5 | 生成 HTTP 200，下载 403 | 无，不能确认实际上游格式 |
| `output_format=webp`，exact | 生成 HTTP 200，下载超时 | 无，不能确认实际上游格式 |

强制 b64 仅用于忽略目录中的诊断 opener；生产默认仍是 URL。两项 b64 成功证明兼容路径能够完整交付，不证明 URL 模式已完整交付。用户提供的 URL 已用于无新生成、无网关凭据的同机下载对照：curl HEAD 为 200，curl GET 为 200 但 90 秒只收到 269,671 字节并超时；系统 urllib、去固定 IP 的标准 urllib 及生产下载器在使用默认 Python UA 时均为 403。相同无代理 HTTP/1.1 curl 只把 UA 改为 `Python-urllib/3.13` 时得到 403；生产安全下载器改用 `Mozilla/5.0` 后得到 200 `image/png`，但正文在 91 秒后仍超时，没有保存文件。最终生产 opener 默认复测在 181.3 秒后为 `URLError` / `TimeoutError`，没有状态码或文件；同一 UA 的普通 HTTPS 连接也在取得 200 响应头后于 150.9 秒超时。Range 探针仍返回 200 而非 206、没有 `Content-Range`，且正文未完成。故已固定最小 UA 兼容回归，但完整 URL 下载故障仍未解决；没有通过关闭代理隔离、SSRF/TLS 校验或无限延长超时来掩盖故障，后续须以最终文件、签名、大小和 SHA-256 为交付证据。

## 下载、失败回退与本地保存

响应支持 `b64_json`、data URL 与 HTTP(S) 图片 URL；三种图片来源统一执行 64 MiB 单图上限、256 MiB 本次总图片上限和 PNG/JPEG/GIF/WebP 签名或有界 SVG 根标签校验，base64 在解码前也限制编码长度。远程图片下载发送普通 `Mozilla/5.0` User-Agent，不转发网关 API key；HTTP 200 响应头不代表完整交付。为防 SSRF，初始 URL 和每次重定向仅允许解析到公网 IP 的 HTTP(S) 地址，连接固定到已校验 IP 且不跟随系统代理，HTTPS 保留原主机名进行证书校验；私网、回环、链路本地、组播和保留地址会被拒绝。图片重定向响应会及时关闭，避免读取不受信任的多余响应体。

网络、HTTP、响应解析、图片下载、图片大小或格式校验、数量不足、空 `data`、非数组 `data`，以及本地输出写入或恢复失败，都会记录脱敏后的失败摘要并继续下一 URL/模型组合；非 HTTP(S) 或 HTTPS 降级重定向会拒绝当前组合并继续回退。**即使上游已返回图片产物且可能已计费，后续交付失败也不会终止回退，而会提交下一组合重新生图，可能产生重复费用。**只有所请求的完整图片集全部成功保存到本地才返回成功；不完整图片集不会被保存为成功结果。只有全部 28 个默认生成组合（或 2.6 参数 / 显式 `--model` / `--base-url` 限定的所有组合）均失败，才能说“本次未能完整保存所请求的图片”。最终错误会汇总各组合失败原因，并明确提示部分尝试可能已生成并计费、重试其他组合可能产生重复费用，请核对上游用量。

完整图片集通过同目录临时文件写入、flush/fsync 后逐文件原子替换，替换前会备份已有目标。任一文件失败会清理临时文件并尽可能逆序恢复此前替换的旧文件；若文件系统也拒绝恢复，会保留未能恢复的备份并在错误中报告其路径，供手动恢复，不承诺跨文件绝对事务。

> 首选地址 `http://222.211.75.198:3000` 是 **HTTP 明文连接**（非 HTTPS）：key、提示词与参考图在该链路上不加密，仅建议在可信内网/专线环境使用；公网环境可临时用 `--base-url` 跳过它。
> `sg-api` 为网关 `/api/status` 公告的新加坡备用入口，已实测可用；若某段时间不可达会自动回退到其他地址。

## 网关实测能力（重要，避免误用）

以下为本机截至 2026-11-04 对线上 Jihuarst 网关的观测；除另行注明混元的测试外，参数结论仅来自三个旧 GPT Image 模型（2.5、2.5-flare、2），不是 2.6 的实测结论。它们不是服务商承诺，也不能外推到其他部署或后续版本；其他站点的 Images / Responses API 文档不能替代本网关实测。更新脚本前请勿凭 OpenAI 官方文档假设：

| 能力 | 实测结果 | 说明 |
|---|---|---|
| `/v1/images/generations` | ✅ | 文生图主通道 |
| `/v1/images/edits` | ✅ | 参考图改图，单图 `image`、多图 `image[]` 均可 |
| `mask`（局部重绘） | ⚠️ 接受但不强制 | 实测遮罩确实生效（遮罩外像素基本原样保留），但**上游不会硬性限制**：若 prompt 表述为"整体换风格/换配色"，模型仍会越过遮罩重绘全图。要限定局部务必在 prompt 里明确"遮罩外保持原样" |
| `n` > 1 | ✅ 真实生效 | 返回多张且按张计费（n=2 → charged_quota 翻倍） |
| `size` | ⚠️ 有条件 | 1536x1024 / 1024x1536 / 1792x1024 / 1024x1792 / 2048x2048 精确生效；**总像素低于 ~1254×1254（1.57M）时被抬升为 1254×1254**，如 1024x1024、768x768、512x512 均被忽略 |
| `quality` | ⚠️ 接受但差异不明显 | 不报错；耗时/体积未见稳定差异 |
| `input_fidelity` | ⚠️ 接受但不稳定 | 传入会改变上游尺寸选择（曾出现 high 时输出 1024x1536） |
| `background=transparent` | ❌ **无效** | 三个旧 GPT Image 模型都返回 RGB 不透明白底 PNG，不会有 alpha 通道 |
| `output_format=jpeg/webp` | ⚠️ 历史观察 | 2026-11-04 的旧 GPT 模型测试仍返回 PNG；本轮最新 JPEG/WebP 请求因下载失败，尚不能确认当前上游格式 |
| `/v1/images/variations` | ❌ 不支持 | 网关返回 400 `Model name not specified` |
| `/v1/embeddings` | ❌ 不实现 | 500 `not implemented` |

**因此：需要透明背景时，应在拿到 PNG 后用本地工具处理。需要确定得到 JPG/WebP 时，也应先检查实际保存文件的签名，必要时本地转换，不能仅凭 `output_format` 请求值认定格式。**

## 客户端兼容

这是标准 Agent Skills 目录，脚本与配置均使用相对路径：

- Claude Code：`~/.claude/skills/jihuarst-image/`
- 跨客户端共享：`~/.agents/skills/jihuarst-image/`（Codex 可读取）
- WorkBuddy：`~/.workbuddy/skills/jihuarst-image/`
- 其他客户端：复制整个目录到其 skills 目录，按同一条 Python 命令调用

> 更新后需把 `scripts/generate.py`、`tests/`、`SKILL.md` 同步到上述其他目录副本，否则各客户端行为会不一致。

## 自检

```bash
python -m unittest discover -s tests -v
```

测试通过本地模拟 API 验证：URL/模型优先级、三个 2.6 模型与旧模型链、2.6 参数限定及原生 JSON/multipart 编码、`output_format` 普通文本编码与光栅/矢量模型选择、合法 GIF 帧范围及非法帧值请求前拒绝、`complexity` 枚举、非正/非有限 timeout 请求前拒绝、本地与 JSON markup、markup 与 mask/另一 markup 输入互斥及参考图要求、文生图与改图各自的混元模型链、`-edit` 不进入默认文生图链、显式模型覆盖、全部组合失败后的报错与重复费用提示、edits 与 generations 的自动切换、单图/多图 `image[]`/`mask` 字段、`size/quality/input_fidelity` 透传、JSON 里 `n` 保持整数、数量范围与多图编号输出、`data` 条目必须严格等于 `n`（额外条目也拒绝）、base64/data URL/远程 URL（含协议大小写）解析、SVG/GIF 字节原样保存及伪 SVG 拒绝、生成接口同源重定向与跨源 key 隔离、HTTPS 降级拒绝、截断错误正文回退、生成 JSON 与错误正文读取上限、单图与聚合图片大小上限和签名验证、HTTP(S) 图片重定向、下载不透传 key、下载发送 `Mozilla/5.0` UA、脱敏的下载 HTTP 状态/异常类别、SSRF 公网地址限制、DNS 混合地址与组播/保留地址拒绝、生产策略下的私网重定向拒绝、HTTPS IP 固定与 SNI、TLS 证书必需、禁用环境代理、图片重定向响应关闭、无图片条目回退、已有计费条目在下载/校验/数量/本地写入失败后继续回退、完整本地保存才成功、原子写入失败保护已有输出及临时文件清理、恢复失败时保留备份路径、key 脱敏。**不调用真实 API、不产生费用。**
