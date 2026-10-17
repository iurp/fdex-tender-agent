"""Bounded, deterministic teaching reference implementations.

M04 reads labelled raw Markdown, M08 reads declared sidecars and checks images.
Neither module claims general document extraction or OCR.
"""
import re
import zipfile
from datetime import date
from pathlib import Path
from PIL import Image
from .core import InputError, digest_file, digest_object, envelope, evidence, issue, read_json, require_same_context, safe_path, stable_id
from .assignment import resolve_assignments

# M07 分工配置的问题码 → 公共信封问题条目（严重度、说明、接手角色、下一步）。
# 顺序与 assignment.resolve_assignments 的逐条判定顺序一致，便于按人、按条复核。
# 未登记的新码给保守兜底，避免因为漏登记直接崩掉整链。
_ASSIGNMENT_ISSUES = {
    "OWNER_MISSING": ("MAJOR", "配置未给出该类别责任角色；保留未知，不沿用默认角色",
                      "招投标负责人", "在 task-assignment.json 中补齐该类别角色后重跑"),
    "DUE_TIME_MISSING": ("MAJOR", "配置未给出该任务期限；保留未知，不填当天",
                         "招投标负责人", "在 task-assignment.json 中补齐该要求期限后重跑"),
    "DUE_TIME_INVALID": ("BLOCKER", "任务期限不是带时区的合法时间；不猜测",
                         "招投标负责人", "修正 task-assignment.json 中的期限后重跑"),
    "DUE_AFTER_DEADLINE": ("BLOCKER", "任务期限晚于该要求自己的业务截止",
                           "招投标负责人", "把期限提前到业务截止之前，或申请调整截止"),
}
_ASSIGNMENT_ISSUE_FALLBACK = ("MAJOR", "分工配置出现未登记的问题", "招投标负责人", "核对配置后重跑")


def register(ctx):
    root = Path(ctx["input_root"])
    supplied = read_json(root / "sources.json")
    refs, problems, sources = [], [], []
    for source in supplied["sources"]:
        if source.get("project_id") not in (None, ctx["project_id"]) or source.get("lot_id") not in (None, ctx["lot_id"]):
            problems.append(issue("SOURCE_CONTEXT_MISMATCH", source["source_id"], "来源属于其他项目或标包"))
            continue
        path = safe_path(root, source["relative_path"])
        if not path.is_file():
            problems.append(issue("SOURCE_MISSING", source["source_id"], "已登记的原件不存在"))
            continue
        value = {**source, "sha256": digest_file(path), "read_status": "REGISTERED"}
        sources.append(value)
        refs.append({k: value[k] for k in ("source_id", "relative_path", "version", "sha256")})
    return envelope(ctx, "M03", {"project": {k: ctx[k] for k in ("project_id", "lot_id", "project_name", "analysis_time")},
                                 "sources_manifest_sha256": digest_file(root / "sources.json"),
                                 "business_participation": ctx.get("business_participation", "UNDECIDED"),
                                 "sources": sources, "current_version_claim": "SUPPLIED_SCOPE_ONLY"}, refs, problems)


def read_tender(ctx, registered):
    require_same_context(ctx, registered)
    declared = read_json(Path(ctx["input_root"]) / "sources.json")["sources"]
    tender_ids = {s["source_id"] for s in declared if s["kind"] == "tender_markdown"}
    requirements, problems = [], [i for i in registered["issues"] if i["object_id"] in tender_ids]
    rule = {"count": None, "qualification": None, "valid_on": None}
    refs = []
    for src in registered["data"]["sources"]:
        if src["kind"] != "tender_markdown":
            continue
        path = safe_path(ctx["input_root"], src["relative_path"])
        if digest_file(path) != src["sha256"]:
            raise InputError("Tender changed after registration")
        lines = path.read_text(encoding="utf-8").splitlines()
        refs.append({k: src[k] for k in ("source_id", "relative_path", "version", "sha256")})
        for number, line in enumerate(lines, 1):
            match = re.fullmatch(r"\[(R-\d{2})\]\[(人员|资格|评分|报价|技术|格式|商务)\] (.+)", line)
            if not match:
                continue
            key, category, text = match.groups()
            requirements.append({"requirement_id": stable_id("REQ", ctx["project_id"], ctx["lot_id"], key),
                                 "source_key": key, "category": category, "text": text,
                                 "mandatory": "必须" in text or "不少于" in text,
                                 "disqualifying": True if "否则否决" in text else None,
                                 "score": None, "fact_kind": "SOURCE_FACT", "version": src["version"],
                                 "missing_reason": {"score": "本适配器未解析出评分数值，请核对原文；不补造分值",
                                                    "disqualifying": None if "否则否决" in text else "原文未给出明确否决性依据"},
                                 "evidence_refs": [evidence(src["source_id"], number, line)],
                                 "in_personnel_scope": key in ("R-01", "R-02", "R-03", "R-04", "R-05", "R-06", "R-07", "R-08")})
            count = re.search(r"人员不少于(\d+)名", text)
            if count:
                rule["count"] = int(count[1])
            qual = re.search(r"持有([^，。]+)证书", text)
            if qual:
                rule["qualification"] = qual[1]
            when = re.search(r"证书有效期以(\d{4}-\d{2}-\d{2})为基准", text)
            if when:
                rule["valid_on"] = when[1]
    keys = [r["source_key"] for r in requirements]
    if len(set(keys)) != len(keys):
        problems.append(issue("REQUIREMENT_CONFLICT", "tender", "发现重复要求定位，尚未确认覆盖关系"))
    if not requirements:
        problems.append(issue("NO_SUPPORTED_REQUIREMENTS", "tender", "当前适配器仅支持示例 Markdown，未提取要求"))
    if any(v is None for v in rule.values()):
        problems.append(issue("MISSING_PERSONNEL_RULE", "personnel", "人员数量、证书类型或有效期基准缺失"))
    return envelope(ctx, "M04", {"requirements": requirements, "personnel_rule": rule,
                                 "coverage": {"read_scope": "provided_markdown_excerpt", "full_tender_read": False},
                                 "adapter": "labelled-markdown-v1"}, refs, problems)


def response_matrix(ctx, tender):
    require_same_context(ctx, tender)
    root = Path(ctx["input_root"])
    manifest = read_json(root / "template-manifest.json")
    template = safe_path(root, manifest["relative_path"])
    problems = list(tender["issues"])
    expected_columns = ["角色", "人员", "证书编号", "有效期", "原件位置"]
    if not template.is_file() or digest_file(template) != manifest["sha256"]:
        problems.append(issue("TEMPLATE_HASH_MISMATCH", manifest["template_id"], "模板文件与声明哈希不一致"))
    if manifest.get("columns") != expected_columns or manifest.get("version") != "1.0":
        problems.append(issue("TEMPLATE_MAPPING_UNSUPPORTED", manifest["template_id"], "模板列或版次变化，需要明确适配"))

    in_scope = [r for r in tender["data"]["requirements"] if r["in_personnel_scope"]]

    # 企业分工配置（task-assignment.json）是**可选**输入。
    # 没有它时严格保持基座行为：角色为默认值、期限保持未知，只在 data 里声明
    # "未配置"。既不改状态，也不凭空造出角色或期限——"没配"要看得见，
    # 而不是让一个看似合理的日期冒充已配置的期限。
    assignment_path = root / "task-assignment.json"
    assignment = read_json(assignment_path) if assignment_path.exists() else None
    if assignment is None:
        assignment_state = {"source": "BASELINE_DEFAULT", "configured": False,
                            "note": "未提供 task-assignment.json；责任角色沿用基座默认，任务期限保持未知，不填当天"}
        by_requirement_id = {r["requirement_id"]: ("资料管理员", None) for r in in_scope}
    else:
        deadlines = assignment.get("deadlines") or {}
        business_deadline = assignment.get("business_deadline")
        # 每条要求用的是**它自己**的业务截止；只有该条没单列时才退回统一业务截止。
        normalized = [{"key": r["source_key"], "category": r["category"], "mandatory": r["mandatory"],
                       "deadline": deadlines.get(r["source_key"], business_deadline)} for r in in_scope]
        resolved, _ = resolve_assignments(normalized, assignment.get("roles"), assignment.get("due_times"))
        by_requirement_id, late_keys = {}, []
        for requirement, row in zip(in_scope, resolved):
            by_requirement_id[requirement["requirement_id"]] = (row["owner_role"], row["due_time"])
            if row["late"]:
                late_keys.append(requirement["source_key"])
            for code in row["issues"]:
                severity, message, owner, action = _ASSIGNMENT_ISSUES.get(code, _ASSIGNMENT_ISSUE_FALLBACK)
                problems.append(issue(code, requirement["source_key"], message,
                                      severity=severity, owner=owner, action=action))
        assignment_state = {"source": "CONFIGURED", "configured": True, "file": "task-assignment.json",
                            "sha256": digest_file(assignment_path),
                            "roles": assignment.get("roles") or {}, "due_times": assignment.get("due_times") or {},
                            "business_deadline": business_deadline, "late_requirements": late_keys}

    rows = []
    for req in in_scope:
        owner_role, due_time = by_requirement_id[req["requirement_id"]]
        rows.append({"response_id": stable_id("RESP", req["requirement_id"], manifest["template_id"]),
                     "requirement_ids": [req["requirement_id"]], "section_id": "SECTION-PERSONNEL",
                     "field_id": "PERSONNEL-TABLE" if req["source_key"] in ("R-01", "R-02", "R-03", "R-04") else "PERSONNEL-ATTACHMENTS",
                     "owner_role": owner_role, "due_time": due_time,
                     "required_assets": ["certificate"], "status": "PROPOSED", "template_version": manifest["version"]})
    return envelope(ctx, "M07", {"responses": rows, "template": manifest,
                                 "excluded_requirements": [r["requirement_id"] for r in tender["data"]["requirements"] if not r["in_personnel_scope"]],
                                 "coverage": {"scope_total": len(rows), "scope_mapped": len(rows), "full_total": len(tender["data"]["requirements"]), "full_tender_complete": False},
                                 "task_assignment": assignment_state}, tender["input_refs"], problems)


def material_index(ctx, registered):
    require_same_context(ctx, registered)
    root = Path(ctx["input_root"])
    persons, assets, refs, problems = [], [], [], []
    for src in registered["data"]["sources"]:
        if src["kind"] != "person_sidecar":
            continue
        path = safe_path(root, src["relative_path"])
        fields = {}
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            if ": " in line:
                key, val = line.split(": ", 1)
                fields[key] = (val, number, line)
        needed = ("person_id", "name", "asset_id", "certificate_id", "qualification", "valid_until", "image", "company_id")
        if any(k not in fields for k in needed):
            problems.append(issue("MATERIAL_FIELDS_MISSING", src["source_id"], "材料说明缺字段"))
            continue
        get = lambda key: fields[key][0]
        if get("company_id") != ctx["company_id"]:
            problems.append(issue("MATERIAL_COMPANY_MISMATCH", get("asset_id"), "材料属于不同企业"))
            continue
        image_path = safe_path(root, get("image"))
        image_hash = None
        try:
            with Image.open(image_path) as image:
                image.verify()
            image_hash = digest_file(image_path)
        except (OSError, ValueError, SyntaxError):
            problems.append(issue("IMAGE_UNREADABLE", get("asset_id"), "图片缺失或损坏，阻断使用该材料", owner="资料管理员"))
        field_refs = {key: evidence(src["source_id"], fields[key][1], fields[key][2]) for key in needed}
        persons.append({"person_id": get("person_id"), "name": get("name"), "company_id": get("company_id"), "source_id": src["source_id"]})
        assets.append({"asset_id": get("asset_id"), "person_id": get("person_id"), "certificate_id": get("certificate_id"),
                       "qualification": get("qualification"), "valid_until": None if get("valid_until") == "unknown" else get("valid_until"),
                       "relative_path": get("image"), "sha256": image_hash, "version": src["version"],
                       "read_method": "provided_sidecar_not_ocr", "field_refs": field_refs,
                       "verification_status": "DEMO_DECLARED_FIELDS", "public": src.get("public", False)})
        refs.append({k: src[k] for k in ("source_id", "relative_path", "version", "sha256")})
    if len({p["person_id"] for p in persons}) != len(persons) or len({a["asset_id"] for a in assets}) != len(assets):
        problems.append(issue("DUPLICATE_MATERIAL_ID", "material_index", "人员或材料ID重复"))
    return envelope(ctx, "M08", {"persons": persons, "assets": assets,
                                 "reading_boundary": "读取教学人员说明并检查图片完整性；未实现OCR、图片字段提取或证书真伪核验"}, refs, problems,
                    status="REVIEW" if problems else "COMPLETE")


def selection_fingerprint(ctx, tender, index, person_ids, roles=None):
    relevant = {"project_id": ctx["project_id"], "lot_id": ctx["lot_id"], "source_mode": ctx["source_mode"],
                "rule": tender["data"]["personnel_rule"], "person_ids": person_ids, "roles": roles or {},
                "persons": [p for p in index["data"]["persons"] if p["person_id"] in person_ids],
                "assets": [a for a in index["data"]["assets"] if a["person_id"] in person_ids]}
    return digest_object(relevant)


def match_materials(ctx, tender, matrix, index):
    require_same_context(ctx, tender, matrix, index)
    problems = list(tender["issues"]) + list(matrix["issues"])
    rule = tender["data"]["personnel_rule"]
    candidates = []
    for person in index["data"]["persons"]:
        owned = [a for a in index["data"]["assets"] if a["person_id"] == person["person_id"]]
        if not owned:
            candidates.append({**person, "status": "MISSING", "asset_id": None})
            continue
        asset = owned[0]
        state = "MATCHED"
        if not asset["sha256"] or not asset["valid_until"] or not rule["valid_on"]:
            state = "REVIEW"
        else:
            try:
                if date.fromisoformat(asset["valid_until"]) < date.fromisoformat(rule["valid_on"]):
                    state = "EXPIRED"
            except ValueError:
                state = "REVIEW"
        if asset["qualification"] != rule["qualification"]:
            state = "MISSING"
        candidates.append({**person, "status": state, "asset_id": asset["asset_id"], "certificate_id": asset["certificate_id"],
                           "valid_until": asset["valid_until"], "evidence_refs": list(asset["field_refs"].values())})
    duplicate_names = {p["name"] for p in candidates if sum(x["name"] == p["name"] for x in candidates) > 1}
    for p in candidates:
        if p["name"] in duplicate_names:
            p["status"] = "REVIEW"
    confirmation_file = safe_path(ctx["input_root"], "selection.json")
    supplied = read_json(confirmation_file) if confirmation_file.exists() else {}
    ids = supplied.get("person_ids", [])
    roles = supplied.get("roles", {})
    fingerprint = selection_fingerprint(ctx, tender, index, ids, roles)
    state = "UNCONFIRMED"
    selected = []
    if supplied:
        if any(supplied.get(k) != ctx[k] for k in ("project_id", "lot_id", "source_mode")):
            problems.append(issue("CONFIRMATION_CONTEXT_MISMATCH", "selection", "确认记录不属于本项目或标包"))
        elif supplied.get("target_digest") != fingerprint:
            state = "STALE"
            problems.append(issue("CONFIRMATION_STALE", "selection", "要求或所选材料已变化，需重新确认"))
        elif supplied.get("status") != "CONFIRMED" or not supplied.get("confirmed_by") or not supplied.get("confirmed_at"):
            problems.append(issue("UNCONFIRMED_SELECTION", "selection", "人员尚未由输入记录确认", severity="MAJOR"))
        else:
            parse_ok = True
            from .core import parse_time
            try:
                parse_time(supplied["confirmed_at"])
            except (ValueError, TypeError):
                parse_ok = False
            by_id = {p["person_id"]: p for p in candidates}
            if not parse_ok or len(set(ids)) != len(ids) or rule["count"] is None or len(ids) < rule["count"] or any(pid not in by_id or by_id[pid]["status"] != "MATCHED" or not isinstance(roles.get(pid), str) or not roles[pid].strip() for pid in ids):
                problems.append(issue("SELECTION_INVALID", "selection", "确认日期、数量、人员ID或证书不满足本次要求"))
            else:
                state = "CONFIRMED"
                selected = [{**by_id[pid], "role": roles[pid]} for pid in ids]
    else:
        problems.append(issue("UNCONFIRMED_SELECTION", "selection", "缺少人员确认记录", severity="MAJOR"))
    if any(i["severity"] == "BLOCKER" for i in problems):
        selected = []
    return envelope(ctx, "M09", {"candidates": candidates, "selected": selected, "selection_digest": fingerprint,
                                 "confirmation": {"status": state, "record": supplied or None,
                                                  "boundary": "DEMO输入中的模拟确认，不代表真实业务批准"}}, index["input_refs"] + tender["input_refs"], problems,
                    status="COMPLETE" if selected else "BLOCKED" if any(i["severity"] == "BLOCKER" for i in problems) else "REVIEW")
