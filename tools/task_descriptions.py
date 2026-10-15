#!/usr/bin/env python3
"""Render task-specific learner explanations; facts and scope stay in config."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "iurp/fdex-tender-agent"
KIT_REF = "19433e19434354e113f6569b4a102684abac317c"
DESCRIPTION_MARKER = "<!-- tender-task-description:v2 -->"
START = "<!-- tender-task-description:start -->"
END = "<!-- tender-task-description:end -->"
HEADINGS = ("你在帮谁解决什么问题", "我们提供哪些材料", "你具体要做什么", "做完后交什么", "怎么判断完成", "技术附录")
DIFFICULTY = {"beginner": "入门", "standard": "常规", "advanced": "进阶（先提交实施计划）"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def link(label, path, ref=None):
    kind = "tree" if (ROOT / path).is_dir() else "blob"
    target = f"https://github.com/{REPO}/{kind}/{ref}/{path}" if ref else "../../" + path
    return f"[{label}]({target})"


def task_specs():
    tasks = read(ROOT / "configs/tasks.json")
    briefs = read(ROOT / "configs/task-briefs.json")
    if {t["module"] for t in tasks} != set(briefs):
        raise ValueError("Every planned task needs a specific learner brief")
    return tasks, briefs


def render(task, brief, ref=None):
    module = task["module"]
    opened = task["status"] == "ready"
    title = f"[{module}] {brief['title']}"
    lines = [DESCRIPTION_MARKER, START, f"# {title}", "", f"任务编号：{task['id']}。难度：{DIFFICULTY[task['difficulty']]}。", "",
             "开放计划：可申请认领；实际状态、负责人和认领结果以此Issue的标签及机器人回执为准。" if opened else "开放计划：暂未开放，不要认领。维护者补齐练习原件和测试后才开放，不要求学员先自备这些材料。",
             "", "## 你在帮谁解决什么问题", "", brief["business"], "", "## 我们提供哪些材料", "", "| 材料 | 在哪里 | 用来做什么 |", "|---|---|---|"]
    for label, path, purpose in brief["materials"]:
        location = link("查看材料", path, ref) if path else "尚未准备，不是现成练习包"
        lines.append(f"| {label} | {location} | {purpose} |")
    if opened:
        lines += ["", "以上专项原件已提供，取得和查看这些材料不需要真实客户资料或服务密钥。故意缺失/损坏的文件是异常测试，按用例报错或转核对，不向老师补要原件。测试包来自 " + link("精确测试版本", "samples/acceptance/README.md", KIT_REF) + "；是否合入main以 [PR #23](https://github.com/iurp/fdex-tender-agent/pull/23) 为准。"]
        if module == "M08":
            lines += ["", "图片识别方式由实施计划说明。可以选择本地识别；如果选择外部模型服务，接入条件要另行说明，不上传密钥，也不能把没有执行的识别写成已通过。"]
    else:
        lines += ["", "现有说明或部分样例不等于完整测试材料已配齐；示意例子也不是现成原件。不要把基座的未确认/过期样例当成这个新模块的专项测试。"]
    lines += ["", "## 你具体要做什么", "", "已有基础与这次新增：" + brief["baseline"], ""]
    lines += [f"{i}. {step}" for i, step in enumerate(brief["steps"], 1)]
    lines += ["", "## 做完后交什么", ""] + ["- " + d for d in brief["deliverables"]]
    lines += ["", "交付效果示例：", "", "> " + brief["example"], "", "本次不要求或不能做的事：", ""] + ["- " + limit for limit in brief["limits"]]
    lines += ["", brief["handoff"], "", "## 怎么判断完成", ""]
    if opened:
        cases = [c for c in read(ROOT / "samples/acceptance/index.json")["cases"] if c["module"] == module]
        lines += ["先用本任务现成的用例验证，不能只演示一次正常结果：", "", "| 用例 | 你要证明什么 |", "|---|---|"]
        for case in cases:
            case_path = f"samples/acceptance/{module}/{case['case_id']}/case.json"
            human_name = {"normal": "正常", "review": "待核对", "abnormal": "异常", "change": "变更", "expired": "已过期", "human-correction": "具名核对", "unknown-id": "不存在的资料", "cross-lot": "标包不符", "missing-image": "缺图片", "wrong-project": "项目不符", "old-person": "旧人员残留", "placeholder": "占位符残留", "approved": "有批准记录"}.get(case['case_id'], case['case_id'])
            purpose = case['title'].replace("trace", "填写对应记录").replace("DOCX", "Word").replace("manifest", "模板清单")
            if module == "M14":
                purpose = {"change": "图片都在，但甲乙两人的证书互换，仍要检出并定位", "missing-image": "实际Word缺少一张可见证书图片", "wrong-project": "实际Word写成另一个项目名称", "old-person": "实际Word残留未选用的旧人员姓名", "placeholder": "实际Word还有没有填写的占位符"}.get(case['case_id'], purpose)
            lines.append(f"| {link(human_name, case_path, ref)} | {purpose} |")
        lines += ["", "交出这些用例的实际运行报告、原始输出和本次新增测试。"]
        if module in ("M03", "M08", "M12"):
            lines += ["", "本任务直接从实际文件、图片或给定数值开始，用它们运行即可，不要求先等其他模块生成结果。与后续程序交接时，说明输出怎样被读取。"]
        else:
            lines += ["", "还要保留一次有关已生成文件的联调记录，说明你实际读了什么。如果先用独立教学输入验证新增部分，明确这个范围和接入方式，不能冒充整条流程已经接通。"]
        if module == "M13":
            lines += ["", "还必须交实际DOCX并逐页查看；截图不能替代文件。"]
        elif module == "M14":
            lines += ["", "报告必须依据实际提供的DOCX，附表/行/列、段落或图片关系的具体位置；不能只引用生成日志。"]
        elif module == "M08":
            lines += ["", "字段证据要回到实际图片区域，注明识别方法和执行记录。"]
        lines += ["", "只有材料完整不等于功能完成；固定公开样例通过也不能替代独立代码审查，复审还会改变合法输入检查是否硬编码。"]
    else:
        lines += ["开放前，维护者先把上面列的输入和正确/待核对/异常结果准备好，再冻结具体运行命令。届时要逐条证明本任务的步骤与边界，补修改后重跑和来源核对；目前不要声称本任务已有完整测试或功能已通过。"]
    lines += ["", "## 技术附录", "", "这里是实现时查阅的约定，不需要先背术语才能理解前面的任务。", "", "| 术语 | 这道任务里的意思 |", "|---|---|"]
    lines += [f"| {term} | {meaning} |" for term, meaning in brief["terms"]]
    lines += ["", "机器输出仍使用已有JSON约定，`bid-training.workflow.v1`只是程序统一读取结果的格式名称，不是额外业务目标。字段细节看 " + link("接口说明", "docs/interfaces.md", ref) + "。", "",
              f"原需求验收索引：{task['acceptance']}。本次只检查上面写明的新增范围，不把整个模块的后续路线图都压进这一个任务。", ""]
    if opened:
        lines += ["自测先检查材料，再用你自己的模块运行结果接受检查：", "", "```bash", f"python tools/task_acceptance.py verify-kit --module {module}", f"python tools/task_acceptance.py run --module {module} --adapter adapters/{module.lower()}.py --output outputs/{module.lower()}-test-01", "python -m unittest discover -s tests -v", "```", "", "第一条只检查材料完整性。第二条的适配器由你把自己的模块接进去，缺适配器不会算通过；每次用新输出目录。Windows命令、结果字段和PR证据见 " + link("测试指南", "docs/testing.md", ref) + "，本任务操作卡见 " + link(module + "操作卡", f"samples/acceptance/{module}/README.md", ref) + "。维护PR合并后才在main启用相应专项CI，不提前宣称已启用。", ""]
    lines += ["只使用公开合成资料；确认人必须来自提供的记录，程序不能补造。工程合并不代表报价、真实签章、递交或业务验收已批准。", ""]
    if opened:
        lines += ["认领：在Issue评论 `/claim`，等机器人明确回复成功。进阶任务要先附实施计划，获得维护者确认后才算认领成功。卡住时 `/help`，需要协作时 `/assist`，退出时 `/release` 留交接。"]
    else:
        lines += ["本任务保持未开放；不要通过改描述自行开始认领。"]
    lines += ["", "GitHub步骤与协作规则见 " + link("学员README", "README.md", ref) + "。", "", END, ""]
    return "\n".join(lines)


def maintenance(number, ref=None):
    if number == 20:
        title = "[OPS] 已完成的协作测试：验证认领、求助和交接"
        body = """# 已完成的协作测试

这是维护者执行的历史合成测试，Issue已经关闭，不开放给学员认领，也不计入学员项目贡献。下列描述解释原测试做了什么，不表示要重新执行。

## 你在帮谁解决什么问题

维护者需要知道GitHub机器人是否真的能处理认领、进度、求助、协作和交接，防止学员发了命令却不知道有没有生效。

## 我们提供哪些材料

本Issue的历史评论与机器人回执，以及已经关闭且未合并的 [PR #21](https://github.com/iurp/fdex-tender-agent/pull/21)。它们是协作测试证据，不是学生代码批准。

## 你具体要做什么

原测试依次检查唯一负责人认领、进度更新、求助暂停回收、交接释放及任务绑定CI。测试后关闭Issue，保留评论和回执；本次仅重写说明，不重新认领、运行或删除历史。

## 做完后交什么

对应命令的真实机器人回执、CI结果和关闭记录；不创建真实业务资料或审批。

## 怎么判断完成

查看原评论中的实际回复和操作顺序，不能只把“命令已经发送”当作认领成功。历史PR未合并，不把它算成有效学员贡献。

## 技术附录

`/claim`是认领请求，`/help`是求助，`/release`是留下交接后释放任务。正式学员操作见仓库README。状态、评论及关闭记录保持不变。
"""
    elif number == 22:
        title = "[KIT] 给所有开放任务配齐练习材料和自测方法"
        body = """# 开放任务的测试交接和任务说明维护

这是所有者授权的维护任务，不是让学员认领并代做课程。交付代码与文档在 [PR #23](https://github.com/iurp/fdex-tender-agent/pull/23)，独立批准与是否合并以该PR为准。

## 你在帮谁解决什么问题

学员认领任务后，要知道业务问题是什么、已有材料在哪里、具体做哪些工作以及怎样判断完成。最初的任务书只有技术缩写与共用样例，不能支撑独立开发和自测。

## 我们提供哪些材料

仓库现有基座、原始需求、19项课程任务，以及11项已开放任务的54个专项用例。每项开放任务都有正常、待核对、异常和变更输入；原文、证书图片、Word模板、错误文件、金额和历史输出均为公开合成资料。

## 你具体要做什么

1. 为11项开放任务配齐实际原件、明确预期、内容指纹和运行命令，不让学员猜验收标准。
2. 做自测入口，分别报告材料完整性和学员实现结果；原有功能回归与新增专项测试都要保留。
3. 把全部课程任务改成业务场景、材料、具体步骤、交付示例、测试方法和技术附录；未开放任务明确尚缺哪些材料，不伪装已经准备完成。
4. 更新对应Issue和仓库任务书；保持任务编号、认领记录、标签、评论和状态不变。
5. 把源码、实际测试和修改范围交独立审查，作者自测不替代批准，不绕过保护分支。

## 做完后交什么

11项专项测试包、统一自测指南、每项操作卡、易读任务说明、CI验证及Issue同步回执。测试包不是11项业务模块的完成实现，也不证明真实客户部署或WorkBuddy实机已验收。

## 怎么判断完成

逐个核对开放任务都有实际输入和明确预期；错误状态、错类型、假产物、非法公开包或历史覆盖会被检查器拒绝。再核对每个Issue读者能说清“帮谁、用什么、做什么、交什么、怎么测”，且原有讨论与认领数据保留。

## 技术附录

材料校验命令是 `python tools/task_acceptance.py verify-kit`，回归测试是 `python -m unittest discover -s tests -v`。具体的学生功能仍由任务作者实现，并接受专项测试与独立审查。实际作者证据看本Issue评论和PR，不将正文描述视为独立批准。
"""
    else:
        raise ValueError("Unknown maintenance issue")
    return title, DESCRIPTION_MARKER + "\n" + START + "\n" + body.rstrip() + "\n\n" + END + "\n"


def write_documents():
    tasks, briefs = task_specs()
    for task in tasks:
        task["title"] = f"[{task['module']}] {briefs[task['module']]['title']}"
        (ROOT / f"docs/tasks/{task['module']}.md").write_text(render(task, briefs[task["module"]]), encoding="utf-8")
    (ROOT / "configs/tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for number in (20, 22):
        _, body = maintenance(number)
        (ROOT / f"docs/tasks/ISSUE-{number}.md").write_text(body, encoding="utf-8")
    print("Rendered 19 learner task descriptions and 2 maintenance descriptions; task IDs/statuses unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--write-docs", action="store_true")
    if not parser.parse_args().write_docs:
        parser.error("Specify --write-docs for explicit bulk document generation")
    write_documents()
