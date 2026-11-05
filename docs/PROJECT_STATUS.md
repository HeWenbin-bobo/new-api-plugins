# 项目进度

> 最后更新：2026-11-05。这里记录跨项目状态与接手入口；长期维护规则见根目录 `AGENTS.md`，MCP 的专项历史见其 `PROJECT_MEMORY.md`。

## 当前基线

- 当前分支：`main`；已发布基线：`03936d8 chore: regenerate video and image client archives`。
- `6b3aef1` 完成 WorkBuddy Video 多模型升级及 Jihuarst Image 完整交付重试；`03936d8` 提交对应的两个客户端 ZIP。
- 已确认 GitHub 文件树与本地提交一致，旧 `kling_wb2api_newapi/` 不再存在于当前版本。
- 已发布的 `index.json` 和 `video_wb2api_newapi/plugin.js` 原始 URL 返回 HTTP 200，源码 SHA-256 与索引一致。
- 上述发布事实对应 2026-11-05 的检查，不代表后续提交也已发布。开始新工作前必须重新检查 Git 状态和远端。

## 五个项目的当前状态

| 项目 | 当前状态 | 最近的验证范围 |
|---|---|---|
| `video_wb2api_newapi/` | WorkBuddy Video 1.1.0，key 为 `workbuddy-video`；依次声明 `minimax-video-h3`、`kling-video-v3` | 源码与干净解压 ZIP 各 14/14 离线测试通过 |
| `jihuarst-image/` | 完整保存全部请求图片后才成功；单组合失败后继续其余选定组合 | 源码与干净解压 ZIP 各 54/54 离线测试通过 |
| `jihuarst-video/` | 双模型异步视频生成 Skill，行为未随本轮图片/插件升级改变 | 干净解压 ZIP 64/64 离线测试通过 |
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

## 已知边界与待办

- **New API 市场安装未实测。** 已验证的是索引、源码 URL、哈希及离线契约，不应把它描述成真实 New API 安装成功。
- **上游视频 MP4 问题未解决。** 曾观察到视频任务完成后 MP4 URL/代理下载异常；本次没有复现、定位或修复该上游问题。
- **全历史 ZIP 扫描存在已知阻断。** `node .githooks/check-push.js --all` 会按历史路径识别旧 `kling_wb2api_newapi/kling_wb2api_newapi.zip`，并因其不再是当前白名单路径而失败。这属于已移除历史产物的路径策略限制，不是本次普通推送失败；普通推送的增量检查已通过。不得为绕过它而弱化当前规则或擅自改写历史。
- `gh` CLI 在当时的 Windows 环境不可用，远端文件树通过 GitHub API 核对；不要假设所有机器都安装了 `gh`。
- 当前没有已批准的后续功能实现任务。真实媒体付费测试、New API 实机验证及上游 MP4 排查应分别明确范围和成本后再做。

## 接手顺序

1. 运行 `git status --short --branch`，确认分支、远端及未提交改动，不依赖本文件的基线代替检查。
2. 阅读根 `AGENTS.md`、对应项目的 `README.md` 或 `SKILL.md`，再阅读 `docs/superpowers/specs/` 中的相关设计。
3. 在对应项目目录运行离线测试；失败、跳过或不可用必须明确报告。
4. 修改可分发项目后重建其指定 ZIP，并执行干净解压、字节一致性及凭据审计。
5. 只有用户明确授权时才提交或推送；推送后核对远端文件树与原始发布 URL。
