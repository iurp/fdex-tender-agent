"""Evidence-preserving parser for the declared Markdown/text personnel excerpt.

shortcut: semantic rules cover this task's clause families, not arbitrary tender
language; unfamiliar obligations are retained for review instead of guessed.
"""
import re
from collections import defaultdict
from datetime import date

from .core import (InputError, digest_file, digest_object, envelope, evidence,
                   issue, require_same_context, safe_path, stable_id)


LABEL = re.compile(r"\[(R-\d{2})\]\[(人员|资格|评分|报价|技术|格式|商务)\]\s+(.+)")
NUMBER = r"(?:\d+|[一二两三四五六七八九]?十[一二三四五六七八九]?|[零一二两三四五六七八九])"
COUNT = re.compile(r"人员(?:人数|数量|总数)?\s*(不少于|不得少于|不低于|至少|不超过|至多|恰为|恰好为?|等于|为)\s*(" + NUMBER + r")\s*(?:名|人)")
RELATIONS = {"不少于": "min", "不得少于": "min", "不低于": "min", "至少": "min",
             "不超过": "max", "至多": "max", "恰为": "exact", "恰好": "exact", "恰好为": "exact", "等于": "exact", "为": "exact"}
KINDS = {
    "personnel_count": ("人员", True, "PERSONNEL-TABLE"),
    "qualification": ("资格", True, "PERSONNEL-TABLE"),
    "validity": ("资格", True, "PERSONNEL-TABLE"),
    "table_fields": ("格式", True, "PERSONNEL-TABLE"),
    "certificate_images": ("格式", True, "PERSONNEL-ATTACHMENTS"),
    "selection_confirmation": ("人员", True, "PERSONNEL-ATTACHMENTS"),
    "personnel_template": ("格式", True, "PERSONNEL-ATTACHMENTS"),
    "project_fields": ("格式", True, "PERSONNEL-ATTACHMENTS"),
    "pricing": ("报价", False, None),
    "implementation_plan": ("技术", False, None),
    "scoring": ("评分", False, None),
    "submission_deadline": ("商务", False, None),
    "unknown": ("未知", False, None),
}


def integer(text):
    if text.isdigit():
        return int(text)
    digits = {c: n for n, c in enumerate("零一二三四五六七八九")}
    digits["两"] = 2
    if "十" in text:
        left, right = text.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits[text]


def classify(text):
    counts = list(COUNT.finditer(text))
    if counts:
        values = [{"relation": RELATIONS[count[1]], "value": integer(count[2])} for count in counts]
        return "personnel_count", {**values[0], "constraints": values}
    match = re.search(r"(?:持有|具备|取得)([^，。；]+?)(?:证书|资格证)", text)
    if match:
        return "qualification", {"qualification": match[1].strip()}
    if re.search(r"证书.*(?:图片|扫描件|复印件|影像)", text):
        return "certificate_images", {}
    if re.search(r"人员(?:表|清单|名单).*证(?:书|号)", text):
        return "table_fields", {}
    if "证书" in text and "有效" in text:
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        # An expiration date is not automatically the checking reference date.
        reference = re.search(r"以\s*\d{4}-\d{2}-\d{2}\s*为基准|截至\s*\d{4}-\d{2}-\d{2}.*(?:有效|未到期)", text)
        try:
            return "validity", {"valid_on": date.fromisoformat(dates[0]).isoformat() if reference and len(dates) == 1 else None}
        except ValueError:
            return "validity", {"valid_on": None}
    if "确认" in text and re.search(r"人员|选用|选派", text):
        return "selection_confirmation", {}
    if re.search(r"人员表|Word|可编辑", text) and re.search(r"版次|模板|版本", text):
        return "personnel_template", {}
    if "项目名称" in text and "项目编号" in text:
        return "project_fields", {}
    if re.search(r"报价|含税|税率|计价", text):
        return "pricing", {}
    if re.search(r"实施计划|实施方案|技术方案", text):
        return "implementation_plan", {}
    if re.search(r"评分|分值|得分", text):
        return "scoring", {}
    if "截止" in text and re.search(r"投标|递交|提交", text):
        match = re.search(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z))?", text)
        return "submission_deadline", {"deadline_text": match[0] if match else None}
    return "unknown", {}


def clauses(lines):
    for number, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        labelled = LABEL.fullmatch(raw.strip())
        if labelled:
            yield number, raw, labelled[3], labelled
            continue
        cleaned = re.sub(r"^\s*(?:[-*•]\s+|\d+[、.)]\s*)", "", raw).strip()
        for text in re.split(r"(?<=[。！？])\s*", cleaned):
            if not text:
                continue
            # Descriptive project metadata and narrative are not obligations.
            if COUNT.search(text) or re.search(r"必须|应当|应提供|须|不得|不少于|至少|不超过|至多|恰为|恰好|人员人数|评分|投标截止|递交截止", text):
                yield number, raw, text, None


def link_versions(ctx, previous, requirements):
    if previous is None:
        return []
    require_same_context(ctx, previous)
    old = {r["requirement_id"]: r for r in previous["data"]["requirements"]}
    new = {r["requirement_id"]: r for r in requirements}
    result = []
    for identity in sorted(old.keys() | new.keys()):
        before, after = old.get(identity), new.get(identity)
        state = "ADDED" if before is None else "REMOVED" if after is None else "UNCHANGED" if before["text"] == after["text"] else "CHANGED"
        result.append({"requirement_id": identity, "change": state,
                       "previous_revision_id": before.get("revision_id") if before else None,
                       "revision_id": after.get("revision_id") if after else None,
                       "previous_version": before["version"] if before else None,
                       "version": after["version"] if after else None,
                       "previous_evidence_refs": before["evidence_refs"] if before else [],
                       "evidence_refs": after["evidence_refs"] if after else []})
    return result


def extract_requirements(ctx, sources, previous=None, inherited_issues=None):
    """Read registered source bytes; output the existing M04 workflow envelope."""
    if ctx["source_mode"] != "DEMO":
        raise InputError("M04 supports DEMO only")
    problems, refs, requirements = list(inherited_issues or []), [], []
    formats = set()
    for src in sources:
        path = safe_path(ctx["input_root"], src["relative_path"])
        refs.append({k: src[k] for k in ("source_id", "relative_path", "version", "sha256")})
        try:
            if digest_file(path) != src["sha256"]:
                raise InputError("Tender changed after registration")
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            problems.append(issue("BODY_UNREADABLE", src["source_id"], "正文缺失或不是可读取的UTF-8文本，未生成伪要求"))
            continue
        found = 0
        for number, raw, text, labelled in clauses(lines):
            kind, attributes = classify(text)
            category, included, field = KINDS[kind]
            formats.add("labelled" if labelled else "plain")
            semantic_key = kind + (":" + attributes["relation"] if kind == "personnel_count" else "")
            if kind == "unknown":
                semantic_key += ":" + digest_object(re.sub(r"\d+", "#", text))[:16]
            key = labelled[1] if labelled else semantic_key
            identity = stable_id("REQ", ctx["project_id"], ctx["lot_id"], key) if labelled else stable_id("REQ", ctx["project_id"], ctx["lot_id"], src["source_id"], key)
            score = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*分(?!值|数)", text) if kind == "scoring" else None
            score_value = float(score[1]) if score and not re.search(r"未公布|未明确|待定|不得补造", text) else None
            disqualifying = True if re.search(r"否则(?:否决|废标)|不满足[^。；]*无效|不提供[^。；]*(?:否决|废标)", text) else None
            ref = {**evidence(src["source_id"], number, raw), "relative_path": src["relative_path"]}
            requirement = {"requirement_id": identity, "source_key": key, "semantic_kind": kind,
                           "category": labelled[2] if labelled else category, "text": text,
                           "mandatory": bool(re.search(r"必须|须|应当|应提供|不少于|不得少于|至少|不得|恰为|恰好", text)),
                           "disqualifying": disqualifying, "score": score_value, "fact_kind": "SOURCE_FACT",
                           "version": src["version"], "revision_id": stable_id("REV", identity, text),
                           "missing_reason": {"score": None if score_value is not None else "原文未明确可提取的评分分值，不补造",
                                              "disqualifying": None if disqualifying else "原文未给出明确否决性依据"},
                           "evidence_refs": [ref], "in_personnel_scope": included,
                           "response_field": field, "attributes": attributes}
            requirements.append(requirement)
            found += 1
            if kind == "unknown":
                problems.append(issue("UNSUPPORTED_CLAUSE", identity, "保留未能可靠分类的要求，需人工核对", severity="MAJOR", evidence=[ref]))
        if not found:
            problems.append(issue("BODY_UNREADABLE", src["source_id"], "正文没有可验证的要求；未生成要求清单"))

    # Repeated identical clauses share an entity and retain all locations.
    groups = defaultdict(list)
    for requirement in requirements:
        groups[requirement["requirement_id"]].append(requirement)
    requirements = []
    for identity, group in groups.items():
        texts = {}
        for requirement in group:
            if requirement["text"] in texts:
                texts[requirement["text"]]["evidence_refs"].extend(requirement["evidence_refs"])
            else:
                texts[requirement["text"]] = requirement
        if len(texts) > 1:
            problems.append(issue("AMBIGUOUS_REQUIREMENT_IDENTITY", identity, "同一语义角色存在多条不同要求，保留双方，版本对应需人工确认", severity="MAJOR",
                                  evidence=[r for item in texts.values() for r in item["evidence_refs"]]))
            for item in texts.values():
                item["requirement_id"] = stable_id("REQ", identity, item["text"])
                item["revision_id"] = stable_id("REV", item["requirement_id"], item["text"])
                item["identity_ambiguous"] = True
        requirements.extend(texts.values())

    constraints = [{**constraint, "requirement_id": r["requirement_id"], "evidence_refs": r["evidence_refs"]}
                   for r in requirements if r["semantic_kind"] == "personnel_count"
                   for constraint in r["attributes"]["constraints"]]
    lower = max([c["value"] for c in constraints if c["relation"] in ("min", "exact")] or [0])
    upper = min([c["value"] for c in constraints if c["relation"] in ("max", "exact")] or [float("inf")])
    conflict = lower > upper
    rule = {"count": lower if constraints and lower > 0 and not conflict else None,
            "qualification": None, "valid_on": None}
    conflicts = []
    if conflict:
        all_refs = [r for c in constraints for r in c["evidence_refs"]]
        problems.append(issue("CLAUSE_CONFLICT", "personnel-count", "人数约束互相冲突，保留双方原文，等待负责人解释", severity="MAJOR", evidence=all_refs))
        conflicts.append({"field": "personnel_count", "values": [c["value"] for c in constraints], "evidence_refs": all_refs})
    for field in ("qualification", "valid_on"):
        applicable = [r for r in requirements if field in r["attributes"]]
        values = {r["attributes"][field] for r in applicable if r["attributes"][field] is not None}
        if len(values) == 1:
            rule[field] = values.pop()
        elif len(values) > 1:
            all_refs = [ref for r in applicable for ref in r["evidence_refs"]]
            problems.append(issue("CLAUSE_CONFLICT", field, "资质或有效期基准存在多个不同值，未擅自裁定", severity="MAJOR", evidence=all_refs))
            conflicts.append({"field": field, "values": sorted(values), "evidence_refs": all_refs})
    if not sources and not problems:
        problems.append(issue("BODY_UNREADABLE", "tender", "没有登记可读取的招标原文"))
    if requirements and any(value is None for value in rule.values()) and not conflicts:
        problems.append(issue("MISSING_PERSONNEL_RULE", "personnel", "人员数量、证书类型或有效期基准缺失，保留未知并转复核", severity="MAJOR"))
    mappings = link_versions(ctx, previous, requirements)
    data = {"requirements": requirements, "personnel_rule": rule, "personnel_constraints": constraints,
            "conflicts": conflicts, "version_mapping": mappings,
            "coverage": {"read_scope": "provided_markdown_excerpt", "full_tender_read": False},
            "adapter": "labelled-markdown-v1" if formats == {"labelled"} else "mixed-markdown-v1" if len(formats) > 1 else "natural-text-v1"}
    return envelope(ctx, "M04", data, refs, problems)
