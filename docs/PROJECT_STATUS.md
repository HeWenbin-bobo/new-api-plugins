# 项目进度

> 最后更新：2026-11-05。这里记录跨项目状态与接手入口；长期维护规则见根目录 `AGENTS.md`，MCP 的专项历史见其 `PROJECT_MEMORY.md`。

## 当前基线

- 当前分支：`main`；已发布基线：`6098964 docs: record project progress and maintenance rules`。
- `6b3aef1` 完成 WorkBuddy Video 多模型升级及 Jihuarst Image 完整交付重试；`03936d8` 提交对应的两个客户端 ZIP；`6098964` 记录项目状态及长期维护规则。
- 已确认 GitHub 文件树与本地提交一致，旧 `kling_wb2api_newapi/` 不再存在于当前版本。
- 已发布的 `index.json` 和 `video_wb2api_newapi/plugin.js` 原始 URL 返回 HTTP 200，源码 SHA-256 与索引一致。
- 上述发布事实对应 2026-11-05 的检查，不代表后续提交也已发布。开始新工作前必须重新检查 Git 状态和远端。

## 五个项目的当前状态

| 项目 | 当前状态 | 最近的验证范围 |
|---|---|---|
| `video_wb2api_newapi/` | WorkBuddy Video 1.1.0，key 为 `workbuddy-video`；依次声明 `minimax-video-h3`、`kling-video-v3` | 源码与干净解压 ZIP 各 14/14 离线测试通过 |
| `jihuarst-image/` | 完整保存全部请求图片后才成功；单组合失败后继续其余选定组合 | 源码与干净解压 ZIP 各 54/54 离线测试通过 |
| `jihuarst-video/` | 双模型异步视频生成 Skill；本轮未改脚本 | 源码 64/64 离线测试通过；2026-11-05 在 New API 更新插件后，通过固定 HTTPS 入口分别完成两个模型的付费端到端实测 |
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

## 已知边界与待办

- **New API 市场安装未实测。** 已验证的是索引、源码 URL、哈希及离线契约，不应把它描述成真实 New API 安装成功。
- **历史视频下载故障已在后续指定路径复测通过，不代表上游问题已根治。** 2026-11-04 曾观察到两个模型的任务完成后返回 MP4 URL 为 404、content/artifact 代理为 502；2026-11-05 固定 HTTPS 入口及单模型的测试均成功交付 MP4。其他入口、参数与后续服务稳定性仍不在此次验证范围内。
- **视频媒体质量未完整验收。** 当前环境没有 `ffprobe`；只验证了下载字节与 MP4 `ftyp` 签名，没有验证编码参数、精确时长、逐帧解码或视觉内容。
- **全历史 ZIP 扫描存在已知阻断。** `node .githooks/check-push.js --all` 会按历史路径识别旧 `kling_wb2api_newapi/kling_wb2api_newapi.zip`，并因其不再是当前白名单路径而失败。这属于已移除历史产物的路径策略限制，不是本次普通推送失败；普通推送的增量检查已通过。不得为绕过它而弱化当前规则或擅自改写历史。
- `gh` CLI 在当时的 Windows 环境不可用，远端文件树通过 GitHub API 核对；不要假设所有机器都安装了 `gh`。
- 当前没有已批准的后续功能实现任务。新增真实媒体付费测试、New API 实机安装验证及其他入口或参数的视频排查，应分别明确范围和成本后再做。
- 根目录的 `可乐生图_API接口参数说明.docx` 是用户提供的本地只读参考，尚未纳入 Git。它描述的是另一部署的前端行为，不能作为 Jihuarst 参数能力的直接证据；若需长期保存，应先决定是否公开及如何去除敏感内容。

## 接手顺序

1. 运行 `git status --short --branch`，确认分支、远端及未提交改动，不依赖本文件的基线代替检查。
2. 阅读根 `AGENTS.md`、对应项目的 `README.md` 或 `SKILL.md`，再阅读 `docs/superpowers/specs/` 中的相关设计。
3. 在对应项目目录运行离线测试；失败、跳过或不可用必须明确报告。
4. 修改可分发项目后重建其指定 ZIP，并执行干净解压、字节一致性及凭据审计。
5. 只有用户明确授权时才提交或推送；推送后核对远端文件树与原始发布 URL。
