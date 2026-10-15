# FDEX 招投标实训项目

欢迎加入 `iurp/fdex-tender-agent`。我们共同建设一套供团队自己使用的招投标工作流：发现机会、读取文件、组织资料、编制响应、审查、模拟递交与经营交接。

仓库由 Zephyr／iurp 长期维护。你围绕已发布任务贡献代码、Skills、配置、样例和验证，不需要把 workshop 中自己的完整版本搬进来。

**第一次加入：先跑通下面的正常样例，阅读任务，再到 Issue 评论 `/claim`。等待机器人明确回复认领成功，然后开发并提交 PR。**

## 1 当前基座能做什么

基座 V0.1.0 已支持这一条有限制作核心线：

**原始 Markdown 招标节选 → 文件登记 → 12条要求及来源 → 人员范围响应矩阵 → 4人/4证资料索引 → 输入记录确认3人 → 可编辑Word及3张证书 → 实际文件检查 → 原件与结果归档。**

可以演示未确认、过期、缺图和换人。正常运行不需要 API key、不调用模型，也不需要联网。Skill 负责指导操作，当前样例的字段、状态、ID和文档制作由 Python 程序完成。

![正常样例实际生成的人员章节](docs/demo-preview.png)

当前原文适配器支持包内带定位的 Markdown；人员字段来自明确提供的说明文件，检查图片完整性，**未实现OCR或证书真伪核验**。Word 支持已声明的人员模板1.0，**不是任意模板、整本标书或真实电子递交**。这些是后续任务，不是已实现能力。完整状态见 [实现范围](docs/implementation-status.md)。

## 2 安装与第一次运行

需要 Git、Python 3.10或以上、能查看 DOCX 的 Word／WPS／LibreOffice。开发工具可使用 Codex。客户侧 Skill 交付使用 WorkBuddy。

### macOS 或 Linux

```bash
git clone https://github.com/iurp/fdex-tender-agent.git
cd fdex-tender-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m fdex_tender run --input samples/e2e/core-normal --output outputs/my-first-run
```

### Windows PowerShell

```powershell
git clone https://github.com/iurp/fdex-tender-agent.git
cd fdex-tender-agent
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m fdex_tender run --input samples/e2e/core-normal --output outputs/my-first-run
```

PowerShell 无需修改系统执行策略，直接使用虚拟环境的 Python。后续命令中的 `python` 可替换为 `.\.venv\Scripts\python.exe`。

第一次依赖安装需要网络；之后基础样例离线可跑。运行后打开：

- `outputs/my-first-run/personnel-chapter.docx`：可编辑人员表和3张图片。
- `tender_brief.json`：实际读取原文得到的要求及行号。
- `response_matrix.json`：仅统计声明的人员章节覆盖。
- `asset_match.json`：候选与所选人员、输入确认记录及绑定摘要。
- `review_result.json`：实际 Word 的结构与内容检查。
- `archive.zip`：用于复现的公开合成原件和结果。

请给每次运行使用新的输出目录。目录已存在时程序拒绝覆盖，避免丢掉之前的验证记录。

## 3 理解状态与人工责任

`COMPLETE` 只表示模块完成声明范围；`REVIEW` 需要人复核；`BLOCKED` 表示相关范围不能继续。

样例的 `selection.json` 是预置的**虚构人员确认输入**。程序不会凭候选匹配自己创建任命或审批。真实迁移时必须换成实际用户提供的确认与企业资料。

生成 Word 仍然是局部草稿。样例还明确提供本次职责，换人或换职责都需要更新确认对象。以下命令显式提供一个教学审批人，放行指定哈希的人员章节：

```bash
python -m fdex_tender release --run outputs/my-first-run --approver "DEMO审核人"
```

这是本地 DEMO 范围的模拟放行，不是签章、全本审批或正式递交。代码合并与这些业务责任分别记录。

## 4 试一次变化

```bash
python -m fdex_tender run --input samples/e2e/replacement --output outputs/my-replacement
python -m fdex_tender run --input samples/e2e/unconfirmed --output outputs/my-unconfirmed
python -m fdex_tender run --input samples/e2e/expired --output outputs/my-expired
python -m fdex_tender run --input samples/e2e/missing-image --output outputs/my-missing-image
```

换人例将第三人换成第四人，表格、证书编号和实际图片同步更新。其他三个例子会明确输出待确认或阻断，通常退出码为2，这是预期业务分支，并不意味着安装失败。

核心模块可以读取上一轮**实际生成文件**独立重跑：

```bash
python -m fdex_tender module M14 --from-run outputs/my-first-run --output outputs/my-review
python -m fdex_tender validate outputs/my-review/review_result.json
```

这个命令只重跑选定模块，复制的下游标记为过期；除独立复审外，应使用新完整运行恢复下游。不要将旧归档或放行当成新结果。

## 5 怎样选择和认领任务

到 [Issues](https://github.com/iurp/fdex-tender-agent/issues) 筛选 `task:ready`。`task:backlog` 是尚未开放或有依赖的任务。

任务正文先解释：你在帮谁解决什么问题、我们给你什么材料、具体做哪些工作、交付效果是什么以及怎么测试。术语、文件名、接口和运行命令放在最后的技术附录。每项都有本任务的业务例子，不需要先读懂所有模块才能认领一个边界清楚的任务。

`task:backlog` 的任务会明确标出还没配齐的资料。它们是后续计划，不要求学员先自备客户文件，也不能把规划说明当作已完成的练习包。

- 入门任务可直接 `/claim`。
- 常规任务先读懂相关模块再认领。
- 复杂任务评论 `/claim 你的实施计划`，由维护者确认后才算成功。
- 同时只负责一个主要任务，先完成或交接再领取下一项。
- 多人同时认领时，以协调工作流实际回复成功的记录为准；它串行处理请求，不承诺评论发布时间就是最终处理顺序。

| 评论命令 | 用途 |
|---|---|
| `/claim` | 请求认领；成功后成为唯一主要负责人 |
| `/progress 实际进展、验证或PR位置` | 更新进度 |
| `/help 已尝试什么、卡在哪里` | 求助，暂停无进展回收 |
| `/assist` | 请求与已有负责人协作 |
| `/approve-assist @账号` | 负责人批准协作者并说明分工 |
| `/release 已完成内容、位置、问题和下一步` | 保留交接后释放任务 |

24小时内补充实施计划，48小时内更新有效进展；提醒后24小时仍无回应且无PR时可释放。等待审查、已有PR或已登记阻塞时不直接回收。协作不重复占位，最终记录实际贡献。

这些命令由本仓库工作流实现，不是 GitHub 原生命令。无机器人回应时先看该 Issue 的 Actions 运行；不要把已发送评论当成认领成功。

## 6 从认领到 PR

公开仓库建议使用自己的 fork，无需得到主仓库直接写入权限。

1. 在 GitHub 点击 Fork，克隆自己的仓库。
2. 添加上游并同步最新版本：

```bash
git remote add upstream https://github.com/iurp/fdex-tender-agent.git
git fetch upstream
git switch main
git merge --ff-only upstream/main
git switch -c task/你的任务编号-简短名称
```

3. 在独立分支完成任务，不把其他任务混进同一个 PR。
4. 运行测试，再验证本次改动相关样例：

```bash
python -m unittest discover -s tests -v
```

**每项开放任务都有专项测试包，不能只跑上面的基座测试。** 阅读 [测试指南](docs/testing.md) 和 [自己任务的操作卡](samples/acceptance/README.md)。例如报价任务：

```bash
python tools/task_acceptance.py verify-kit --module M12
python tools/task_acceptance.py run --module M12 --adapter adapters/m12.py --output outputs/m12-test-01
```

适配器由认领者接入自己的实现。第一条只检查测试材料完整性，第二条才验证新增功能；原文、图片、新模板、实际Word错误与明确预期都在仓库内。初始 v0.1.0 Release ZIP 不包含这批后补测试，请以最新仓库或任务 Issue 指向的精确提交为准。

5. 提交到自己的 fork，向上游 main 发 PR。正文单独一行写 `Closes #任务号`，按模板补齐实际证据。
6. 阅读 CI 和审查意见，在同一 PR 修订；新提交需要重新审核。

PR 最低交付：实现或 Skill、正常/REVIEW/异常验证、实际上游文件联调、接口影响、未实现范围、运行记录和可证明结果的截图。输出目录默认不进 Git；在PR贴合成证据或上传公开演示附件。含真实信息的输出不能上传。

普通学员无需点 Merge。维护流程在任务绑定、CI和当前提交审查通过后合并。核心接口、仓库规则和模板变化由指定维护者审查。自动化实际接入状态见 [协作服务状态](docs/automation-status.md)。

## 7 Codex 和 WorkBuddy 怎样使用

Codex 用于构建和测试交付物；WorkBuddy 用于让最终使用者调用 Skills。两边用同一接口和公开样例验证。

给 Codex 的启动请求：

```text
先读 README、AGENTS.md、docs/implementation-status.md 和我认领的 Issue。
我负责【任务号】，请先解释当前基座已经做什么、我需要新增什么以及验收方式。
使用原始样例和实际生成的上游JSON，保留来源、确认和范围，不读取参考答案冒充运行。
在本任务分支实现，增加有关回归测试，并记录实际结果、接口影响和仍未实现的部分。
```

四个核心 Skill 在 `skills/`。Release 提供独立 ZIP，可在 WorkBuddy 技能页导入。导入后指定本地工程目录，并先执行安装步骤；Skill 不会凭空提供 Python 依赖。

```text
请使用 requirements-analysis、response-planning、material-matching、document-assembly。
工作目录为【工程绝对路径】。按 README 先跑 core-normal，再跑 replacement。
展示实际 JSON 和 DOCX 位置；保持人员确认来自输入记录。
没有安装或没有真正执行的步骤请明确说明，不把Python测试当成WorkBuddy实机通过。
```

## 8 目录导航

| 位置 | 内容 |
|---|---|
| `docs/requirements-v1.0.md` | Zephyr 提供的完整需求原稿 |
| `docs/requirements-addendum.md` | 仓库名称、范围、接口和协作补充 |
| `docs/implementation-status.md` | 当前能力与缺口，不把路线图当实现 |
| `docs/tasks/` | 18个模块及底座任务书 |
| `schemas/` | 公共 JSON 接口 |
| `src/fdex_tender/` | 可运行参考实现 |
| `samples/e2e/` | 正常、未确认、过期、缺图、换人原始输入 |
| `samples/modules/` | 模块的规划输入与扩展挑战 |
| `samples/acceptance/` | 11项开放任务的专项原件、正常/复核/异常/变更用例、预期与哈希 |
| `docs/testing.md` | 安装、自测、适配器接口、实际文件检查及PR证据 |
| `adapters/` | 学员接入本任务实现的测试适配器位置 |
| `templates/` | 声明支持的 Word 模板 |
| `skills/` | 四个核心 Skill |
| `tests/` | 业务与协作回归测试 |
| `tools/` | 样例制作、打包、任务发布与 GitHub 协调 |

## 9 贡献与学习成果

项目贡献可以是功能、缺陷修复、测试、适配器、文档交接或经过接受的业务验证。要有明确任务、被接受的成果、必要修订和可解释的本人工作。

全体参加8个不同主题 workshop；每人至少在3个项目中形成有效课后贡献，建议1个主项目深入迭代、2个项目承担边界清楚的任务。当前项目只有一个贡献记录，不因拆成多个 Issue 变成多个项目。

昨天的 workshop 成果保留为学习证据。持续建设从本仓库最新版本开始，选择性吸收原版本有价值的部分。

## 10 常见问题

- `ModuleNotFoundError`：确认使用已安装 `pip install -e .` 的同一个虚拟环境。
- 输出目录已存在：换新名字，不清空以前的成果。
- 未确认／证书过期：打开 JSON 的 issues 和 next_actions；这些是要解释的业务分支。
- Word 排版：查看字体、图片、表格和断页；结构测试通过不能代替实际打开和渲染。
- 已有参与决定：样例登记 `EXISTING_GO`，不要求先开发机会筛选模块。
- 想做高级任务：提交计划或请求结对，不用先抢到后独自卡住。
- 不知道是否有权联系采购方或提交：本实训没有授予真实交易、签章或对外承诺权限。

本仓库公开，使用合成材料即可完成当前任务。不要提交真实人员、身份证明、企业证书、客户文件、报价、密码或 API key。公开可阅读不等于已授予任意商业再分发许可；正式项目许可由仓库所有者决定。
