#!/usr/bin/env python3
"""Update only our managed test handoff block; preserve claims and discussion."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "iurp/fdex-tender-agent"
START = "<!-- tender-acceptance-kit:start -->"
END = "<!-- tender-acceptance-kit:end -->"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--ref", required=True); parser.add_argument("--pr", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}|main", args.ref):
        raise ValueError("Use an exact published commit or the reviewed main branch")
    if not args.pr.startswith("https://github.com/iurp/fdex-tender-agent/pull/"):
        raise ValueError("PR must belong to this repository")
    mapping = json.loads((ROOT / "configs/task-issues.json").read_text())
    for number, module in mapping.items():
        item = json.loads(gh("issue", "view", number, "-R", REPO, "--json", "body,title,state"))
        if item["state"] != "OPEN" or not item["title"].startswith(f"[{module}]"):
            raise ValueError("Issue context drifted: " + number)
        body = item["body"]
        if "<!-- tender-task-description:v2 -->" in body:
            print("FRIENDLY_DESCRIPTION_PRESENT", number, module, "Use sync_task_descriptions to update versioned links; no legacy appendix appended.", flush=True)
            continue
        block = f"""{START}
## 本任务专项测试交接

本任务的练习原件、正确结果和异常情况见下面的操作卡。按正文中的业务步骤实现，再用这些用例检查；基座的共用例子只用来了解已有功能，不能代替本任务自测。

- [本任务操作卡](https://github.com/{REPO}/blob/{args.ref}/samples/acceptance/{module}/README.md)：正常、需复核、异常与变更原始输入，明确预期、实际文件检查及命令。
- [统一测试指南](https://github.com/{REPO}/blob/{args.ref}/docs/testing.md)：适配器接口、Windows命令与PR证据。
- 测试包提交 `{args.ref}`；维护PR：{args.pr}。待独立批准时请使用此精确提交，不声称已合入main。

```bash
python tools/task_acceptance.py verify-kit --module {module}
python tools/task_acceptance.py run --module {module} --adapter adapters/{module.lower()}.py --output outputs/{module.lower()}-test-01
```

适配器由本任务作者调用自己的实现；材料完整性通过不代表业务功能通过。11项任务共54用例，输入与参考预期分离，不需要真实数据或服务密钥。**维护PR合并后**，对应任务PR的CI会实际执行整套专项检查，缺适配器/缺结果/不匹配均失败；在此之前不得声称main已启用新专项门禁。独立审查、业务确认和WorkBuddy实机证据另行记录；认领状态和讨论不受此次更新影响。
{END}"""
        if START in body:
            if END not in body or body.count(START) != 1 or body.count(END) != 1:
                raise ValueError("Managed block malformed: " + number)
            updated = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, body, flags=re.S)
        else:
            updated = body.rstrip() + "\n\n" + block + "\n"
        if updated == body:
            print("UNCHANGED", number, module); continue
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as temp:
            temp.write(updated); temp.flush()
            gh("issue", "edit", number, "-R", REPO, "--body-file", temp.name)
        print("UPDATED", number, module, flush=True)


if __name__ == "__main__":
    main()
