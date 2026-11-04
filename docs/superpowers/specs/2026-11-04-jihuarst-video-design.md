# jihuarst-video 设计

## 目标

新增独立 Agent Skill `jihuarst-video/`，复用 `jihuarst-image` 的四个网关地址和本地 `config.json` 密钥配置，通过 OpenAI Video 兼容接口生成视频。只使用 `minimax-video-h3`（优先）和 `kling-video-v3`。不加入 New API 市场索引。

## 结构与接口

- `SKILL.md`：中文使用说明、参数、回退顺序、安装和自检方法。
- `scripts/generate.py`：Python 3.9+ 标准库命令行脚本。
- `config.example.json`：仅包含空 `api_key`；真实 `config.json` 保持 Git 忽略。
- `tests/test_generate.py`：使用 loopback 模拟网关的离线测试。
- `jihuarst-video.zip`：由明确允许列表生成的客户端分发包，经归档安全审计后作为白名单归档纳入 Git 跟踪。

文生视频发送 JSON；图生视频通过 `-r IMAGE` 读取一张本地图片，转为 data URL 后放入 `input_reference`，仍发送 JSON。两种模式均调用 `POST /v1/videos`，从响应取得任务 ID，再轮询 `GET /v1/videos/{id}`。成功后从任务返回的签名 URL 或 `/content` 端点下载 MP4。

## 命令行

位置参数为非空提示词。支持：

- `-o, --output`：输出路径，默认 `jihuarst-video.mp4`。
- `-r, --ref`：一张本地参考图；存在或空文件在联网前报错。
- `--seconds`：正数视频时长，默认 5 秒。
- `--size`：可选尺寸，原样传给网关。
- `--timeout`：单次 HTTP 请求超时。
- `--poll-interval` 与 `--max-wait`：限制轮询频率和总等待时间。
- `--model` / `--base-url`：将回退范围限制为指定模型或地址，模型仍只能选自两个候选。
- `--json`：输出机器可读的成功摘要；失败返回非零退出码。

不复制图片 Skill 的 mask、多图融合、图片数量和质量参数。

## 回退与状态处理

默认按 URL 优先、模型其次执行：每个地址先尝试 `minimax-video-h3`，再尝试 `kling-video-v3`，四个地址共八个提交组合。提交或轮询请求的网络/HTTP/响应格式错误进入下一组合；已提交任务进入排队或处理中时持续轮询同一任务，不重复提交。明确的失败、拒绝、取消、丢失状态以及超时均保留为失败，不返回空成功结果。

识别 `queued`、`pending`、`submitted`、`processing`、`in_progress`、`running`、`completed`、`succeeded`、`failed`、`rejected`、`cancelled`、`lost`。未知状态不作为成功；轮询总时限到达后报错。

下载远程视频时不转发网关 API key，只允许 HTTP(S) 重定向，并检查 MP4 文件签名。只有完整视频写入临时文件并原子替换目标后才报告成功。错误摘要移除配置密钥和常见 token 形状，不记录参考图内容。

## 验证与仓库同步

离线模拟服务覆盖：模型与 URL 优先级、显式限制、文生/图生请求字段、本地输入校验、任务状态映射、轮询不重复提交、失败与超时、视频 URL/内容下载、下载鉴权隔离、重定向和非法内容拒绝、密钥脱敏及 CLI JSON 输出。测试不连接真实网关、不产生费用。

创建后运行完整离线测试，从 ZIP 干净解压再次运行，并逐字节比对归档与当前源文件。按仓库要求同步根 README 和 AGENTS 中的项目数量、Skill 列表、测试及打包说明；`index.json` 不变。真实视频生成属于付费操作，执行前另行确认提示词、参考图、网关和最小生成参数。根据仓库规则，不自动提交或推送。
