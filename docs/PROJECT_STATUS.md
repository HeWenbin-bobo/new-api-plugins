# 项目进度

> 最后更新：2026-11-07。这里记录跨项目状态与接手入口；长期维护规则见根目录 `AGENTS.md`，MCP 的专项历史见其 `PROJECT_MEMORY.md`。

## 当前基线

- 当前分支：`main`；已发布基线：`35e8930 chore: rebuild Jihuarst client archives`，前一提交为 `b37acb6 fix: stabilize Jihuarst offline HTTP fixtures`。两个提交已推送至 `origin/main`；推送后本地与远端均为 `35e8930`，工作区无未提交的跟踪文件变更。GitHub 根树为 `8a08cde4a0bd8ef7d392d8ec0cb6e735c06ad4a5`，68 个 blob 的路径、SHA 和大小与本地完全一致；`AGENTS.md`、本状态文档、两个 Jihuarst 测试文件及两个官方 ZIP 的固定提交 Raw URL 均返回 HTTP 200，且字节与本地提交一致。
- 本轮发布包括仓库文档整理、Jihuarst Image/Video 离线内存 HTTP fixture、对应官方 ZIP，以及 2026-11-07 的真实付费验证记录。生产 `scripts/generate.py`、New API 插件源码、市场索引及版本均未修改；本地凭据、任务 ID、日志和付费媒体仍只保留在忽略目录。
- 更早的发布基线：`b6172df docs: record moejs plugin publication`，此前依次为 `a3f2a47 chore: rebuild video plugin client archives`、`6800031 fix: support moejs video gateway URLs`。三个提交已推送至 `origin/main`，Hub 1.3.2、Panel 1.1.2、索引、两个插件源码及两个 ZIP 的 Raw URL 均返回 HTTP 200；当时 GitHub 根树及 66 个 blob 条目与本地 `b6172df` 完全一致，Raw 索引、源码、ZIP 字节和源码 SHA-256 均与本地提交一致。
- `6b3aef1` 完成 WorkBuddy Video 多模型升级及 Jihuarst Image 完整交付重试；`03936d8` 提交对应的两个客户端 ZIP；`6098964` 建立项目状态及长期维护规则；`3a24780` 更新参数契约、实测边界和维护规则，并重建图片、视频客户端 ZIP。
- `726dfec` 将视频插件重命名为 Hub 专用：目录 `video_wb2api_hub_newapi/`、key `workbuddy-video-hub`、显示名 `WorkBuddy Video Hub`、版本 1.2.0；同步 `index.json`、文档、ZIP 与发布保护白名单，共 14 个文件。
- `3a24780` 与 `726dfec` 均已推送至 `origin/main`。`726dfec` 推送后远端文件树与本地提交一致；新 `index.json`、`video_wb2api_hub_newapi/plugin.js`、`video_wb2api_hub_newapi/video_wb2api_hub_newapi.zip` 的 GitHub Raw URL 均返回 HTTP 200（分别为 961、8806、9187 字节），旧目录 `video_wb2api_newapi/` 不再存在于当前版本。
- 1.2.0 的 `index.json` 版本、路径与插件源码 LF 归一化 SHA-256（`9bfee89c5e9ce129f23c3b45f48efac3b9111855553671ff4ba1601c4a308a32`）一致。
- 上述发布事实分别对应 2026-11-06 与 2026-11-07 的检查，不代表后续提交也已发布。开始新工作前必须重新检查 Git 状态和远端。

## 六个项目的当前状态

| 项目 | 当前状态 | 最近的验证范围 |
|---|---|---|
| `video_wb2api_hub_newapi/` | WorkBuddy Video Hub 1.3.2，key 为 `workbuddy-video-hub`；仅用于 wb2api Hub，不兼容 Panel；moejs 兼容地址解析、错误脱敏 | 源码与干净解压 ZIP 各 20/20 离线测试通过；用户报告 2026-11-06 两个模型实测成功 |
| `video_wb2api_panel_newapi/` | WorkBuddy Panel Video 1.1.2，key 为 `workbuddy-panel-video`；仅用于 wb2api Panel；moejs 兼容渠道/COS 解析、错误脱敏、不向 COS 转发密钥 | 源码与干净解压 ZIP 各 18/18 离线测试通过；用户报告 2026-11-06 两个模型实测成功 |
| `jihuarst-image/` | 完整保存全部请求图片后才成功；本轮只修复离线测试 fixture，未改脚本 | 2026-11-06 新内存 fixture 连续五轮 57/57 通过；重建 ZIP 干净解压 57/57 通过，详见下方修复记录 |
| `jihuarst-video/` | 双模型异步视频生成 Skill；本轮只修复离线测试 fixture，未改脚本 | 2026-11-06 新内存 fixture 连续五轮 67/67 通过；重建 ZIP 干净解压 67/67 通过，详见下方修复记录 |
| `zaiwen-image-generation/` | 独立图像 Skill；本轮未改动 | 本轮未重新运行其专项测试；六 ZIP 跟踪状态检查通过，历史安全审计覆盖其归档 |
| `unified-web-mcp/` | 0.1.0；本轮未改动 | 2026-11-06 文档整理中源码 85/85 离线测试通过；更早历史见项目内 `PROJECT_MEMORY.md` |

这些数字是注明日期的发布基线及文档整理验证快照，不是永久有效的当前测试结论。改动后必须重跑相关套件。

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

## 2026-11-06 仓库文档整理

- 保留六个产品目录、历史项目文档和六个发布 ZIP 的原位分类；本次设计与计划分别记录在 `docs/superpowers/specs/2026-11-06-repository-maintenance-organization-design.md`、`docs/superpowers/plans/2026-11-06-repository-maintenance-organization.md`。修正 README 离线测试目录切换及六 ZIP 注释，将 moejs、实测证据、精确源打包与远端树核对规则沉淀到 `AGENTS.md`。本整理未改动插件源码、索引、版本或 ZIP；本地 DOCX 新增精确忽略规则，两份实测输入 ZIP 保持原位且均不纳入 Git。
- 文档检查通过：五份文档无占位标记，12 个本地链接可解析，两项插件 LF 源码 SHA-256 与索引一致，六个发布 ZIP 均保持跟踪，三份本地输入保持 ignored/untracked，产品源码、索引、版本、ZIP 与 `CLAUDE.md` 无差异。发布保护测试 38/38 通过。
- 本次顺序运行 Hub、Panel、Jihuarst Image、Jihuarst Video、MCP 的离线测试，确认 README 的目录切换均可执行；Hub 20/20、Panel 18/18、MCP 85/85 通过。Jihuarst Image 首轮 54 条有 1 failure、4 errors，再次全量运行有 1 failure、1 error；失败项含本地环回 mock 的 `WinError 10048`，其中五条定向重跑通过，但全量套件仍未通过。独立 socket 跟踪将图片错误定位到发送 HTTP 请求前的客户端 `socket.create_connection()`；没有捕获到可确认的跨进程冲突四元组，不将推断写成已证实的端口冲突细节。
- Jihuarst Video 64 条有 2 failures，其中未知状态用例定向重跑通过；终态任务回退用例在全量运行观察到 0 次提交、定向运行观察到 1 次提交，均非预期的 2 次。独立诊断确认该 mock 的提交响应固定为 `queued`，首次轮询选择 `failed`，而 `TaskTerminalError` 允许继续下一组合；这一路径本身不能解释第二次提交为何未被观察到，现有证据也不足以判断应修改源码还是 fixture。图片 socket 诊断不得泛化为该视频断言失败的根因；文档整理阶段未修改产品或测试实现，后续测试修复及验证见下节。

## 2026-11-06 Jihuarst 离线测试修复

- 保留上述文档整理时的失败记录作为历史证据。修复只涉及 `jihuarst-image/tests/test_generate.py`、`jihuarst-video/tests/test_generate.py`，两个生产 `scripts/generate.py` 均无差异；没有调整生产重试、任务提交、轮询、下载或计费错误策略。
- 将不稳定的 Windows 环回 TCP fixture 改为测试内内存 HTTP 传输：只在测试期间替换最终的 `socket.create_connection()`，生产 opener、连接类、地址校验、重定向及凭据处理保持不变。每个伪服务器使用唯一合成端口，未注册地址显式失败；新增真实 `socket.socket()` 创建即失败的回归用例。测试仍解析真实 HTTP 请求及响应字节，全程不创建网络监听器或真实凭据。
- 独立代码审查指出内存 fixture 对未知 HTTP 方法及关闭后 socket 的行为与标准库不一致；新增两条回归后，伪服务器改用 `handle_one_request()` 处理未知方法，`sendall()`/`makefile()` 在关闭后显式失败。定向验证中的 `HTTPError` 析构警告也通过先关闭错误响应、再清理服务器内存流消除，没有放宽断言或吞掉异常。
- 验证：图片连续五轮各 57/57（共 285/285）、视频连续五轮各 67/67（共 335/335）通过，均无析构警告。两份四文件 ZIP 已按最终测试源码重建，条目白名单、CRC、源文件逐字节一致性、干净解压 57/57 与 67/67 测试及四个非空本地凭据值的精确扫描通过。隔离临时 Git 元数据中的当前索引快照通过仓库推送保护检查（65 个 blob，未显示凭据值）；一次误用 `--all` 的审计被已知历史旧 ZIP 路径阻断，未据此判定本次归档失败，也未弱化保护规则。本次记录当时未运行真实网关、付费媒体生成或 New API 实机测试；后续真实付费验证见下节，发布结果见文末。

## 2026-11-07 Jihuarst 真实付费验证

- 用户明确请求真实付费调用；按最小范围对刚修复测试的两个 Skill 各运行一次，使用仓库中的生产脚本，不使用测试 fixture。两项均固定 HTTPS 入口 `https://api.jihuarst.top` 和单模型，不发送参考图或本地私有媒体，不扩展到其他入口或模型。现有资料没有可靠单价，实际费用仍需通过网关核对。
- 图片固定 `gpt-image-2.5`，文生图 1 张、1536x1024、low 质量；请求、下载及本地保存成功。私有产物位于被忽略的 `.omc/artifacts/live-validation-20261107/`，PNG 为 1,795,875 字节、1536x1024，SHA-256 `9235d22f16b28a51b09bf71f031c0dcf5241165c3184a863546f282a3206d687`；只验证文件字节、PNG 签名及尺寸，未单独验收视觉质量。
- 视频固定 `minimax-video-h3`，文生视频 5 秒、1280x720；同一任务完成提交、轮询、MP4 下载及本地保存，没有创建替代任务。MP4 为 609,068 字节，SHA-256 `3b010afd9c19a1d320b572bb394877d147cf36c8f59f51566a7cf248c561ac32`，`ftyp` 签名检查通过。本机未找到 `ffprobe`，未验证编码参数、精确时长、逐帧解码或视觉质量。
- 两个后台命令均以退出码 0 完成；结果文件与日志保存在同一忽略目录，真实任务 ID 不写入公开状态文档，媒体及日志不进入 Git 或发布 ZIP。本次没有修改生产脚本；对应发布记录见下节。

## 2026-11-07 文档、测试修复及 ZIP 发布

- `b37acb6` 提交文档整理、两个离线测试 fixture 及真实验证记录，`35e8930` 单独提交按最终源文件重建的两份官方 ZIP。普通推送由 `b6172df` 更新到 `35e8930`，未使用绕过选项、未打标签或改写历史。
- 发布前最终检查：提交树的干净导出中图片 57/57、视频 67/67 通过；精确提交树 68 个唯一 blob 的仓库原生安全检查通过，实际 pre-push 检查 69 个唯一 blob 通过。两份 ZIP 保持四文件白名单、CRC 和源码字节一致，干净解压测试分别为 57/57、67/67，且无清理警告。
- 推送后 `origin/main` 与本地 `HEAD` 一致。通过 GitHub 根树 ID 查询递归树，确认 68 个 blob 的路径、SHA 和大小全部匹配；六个本轮代表性公开文件的固定提交 Raw URL 均为 HTTP 200 且字节一致。该核验没有修改源码或归档。
- 本次保存进度只更新 `AGENTS.md` 与本状态文档，保留既有目录分类及历史文档，不移动或重打官方 ZIP，也不改变已发布提交。New API 市场实机安装及最终 moejs 运行仍未验证；真实视频媒体质量仅完成文件与 `ftyp` 检查。

## 已知边界与待办

- **New API 市场安装未实测。** 已验证的是索引、源码 URL、哈希及离线契约，不应把它描述成真实 New API 安装成功。
- **Jihuarst 历史离线测试失败已单独修复并复验。** 详见上方 2026-11-06 修复记录及 2026-11-07 真实付费验证。离线 fixture 和真实网关属于不同验证层次，离线通过不代替真实交付验收。
- **Panel 模型实测范围。** 用户报告 2026-11-06 Panel 的 MiniMax H3 与 Kling V3 任务成功；维护规则现已改为保留该版本范围的证据，不将其扩张为后续最终 COS 解析补丁的实测结论。
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
