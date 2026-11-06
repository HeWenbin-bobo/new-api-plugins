# 项目进度

> 最后更新：2026-11-06。这里记录跨项目状态与接手入口；长期维护规则见根目录 `AGENTS.md`，MCP 的专项历史见其 `PROJECT_MEMORY.md`。

## 当前基线

- 当前分支：`main`；已发布基线：`a3f2a47 chore: rebuild video plugin client archives`，前一提交为 `6800031 fix: support moejs video gateway URLs`。两个提交已推送至 `origin/main`，Hub 1.3.2、Panel 1.1.2、索引、两个插件源码及两个 ZIP 的 Raw URL 均返回 HTTP 200；GitHub 根树及 66 个 blob 条目与本地 `a3f2a47` 完全一致。Raw 索引、源码、ZIP 字节和源码 SHA-256 均与本地提交一致。
- `6b3aef1` 完成 WorkBuddy Video 多模型升级及 Jihuarst Image 完整交付重试；`03936d8` 提交对应的两个客户端 ZIP；`6098964` 建立项目状态及长期维护规则；`3a24780` 更新参数契约、实测边界和维护规则，并重建图片、视频客户端 ZIP。
- `726dfec` 将视频插件重命名为 Hub 专用：目录 `video_wb2api_hub_newapi/`、key `workbuddy-video-hub`、显示名 `WorkBuddy Video Hub`、版本 1.2.0；同步 `index.json`、文档、ZIP 与发布保护白名单，共 14 个文件。
- `3a24780` 与 `726dfec` 均已推送至 `origin/main`。`726dfec` 推送后远端文件树与本地提交一致；新 `index.json`、`video_wb2api_hub_newapi/plugin.js`、`video_wb2api_hub_newapi/video_wb2api_hub_newapi.zip` 的 GitHub Raw URL 均返回 HTTP 200（分别为 961、8806、9187 字节），旧目录 `video_wb2api_newapi/` 不再存在于当前版本。
- 1.2.0 的 `index.json` 版本、路径与插件源码 LF 归一化 SHA-256（`9bfee89c5e9ce129f23c3b45f48efac3b9111855553671ff4ba1601c4a308a32`）一致。
- 上述发布事实对应 2026-11-05 的检查，不代表后续提交也已发布。开始新工作前必须重新检查 Git 状态和远端。

## 六个项目的当前状态

| 项目 | 当前状态 | 最近的验证范围 |
|---|---|---|
| `video_wb2api_hub_newapi/` | WorkBuddy Video Hub 1.3.2，key 为 `workbuddy-video-hub`；仅用于 wb2api Hub，不兼容 Panel；moejs 兼容地址解析、错误脱敏 | 源码与干净解压 ZIP 各 20/20 离线测试通过；用户报告 2026-11-06 两个模型实测成功 |
| `video_wb2api_panel_newapi/` | WorkBuddy Panel Video 1.1.2，key 为 `workbuddy-panel-video`；仅用于 wb2api Panel；moejs 兼容渠道/COS 解析、错误脱敏、不向 COS 转发密钥 | 源码与干净解压 ZIP 各 18/18 离线测试通过；用户报告 2026-11-06 两个模型实测成功 |
| `jihuarst-image/` | 完整保存全部请求图片后才成功；参数表区分请求字段、客户端行为和后处理 | 更新后 ZIP 干净解压 54/54 离线测试通过 |
| `jihuarst-video/` | 双模型异步视频生成 Skill；本轮未改脚本 | 更新后 ZIP 干净解压 64/64 离线测试通过；2026-11-05 在 New API 更新插件后，通过固定 HTTPS 入口分别完成两个模型的付费端到端实测 |
| `zaiwen-image-generation/` | 独立图像 Skill；本轮未改动 | 本轮未重新运行其专项测试；五 ZIP 统一安全审计已覆盖其归档 |
| `unified-web-mcp/` | 0.1.0；本轮未改动 | 本轮未重新运行 MCP 测试；历史状态见项目内 `PROJECT_MEMORY.md` |

这些数字是上述基线的验证快照，不是永久有效的当前测试结论。改动后必须重跑相关套件。

## 已完成的重点

1. 将 Kling 专用插件原位泛化为 WorkBuddy Video，同步目录、key、模型、版本、市场索引、文档、ZIP 和发布保护白名单。
2. 插件保持 New API 所选模型的显式转发，没有隐式模型替换。
3. 图片生成在网络、HTTP、解析、下载、图片校验、数量不足及本地输出失败后尝试下一 URL/模型组合；显式 URL/模型参数仍限制候选范围。
4. 原子写入、旧文件备份、逆序回滚及恢复失败时的备份保留行为均保留。
5. 五个发布 ZIP 共 37 个条目通过白名单、CRC、源码逐字节一致性和本地凭据值审计；两个升级 ZIP 已重建。
6. 本轮改动经独立 Opus 审查通过，无 CRITICAL、HIGH 或 MEDIUM 问题。
7. 2026-11-05，用户确认 New API 上游已更新 WorkBuddy Video 插件后，分别固定 `https://api.jihuarst.top` 与单一模型进行付费验证。MiniMax H3 和 Kling V3 均完成提交、同任务轮询、MP4 下载及本地 `ftyp` 签名校验，每个模型只创建一个任务。请求为 5 秒、1280x720，未触发模型或入口回退。
8. 本地验证产物保存在被忽略的 `.omc/artifacts/live-video-20261105/`，不进入 Git 或发布 ZIP。MiniMax 文件为 1,182,697 字节，SHA-256 `def30e58a0d118d69b62c703b4dee3c7978ef84f1ead7d08dbfcaa45f8af1dce`；Kling 文件为 4,330,324 字节，SHA-256 `dcb05b191bc96fa38ae815f5c63946a2cf144d1b469fcb2dc3b6090cae002e87`。
9. 根据用户提供的第三方生图 API 参考文档，改进图片、视频 Skill 的参数说明，区分接口请求、客户端处理与本地交付；第三方部署行为不作为 Jihuarst 能力证据。未新增 Responses API、流式生图或通用服务商框架。
10. `3a24780` 发布前验证：图片、视频更新 ZIP 的干净解压离线测试分别为 54/54、64/64，推送保护回归 38/38；归档条目、源码一致性、凭据、文档链接、JSON 与插件源码哈希检查通过。

## 本次重命名发布记录（726dfec）

- 将视频插件目录、key 和显示名分别重命名为 `video_wb2api_hub_newapi/`、`workbuddy-video-hub`、`WorkBuddy Video Hub`，明确仅适用于 wb2api Hub，不兼容 Panel。版本升为 1.2.0；索引、ZIP、文档与发布保护白名单同步更新。历史发布事实保留旧路径作为当时记录。
- 验证：插件源码 14/14、干净解压 ZIP 14/14、发布保护 38/38 离线测试通过；`node --check plugin.js`、`git diff --check`、索引 JSON/版本/哈希一致性检查通过；推送前 `check-push.js` 扫描 58 个 blob 通过。New API 市场实机安装未验证。
- SSRF 审查结论（2026-11-05，后台安全审查 MEDIUM）：插件只向渠道管理员配置的 `ctx.baseUrl` 发请求，`input_reference`/`image`/`reference_images` 按 hub 原生 `/v1/videos` 契约透传，实际抓取这些 URL 的是 wb2api-hub，插件未新增攻击面。若需加固，应在 hub 侧对图片 URL 做 http/https、DNS 解析与私网/环回/链路本地地址拒绝、逐跳重定向重校验（如 `validateRemoteImageUrl()`），而非在插件层实现。

## 本次发布记录：moejs 实测兼容更新（6800031、a3f2a47）

- 用户提供 `workbuddy-video-hub-current-20261106.zip` 和 `workbuddy-panel-video-current-20261106.zip`，核心修改是用受限字符串解析替代 moejs 不支持的 `new URL()`。
- Hub 升级为 1.3.2，Panel 升级为 1.1.2；不复用已发布版本号。保留现有错误脱敏、模型重定向和协议边界，不直接采用实测 ZIP 对完整文档及测试的删减。
- Panel 的 COS `contentUrl()` 同步移除 `URL` 依赖，保留 HTTPS 精确域名、端口、凭据和路径边界检查；否则提交修复后下载仍会在 moejs 失败。
- 用户报告 2026-11-06 两个插件的 MiniMax H3 与 Kling V3 真实任务、MP4 下载及 `ftyp` 校验均成功；这是用户提供的实测报告，本次未创建付费任务。
- 验证：Hub 源码及干净解压 ZIP 各 20/20，Panel 源码及干净解压 ZIP 各 18/18 离线测试通过，包含无 `URL` 构造器、渠道路径前缀、合法及非法 IPv6、非法端口和 COS 路径边界的回归用例。合法压缩 IPv6 用例先在旧实现上按预期失败，再修正校验；最终 IPv6 判断经独立审查无发现，但最终版本未在真实 moejs 运行时重新验证。
- 发布：`6800031` 提交源码、索引、版本及文档，`a3f2a47` 单独提交从精确源 blob 重建的两个客户端 ZIP。推送前检查器扫描 67 个唯一 blob 通过，精确 `HEAD` 导出与干净 ZIP 测试再次通过；普通推送保留 `.githooks/pre-push`，未使用绕过选项。推送后 `origin/main` 与本地 HEAD 一致，GitHub API 树核对及 Raw URL 检查通过。
- 仍未验证：New API 市场实机安装、最终 Panel COS 兼容解析的真实任务执行。本轮未创建付费任务；用户实测报告对应其提供的实测版本，不自动证明本轮最终补丁已在同一环境执行。

## 已知边界与待办

- **New API 市场安装未实测。** 已验证的是索引、源码 URL、哈希及离线契约，不应把它描述成真实 New API 安装成功。
- **历史视频下载故障已在后续指定路径复测通过，不代表上游问题已根治。** 2026-11-04 曾观察到两个模型的任务完成后返回 MP4 URL 为 404、content/artifact 代理为 502；2026-11-05 固定 HTTPS 入口及单模型的测试均成功交付 MP4。其他入口、参数与后续服务稳定性仍不在此次验证范围内。
- **视频媒体质量未完整验收。** 当前环境没有 `ffprobe`；只验证了下载字节与 MP4 `ftyp` 签名，没有验证编码参数、精确时长、逐帧解码或视觉内容。
- **全历史 ZIP 扫描存在已知阻断。** `node .githooks/check-push.js --all` 会按历史路径识别旧 `kling_wb2api_newapi/kling_wb2api_newapi.zip` 与 `video_wb2api_newapi/video_wb2api_newapi.zip`，并因其不再是当前白名单路径而失败。这属于已移除历史产物的路径策略限制，不是本次普通推送失败；普通推送的增量检查已通过。不得为绕过它而弱化当前规则或擅自改写历史。
- `gh` CLI 在当时的 Windows 环境不可用，远端文件树通过 GitHub API 核对；不要假设所有机器都安装了 `gh`。
- 当前没有已批准的后续功能实现任务。新增真实媒体付费测试、New API 实机安装验证及其他入口或参数的视频排查，应分别明确范围和成本后再做。
- 根目录的 `可乐生图_API接口参数说明.docx` 是用户提供的本地只读参考，尚未纳入 Git。它描述的是另一部署的前端行为，不能作为 Jihuarst 参数能力的直接证据；若需长期保存，应先决定是否公开及如何去除敏感内容。

## 接手顺序

1. 运行 `git status --short --branch`，确认分支、远端及未提交改动，不依赖本文件的基线代替检查。
2. 阅读根 `AGENTS.md`、对应项目的 `README.md` 或 `SKILL.md`，再阅读 `docs/superpowers/specs/` 中的相关设计。
3. 在对应项目目录运行离线测试；失败、跳过或不可用必须明确报告。
4. 修改可分发项目后重建其指定 ZIP，并执行干净解压、字节一致性及凭据审计。
5. 只有用户明确授权时才提交或推送；推送后核对远端文件树与原始发布 URL。
