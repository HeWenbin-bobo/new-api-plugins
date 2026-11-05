---
name: jihuarst-video
description: Use when 用户要求使用 jihuarst 生成视频、文生视频、单张参考图生视频，或指定 minimax-video-h3 / kling-video-v3，并需要在多个 jihuarst API 地址之间自动切换、轮询任务和下载 MP4。
---

# jihuarst 文生视频 / 图生视频

通过 OpenAI Video 兼容的异步接口生成视频，运行与离线测试只依赖 Python 3.9+ 标准库。提交任务后轮询同一任务，完成并成功下载、校验 MP4 后才保存输出。

| 模式 | 触发条件 | 提交端点 | 轮询端点 |
|---|---|---|---|
| 文生视频 | 不传 `-r` | `POST /v1/videos` | `GET /v1/videos/{id}` |
| 图生视频 | 传一张 `-r IMAGE` | `POST /v1/videos`，JSON 的 `input_reference` 为图片 data URL | `GET /v1/videos/{id}` |

## 调用

在技能目录中运行（Windows 用 `python`，其他系统可用 `python3`）：

```bash
# 文生视频
python scripts/generate.py "一只猫在阳光下的窗边伸懒腰，镜头缓慢推进" --seconds 5 -o out.mp4

# 单张本地参考图生视频
python scripts/generate.py "人物自然转头，镜头缓慢推进" -r photo.png --seconds 5 -o out.mp4

# 指定模型、HTTPS 入口、尺寸和轮询参数
python scripts/generate.py "海浪拍打礁石" --model minimax-video-h3 --base-url https://api.jihuarst.top --seconds 5 --size 1280x720 --poll-interval 5 --max-wait 1800 -o out.mp4

# 输出机器可读的成功摘要
python scripts/generate.py "城市夜景延时" --json -o out.mp4
```

也可从任意工作目录使用脚本绝对路径。成功 JSON 包含 `base_url`、`model`、`task_id`、`path`；普通运行将信息写入 stderr。

## 参数

| 参数 | 类型 | 实际发送 / 客户端行为 |
|---|---|---|
| `prompt` | 字符串 | 提交 JSON 的 `prompt`；描述主体动作、镜头运动等 |
| `-o, --output` | 本地路径 | 不进入请求；默认 `jihuarst-video.mp4`，成功下载后原子替换 |
| `-r, --ref IMAGE` | 一张本地图片 | 转为 `input_reference` data URL；不传则文生视频，不支持多图或视频参考 |
| `--seconds` | 有限正数，默认 5 | 转为字符串写入 `seconds`，兼容 New API |
| `--size` | 尺寸字符串 | 可选透传，如 `1280x720`；实际支持由上游模型决定 |
| `--timeout` | 正数秒，默认 30 | 仅控制单次提交、轮询或下载请求，不进入请求体 |
| `--poll-interval` | 非负秒，默认 5 | pending 状态下客户端轮询间隔，不进入请求体 |
| `--max-wait` | 正数秒，默认 1800 | 单任务首次轮询后的最长客户端等待，不取消上游任务 |
| `--model` | 单一受支持模型 ID | 只使用该模型，不尝试另一个 |
| `--base-url` | 单一网关地址 | 只使用该入口，跳过其他入口 |
| `--json` | CLI 开关 | 成功时输出本地交付摘要，不改变提交协议 |

等待超时只停止当前脚本的轮询，不会取消上游已创建的任务。若需要取消或查询费用，应通过相应网关管理。

## API Key

Key 保存在技能根目录的 `config.json`；将 `config.example.json` 复制为该文件并填写自己的 key：

```json
{"api_key": ""}
```

各客户端副本的 `config.json` 是独立文件，复制技能目录时需一并配置同一把 key。不要在日志、回复或命令参数中显示 key。脚本始终从自身上一级的 `config.json` 读取。

## 强制回退顺序

**URL 优先，模型其次。** 在当前 URL 上依次尝试两个模型，均失败后切换到下一 URL：

| 尝试 | Base URL | 模型顺序 |
|---|---|---|
| 1–2 | `http://222.211.75.198:3000` | `minimax-video-h3` → `kling-video-v3` |
| 3–4 | `https://gz-api.jihuarst.top:8443` | 同上 |
| 5–6 | `https://api.jihuarst.top` | 同上 |
| 7–8 | `https://sg-api.jihuarst.top` | 同上 |

指定 `--model` 或 `--base-url` 会缩小回退范围。提交成功且任务处于 `queued`、`pending`、`submitted`、`processing`、`in_progress` 或 `running` 时只轮询该任务，不会重复提交。`completed` / `succeeded` 才进入下载；上游明确返回 `failed`、`rejected`、`cancelled` 或 `lost` 时回退到下一组合。取得任务 ID 后，未知或空状态、等待超时、网络、HTTP 或响应解析错误均保留该任务 ID 并终止，不创建另一任务。

提交成功后立即在 stderr 记录任务 ID，便于只读查询与恢复；日志及成功 JSON 中的任务 ID 会脱敏。完成响应有非空 `url` 时先下载该地址，相对地址按当前网关解析；下载失败或地址无效则对**同一任务**请求同源 `/v1/videos/{id}/content`，不会再次提交。没有 `url` 时直接使用该 content 地址。跨源 URL 或跨源重定向不会携带网关 key；同源下载可使用 key。仅允许 HTTP(S) 地址与重定向，HTTPS 不允许降级到 HTTP。提交与轮询 JSON 响应上限为 8 MiB。为防 SSRF，提交、轮询、下载及其重定向均必须解析到公网 IP，连接固定到已校验 IP，不使用系统代理；私网、回环、链路本地、组播及保留地址会被拒绝。

下载先验证初始内容第 4–7 字节为 `ftyp`，再流式写入输出目录中的临时文件；MP4 上限为 1 GiB。响应和临时文件成功关闭并 flush/fsync 后才原子替换目标。失败会清理临时文件并保留已有输出。两个候选地址都失败时，以“任务已计费但下载失败”终止，错误保留任务 ID，不继续下一模型或入口，也不提交新任务；请使用同一任务 ID 重试下载或检查网关的 content/artifact 代理。本地写入、权限等错误同样不会触发重新提交。

> **费用提醒：** 提交前失败或上游明确报告任务终态失败后的回退可能创建多个上游任务并产生多次费用。取得任务 ID 后的非终态轮询异常会保留任务 ID 并终止；任务完成后的下载失败只尝试同一任务的返回地址和 content 地址，不会再创建任务。默认最多有 8 个 URL/模型组合，这是回退上限，不是固定的任务数或价格。实际计费规则未通过本 Skill 验证，付费运行前应确认网关价格并尽量用单个 `--model` / `--base-url` 做最小验证。

> **明文入口警告：** 首选地址 `http://222.211.75.198:3000` 使用 HTTP 明文连接，key、提示词和参考图在该链路上不加密。公网或不可信网络中请用 `--base-url https://api.jihuarst.top`（或其他 HTTPS 入口）跳过它。

只有所选 URL/模型组合全部失败，才报告“jihuarst 视频 skill 当前无法使用”，并附脱敏、截断的组合失败摘要；不会把失败、等待中或无法下载的任务当作成功。

## 客户端兼容

这是标准 Agent Skills 目录，脚本与配置均使用相对路径：

- Claude Code：`~/.claude/skills/jihuarst-video/`
- 跨客户端共享：`~/.agents/skills/jihuarst-video/`
- WorkBuddy：`~/.workbuddy/skills/jihuarst-video/`
- 其他客户端：复制整个目录到其 skills 目录，按同一 Python 命令调用。

## 自检

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

测试使用临时假 key 和本地回环模拟服务，覆盖提交、单参考图序列化、URL/模型回退、任务轮询与状态、超时、脱敏、重定向 key 隔离与 HTTPS 降级拒绝、公网下载限制、JSON 响应与 MP4 大小上限、MP4 校验、原子保存、已有输出保护、返回地址失败后同任务 content 恢复、两个候选均失败时终止且不重新提交、本地错误边界及 CLI。**不调用真实网关、不产生费用。**

离线通过不代表线上模型可下载或实际生成质量已验证。2026-11-04 的付费实测确认两个模型 ID 均存在于 `https://api.jihuarst.top`，`seconds` 必须使用字符串；两者任务均达到完成状态，但视频地址返回 404、任务内容及产物代理返回 502，未获得 MP4。2026-11-05，用户确认 New API 上游已更新 WorkBuddy Video 插件后，使用相同 HTTPS 入口、5 秒、1280x720，分别固定单模型再次实测：MiniMax H3 与 Kling V3 均完成任务并实际下载 MP4，本地文件通过 `ftyp` 签名校验，每个模型只创建一个任务。结果只覆盖该入口和参数组合，不证明其他入口或所有后续任务均稳定。测试环境没有 `ffprobe`，未验证编码参数、精确时长、逐帧解码或视觉质量；实际计费总额未知，需由网关方核对。
