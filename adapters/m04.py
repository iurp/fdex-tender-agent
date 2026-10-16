"""M04 acceptance projection; only requests/source bytes/manifests are inputs."""
import argparse
from pathlib import Path

from fdex_tender.core import (InputError, digest_file, read_json, safe_path,
                              save_module, stable_id, write_json)
from fdex_tender.requirements import extract_requirements


# Public evaluator aliases describe clause families, not production entity IDs.
SEMANTIC_KEYS = dict(zip(("personnel_count", "qualification", "validity", "table_fields",
                          "certificate_images", "selection_confirmation", "personnel_template",
                          "project_fields", "pricing", "implementation_plan", "scoring", "submission_deadline"),
                         (f"Q{n:02}" for n in range(1, 13))))


def analyze(request, root):
    if request.get("module") != "M04" or request.get("source_mode") != "DEMO":
        raise InputError("Expected an M04 DEMO request")
    if request["payload"].get("coverage") != "excerpt_only":
        raise InputError("Only explicitly declared excerpt coverage is supported")
    ctx = {"project_id": request["project_id"], "lot_id": request["lot_id"], "source_mode": "DEMO",
           "input_root": str(root), "run_id": stable_id("RUN", request)}
    payload = request["payload"]

    def source(relative):
        path = safe_path(root, relative)
        sha256 = digest_file(path)
        return {"source_id": payload["source_id"], "relative_path": relative, "sha256": sha256,
                "version": "sha256:" + sha256}

    previous = extract_requirements(ctx, [source(payload["previous"])]) if payload.get("previous") else None
    current = extract_requirements(ctx, [source(payload["document"])], previous)
    return current, previous


def project(value, previous):
    data = value["data"]
    requirements = data["requirements"]
    old_by_id = {r["requirement_id"]: r for r in previous["data"]["requirements"]} if previous else {}
    by_id = {r["requirement_id"]: r for r in requirements}
    changed, unchanged = [], []
    for mapping in data["version_mapping"]:
        requirement = by_id.get(mapping["requirement_id"]) or old_by_id[mapping["requirement_id"]]
        key = SEMANTIC_KEYS.get(requirement["semantic_kind"], requirement["source_key"])
        (unchanged if mapping["change"] == "UNCHANGED" else changed).append(key)
    conflicts = next((c["values"] for c in data["conflicts"] if c["field"] == "personnel_count"), [])
    return {"requirement_count": len(requirements),
            "requirements": [{"key": SEMANTIC_KEYS.get(r["semantic_kind"], r["source_key"]),
                              "line": r["evidence_refs"][0]["locator"]["line"],
                              "quote": r["evidence_refs"][0]["quote"], "score": r["score"],
                              "requirement_id": r["requirement_id"]} for r in requirements],
            "full_tender_complete": False, "conflicting_counts": conflicts,
            "effective_personnel_count": data["personnel_rule"]["count"],
            "changed_keys": sorted(changed), "unchanged_keys": sorted(unchanged),
            "previous_personnel_count": previous["data"]["personnel_rule"]["count"] if previous else None,
            "personnel_count": data["personnel_rule"]["count"],
            "stable_ids_preserved": bool(previous) and set(old_by_id) == set(by_id)
                                    and not any(r.get("identity_ambiguous") for r in requirements)}


def run_adapter(input_path, output, root):
    root, input_path, output = Path(root).resolve(), Path(input_path).resolve(), Path(output)
    if not input_path.is_relative_to(root):
        raise InputError("Request must be inside the declared repository root")
    if output.exists() and any(output.iterdir()):
        raise InputError("Output must be new or empty; previous evidence is preserved")
    request = read_json(input_path)
    value, previous = analyze(request, root)
    output.mkdir(parents=True, exist_ok=True)
    save_module(output, "tender_brief.json", value)
    if previous:
        save_module(output, "previous_tender_brief.json", previous)
    # The manifest supplies inventory only; expected results are never read.
    manifest = read_json(input_path.with_name("case.json"))
    hashes = {item["path"]: digest_file(safe_path(root, item["path"])) for item in manifest["inputs"]}
    evidence = [{"path": ref["relative_path"], "kind": "line", "line": ref["locator"]["line"], "quote": ref["quote"]}
                for r in value["data"]["requirements"] for ref in r["evidence_refs"]]
    result = {"schema_version": "bid-training.acceptance-result.v1", "module": "M04", "case_id": request["case_id"],
              "source_mode": "DEMO", "status": value["processing_status"], "facts": project(value, previous),
              "issue_codes": sorted({i["code"] for i in value["issues"]}), "input_hashes": hashes,
              "evidence": evidence, "artifacts": {"brief": "tender_brief.json", "summary": "tender_brief.md"},
              "real_submission_authorized": False}
    write_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--root", default=str(Path.cwd()), help="Root containing the request and its relative source paths")
    args = parser.parse_args()
    result = run_adapter(args.input, args.output, args.root)
    print(f"M04 {result['status']}: {result['facts']['requirement_count']} requirements; {args.output}")
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
