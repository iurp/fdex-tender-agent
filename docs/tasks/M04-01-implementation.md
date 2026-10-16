# M04-01 实现与本地验证

任务对应 Issue #4。本分支新增的是无 `[R-01]` 人工标签的文本提取，工程结果仍使用 `bid-training.workflow.v1`。

## 做了什么

- `src/fdex_tender/requirements.py` 读取实际 UTF-8 文件，识别本任务的12类条款：人数、资质、有效期基准、人员表字段、证书图片、选人确认、模板、项目信息、报价、实施计划、评分、投标截止。
- `modules.read_tender()` 接入该解析器。旧标签仍沿用原 ID；无标签 ID 绑定项目、标包、来源编号和语义角色，数值变化和换行/顺序调整不会导致无关 ID 变化。
- 要求保留原文完整行、来源编号、文件相对路径、行号及原件哈希。句子提取不改写证据。未知评分/否决性保持 `null`，不能把“必须”自动当废标。
- 人数按最低/最高/恰好约束求交集；冲突保留双方、有效人数为 `null`、状态为 `REVIEW`。资质/基准日期冲突同样保留双方。无法读取的正文为 `BLOCKED`，不生成伪要求。
- `read_tender(ctx, registered, previous=上一版实际M04信封)` 支持 `CHANGED/UNCHANGED/ADDED/REMOVED` 对应，保留旧新证据与修订 ID。适配器也支持请求里的 `payload.previous` 原件。
- 同一来源同一语义角色出现多条不同条款时，不能可靠自动判定版本身份，因此保留不同 ID 并标 `AMBIGUOUS_REQUIREMENT_IDENTITY`；不宣称解决任意补遗映射。
- `save_module()` 为 M04 输出逐条中文摘要。M07 使用 `response_field` 区分表格/附件；M09 检查新增精确/上限约束，约束变化会让旧确认过期。

## 最容易复现的命令

在仓库根目录使用项目虚拟环境，Windows 加 `-X utf8`：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_m04.py -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 tools/demo_m04.py --output outputs/m04-demo-02
```

每次演示使用新的输出目录。演示脚本从公开合成原件创建无标签输入，正常场景跑完整链；其余场景实际执行 M03、读取保存的登记 JSON，再交给 M04。变化场景还读取正常场景实际保存的 `tender_brief.json`，没有调用老师预期答案。

| 产物 | 查看内容 |
|---|---|
| `normal/tender_brief.json` 与 `.md` | 12条要求、证据和中文摘要 |
| `normal/personnel-chapter.docx` | 正常整链实际生成的人员章 |
| `review/tender_brief.json` | 3人/2人冲突及双方证据 |
| `abnormal/tender_brief.json` | 不可读正文，零条要求和阻断原因 |
| `change/tender_brief.json` | 数量3→4，其余身份不变，旧新证据对应 |
| `upstream/*/source_manifest.json` 与 `*/handoff.json` | 实际上游文件联调记录 |
| `demo-report.json` | 模块状态、实际DOCX表格/图片数量及验证范围 |

测试会变更人数、证书类型、日期、措辞、顺序、文件路径和项目，并检查重复条款、上下界冲突、乱码、越界路径、哈希漂移、旧确认失效，以及适配器不读取 `expected.json`。这些测试验证声明的条款族，不证明任意文本均能理解。

## 本次实际验证记录

2026-10-16，基于同步后的 `upstream/main` 提交 `b31d2b9` 完成本地验证。

| 检查 | 实际结果 | 本地证据（输出目录默认不进Git） |
|---|---|---|
| 完整回归 | 111项通过，耗时115.738秒；其中26项为本次M04测试 | `outputs/m04-validation/regression-02.log` |
| 老师测试包完整性 | M04四个用例材料完整，原始哈希一致 | 精确提交及命令见下一节 |
| 老师功能验收 | normal/review/abnormal/change全部通过 | `outputs/m04-validation/acceptance-02/report.json` |
| 无标签正常整链 | M03/M04/M07/M08/M09/M13/M14均COMPLETE；实际DOCX一张4行表、3张嵌入图片 | `outputs/m04-demo-01/demo-report.json` |
| 自建变化联调 | 12个要求ID集合一致，1条CHANGED、11条UNCHANGED，旧新引用均保留 | `outputs/m04-demo-01/change/tender_brief.json` |

老师测试包的 PR #23 已核对为 open、未合并；独立维护者审查、业务UAT、WorkBuddy和Word逐页视觉检查均未完成。测试报告的 `independent_review=PENDING` 保持原样。

供远端审查的公开合成证据已整理为 [实际结果 JSON](../evidence/M04-01.json) 和 [Windows 演示截图](../evidence/M04-01-demo.png)。JSON 保留四类实际 M04 输出、专项报告结果、测试包精确版本与本地记录哈希；截图来自贡献者执行 `tools/demo_m04.py` 的实际终端结果。完整运行目录仍不进 Git。

## 老师专项测试包

本地验证使用维护测试包精确提交 `53e3c9d5e23e02ff77de1d202da003aef64eee2b`，独立展开在忽略目录 `outputs/m04-validation/kit-53e3c9d-lf`。测试包提交未混入功能分支。当前同步的上游 main `b31d2b9` 仍没有 `tools/task_acceptance.py`；维护 PR #23 合并后应在最新测试包重跑。

Windows 导出该包必须保留 LF 原始字节；不要修改哈希清单来“通过”完整性检查。本地导出命令使用 `git -c core.autocrlf=false archive`，只影响这次导出。

当前已取得独立测试包时，从其根目录运行：

```powershell
& D:\fdex\fdex-tender-agent\.venv\Scripts\python.exe -X utf8 tools/task_acceptance.py verify-kit --module M04
& D:\fdex\fdex-tender-agent\.venv\Scripts\python.exe -X utf8 tools/task_acceptance.py run --module M04 --adapter D:/fdex/fdex-tender-agent/adapters/m04.py --output D:/fdex/fdex-tender-agent/outputs/m04-test-next
```

维护测试包合入后，从本仓库根目录用相同工具和相对适配器路径即可。`verify-kit` 只验证材料；`run` 才调用自己的功能。适配器读取 `input.json`、实际原件和 `case.json` 的输入清单，按实际文件计算哈希。生产 `tender_brief.json` 与验收投影 `result.json` 分别保存；Q01..Q12 仅是公开验收语义键，生产 ID 不依赖它们或 `case_id`。

## 接口影响和边界

公共信封和必填字段未改。M04 新增 `semantic_kind/attributes/response_field/revision_id`、证据的 `relative_path` 及 `personnel_constraints/conflicts/version_mapping`，旧消费者可以忽略。M07 保留读取旧结果的 fallback；M09 对旧结果没有约束数组时仍沿用原检查。旧最低人数确认摘要保持兼容；新增上下界或精确人数需要重新确认。

按语义身份匹配适用于本任务条款族；同一语义角色有多个实体或无法理解的要求时转复核。跨来源编号变更不会自动猜测同一文件。缺少上一版输入就不生成历史对应。日期只接受明确支持的表达，无法可靠提取保持未知。

本次没有 PDF/OCR、真实证书核验、整本标书、真实业务批准、对外递交或 WorkBuddy 实机验证。程序检查 DOCX 结构与嵌入图片，不代替逐页视觉检查。最终合并仍需当前提交的独立维护者审查。
