#!/usr/bin/env python3
"""Owner-requested issue prose updates with snapshots and metadata verification.

Never creates issues, changes labels/assignees/state, edits or deletes comments,
or updates PR review/merge state. Unknown issues require a separate decision.
"""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from task_descriptions import ROOT, REPO, render, task_specs, maintenance, DESCRIPTION_MARKER, START, END

META = re.compile(r"<!-- tender-task-meta:.*? -->", re.S)


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scan(snapshot):
    if Path(snapshot).exists():
        raise ValueError("Snapshot exists; retain history and use a new path")
    issues = json.loads(gh("issue", "list", "-R", REPO, "--state", "all", "--limit", "1000", "--json", "number"))
    captured = []
    for issue in issues:
        item = json.loads(gh("issue", "view", str(issue["number"]), "-R", REPO, "--json", "number,title,body,state,labels,assignees,comments,author,url"))
        captured.append(item)
        print("SCANNED", item["number"], item["title"], item["state"], flush=True)
    save(snapshot, {"repository": REPO, "issues": captured})
    return captured


def metadata(item):
    return {"state": item["state"], "labels": sorted(i["name"] for i in item["labels"]), "assignees": sorted(i["login"] for i in item["assignees"])}


def desired(item, ref):
    tasks, briefs = task_specs()
    match = META.search(item["body"])
    if not match:
        raise ValueError("Issue has no known task identity: " + str(item["number"]))
    meta = json.loads(match[0].split(":", 1)[1].split(" -->", 1)[0])
    task = next((t for t in tasks if t["id"] == meta.get("id")), None)
    if task:
        expected_number = 19 if task["module"] == "X01" else int(task["module"][1:])
        if item["number"] != expected_number:
            raise ValueError("Task identity appears on an unexpected Issue; preserve it for manual review")
        if meta != {"id": task["id"], "module": task["module"], "difficulty": task["difficulty"]}:
            raise ValueError("Task identity/difficulty drifted")
        title = task["title"]
        body = render(task, briefs[task["module"]], ref)
    elif {20: "OPS-SMOKE-01", 22: "KIT-01"}.get(item["number"]) == meta["id"]:
        title, body = maintenance(item["number"], ref)
    else:
        raise ValueError("Unknown issue: preserve it for manual scope review")
    # The author requested rewording of the known original descriptions. Any
    # later outside addition on a v2 body is preserved, not silently discarded.
    if DESCRIPTION_MARKER in item["body"]:
        if item["body"].count(START) != 1 or item["body"].count(END) != 1:
            raise ValueError("Managed description markers are incomplete")
        pattern = re.escape(DESCRIPTION_MARKER) + r"\s*" + re.escape(START) + r".*?" + re.escape(END)
        updated, count = re.subn(pattern, lambda _: body.rstrip(), item["body"], flags=re.S)
        if count != 1:
            raise ValueError("Could not safely locate managed description")
        return title, updated
    return title, match[0] + "\n\n" + body.rstrip() + "\n"


def sync(snapshot, ref, apply=False):
    if not re.fullmatch(r"[a-f0-9]{40}", ref):
        raise ValueError("Use the exact published documentation commit")
    record = json.loads(Path(snapshot).read_text())
    if record["repository"] != REPO:
        raise ValueError("Wrong repository snapshot")
    planned = []
    for item in record["issues"]:
        title, body = desired(item, ref)
        planned.append({"number": item["number"], "title": title, "body": body, "before_metadata": metadata(item)})
    save(Path(snapshot).with_suffix(".planned.json"), planned)
    if not apply:
        print("DRY RUN", len(planned), "issue descriptions prepared; no GitHub writes.")
        return
    # Read-only confirmation that all immutable documentation links are valid.
    remote = json.loads(gh("api", f"repos/{REPO}/commits/{ref}"))
    if remote["sha"] != ref:
        raise ValueError("Documentation commit is not available")
    audit = []
    by_number = {i["number"]: i for i in record["issues"]}
    for plan in planned:
        n = str(plan["number"]); old = by_number[plan["number"]]
        before = json.loads(gh("issue", "view", n, "-R", REPO, "--json", "number,title,body,state,labels,assignees,comments"))
        if before["title"] == plan["title"] and before["body"] == plan["body"]:
            print("UNCHANGED", n, flush=True); continue
        if before["body"] != old["body"] or before["title"] != old["title"]:
            raise ValueError("Issue text changed since snapshot; stopped without overwriting #" + n)
        if metadata(before) != metadata(old):
            raise ValueError("Issue state/ownership changed; rescan before modifying #" + n)
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as temp:
            temp.write(plan["body"]); temp.flush()
            gh("issue", "edit", n, "-R", REPO, "--title", plan["title"], "--body-file", temp.name)
        after = json.loads(gh("issue", "view", n, "-R", REPO, "--json", "number,title,body,state,labels,assignees,comments"))
        if after["title"] != plan["title"] or after["body"] != plan["body"] or metadata(before) != metadata(after):
            raise ValueError("Post-update verification failed: #" + n)
        current_comments = {c["id"]: c for c in after["comments"]}
        for comment in before["comments"]:
            if current_comments.get(comment["id"]) != comment:
                raise ValueError("Historical comment changed during update: #" + n)
        audit.append({"number": plan["number"], "title": plan["title"], "body_sha256": hashlib.sha256(plan["body"].encode()).hexdigest(), "metadata_preserved": True, "historical_comments_preserved": True})
        save(Path(snapshot).with_suffix(".audit.json"), audit)
        print("UPDATED", n, plan["title"], flush=True)
    print("VERIFIED", len(audit), "updates; labels, ownership, state and historical comments unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="mode", required=True)
    inventory = sub.add_parser("scan"); inventory.add_argument("--snapshot", required=True)
    update = sub.add_parser("sync"); update.add_argument("--snapshot", required=True); update.add_argument("--ref", required=True); update.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.mode == "scan":
        scan(args.snapshot)
    else:
        sync(args.snapshot, args.ref, args.apply)
