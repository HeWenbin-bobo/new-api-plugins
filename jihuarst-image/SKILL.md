---
name: jihuarst-image
description: Use when 用户要求使用 jihuarst 生成或编辑图片、需要上传参考图做图生图/局部重绘/多图融合，或指定 gpt-image-2.5 / gpt-image-2.5-flare / gpt-image-2 / hunyuan-image-alpha / hunyuan-image-alpha-edit 出图，或需要在多个 jihuarst API 地址之间自动切换完成出图。
---

# jihuarst 生图 / 改图

使用 OpenAI 兼容接口出图，只依赖 Python 3.9+ 标准库（测试与 `PIL` 相关校验另需 Pillow）。

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
```

也可从任意工作目录用脚本绝对路径调用。成功后会打印实际使用的 URL、模型、端点，以及上游重写后的提示词。

## 参数

| 参数 | 说明 |
|---|---|
| `prompt` | 位置参数，图片描述或编辑指令 |
| `-o, --output` | 输出路径，默认 `jihuarst-image.png`；`-n>1` 时自动加 `-1/-2…` 后缀 |
| `-r, --ref IMAGE` | 参考图，可重复。**传了就走 edits 模式** |
| `-m, --mask` | 局部重绘遮罩，透明处为待编辑区域；仅可与单张参考图同用 |
| `--size` | 如 `1536x1024`、`2048x2048`、`auto`；低于约 1254×1254 总像素会被上游抬升（见下） |
| `--quality` | `low` / `medium` / `high` / `auto` |
| `--input-fidelity` | `low` / `high`，仅 edits 模式，控制对参考图的贴合程度 |
| `-n, --count` | 生成数量，默认 1 |
| `--timeout` | 单次请求超时秒数，默认 180 |
| `--model` / `--base-url` | 只使用指定的模型 / 地址，跳过回退链 |
| `--json` | 以 JSON 输出结果摘要，便于程序化处理 |

## API Key

Key 保存在技能根目录的 `config.json`；将 `config.example.json` 复制为该文件并填写自己的 key：

```json
{"api_key": ""}
```

各客户端副本的 `config.json` 是**独立文件**，不存在"自动同源"——复制目录时请一并复制同一把 key。

不要在日志、回复或命令参数中显示 key。脚本始终从自身上一级的 `config.json` 读取，因此复制整个技能目录即可使用。除首选的 HTTP 入口外，其余默认回退地址均使用 HTTPS。

## 强制回退顺序

**URL 优先，模型其次。** 在当前 URL 上依次尝试全部模型，全部失败后切换到下一 URL：

| 尝试 | Base URL | 文生图模型 | 改图模型 |
| -- | --- | --- | --- |
| 1-4 | `http://222.211.75.198:3000` | `gpt-image-2.5` → `gpt-image-2.5-flare` → `gpt-image-2` → `hunyuan-image-alpha` | 同左，但末位为 `hunyuan-image-alpha-edit` |
| 5-8 | `https://gz-api.jihuarst.top:8443` | 同上 | 同上 |
| 9-12 | `https://api.jihuarst.top` | 同上 | 同上 |
| 13-16 | `https://sg-api.jihuarst.top` | 同上 | 同上 |

模型链按模式分流：**不传 `-r` 的文生图**末位追加 `hunyuan-image-alpha`；**传 `-r` 的改图**末位追加 `hunyuan-image-alpha-edit`。混元 `-edit` 是上游目录标记的 `image-to-image` 模型，**只能与参考图一起用于 edits 模式**，因此不会进入默认文生图回退链；反之 `hunyuan-image-alpha` 标记为 `text-to-image`，不进入默认改图链。显式 `--model` 指定时跳过该分流（只试这一个模型），便于调试。

新入口的 `/v1/models` 已确认包含这两个模型 ID；模式依据上游目录标签与[混元接入文档](https://github.com/dingminhua/dsh-connect-workbuddy/blob/main/docs/IMAGE_GEN.md)。下方尺寸、质量、透明背景等实测结论来自三个 GPT Image 模型，不代表混元模型已完成出图实测。

每次请求使用 `n=<count>`、`response_format=b64_json`，默认单次超时 180 秒。网络错误、HTTP 错误、响应解析错误都继续下一组合；保存成功后立即停止。**只有全部 16 个默认组合失败，才能说“jihuarst 生图 skill 当前无法使用”**，并附各组合失败摘要。

> 首选地址 `http://222.211.75.198:3000` 是 **HTTP 明文连接**（非 HTTPS）：key、提示词与参考图在该链路上不加密，仅建议在可信内网/专线环境使用；公网环境可临时用 `--base-url` 跳过它。
> `sg-api` 为网关 `/api/status` 公告的新加坡备用入口，已实测可用；若某段时间不可达会自动回退到其他地址。

## 网关实测能力（重要，避免误用）

以下结论由本机对线上网关逐项实测得出，更新脚本前请勿凭 OpenAI 官方文档假设：

| 能力 | 实测结果 | 说明 |
|---|---|---|
| `/v1/images/generations` | ✅ | 文生图主通道 |
| `/v1/images/edits` | ✅ | 参考图改图，单图 `image`、多图 `image[]` 均可 |
| `mask`（局部重绘） | ⚠️ 接受但不强制 | 实测遮罩确实生效（遮罩外像素基本原样保留），但**上游不会硬性限制**：若 prompt 表述为"整体换风格/换配色"，模型仍会越过遮罩重绘全图。要限定局部务必在 prompt 里明确"遮罩外保持原样" |
| `n` > 1 | ✅ 真实生效 | 返回多张且按张计费（n=2 → charged_quota 翻倍） |
| `size` | ⚠️ 有条件 | 1536x1024 / 1024x1536 / 1792x1024 / 1024x1792 / 2048x2048 精确生效；**总像素低于 ~1254×1254（1.57M）时被抬升为 1254×1254**，如 1024x1024、768x768、512x512 均被忽略 |
| `quality` | ⚠️ 接受但差异不明显 | 不报错；耗时/体积未见稳定差异 |
| `input_fidelity` | ⚠️ 接受但不稳定 | 传入会改变上游尺寸选择（曾出现 high 时输出 1024x1536） |
| `background=transparent` | ❌ **无效** | 三个 GPT Image 模型都返回 RGB 不透明白底 PNG，不会有 alpha 通道 |
| `output_format=jpeg/webp` | ❌ **无效** | 恒返回 PNG |
| `/v1/images/variations` | ❌ 不支持 | 网关返回 400 `Model name not specified` |
| `/v1/embeddings` | ❌ 不实现 | 500 `not implemented` |

**因此：需要透明背景或指定 JPG/WebP 时，不要依赖接口参数，应在拿到 PNG 后用本地工具处理。**

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

测试通过本地模拟 API 验证：URL/模型优先级、文生图与改图各自的混元模型链、`-edit` 不进入默认文生图链、显式模型覆盖、全部组合失败后的报错、edits 与 generations 的自动切换、单图/多图 `image[]`/`mask` 字段、`size/quality/input_fidelity` 透传、JSON 里 `n` 保持整数、多图编号输出、key 脱敏。**不调用真实 API、不产生费用。**
