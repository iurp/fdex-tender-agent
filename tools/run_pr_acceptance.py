#!/usr/bin/env python3
"""CI task binding; run learner adapters only in the no-secrets PR job."""
import json
import os
import re
import sys
from pathlib import Path

from task_acceptance import ROOT, run_suite


def assigned_module(body, author):
    links = re.findall(r"^Closes #(\d+)\s*$", body or "", re.M | re.I)
    if len(links) != 1:
        raise ValueError("PR must bind exactly one primary task with a standalone Closes #N line")
    tasks = json.loads((ROOT / "configs/task-issues.json").read_text())
    module = tasks.get(links[0])
    if module:
        return module
    # The owner-authored kit maintenance PR adds fixtures, not a learner solution.
    # This fixed exception cannot skip any of the eleven learner task issues.
    if links[0] == "22" and author == "iurp":
        return None
    raise ValueError("No acceptance mapping for this task; maintenance needs an explicitly reviewed mapping")


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    pr = event["pull_request"]
    module = assigned_module(pr.get("body"), pr["user"]["login"])
    if module is None:
        print("Owner-authored test-kit maintenance: corpus/harness regressions apply; no learner feature completion claimed.")
        return 0
    adapter = ROOT / "adapters" / (module.lower() + ".py")
    return 0 if run_suite(module, adapter, ROOT / "outputs/ci-assigned-task") else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as exc:
        print("Assigned acceptance failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
