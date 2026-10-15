# 学员任务测试指南

11 项开放任务都有独立测试包：M03、M04、M06、M07、M08、M09、M12、M13、M14、M18、X01。先读自己任务的 [测试操作卡](../samples/acceptance/README.md)，再开始实现。全部文件是公开合成数据，无需采购方账号、真实证书、企业价格或 API key。

## 三种结果不要混淆

`verify-kit` 验证测试文件是否齐全、字节哈希是否一致，明确输出 `student_implementation=NOT_TESTED`。基座回归验证没有破坏已有功能。专项 `run/check` 才检查你新增功能的实际结果；这三个通过以后，仍需当前提交的独立工程审查。任何工程结果都不授予真实报价、签章、递交或业务批准。

## 安装和取得最新测试包

按根 README 克隆、创建虚拟环境并 `python -m pip install -e .`。测试包在 Git 仓库内，不依赖过时的初始 Release ZIP。若测试包 PR 尚未合并，请使用 Issue 链接指向的精确提交或分支；不要把待审分支称作已审 main。

待审期间可以在独立 checkout 查看和试用测试包，功能贡献仍按原任务分支开发。不要把维护PR的未批准提交混入自己的功能PR；维护PR合并后同步main，再提交最终验收。若刚下载的main找不到 task_acceptance.py，请先查看原Issue中维护PR的合并状态。

Windows PowerShell 可以把以下命令中的 `python` 替换为 `.\.venv\Scripts\python.exe`。

```bash
python tools/task_acceptance.py verify-kit
python -m unittest discover -s tests -v
```

`samples/acceptance/index.json` 列全部用例。每个用例包括：

- `input.json`：适配器读取的输入请求，路径相对仓库根目录。
- `case.json`：文件清单、SHA256、目的、正常/复核/异常/变更类别及人工检查项。
- `expected.json`：公开测试预期，只有检查器读取；禁止把它当业务输入。
- `shared/`：无标签原文、补遗、证书图片、企业资料、模板1.1、实际Word错误注入、历史输出和依赖图。

缺失文件、损坏图片、没有期限或确认是故意设计的异常，不需要向老师补要文件。每条需求应明确这时如何停止、报错或转复核。

## 适配器接口

创建 `adapters/你认领的模块小写.py`。它接收 `--input 绝对路径 --output 新空目录`，读取请求并调用你自己的模块，保存原始机器输出、中文摘要和要求的实际产物，再生成验收投影 `result.json`。既有生产信封仍为 `bid-training.workflow.v1`，这个投影只是测试格式，不替换生产接口。

`result.json` 的公共字段如下；`facts` 按本任务 expected.json 的字段描述输出**实际计算或解析结果**，自然语言解释无需逐字相同。映射可以增加字段，列表的顺序/元素和金额字符串必须匹配明确约定。

```json
{
  "schema_version": "bid-training.acceptance-result.v1",
  "module": "M12",
  "case_id": "normal",
  "source_mode": "DEMO",
  "status": "COMPLETE",
  "facts": {"quotes": {}, "release_allowed": false},
  "issue_codes": [],
  "input_hashes": {"仓库相对输入路径": "实际SHA256"},
  "evidence": [],
  "artifacts": {},
  "real_submission_authorized": false
}
```

输入清单全部哈希填入 `input_hashes`（从 case.json 的路径读取实际文件并计算，不复制预置哈希）。运行可以用相同目录的 case.json 获取清单，但不能读取 expected.json。哈希声明能查出错版，不能证明程序真正理解输入，因此还需源码审查、输入变异和上游联调。

最小骨架只负责参数与读输入，不给出任何任务答案：

```python
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
request_path = Path(args.input)
request = json.loads(request_path.read_text(encoding="utf-8"))
output = Path(args.output)
# 调用你实现的模块，保存实际输出，再投影成 result.json。
# 不能按 request['case_id'] 返回固定答案。
raise NotImplementedError("在这里接入本任务实现，而非复制 expected.json")
```

## 一次跑完本任务

以 M12 为例：

```bash
python tools/task_acceptance.py run --module M12 --adapter adapters/m12.py --output outputs/m12-test-01
```

检查器逐个调用适配器，保存 stdout/stderr/result.json 并生成整套 `report.json`。异常业务分支允许进程返回 2，但仍必须提供可检查的结果；返回0却状态或计算错误仍失败。适配器不存在、超时、少字段、错类型、错误哈希都会失败。输出目录已存在时拒绝覆盖，请给下一轮取新名字。

对应任务 PR 的无秘密 CI 作业按 `Closes #任务号` 自动执行本模块整套专项测试，并上传 outputs 中的证据；未交适配器不能只凭基座回归变绿。11项现有任务的映射在 configs/task-issues.json。维护测试包的所有者PR是独立明确的维护范围，不代表任一学生功能已完成。

只检查自己已经生成的一份结果：

```bash
python tools/task_acceptance.py check --module M12 --case normal --result outputs/m12-test-01/normal/result.json
```

金额均为 Decimal 十进制字符串，正常三组独立报价分别是318.00、282.48、125.00，不把三条合成一个投标总价。未知税率不能填0。缺值和错误必须匹配对应复核/阻断状态。

## 原件证据与文件检查

M04 正常用例需要12条原文行证据，形如 `{"path":"仓库相对原文路径","kind":"line","line":4,"quote":"该行完整原文"}`。Q01..Q12 是验收的语义键，不要求生产实体 ID 恰好叫 Q01；适配器要保留生产 ID 并映射到对应语义键，变化测试展示稳定性与历史映射。

M08 正常用例每张图片需要 person_id、certificate_id、qualification、valid_until 四个像素区域证据，形如 `{"path":"仓库相对图片路径","kind":"image_region","field":"valid_until","box":[65,490,1200,590]}`。检查器检查真实图片和区域边界，复审核对该区域是否支持字段；不要从文件名猜编号。遮挡日期保持 null，即使资料作者知道日期也不能补出。图片字段不证明真伪。离线 OCR 或已接入的模型均可，必须说明实际执行方式，没服务时保留任务求助记录而不是伪造识别结果。

M13 `artifacts.document` 是相对本用例输出目录的实际 DOCX。检查器打开文件检查六列表格、对应图片出现顺序、嵌入图片字节、上下文和旧人员残留；阻断/未确认用例输出目录不能生成 DOCX。禁产物检查递归扫描输出目录，扩展名不区分大小写（包括 `.docx`、`.DOCX`、`.Docx`）；同时检查 `result.artifacts` 的嵌套路径声明，不能通过别名、尚不存在的路径或把 `document` 后缀改成 `.bin` 来放行。声明路径必须是输出目录内的非空相对路径。还须用 Word/WPS 或渲染器逐页检查中文、列宽、图片与断页。模板故意保留 `{{PROJECT_NAME}}` 等输入占位符，最终输出不得残留。

M14 提供从实际基座生成的 Word 和上游 JSON，以及正确/错位 trace。图片互换用例媒体集合完全相同，只是可见关系改变；仅扫描 ZIP 里的图片哈希集合无法通过。`located_issue_kinds` 区分表格单元格、段落和图片关系，PR 中再给出具体表/行/列/段落/rId定位。异常 Word 本身故意包含错误，不能用“打开得了”当作已通过。未进行视觉审查时必须保持 `NOT_PERFORMED_BY_PROGRAM`。

M18 正常公开包 `artifacts.archive` 为相对路径，ZIP 中恰有模板、规则、脱敏章节三个原件 basename，字节须与允许公开的原件一致；这是本任务的候选导出切片，不替换既有完整运行归档。含禁公开材料时不能产出公开 ZIP；实际文件及 `result.artifacts` 声明均检查，`.zip`、`.ZIP`、`.Zip` 同样拒绝，`archive` 声明也不能用其他后缀绕过。候选未批准不意味着禁止在明确可公开的教学包中查看，但禁止用于下次已确认响应。

X01 正常用例 `artifacts.old_run` 与 `artifacts.new_run` 指向输出目录内两个互不包含的目录，各模块为 `Mxx.json`。旧文件须逐字节保留；新目录未受影响文件字节一致，重跑结果采用新 run_id，不继承 RELEASED。依赖图的 M12 和历史 JSON 是合成扩展输入，不表示基座已经实现报价调度。变化用例的两套计划需分别执行并在PR提供目录与日志。

X01 变化用例输出 `artifacts.scenarios.template_mapping` 和 `artifacts.scenarios.pricing`，各含 old_run/new_run 相对目录；检查器会分别检查实际字节和新run_id，不能只给重跑计划JSON。

## 提交和复审

每个 PR 附基座回归结果、专项 report.json、实际产物、新增单元测试和一次实际生成上游的联调记录。不要把学生代码读参考预期、删除失败断言或伪造文件当作解决办法。

公开固定样例是学习用可解释预期，不是隐藏考试。独立复审应改变合法输入中的数量、证号、路径、顺序等，检查实际原件与代码，发现硬编码就退回。未有学生实现时，本测试包只有完整性与检查器自测记录，没有“11项业务功能已通过”的结论。

维护者不会在带 GitHub/SSH/API secrets 的环境直接跑陌生适配器。GitHub CI 使用无秘密测试作业；本地运行由学员在自己的无秘密开发环境明确执行。WorkBuddy 导入和客户环境运行需要另交实机证据，不能由 Python 测试推导。
