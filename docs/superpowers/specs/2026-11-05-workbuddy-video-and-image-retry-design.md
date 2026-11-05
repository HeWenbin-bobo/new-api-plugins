# WorkBuddy Video 与图片全组合重试设计

## 目标

将单一 Kling 的 New API Task Plugin 升级为通用 WorkBuddy Video 插件，支持 `minimax-video-h3` 和 `kling-video-v3`；同时让 `jihuarst-image` 在任何组合未完整交付图片时继续尝试其余组合。

## WorkBuddy Video

- 项目目录由 `kling_wb2api_newapi/` 重命名为 `video_wb2api_newapi/`。
- 插件 key 由 `workbuddy-kling` 改为 `workbuddy-video`，显示名改为 `WorkBuddy Video`。
- `meta.models` 和市场协议模型按 `minimax-video-h3`、`kling-video-v3` 排列。
- 请求仍透传 New API 选择的模型，不增加额外模型或隐式替换模型。
- 插件和 `package.json` 版本升级为 `1.1.0`；`index.json` 只列出新版本、新 key 和新源码路径，SHA-256 按 LF 规范化源码计算。
- 更新项目与根 README、仓库指南、Git 忽略规则、pre-push ZIP 白名单及其测试。
- 客户端 ZIP 改名为 `video_wb2api_newapi/video_wb2api_newapi.zip`，只包含现有四个公开文件；旧 ZIP 不再保留或允许发布。
- 增加双模型声明及 MiniMax 请求透传的离线回归，运行完整插件测试。

## jihuarst-image 全组合重试

- 保留 URL 优先、模型其次的现有顺序，以及参考图模式专用模型链。
- 网络、HTTP、响应解析、无图片、无效图片、下载失败、数量不足和本地输出失败均记录脱敏摘要并进入下一组合。
- 上游已返回图片后再尝试其他组合可能重复计费；这是用户明确选择的行为，文档和错误汇总必须明确说明。
- 显式 `--base-url` 或 `--model` 仍限制候选范围，不暗中扩大用户选择。
- 本地输入错误和 CLI 参数错误仍在任何付费请求前失败。
- 每次尝试都使用原子输出写入、旧文件备份与失败恢复；只有完整保存全部请求图片才返回成功。
- 所有组合失败时抛出包含全部脱敏摘要的失败，不返回空结果或伪成功。
- 更新现有“已计费即终止”测试为继续回退，并覆盖返回图片后下载失败、数量不足和本地写入失败后的成功回退，以及全部失败汇总。

## 验证与边界

- 所有自动化测试离线运行，使用临时文件和回环 mock 服务，不调用真实付费 API。
- 分别运行插件、图片及仓库保护检查测试；重建并审计新插件和图片 ZIP，检查干净解压测试、逐字节一致性及真实本地凭据值。
- 本设计不验证 New API 市场内实际安装，也不声称解决上游真实视频 MP4 下载问题。
- 未经新的明确授权，不提交或推送 Git。
