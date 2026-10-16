"""Shared IDs, source confinement, envelopes and supplied confirmations."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]


class InputError(ValueError):
    pass


def digest_bytes(content):
    return hashlib.sha256(content).hexdigest()


def digest_file(path):
    return digest_bytes(Path(path).read_bytes())


def digest_object(value):
    return digest_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def stable_id(prefix, *values):
    return f"{prefix}-{digest_object(list(values))[:16]}"


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"Cannot read JSON {Path(path).name}: {exc}") from exc


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_path(root, relative):
    root = Path(root).resolve()
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise InputError(f"Input path must be relative and confined: {relative}")
    result = (root / candidate).resolve()
    if result != root and root not in result.parents:
        raise InputError(f"Input path escapes root: {relative}")
    return result


def parse_time(text):
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise InputError("Timestamp requires an explicit timezone")
    return value


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def issue(code, obj, message, severity="BLOCKER", evidence=None, owner="招投标负责人", action="核对输入并重新运行"):
    return {"issue_id": stable_id("ISS", code, obj), "code": code, "severity": severity,
            "object_id": obj, "message": message, "evidence_refs": evidence or [],
            "owner_role": owner, "next_action": action}


def evidence(source, line, quote):
    return {"source_id": source, "locator": {"kind": "line", "line": line}, "quote": quote}


def load_context(root, run_id):
    root = Path(root).resolve()
    context = read_json(root / "context.json")
    for key in ("project_id", "lot_id", "project_name", "company_id", "source_mode", "analysis_time"):
        if not context.get(key):
            raise InputError(f"Missing context field: {key}")
    if context["source_mode"] != "DEMO":
        raise InputError("This baseline supports DEMO only; real input is never replaced with fixtures")
    parse_time(context["analysis_time"])
    context.update(input_root=str(root), run_id=run_id)
    return context


def validate_envelope(value):
    schema = read_json(REPO / "schemas/workflow.schema.json")
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        raise InputError("; ".join(f"{'.'.join(map(str,e.path)) or '$'}: {e.message}" for e in errors))
    for item in value["input_refs"]:
        if not re.fullmatch(r"[a-f0-9]{64}", item["sha256"]):
            raise InputError("Source hash is invalid")


def envelope(ctx, module, data, refs=None, issues=None, status=None):
    problems = issues or []
    status = status or ("BLOCKED" if any(i["severity"] == "BLOCKER" for i in problems) else "REVIEW" if problems else "COMPLETE")
    value = {"schema_version": "bid-training.workflow.v1", "module": module,
             "run_id": ctx["run_id"] + "-" + module, "project_id": ctx["project_id"], "lot_id": ctx["lot_id"],
             "source_mode": ctx["source_mode"], "processing_status": status,
             "input_refs": refs or [], "scope": {"included": ["人员资质章节"], "excluded": ["全本标书", "技术方案", "商务与报价", "正式递交"]},
             "issues": problems, "data": data,
             "next_actions": [{"owner_role": i["owner_role"], "action": i["next_action"]} for i in problems]}
    validate_envelope(value)
    return value


def save_module(run_dir, filename, value):
    validate_envelope(value)
    write_json(Path(run_dir) / filename, value)
    summary = [f"# {value['module']} 运行摘要", "", f"处理状态：{value['processing_status']}",
               "范围：人员资质章节。全本标书未完成。", "", "## 问题与接手"]
    summary += [f"- {i['code']}：{i['message']}；{i['owner_role']}接手；{i['next_action']}" for i in value["issues"]] or ["本次声明范围内未发现已知阻断问题；业务确认与放行另行记录。"]
    summary += ["", f"机器可读详情：{filename}"]
    if value["module"] == "M04":
        summary += ["", "## 实际提取的要求"]
        for requirement in value["data"]["requirements"]:
            locations = "；".join(f"{ref.get('relative_path', ref['source_id'])} 第{ref['locator']['line']}行" for ref in requirement["evidence_refs"])
            summary += [f"- {requirement['requirement_id']}【{requirement['category']}】：{requirement['text']}（{locations}）"]
        summary += ["", "评分与否决依据未明确时保持未知；未知信息不构成业务认定。"]
        changes = value["data"].get("version_mapping", [])
        if changes:
            summary += ["", "## 版本对应"] + [f"- {item['requirement_id']}：{item['change']}" for item in changes]
    Path(run_dir, filename.replace(".json", ".md")).write_text("\n".join(summary) + "\n", encoding="utf-8")


def require_same_context(ctx, *values):
    for value in values:
        validate_envelope(value)
        if any(value[k] != ctx[k] for k in ("project_id", "lot_id", "source_mode")):
            raise InputError("Cross-project, lot or mode input rejected")
