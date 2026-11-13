# 项目进度

> 最后更新：2026-11-13。这里记录跨项目状态与接手入口；长期维护规则见根目录 `AGENTS.md`，MCP 的专项历史见其 `PROJECT_MEMORY.md`。

## 整合：Local OCR 0.1.9 更新与 Local Decisions 新增（2026-11-13）

- 在分支 `feat/local-decisions-and-ocr-updates`（起点为干净的 `main`，与 `origin/main` 同为 `ec77df8`）上完成两组整合。OCR 侧按用户提供的 `local-ocr-task-plugin-0.1.9.zip` 与 `local-document-ocr.zip` 更新现有目录：插件由 0.1.7 升级到 0.1.9，模型从 2 个扩为 7 个（`mineru-pipeline-cpu`、`paddleocr-vl-1.6-cpu`、`hunyuanocr-1.5-cpu`、`glm-ocr-cpu`、`xiaomi-ocr-0-cpu`、`minicpm-ocr-1.0-cpu`、`ovisocr3-cpu`），Skill 增加 `--quality` 开关。
- 新项目按仓库规范落位为 `local-decisions-plugin/`（Task Plugin 0.4.0，key `local-decisions`）与 `local-decisions/`（Agent Skill）。插件源码 6,571 个 LF 字节、SHA-256 `30b7c560f4bf86b2c1132d99044e372cf87fb9d80c1ff640010ae999b58bee1a`，与 manifest、`SHA256SUMS` 和根索引一致。适配器只提供同步 `POST /v1/systemone`：`choice`（2–256 个 criteria）与 `noul`（P(yes)）两类问题，校验概率归一化（±0.001）与 `usage.output_tokens === 0`，Jev-Omni 固定转发到独立运行时，提交前预留 8192 token 上限并在完成时按实际 `input_tokens` 结算。没有任务 ID、轮询接口或 `/v1/chat/completions` 通道。
- 整合时保留仓库既有防护而非照搬上游归档：OCR 插件继续对每次任务表达式提交统一预留 100 页、不信任调用方 `pages`/文件名/MIME；OCR Skill 继续在轮询、产物列表、下载及下载后格式校验失败时保留公共任务 ID 且不重复提交（代码、`SKILL.md` 与回归同时恢复）。上游归档中的 `.omc/state/` 限流文件和 `__pycache__` 未纳入。
- 根索引新增 `local-decisions`（0.4.0，路径 `local-decisions-plugin/plugin.js`，两条 `usageSchema`：`input_tokens`/`output_tokens`），并把 `local-ocr` 升级到 0.1.9、七个模型与新的 `sha256`。`.githooks/check-push.js` 及其回归、`.gitignore` 的白名单同步加入两份新 ZIP，白名单现为十份；根 `README.md` 与 `AGENTS.md` 同步为十个工具、四个市场插件、五个 Skill。
- 离线验证：Local OCR 插件 fixture 14/14、Local OCR Skill 23 个用例全部通过、Local Decisions 插件 fixture 17/17、Local Decisions Skill 9/9，退出码均为 0，无跳过或 todo；发布保护回归 40/40。四份 ZIP 均由显式条目白名单重建，通过 CRC、安全路径、无嵌套归档、与工作树逐字节一致及干净解压测试（分别 14/14、17/17、23 OK、9 OK）。
- 未验证范围（整合当时）：未在 New API 或 moejs 实机安装或调用，未调用真实 OCR 或决策推理服务，未实测端口 18083/18503 的路由、配额预留与结算、市场安装和模型识别质量。用户提供的 2026-11-12 渠道 `#82` 实测记录只覆盖该部署与当时的源码，不是本轮最终源码的实测证据。本轮未提交、打标签或推送。下一节的隔离 rc.50 验证只补齐其中一部分。

## 隔离 New API rc.50 端到端验证（2026-11-13）

- 测试环境：本机起了与用户 `new-api-slave` 同镜像（`calciumion/new-api`，`v1.0.0-rc.50`）的隔离容器，端口 3001、独立本地 SQLite，未接共享 PostgreSQL，未使用用户账号、令牌或真实上游密钥。上游由宿主 mock 服务代替（18082 OCR / 18083 Piccolo / 18503 Jev-Omni），全部为合成请求，无真实文档、真实模型或付费调用。结束后 `docker rm -f new-api-plugin-test mockfwd`，并只按 PID 终止本次启动的 mock 监听进程；用户容器与共享数据库未被触碰。
- 安装链路：市场源指向本地提供的 `index.json` 与 `plugin.js`，在 New API 内完成「添加插件源 → 安装 → moejs 编译 → 新建 type 61 渠道 → 建令牌 → 客户端调用」。这验证了 New API 的插件安装与 moejs 运行时，**不验证从 GitHub Raw 公网索引一键安装**。
- Local OCR 插件 7/7 模型通过：每个模型都完成 `POST /v1/tasks/local-ocr` → 轮询 `GET /v1/tasks/<id>` 至 `SUCCESS` → `GET .../artifacts` → `GET .../artifacts/<key>/content`，各取回 20 字节 markdown；mock 日志确认选中模型名逐字转发，无隐式替换。`billing_context` 可见提交前预留与完成时结算（`model_ratio 37.5`、`other_ratios.pages`，100 页约合 $18.75 预消费）。
- Local Document OCR Skill 7/7：`scripts/parse.py --model` 逐个模型产出 7 个 markdown，md5 一致（mock 内容相同所致）；全程同一公共任务 ID，无重复提交。
- Local Decisions 插件 3/3 模型通过：`POST /v1/systemone` 均 200，`choice` 概率为两项且和为 1.0，`noul` 回答正常，`usage.output_tokens === 0`。路由由 mock 记录的 Host 头证实：两个 Piccolo 走 `127.0.0.1:18083`，Jev-Omni 走 `127.0.0.1:18503`，与 `MODEL_BASE_URLS` 一致，渠道 `base_url` 未覆盖该映射。
- Local Decisions Skill 3/3 模型、5 次调用：`request-choice`（Piccolo-4B）、`request-choice --model Piccolo-9B-Q8_0`、`request-jev`、`request-multi`、`request-noul` 全部成功，客户端校验与退出码符合文档。
- 四个离线套件同时全绿：Local OCR 插件 14/14、Local Decisions 插件 17/17、Local Document OCR 23 个用例 OK、Local Decisions Skill 9/9，无跳过或 todo。
- rc.50 部署侧观察（版本范围限定，是部署行为而非产品契约）：
  - type 61 渠道的模型集合必须与插件 `meta.models` 完全一致，否则被任务插件认领的模型返回 503 `model_not_found ... claimed by a task plugin`。
  - `users.group` 与 `tokens.group` 为空时，即使渠道与 abilities 正常，分销仍记录 `event=no_available_channel group=""` 并 503；补回 `default` 组后立即恢复。
  - `fetch_setting.enable_ssrf_protection`（默认 `true`）拦截从回环上游拉取 artifact 内容，表现为 `502 artifact_request_rejected`，回环部署需关闭该项。
  - 任务未到终态前 `GET .../artifacts` 返回 `409 artifact_not_ready`，属正常时序，不是插件缺陷。
  - `PUT /api/channel/` 在 rc.50 返回 `record not found`（更新需先 DELETE 再 POST）；`PUT /api/user/` 对配额的修改未见持久化，本地 SQLite 直改才生效。
  - 以 `--network container:<目标>` 挂接的 sidecar 在 `docker restart <目标>` 后消失，需重建并重新确认上游可达。
- 仍未验证：真实 OCR 识别质量与真实决策模型输出（上游全程为 mock）；GitHub Raw 公网索引的一键安装；用户的 `new-api-slave`（共享 PostgreSQL）部署；真实计费金额。用户提供的 2026-11-12 渠道 `#82` 记录仍只对应那一部署。本轮仍未提交、打标签或推送。
- 验证中发现并修正的文档偏差：`local-decisions-plugin` 的 `baseFor()` 对三个模型都命中 `MODEL_BASE_URLS`，渠道 Base URL 实际只在模型不在映射表时兜底，因此三个运行时必须与 New API 同机。原 README 第 5 步与根 README 第 7 步写成「把渠道 Base URL 指向 Piccolo 运行时、Jev-Omni 需加入 `allowedHosts`」，会让读者以为改渠道 Base URL 即可迁到其他主机。已改为说明同机约束与「同时改 `MODEL_BASE_URLS` + `meta.allowedHosts` 并按新版本重算 `sha256`」的路径。插件 `plugin.js` 未改，版本仍为 0.4.0，`index.json` 哈希复核一致；同一处措辞也已修正 `CHANGELOG.md`，因 README 与 CHANGELOG 都在发布 ZIP 内，`local-decisions-plugin.zip` 已按新内容重建（8 条目、9,862 字节、CRC 与逐字节一致）。另核对 `local-decisions/references/api-contract.md` 的上游端口表与 `plugin.js` 一致，无需改动。

## 本轮文件盘点（2026-11-13）

- 四个根目录输入 ZIP（`local-ocr-task-plugin-0.1.9.zip`、`local-document-ocr.zip`、`local-decisions-plugin-0.4.0.zip`、`local-decisions-skill-20261113.zip`）按仓库规则保持原位、保持 ignored/untracked，未移动、未重命名、未纳入 Git，也未改写成白名单发布路径。
- `git ls-files` 盘点：十个产品目录原位；`git ls-files --others --exclude-standard` 恰好是 `local-decisions-plugin/` 与 `local-decisions/` 下 20 个应发布文件，无其他游离文件。四份发布 ZIP 与工作树逐字节一致，两个插件源码的 LF SHA-256 与 `index.json` 一致。
- 各产品目录下由解压/测试残留产生的 `.omc/` 与 `__pycache__/` 均被忽略规则覆盖，且不在任何发布 ZIP 内。本轮删除了产品目录下的 `__pycache__/`（纯可再生缓存），保留了各目录的 `.omc/` 会话状态与根 `.omc/artifacts/` 下的验证材料，因后者的删除未获单独授权。
- 整理只做到「盘点 + 清理可再生缓存 + 记录」这一层：未移动、删除或重命名任何产品目录、历史文档、白名单归档或 `.omc/` 验证材料。

## 已发布：Local OCR 0.1.7 初始页数预留（2026-11-11）

- 在新分支 `fix/local-ocr-page-reservation` 上修复已发布 0.1.6 的初始配额预留不足，基线为 `0e82a84`。0.1.7 对每次任务表达式提交统一预留 100 页，不再信任调用方 `pages`、文件名或 MIME 元数据；独立旧式 `billing_ratios` 路径仍为 1，完成时继续使用任务服务的实际页数。提交、轮询、产物、模型和凭据转发逻辑未改。已发布 0.1.6 的源码和历史保持不变，根市场索引现已升级为 0.1.7。
- 三条初始回归先在旧逻辑上得到 10 通过、3 个预期失败，修复后通过。首次独立安全审查又指出按图片文件名预留 1 页仍信任调用方元数据；针对该边界新增回归先得到 12 通过、1 个预期失败（实际 1、预期 100），再改为统一 100 页。最终源码与干净解压 ZIP 各 13/13 通过，0 失败、跳过或 todo。最终独立安全复审无剩余 CRITICAL/HIGH/MEDIUM 安全问题。独立 verifier 对工作树与干净导出、版本/哈希、七文件 ZIP 和计费探针给出离线产品门禁 PASS；该结论不扩展为实机计费或 OCR 验证。
- 官方 New API 源码提交 `0409deccfff2b0e8babc28ca552af44d526375bf` 的静态检查确认表达式 usage facts 在预消费前参与授权；这不是对部署版本或真实计费行为的实测。0.1.7 的 `plugin.js` 为 7,314 个 LF 字节，SHA-256 `ec9a1b23bee8c05afe783698c44ff8fc4321c658f5dde82f719b9686ebc31bfb`，与 `package.json` 和根索引同步。
- 七文件 ZIP 已重建为 9,976 字节，SHA-256 `c8c10bc83d9a9aea3cf430683a0f50952d4c9f97b9dc98ba9ea35f1360697245`；白名单、CRC、安全路径、无嵌套归档、逐字节源一致性及干净解压测试通过。发布保护回归 40/40。实际 pre-push 对普通外发提交的 85 个唯一 blob 检查通过，无 `--no-verify` 或规则弱化。四个本地非空凭据值随后对全部可达历史的 237 个唯一 blob 完成精确扫描，0 匹配，未显示凭据；该启发式检查不证明未知秘密绝对不存在。
- 本轮未调用真实 New API/moejs、OCR 或付费服务；实际预留、扣费、退款、宿主 multipart/文件持久化、市场安装、OCR 文档处理和识别质量仍未验证。插件无声明依赖，审查中的 `npm audit` 因无 lockfile 返回 `ENOLOCK`，不作为依赖审计通过证据。产品基线提交 `ca8d3c7 fix: reserve maximum pages for Local OCR submissions` 已快进合并并推送到 `main`；其 `origin/main`、GitHub 递归树 86 个 blob 及固定提交 Raw 索引、插件源码和 ZIP 均核验一致。本发布状态由后续文档提交记录，避免状态提交使自身产品基线失效。

## 仓库整理与维护规则沉淀（2026-11-11，Local OCR 0.1.7 发布后）

- 接手时 `main` 与 `origin/main` 均为 `76471c5 docs: record Local OCR 0.1.7 publication`，工作树干净，`git ls-files --others --exclude-standard` 无游离的非忽略文件。`git ls-files` 盘点为 86 个跟踪文件、8 份白名单发布 ZIP、5 份仓库级设计与 5 份计划，八个产品目录保持原位。`git check-ignore -v` 的代表性检查覆盖 `.omc/`、`.remember/`、`.idea/`、`.superpowers/`、各产品真实配置类型、Python 缓存、两个未白名单实测输入 ZIP 及根目录参考 DOCX，均匹配忽略规则；其余本地路径未逐一检查，由忽略清单及零非忽略游离文件结果界定。本轮未移动、删除或纳入这些本地材料，也未读取或公开凭据内容。
- 本轮只修改 `AGENTS.md` 与本状态文档：新增 `git ls-files` 盘点入口、零文件/零 blob 审计无效、ZIP 条目路径不要重复拼接产品目录、下载与字节比对必须 fail-fast 四条规则。未修改任何产品源码、测试、版本、市场索引或八份发布 ZIP，也未因纯文档改动重打归档。`CLAUDE.md` 仍仅含 `@AGENTS.md`。
- 验证边界：上述为本轮实际执行的目录与忽略规则检查；未重新运行产品测试套件，因为产品代码与测试无差异。Local OCR 0.1.7 的离线验证结论仍以 `ca8d3c7` 基线记录为准。此前对最终状态提交 `76471c5` 的固定提交 Raw URL 重试遇到连接重置/超时，该提交的 Raw 字节一致性未完成核验；产品提交 `ca8d3c7` 的 Raw 与 GitHub 递归树核验已通过。下一次推送前后应按 `AGENTS.md` 的 fail-fast 规则重新验证，不将失败重试记为通过。

## 仓库整理与维护规则沉淀（2026-11-10）

- 盘点时 `main` 与 `origin/main` 均为 `0e82a84`，产品文件无未提交改动，Git 中无游离的非忽略文件。86 个跟踪文件保留八个产品目录的原位分类：每个产品内分别放置源码、测试、公开文档和精确发布 ZIP；仓库级设计与计划保留在 `docs/superpowers/`，状态留在本文件，长期规则集中在根 `AGENTS.md`。没有为美观移动或删除文件。
- 本地 `.remember/remember.md` 作为接手记录，`.omc/` 中的诊断、付费测试、审查及干净导出材料继续作为忽略证据保留；真实配置、缓存、编辑器状态和未白名单归档不纳入 Git。未删除这些可能含本地凭据或付费产物的材料，也未将其内容复制到公开文档。
- `AGENTS.md` 新增可信配额预留、文档凭据占位符、仅 amend 未推送提交、GitHub API 限流时固定提交 codeload 的核验边界，以及状态文档使用耐久产品基线等规则。本轮只修改维护文档和本地接手记录，不修改任何产品源码、测试、版本、市场索引或八份发布 ZIP，不追溯调整已发布的 Image 2.6 或 Local OCR 0.1.6。

## 已发布：Local OCR 插件与 Skill（2026-11-10）

- 按用户确认的统一目录方案，将 `local-ocr` Task Plugin 0.1.6 和 `local-document-ocr` Agent Skill 分别整合到 `local-ocr-task-plugin/` 与 `local-document-ocr/`，删除经逐字节核对的嵌套重复源码及第二份插件索引。插件源码、模型 ID、版本和哈希保持不变；插件 LF SHA-256 为 `c10ce313198ff5e4e33b9f6638fbfd44d1901ce745997fdd82261906e24ad60a`。独立审查后，Skill 为轮询、产物列表、下载及下载后格式校验失败补齐公共任务 ID，并将非法 UTF-8 Markdown 转为友好错误；新增不重复提交、保留既有输出、非标准凭据脱敏及这些恢复路径的五条 CLI 回归；最终独立只读复审无剩余 CRITICAL/HIGH/MEDIUM 并批准。非标准凭据回归证实所指提交应用级错误路径原本已传入密钥。设计与计划见 `docs/superpowers/specs/2026-11-10-local-ocr-repository-integration-design.md`、`docs/superpowers/plans/2026-11-10-local-ocr-repository-integration.md`。
- 根 `index.json` 只新增 `local-ocr@0.1.6`，源码路径为 `local-ocr-task-plugin/plugin.js`；同步两个模型、两条原生路由及 `pages` 用量。Skill 未加入市场索引。安装插件不会安装 Skill 或 OCR 推理服务，仍需独立部署的鉴权 OCR 任务网关。根 README、`AGENTS.md`、插件 README 和两份精确 ZIP 白名单均已同步。
- 新验证：插件 Node fixture 11/11、Skill Python 22/22、发布保护 40/40，退出码均为 0，无跳过或 todo。两份 ZIP 分别从 7 个和 5 个白名单文件重建，通过 CRC、安全路径、无嵌套归档/私有状态、源文件逐字节一致性及 4 个本地非空凭据值的精确扫描，0 匹配；干净解压后插件 11/11、Skill 22/22 通过。该扫描不证明未知秘密绝对不存在。两个 OCR Python 文件通过 3.9 语法级解析检查；本机无 Python 3.9，未做该版本运行时测试。插件示例默认 HTTP 地址的传输边界已补充到安装文档，未为消除通用告警而改变已冻结的 0.1.6 源码/哈希。
- 未验证范围：本环境没有 `new-api` 可执行文件；未在 New API 市场或 moejs 实机安装/运行，未调用真实 OCR 服务或上传文档。离线 fixture 不能确认宿主对选中模型的传递方式，也不能解决根索引 `taskIdParam: "task_id"` 与插件原生路由未显式声明该字段之间的契约差异；两项均保留原实现，未凭猜测改动版本化源码。插件 README 中的真实 New API 双模型测试及 Skill 中 CPU 耗时是用户提供资料对特定版本和硬件的报告，不是本轮新增实测。
- 功能提交 `7e01a51 feat: integrate Local OCR plugin and Skill` 包含 22 个路径及 Skill ZIP；`aae43c1 chore: add Local OCR client archives` 单独提交插件 ZIP。初次推送被 pre-push 正确拦截：插件 README 的虚构 OpenAI-style 示例令牌同时触发 Bearer/OpenAI-style key 启发式检查；与 4 个真实本地凭据值无匹配。已改为尖括号占位符并重建插件 ZIP，未使用 `--no-verify` 或弱化 guard。两个当时尚未推送的提交经 soft reset 重新创建，未改写已发布历史。最终普通推送 `70be661..aae43c1` 成功，实际 pre-push 对 85 个唯一 blob 检查通过。
- 首次发布归档的插件 ZIP 为 9,238 字节、7 个条目，SHA-256 `6a96d0c357d9e3e4d7a94ca2de15a4899f0fae80de5fa0ca3ac795c282771a3f`；Skill ZIP 为 46,719 字节、5 个条目，SHA-256 `0d6505a5bbf620dfba85dc64db40953d15bc4f7b80bdcc8d9ec5c5e978d67e4e` 且后续未变。
- 推送后 GitHub 固定提交递归树的 86 个 blob 路径、SHA 和大小与本地一致且未截断；`index.json`、插件源码/README/ZIP、Skill 源码/测试/SKILL/ZIP、`AGENTS.md` 和根 README 共 10 个固定提交 Raw URL 与 Git 字节一致。匿名逐 blob API 审计因限流未完成，未宣称该路径通过；改用同一不可变提交的 codeload ZIP，86 个文件 CRC 通过，对 4 个真实本地凭据值扫描为 0 匹配。这些检查不等于 New API 实机安装或未知秘密不存在的证明。
- 推送后静态安全审查发现 0.1.6 的 `extractUsage()` 以请求中的 `pages` 或默认 1 页作提交预授权，而可信页数由任务服务稍后提供；多页 PDF 可能以不足的初始预留通过配额检查，完成时结算不能补足提交授权。该风险适用于非零按页价格，不证明离线 fixture 已复现真实扣费绕过。随后纯文档更新补充 README 安全警告：0.1.6 不得启用非零按页计费或作为唯一配额控制，保持零价格配置，或另设可信预留；修复应在后续版本改为可信文档检查或最多 100 页预留，不能覆盖已发布版本源码/哈希。README 变更同步重建插件 ZIP；更新后归档为 9,573 字节，SHA-256 `7ebd2ca13dd27dbaa50d1c36328d9c9c31fbaf90b67771a08df6ba46aa5580ec`。

## 已发布：Jihuarst Image 2.6（2026-11-10）

- Image 2.6 的发布状态提交为 `70be661 docs: record Image 2.6 publication`；其中 `88703f0 merge: integrate Jihuarst Image 2.6 support` 是以 `--no-ff` 创建的功能合并提交，父提交为 `f656bc9` 与 `877e034`。功能提交依次为 `94e765d feat: support GPT Image 2.6 generation options`、`e89ef06 chore: rebuild Jihuarst Image client archive`、`877e034 fix: scope first-push checks to outgoing commits`。`feat/jihuarst-image-2-6` 在本地和远端均保留于 `877e034`，未删除、变基或强推；本轮未打标签、未创建 PR、未在 New API 中安装验证。实现与计划见 `docs/superpowers/specs/2026-11-09-jihuarst-image-2-6-design.md`、`docs/superpowers/plans/2026-11-09-jihuarst-image-2-6.md`。
- Jihuarst Image 新增 `gpt-image-2.6-sunburst`、`gpt-image-2.6-exact`、`gpt-image-2.6-flare`，支持 `complexity=low|medium|high`、任意非 null JSON 的 `svg` / `markup-json`、2–16 的 `frame_count`、至少 20 ms 的 `frame_duration_ms`，以及 edits 模式的本地 `markup` 文件。mask 与两种 markup 输入互斥，非法 complexity、帧参数及非正/非有限 timeout 均在付费请求前拒绝。generations 与 edits 默认请求 `response_format=url`，保留 base64/data URL/远程 URL 响应兼容、URL 下载安全限制和默认 180 秒超时。默认回退扩为 4 URL × 7 模型共 28 个组合；提供 2.6 新参数且未指定模型时只选三个 2.6 候选，显式非 2.6 模型在请求前失败。SVG/GIF 按字节本地交付，SVG 只识别有界根标签，不执行、不渲染、不宣称已消毒。
- New API `v1.0.0-rc.49` 与 PR #8208 是字段转发契约证据；2026-11-09 只读 `/v1/models` 只证明三个 ID 已列入 Jihuarst 目录。任意 JSON `svg` 和 generations JSON markup 是用户确认的宽松网关兼容扩展：官方 `svg` 为结构化对象，官方 generations schema 不含 markup；`json.RawMessage` 不证明任意值符合官方语义。`response_format=url` 是 Jihuarst 部署特定选择，官方 GPT Image 使用 base64；`gpt-image-2.6-exact` 是目录 ID，不称为官方模型枚举。官方 OpenAPI 与 Python SDK 对 edits SVG 的版本定义冲突，客户端不宣称该路径已获上游支持。最新 URL 模式真实验证中，七模型 generations 与八模型单图 edits 的生成响应均 HTTP 200；完整交付仅混元 generations 一项和混元 edits 两项，六个 GPT 模型均因 `img.hud.im` 图片下载失败而无文件。`complexity`、SVG、GIF、本地/JSON markup 请求均为 HTTP 500 无可用渠道，未取得真实产物。私有 b64 强制对照的 generations/edits 各成功交付一张 PNG，不代表生产默认 URL 路径已完整交付，详见下方完整矩阵。
- 当前源码通过 80/80 离线测试，退出码 0；发布保护测试 40/40，退出码 0。最终客户端 ZIP 已按最终源重建为 34,698 字节，SHA-256 `d6fc7f67840df8a330b65c7dade25fad0b01df7f67853454932d9d980d800247`，仅含四个白名单文件，通过 CRC、源文件逐字节一致性、无嵌套归档和本地非空凭据值精确扫描。干净解压离线测试为 80/80、退出码 0；变更文件凭据扫描及空暂存区检查通过。新增覆盖包括默认 URL、`output_format`、严格 `data` 条目数、脱敏下载错误、普通 `Mozilla/5.0` 下载 UA，以及 complexity/帧参数/timeout 和 mask+markup 的请求前拒绝；新校验回归在旧实现上产生 14 个预期失败后转为通过。UA 修复有真实红绿回归：它解决了已复现的 Python 默认 UA 触发 HTTP 403 的一层兼容问题，但最终生产 opener 对既有 URL 仍在 181.3 秒后超时且无文件；同一 UA 的普通 HTTPS 也在 200 响应头后超时，不能宣称 URL 正文交付已修复。上述离线测试不验证真实 TCP/TLS、网络时序或线上交付。
- 三个视频项目使用 `/v1/videos`（插件协议为 `openai_video`），本次 Images API 扩展不要求修改其模型、源码、版本或市场索引。未改动 `jihuarst-video`、`video_wb2api_hub_newapi`、`video_wb2api_panel_newapi` 源码；回归结果分别为 67/67、20/20、18/18 离线测试通过，退出码均为 0；同日两个视频模型均完成真实 MP4 交付。此结果不代表真实 New API rc.49 已实测。

## 当前基线

- Local OCR 的最近产品基线为 `ca8d3c7 fix: reserve maximum pages for Local OCR submissions`，已快进合并并推送到 `main`；`76471c5 docs: record Local OCR 0.1.7 publication` 记录其发布状态。本地分支 `fix/local-ocr-page-reservation` 仍指向 `ca8d3c7`，未删除。开始新工作前以实际 Git/远端为准，不以本文件的提交号代替检查。
- `70be661 docs: record Image 2.6 publication` 推送后，GitHub 递归树的 70 个 blob 路径、SHA、大小与本地一致且未截断，脚本、测试、`SKILL.md`、ZIP、状态文档、guard 及设计/计划等 10 个发布敏感文件的固定合并提交 Raw URL 与 Git 字节一致。两个功能分支提交正常推送时 pre-push 均扫描 73 个唯一 blob 并通过，未绕过检查；对 4 个本地非空凭据值检查 208 个历史 blob、70 个远端树条目及发布 ZIP 内容均为 0 匹配。该精确值审计不证明未知历史秘密绝对不存在。
- 上一已发布基线：`35e8930 chore: rebuild Jihuarst client archives`，前一提交为 `b37acb6 fix: stabilize Jihuarst offline HTTP fixtures`。其后 `f656bc9 docs: reorganize maintenance guide and release status` 是本轮分支起点。当时 `35e8930` 的 GitHub 根树为 `8a08cde4a0bd8ef7d392d8ec0cb6e735c06ad4a5`，68 个 blob 的路径、SHA 和大小与本地一致，相关固定提交 Raw URL 均返回 HTTP 200 且字节一致。
- 本轮发布包括仓库文档整理、Jihuarst Image/Video 离线内存 HTTP fixture、对应官方 ZIP，以及 2026-11-07 的真实付费验证记录。生产 `scripts/generate.py`、New API 插件源码、市场索引及版本均未修改；本地凭据、任务 ID、日志和付费媒体仍只保留在忽略目录。
- 更早的发布基线：`b6172df docs: record moejs plugin publication`，此前依次为 `a3f2a47 chore: rebuild video plugin client archives`、`6800031 fix: support moejs video gateway URLs`。三个提交已推送至 `origin/main`，Hub 1.3.2、Panel 1.1.2、索引、两个插件源码及两个 ZIP 的 Raw URL 均返回 HTTP 200；当时 GitHub 根树及 66 个 blob 条目与本地 `b6172df` 完全一致，Raw 索引、源码、ZIP 字节和源码 SHA-256 均与本地提交一致。
- `6b3aef1` 完成 WorkBuddy Video 多模型升级及 Jihuarst Image 完整交付重试；`03936d8` 提交对应的两个客户端 ZIP；`6098964` 建立项目状态及长期维护规则；`3a24780` 更新参数契约、实测边界和维护规则，并重建图片、视频客户端 ZIP。
- `726dfec` 将视频插件重命名为 Hub 专用：目录 `video_wb2api_hub_newapi/`、key `workbuddy-video-hub`、显示名 `WorkBuddy Video Hub`、版本 1.2.0；同步 `index.json`、文档、ZIP 与发布保护白名单，共 14 个文件。
- `3a24780` 与 `726dfec` 均已推送至 `origin/main`。`726dfec` 推送后远端文件树与本地提交一致；新 `index.json`、`video_wb2api_hub_newapi/plugin.js`、`video_wb2api_hub_newapi/video_wb2api_hub_newapi.zip` 的 GitHub Raw URL 均返回 HTTP 200（分别为 961、8806、9187 字节），旧目录 `video_wb2api_newapi/` 不再存在于当前版本。
- 1.2.0 的 `index.json` 版本、路径与插件源码 LF 归一化 SHA-256（`9bfee89c5e9ce129f23c3b45f48efac3b9111855553671ff4ba1601c4a308a32`）一致。
- 上述发布事实分别对应 2026-11-06 与 2026-11-07 的检查，不代表后续提交也已发布。开始新工作前必须重新检查 Git 状态和远端。

## 十个项目的当前状态

| 项目 | 当前状态 | 最近的验证范围 |
|---|---|---|
| `video_wb2api_hub_newapi/` | WorkBuddy Video Hub 1.3.2，key 为 `workbuddy-video-hub`；仅用于 wb2api Hub，不兼容 Panel；moejs 兼容地址解析、错误脱敏 | 2026-11-09 回归 20/20 离线测试通过；用户报告 2026-11-06 两个模型实测成功 |
| `video_wb2api_panel_newapi/` | WorkBuddy Panel Video 1.1.2，key 为 `workbuddy-panel-video`；仅用于 wb2api Panel；moejs 兼容渠道/COS 解析、错误脱敏、不向 COS 转发密钥 | 2026-11-09 回归 18/18 离线测试通过；用户报告 2026-11-06 两个模型实测成功 |
| `jihuarst-image/` | 已合并并推送到 `main` 的 `88703f0`，后续 `70be661` 记录发布状态；三个 2.6 模型、新请求字段、markup、`output_format` 与 SVG/GIF 字节交付；保留 `feat/jihuarst-image-2-6` | 2026-11-10 合并结果 80/80 离线测试通过；此前源码与干净解压 ZIP 各 80/80；四文件归档与安全审计通过；真实交付限制见完整矩阵 |
| `jihuarst-video/` | 双模型异步视频生成 Skill；本轮未改源码，Images API 更新不适用于其 `/v1/videos` 通道 | 2026-11-09 回归 67/67 离线测试通过 |
| `zaiwen-image-generation/` | 独立图像 Skill；本轮未改动 | 本轮未重新运行其专项测试；本轮整合前六个 ZIP 的跟踪状态检查通过，历史安全审计覆盖其归档 |
| `local-ocr-task-plugin/` | Local Document OCR 0.1.9，key 为 `local-ocr`；七个 OCR 模型；任务表达式提交统一预留 100 页，完成时按任务服务实际页数结算；本轮在 `feat/local-decisions-and-ocr-updates` 上从 0.1.7 更新 | 2026-11-13 源码与干净解压 ZIP 各 14/14 离线测试通过；同日隔离 rc.50 实例内 7/7 模型完成提交→轮询→产物→内容下载；真实 OCR 识别质量、公网 Raw 一键安装、用户共享 PostgreSQL 部署未验证 |
| `local-document-ocr/` | 对应 OCR Skill；新增 VLM 模型的 `--quality`；单文档提交、同任务轮询、同源产物下载、格式/ZIP 校验，轮询、产物列表、下载及下载后格式校验错误保留任务 ID 及原子输出保护 | 2026-11-13 源码与干净解压 ZIP 各 23 个用例通过；同日隔离 rc.50 实例内 7/7 模型运行 `scripts/parse.py --model` 各产出 markdown；真实 OCR 文档及识别质量未验证 |
| `local-decisions-plugin/` | 新增：Local Decisions 0.4.0，key 为 `local-decisions`；同步 `/v1/systemone`，`choice`/`noul` 校验，Jev-Omni 独立运行时，8192 token 上限预留；本轮未提交或发布 | 2026-11-13 源码与干净解压 ZIP 各 17/17 离线 fixture 通过；同日隔离 rc.50 实例内 3/3 模型 `/v1/systemone` 通过，Piccolo→18083、Jev-Omni→18503 路由经 Host 头证实；真实决策模型输出、公网 Raw 一键安装未验证 |
| `local-decisions/` | 新增：对应决策 Skill；标准库客户端、请求/响应校验、退出码 0/2/3/4，文档强调决策为建议而非授权 | 2026-11-13 源码与干净解压 ZIP 各 9/9 离线用例通过；同日隔离 rc.50 实例内 3/3 模型、5 次示例调用全部成功；真实推理服务未调用 |
| `unified-web-mcp/` | 0.1.0；本轮未改动 | 2026-11-06 文档整理中源码 85/85 离线测试通过；更早历史见项目内 `PROJECT_MEMORY.md` |

这些数字是注明日期的发布基线及文档整理验证快照，不是永久有效的当前测试结论。改动后必须重跑相关套件。

## 已完成的重点

1. 将 Kling 专用插件原位泛化为 WorkBuddy Video，同步目录、key、模型、版本、市场索引、文档、ZIP 和发布保护白名单。
2. 插件保持 New API 所选模型的显式转发，没有隐式模型替换。
3. 图片生成在网络、HTTP、解析、下载、图片校验、数量不足及本地输出失败后尝试下一 URL/模型组合；显式 URL/模型参数仍限制候选范围。
4. 原子写入、旧文件备份、逆序回滚及恢复失败时的备份保留行为均保留。
5. 五个发布 ZIP 共 37 个条目通过白名单、CRC、源码逐字节一致性和本地凭据值审计；两个升级 ZIP 已重建。
6. 历史发布阶段的相关改动曾经独立 Opus 审查通过，当时无 CRITICAL、HIGH 或 MEDIUM 问题；该结论不自动覆盖当前 `feat/jihuarst-image-2-6` 最终差异。当前 2.6 工作的审查范围和后续校验修复见实施计划，未把早期 75-test 审批套用到当前版本。
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

## 2026-11-09 Jihuarst 全模型基础付费验证

- 用户明确授权对 Jihuarst Image 当前 8 个基础模型和 Video 两个模型逐项测试。每项只启动一次当前仓库生产命令，固定 `https://api.jihuarst.top` 和单模型，不扩展入口或模型回退；图片 `n=1`、1536x1024、low，视频 5 秒、1280x720。改图只上传本地生成的 64x64 测试 PNG，不上传私人文件。现有资料没有可靠单价，实际费用须由网关核对。
- 图片成功 2/8：`gpt-image-2.5` 与 `gpt-image-2` 完成请求、图片交付及本地保存，PNG 签名和 1536x1024 尺寸通过；文件分别为 1,362,001 字节、SHA-256 `b78995221d5d7b933c8050dee101a344b1f24f29504046cc0e42efa1aef64432`，以及 962,536 字节、SHA-256 `c9f164c137852fbd31f3a21b5d359584aa0408c945d158a79faf9aa10e2a9733`。未单独验收视觉质量。
- 图片失败 6/8：三个 `gpt-image-2.6-*` 模型、`gpt-image-2.5-flare`、`hunyuan-image-alpha` 均在读取 HTTP 响应前观察为 `RemoteDisconnected`；`hunyuan-image-alpha-edit` 观察为 TLS EOF。六项均无本地图片，未进入图片下载或保存。客户端无法确定断开发生在渠道、代理或其他网络层，先前将其归因于“上游关闭连接”的证据不足，已修正。默认等待上限已经是 180 秒，实际 `RemoteDisconnected` 在 18–141 秒出现，不是 Python `socket.timeout`，不能改判为客户端等待超时。请求可能已在上游产生费用，未重试、未切换入口或模型。
- 用户随后提供的渠道记录与手动直连报告显示：渠道 #69 的三个 2.6 模型均返回 HTTP 200，手动直连在 102–119 秒得到有效 b64_json 图片；渠道 #72 的 `hunyuan-image-alpha` 及 `hunyuan-image-alpha-edit` 也成功返回有效图片，改图直连耗时 9 秒。这是用户提供的上游与直连证据，证明上游能够完成生成，但尚未证明本客户端路径恢复或失败断点的具体位置。本次混元客户端只传一张参考图，生产代码在单图分支发送 `image`，并非多图的 `image[]`；因此多图字段问题不能解释本次单图 TLS EOF，未据此修改字段名或增加超时。
- 视频成功 2/2：`minimax-video-h3` 和 `kling-video-v3` 均完成提交、同一任务轮询、MP4 下载及本地保存，没有创建替代任务；文件分别为 439,632 字节、SHA-256 `ea00c29441dad7c749fc5a7a4614ffec8b4941ff8e16a5ac51a0d9e90b47168f`，以及 2,733,430 字节、SHA-256 `c537c96e04864a989184c29002b60dce6d94a02f7f61a991a53d3b5be0205d55`，MP4 `ftyp` 签名均通过。本机没有 `ffprobe`/`ffmpeg`，未验证编码参数、精确时长、逐帧解码或视觉质量。
- 串行测试运行器因存在 6 个失败模型以退出码 1 结束，未将其写成全通过。产物、逐项日志和结果保存在忽略的 `.omc/artifacts/live-all-models-20261109/`；真实任务 ID、凭据及媒体不进入公开状态、Git 或发布 ZIP。本次没有修改生产脚本，也未提交或推送。

## 2026-11-09 八模型单参考图 edits 付费验证

- 用户明确要求对 Jihuarst Image 的八个模型全部各跑一次单图 edits。运行器串行启动八次当前仓库生产命令，每项固定 `https://api.jihuarst.top` 和单模型，不重试或扩展回退；使用同一本地生成的 64x64 PNG，`n=1`、1536x1024、low，保留默认 180 秒等待。单图 multipart 文件字段为生产代码原有的 `image`。没有可靠单价，实际费用须向网关核对，失败请求也可能已生成或计费。
- 成功交付 4/8，均为完整本地保存的 1536x1024 PNG：

| 模型 | 耗时 | 文件大小 | SHA-256 |
| --- | ---: | ---: | --- |
| `gpt-image-2.6-exact` | 101.1 秒 | 1,493,038 字节 | `03be70591bfca4009d069aacd827ab530942f97cadb7ffde21d63bec8a9a57fe` |
| `gpt-image-2.5` | 44.3 秒 | 1,640,153 字节 | `06eb5713a873c7f939b808774431115346f81f3d2ce5bf87512c94df3ce4039a` |
| `hunyuan-image-alpha` | 19.6 秒 | 858,080 字节 | `ad9a3ad310491a714ee8630b5683501cbfdb1f5392cb11c688b8d19d118f0ba8` |
| `hunyuan-image-alpha-edit` | 18.5 秒 | 930,214 字节 | `974c8ad8cf2fb8f3130ed766d172061c67fbd4af75defbff5a26af8df4fc076d` |

- 失败 4/8：`gpt-image-2.6-sunburst` 在 173.9 秒、`gpt-image-2.6-flare` 在 171.7 秒观察为 `RemoteDisconnected`；`gpt-image-2.5-flare` 在 49.6 秒观察为 `JSONDecodeError: Unterminated string`，即客户端收到不完整 JSON；`gpt-image-2` 在 3.4 秒观察为 TLS EOF。四项均无本地图片，不能确定异常具体发生在渠道、代理或其他网络层，也不把异常改判为默认等待超时。此处结果只对应各自单次 edits 请求，不与上一轮 generations 或用户直连报告混算。
- 独立复核确认四个实际文件的大小、SHA-256、PNG 签名及 1536x1024 尺寸与累计结果一致，四个失败项均无输出文件。串行运行器因存在失败项以退出码 1 结束。产物、逐项日志、结果及核验文件保存在忽略的 `.omc/artifacts/live-all-edits-20261109/`，真实任务 ID、凭据及媒体不进入公开状态、Git 或发布 ZIP。
- 本轮没有修改生产脚本。测试不覆盖多图、mask、SVG/GIF/markup，不验证视觉质量；失败请求未自动重试。分支仍未提交或推送。

## 2026-11-09 默认图片响应格式调整

- 用户补充提供 new-api HTTP 200 日志及独立直连结果：sunburst、flare 的 base64 JSON 响应约 2.7–2.9 MiB，指定 `response_format=url` 后三个 2.6 模型均返回 270–429 字节的 JSON 和图片 URL。该证据证明该部署能够返回 URL、避免大 base64 JSON，但 `RemoteDisconnected` 本身不证明本机主动断开；客户端生成响应上限实际为 256 MiB，默认超时同时覆盖连接和读取，不能把失败解释为 2–3 MiB 超过上限或独立读取超时。
- 据此将 `jihuarst-image/scripts/generate.py` 的 generations 与 edits 默认 `response_format` 从 `b64_json` 改为 `url`。保留 `b64_json`、data URL 和远程 URL 的既有解析、远程图片下载不转发网关 key、SSRF/重定向限制及 180 秒默认等待，不调整响应大小上限或字段名。回归测试先要求 generations 发送 `url` 并在旧实现上失败，再修改生产代码通过；另为 edits 请求补充同值断言。
- 这是上述八次真实 edits 之后的生产改动。2026-11-09 随后按用户授权，仅对 `gpt-image-2.6-sunburst` 与 `gpt-image-2.6-flare` 各运行一次单图 edits 真实付费复测，固定原 HTTPS 入口、同一参考图和参数，不重试。两项均未再出现 `RemoteDisconnected`，但完整交付仍为 0/2：sunburst 在 33.0 秒后进入图片 URL 下载阶段并失败；flare 在 49.9 秒返回 3 个图片条目，与请求 `n=1` 不符，被严格数量校验拒绝。两项均无本地图片，运行器退出码 1。原始生成 JSON 未落盘，sunburst 的下载异常又被归一为“图片下载失败”，现有证据不能进一步区分 HTTP 错误、网络异常或 URL 校验拒绝；没有为补日志再次生图。此前成功/失败表仍精确描述旧 `b64_json` 默认行为。文档与客户端 ZIP 随生产改动同步重建，提交和推送仍未授权。

## 2026-11-09 Jihuarst Image 完整验证、下载诊断与交付边界

- 用户随后明确授权完整 Image 全量验证、必要修复和真实付费测试。矩阵固定 `https://api.jihuarst.top` 与单模型，每项只启动一次，不扩大回退；只上传脚本生成的 64x64 PNG。没有可靠单价，实际费用须由网关核对，失败请求也可能已生成或计费。产物和含敏感 URL 的原始诊断均保存在忽略的 `.omc/artifacts/`，不进入公开 Git 或 ZIP。
- 最新默认 URL generations：七个模型均 HTTP 200 且各有一个 `data` 条目。仅 `hunyuan-image-alpha` 完整交付 1536x1024 PNG，2,022,259 字节，SHA-256 `0e08546dd5e5b2cf2bf20893fe3ed7fa64fa0a6b1915805be578665edf301e9b`。六个 GPT 模型的图片均来自 `img.hud.im`；五项下载 HTTP 403，flare 为 180 秒 URLError/超时，均无本地文件。
- 最新默认 URL 单图 edits：八个模型均 HTTP 200 且各有一个条目。`hunyuan-image-alpha` 与 `hunyuan-image-alpha-edit` 分别交付 1536x1024 PNG（1,441,819 / 838,126 字节；SHA-256 `ce53af2896ddf7fa1b10aee584e11918143588a2d1c617b94462f78427ef4446` / `0ca34001d2bc9da2e729670bdd155a47134e977a474cc64ce335e79ead9284ee`）；六个 GPT 模型下载失败（五次 HTTP 403，sunburst 为 180 秒 URLError），均无文件。flare 的一次三条目现象未复现，仍保持严格 `n` 数量合同。
- 三个 2.6 模型的 `complexity=low`、exact 的 SVG/GIF，以及本地 markup 文件和 JSON markup 均 HTTP 500，网关报告 `auto` 分组没有可用渠道；已离线核对请求编码，但没有真实产物，不能宣称这些参数的语义、格式或标注效果已验证。
- 其余参数路径：`n=2` 的生成响应恰好两条目，但一次下载超时、一次 403，两张均未保存；多图 edits 为 96.9 秒 `RemoteDisconnected`；mask、fidelity、尺寸/质量、JPEG、WebP 均因下载失败或超时不能验证最终内容语义。私有强制 b64 generations/edits 各成功交付 1536x1024 PNG（1,093,349 / 1,083,623 字节；SHA-256 `90fdff797430fb99ff7248d39d0a74a07431fb876cabd8294b68d6eae5a9ab4b` / `24770c1c08900268be795251f35c8b9d9e3644367b0021b64e46acc7d899a2cd`），生产默认仍保持 URL。
- 无新生成的同机 URL 对照证明默认 Python UA 是 HTTP 403 的触发因素之一：同 URL、无代理、HTTP/1.1 curl 改为 Python UA 后为 403；生产安全 opener 改用 `Mozilla/5.0` 后可取得 200 `image/png` 响应头，但正文仍超时。最终生产 opener 对既有 URL 在 181.3 秒后为 `URLError` / `TimeoutError`，无状态码和文件；同 UA 普通 HTTPS 也在 200 响应头后 150.9 秒超时。Range 没有取得 206/`Content-Range`，也未完成正文。因此 UA 兼容修复保留，URL 正文完整交付仍明确未解决；没有关闭 SSRF、TLS、凭据隔离或代理隔离。
- 本轮没有重新启动已完成的付费矩阵，也没有新增视频付费任务。New API 实机安装、SVG/GIF/complexity/markup 真实产物、GPT URL 完整交付及真实费用仍未验证。

## 已知边界与待办

- **Local OCR 0.1.7 已合并并推送到 `main`。** 产品基线为 `ca8d3c7`，根索引、源码和 ZIP 已核验远端一致；真实 New API/moejs、实际预留/扣费/退款、市场安装和 OCR 服务仍未验证。
- **隔离 rc.50 只补上「契约与运行时」这一层。** 2026-11-13 的隔离实例验证了安装、moejs 编译、type 61 渠道、`/v1/systemone`、任务驱动的提交/轮询/产物下载和 18083/18503 路由；上游是 mock，因此真实 OCR/决策质量、真实计费金额、公网 Raw 索引一键安装、用户的共享 PostgreSQL 部署仍属未验证。不要把这一节的结论外推为「用户的 slave 上已跑通」。
- **New API 市场安装未实测。** 已验证的是索引、源码 URL、哈希及离线契约，不应把它描述成真实 New API 安装成功。
- **Jihuarst 历史离线测试失败已单独修复并复验。** 详见上方 2026-11-06 修复记录及 2026-11-07 真实付费验证。离线 fixture 和真实网关属于不同验证层次，离线通过不代替真实交付验收。
- **Panel 模型实测范围。** 用户报告 2026-11-06 Panel 的 MiniMax H3 与 Kling V3 任务成功；维护规则现已改为保留该版本范围的证据，不将其扩张为后续最终 COS 解析补丁的实测结论。
- **历史视频下载故障已在后续指定路径复测通过，不代表上游问题已根治。** 2026-11-04 曾观察到两个模型的任务完成后返回 MP4 URL 为 404、content/artifact 代理为 502；2026-11-05 固定 HTTPS 入口及单模型的测试均成功交付 MP4。其他入口、参数与后续服务稳定性仍不在此次验证范围内。
- **视频媒体质量未完整验收。** 当前环境没有 `ffprobe`；只验证了下载字节与 MP4 `ftyp` 签名，没有验证编码参数、精确时长、逐帧解码或视觉内容。
- **全历史 ZIP 扫描存在已知阻断。** `node .githooks/check-push.js --all` 会按历史路径识别旧 `kling_wb2api_newapi/kling_wb2api_newapi.zip` 与 `video_wb2api_newapi/video_wb2api_newapi.zip`，并因其不再是当前白名单路径而失败。这属于已移除历史产物的路径策略限制，不是本次普通推送失败；普通推送的增量检查已通过。不得为绕过它而弱化当前规则或擅自改写历史。
- `gh` CLI 在当时的 Windows 环境不可用，远端文件树通过 GitHub API 核对；不要假设所有机器都安装了 `gh`。
- 2026-11-10 已按用户明确授权提交、先推送 `feat/jihuarst-image-2-6`，以 `--no-ff` 合并并推送 `main`，保留功能分支。没有新增视频付费任务、打标签或 New API 实机安装；合并后 80/80 图片离线测试通过，两次真实推送均未绕过 pre-push。完整结果见上一节：GPT URL 正文交付仍未修复，SVG/GIF/complexity/markup 因无可用渠道没有真实产物，其他入口或参数的重试仍需注明范围与可能费用。
- 根目录的 `可乐生图_API接口参数说明.docx` 是用户提供的本地只读参考，尚未纳入 Git。它描述的是另一部署的前端行为，不能作为 Jihuarst 参数能力的直接证据；若需长期保存，应先决定是否公开及如何去除敏感内容。

## 接手顺序

1. 运行 `git status --short --branch`，确认分支、远端及未提交改动，不依赖本文件的基线代替检查。
2. 阅读根 `AGENTS.md`、对应项目的 `README.md` 或 `SKILL.md`，再阅读 `docs/superpowers/specs/` 中的相关设计。
3. 在对应项目目录运行离线测试；失败、跳过或不可用必须明确报告。
4. 修改可分发项目后重建其指定 ZIP，并执行干净解压、字节一致性及凭据审计；接手 Local OCR 0.1.7 时先阅读顶部已发布记录及其实机验证边界。
5. 只有用户明确授权时才提交或推送；推送后核对远端文件树与原始发布 URL。
