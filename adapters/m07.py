#!/usr/bin/env python3
"""M07 责任与任务期限的验收适配器。

读取测试请求 input.json，调用生产模块 `fdex_tender.assignment.compute_assignment`，
把结果投影成 result.json 写进输出目录。

约定（docs/testing.md / tools/task_acceptance.py 契约）：
- 只读 input.json 与同目录的 case.json；不读 expected.json；
- 不按 case_id 返回固定答案，全部结论来自本次实际输入计算；
- 路径按仓库根目录解析，因为检查器以仓库根为工作目录启动本适配器；
- 必须写出 <output>/result.json，且含 input_hashes（每个登记输入的 相对路径→sha256）。
"""
import argparse
import json
from pathlib import Path

from fdex_tender.assignment import compute_assignment
from fdex_tender.core import digest_file, read_json

ROOT = Path.cwd()


def resolve(relative):
    path = Path(relative)
    return path if path.is_absolute() else ROOT / path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    request_path = resolve(args.input)
    request = read_json(request_path)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    case = read_json(request_path.parent / "case.json")

    result = compute_assignment(request)

    # input_hashes 从清单里的路径**现算**，不复制 case.json 的预置哈希：
    # 声明的哈希只能证明"文件没被换掉"，不能证明程序真的读过它。
    result["input_hashes"] = {
        item["path"]: digest_file(resolve(item["path"])) for item in case["inputs"]
    }
    result["evidence"] = []
    result["artifacts"] = {}

    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {"case_id": request["case_id"], "status": result["status"],
         "issue_codes": result["issue_codes"]}, ensure_ascii=False
    ))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
