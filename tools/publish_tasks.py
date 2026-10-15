#!/usr/bin/env python3
"""Idempotently publish planned task bodies using the user's gh session."""
import json
import subprocess
import tempfile
from pathlib import Path
from task_descriptions import render, task_specs

ROOT = Path(__file__).resolve().parents[1]
REPO = "iurp/fdex-tender-agent"


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def main():
    labels = {"task:ready": "0e8a16", "task:backlog": "d4c5f9", "task:claimed": "1d76db", "task:blocked": "d93f0b", "task:done": "006b75",
              "difficulty:beginner": "c2e0c6", "difficulty:standard": "bfdadc", "difficulty:advanced": "f9d0c4", "needs-maintainer-review": "fbca04"}
    for name, color in labels.items():
        gh("label", "create", name, "--repo", REPO, "--color", color, "--force")
    existing = json.loads(gh("issue", "list", "--repo", REPO, "--state", "all", "--limit", "200", "--json", "number,title,body,url"))
    tasks, briefs = task_specs()
    mapping = {}
    for task in tasks:
        token = f'"id":"{task["id"]}"'
        prior = next((i for i in existing if token in (i["body"] or "")), None)
        if prior:
            mapping[task["id"]] = prior["url"]
            print("EXISTS", task["id"], prior["url"])
            continue
        meta = json.dumps({"id": task["id"], "module": task["module"], "difficulty": task["difficulty"]}, separators=(",", ":"))
        body = f"<!-- tender-task-meta:{meta} -->\n\n" + render(task, briefs[task["module"]], "main")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md") as temp:
            temp.write(body); temp.flush()
            url = gh("issue", "create", "--repo", REPO, "--title", task["title"], "--body-file", temp.name,
                     "--label", "task:" + task["status"], "--label", "difficulty:" + task["difficulty"])
        mapping[task["id"]] = url
        print("CREATED", task["id"], url, flush=True)
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs/published-task-map.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
