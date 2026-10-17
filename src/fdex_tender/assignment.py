#!/usr/bin/env python3
"""M07 责任角色与任务期限（共享核心 + 验收投影）。

任务 M07-01：为响应矩阵增加**配置的**责任角色与明确任务期限，并检查不晚于业务时限。

设计要点（与 M07 验收包 samples/acceptance/M07 的四类用例对齐）：

- 责任角色来自配置的「类别 → 角色」映射。该类别没有配角色时保留未知
  （owner_role=None）并报 OWNER_MISSING，**绝不**沿用某个固定角色冒充"已配置"。
- 任务期限来自配置的「要求键 → 时间」映射。缺失时保留未知（due_time=None）并报
  DUE_TIME_MISSING，**绝不**把未知期限填成当天或分析时间——"不知道"必须留成
  null，让人看见，而不是让一个看似合理的日期掩盖它。
- 期限必须能解析且带时区。不可解析/无时区 → DUE_TIME_INVALID（阻断），不猜。
  与"缺失"严格区分：缺失是"没给"（复核），非法是"给错了"（阻断）。
- 期限晚于该要求自己的业务截止 → DUE_AFTER_DEADLINE（阻断）。
- 调用方同时给出实际模板列与支持列时，出现未映射列 → TEMPLATE_MAPPING_REQUIRED
  （复核）；不静默按位置填错列。

本模块只做解析与状态判定。不读 expected.json、不按 case_id 返回固定答案、
不生成 Word、不授予真实报价/签章/递交授权。
对外返回 bid-training.acceptance-result.v1；input_hashes / evidence / artifacts
由适配器补齐，本模块不产出。
"""
from .core import parse_time

RESULT_VERSION = "bid-training.acceptance-result.v1"

# 阻断类：坏数据或硬约束违反，必须先修数据才能继续。
_BLOCKING = {"DUE_AFTER_DEADLINE", "DUE_TIME_INVALID"}
# 复核类：配置缺口，需要人补配置或重新确认。
_REVIEW = {"OWNER_MISSING", "DUE_TIME_MISSING", "TEMPLATE_MAPPING_REQUIRED"}


def _clean_text(value):
    """非空字符串 → 去空白后的原值；其它（None/空白/数字/bool）→ None。"""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_moment(raw):
    """时间字符串 → (datetime 或 None, state)。

    state:
      "missing" —— 未提供（None / 空白串），语义是"没给"；
      "invalid" —— 提供了但非法（非字符串、不可解析、无时区），语义是"给错了"；
      "ok"      —— 带时区的合法时间。

    关键：不把"非法"降级成"缺失"，否则一个写坏的时间会被当成"还没配"
    而在复核队列里排队，掩盖真正的数据错误。
    """
    if raw is None:
        return None, "missing"
    if not isinstance(raw, str):
        return None, "invalid"
    text = raw.strip()
    if not text:
        return None, "missing"
    try:
        return parse_time(text), "ok"
    except (ValueError, TypeError):
        return None, "invalid"


def _unique(codes):
    """去重并保持首次出现顺序——判定顺序本身是可复核的证据。"""
    seen, ordered = set(), []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered


def status_for(codes):
    """问题码集合 → 处理状态。阻断优先于复核。"""
    if set(codes) & _BLOCKING:
        return "BLOCKED"
    if set(codes) & _REVIEW:
        return "REVIEW"
    return "COMPLETE"


def resolve_assignments(requirements, roles, due_times):
    """给每条**在范围内**的要求解析责任角色与任务期限。

    requirements: [{"key", "category", "deadline"}]，只含本次要派活的要求。
    roles:          {类别: 角色名}
    due_times:      {要求键: ISO 时间}

    返回 (rows, issue_codes)：
      rows[i] = {"key", "category", "owner_role", "due_time", "late", "issues"}
        owner_role / due_time 取不到时是 None —— 未知就留空，不编。
        issues 是该条自己的问题码，生产链据此逐条建公共信封问题条目。
      issue_codes 顺序稳定：逐条要求先判责任角色，再判期限，最后判业务截止。
        这个顺序让复核者能按人、按条往下读，而不是面对一堆乱序代码。
    """
    roles = roles if isinstance(roles, dict) else {}
    due_times = due_times if isinstance(due_times, dict) else {}
    rows, codes = [], []
    for requirement in requirements or []:
        key = requirement.get("key")
        row_issues = []

        owner = _clean_text(roles.get(requirement.get("category")))
        if owner is None:
            row_issues.append("OWNER_MISSING")

        due, due_state = _parse_moment(due_times.get(key))
        if due_state == "missing":
            row_issues.append("DUE_TIME_MISSING")
        elif due_state == "invalid":
            row_issues.append("DUE_TIME_INVALID")

        deadline, _ = _parse_moment(requirement.get("deadline"))
        late = due is not None and deadline is not None and due > deadline
        if late:
            row_issues.append("DUE_AFTER_DEADLINE")

        codes.extend(row_issues)
        rows.append({"key": key, "category": requirement.get("category"),
                     "owner_role": owner, "due_time": due.isoformat() if due else None,
                     "late": late, "issues": row_issues})
    return rows, _unique(codes)


def check_template_columns(provided_columns, supported_columns, template_version=None):
    """模板列 → (unmapped, issue_codes, version)。

    只有调用方**同时**给出实际列与支持列才能判定；缺任何一侧都保持"未判定"
    并返回空列表，不假装已经适配过。
    """
    provided = [c for c in (provided_columns or []) if _clean_text(c)]
    supported = [c for c in (supported_columns or []) if _clean_text(c)]
    version = _clean_text(template_version)
    if not provided or not supported:
        return [], [], version
    unmapped = [c for c in provided if c not in set(supported)]
    return unmapped, (["TEMPLATE_MAPPING_REQUIRED"] if unmapped else []), version


def compute_assignment(request):
    """request = 验收 input.json 解析后的 dict（含 payload）。返回结果字典。

    适配器读到的 payload 形状：
      requirements[]: {key, category, mandatory, deadline}
      roles:          {category: 角色名}
      due_times:      {key: ISO 时间}
      included_categories / template_columns / supported_columns / template_version
    """
    payload = request.get("payload") or {}
    requirements = payload.get("requirements") or []
    included = [c for c in (payload.get("included_categories") or []) if _clean_text(c)]
    included_set = set(included)

    in_scope = [r for r in requirements if r.get("category") in included_set]
    out_scope = [r for r in requirements if r.get("category") not in included_set]

    rows, codes = resolve_assignments(in_scope, payload.get("roles"), payload.get("due_times"))
    unmapped, template_codes, version = check_template_columns(
        payload.get("template_columns"), payload.get("supported_columns"), payload.get("template_version"))
    codes = _unique(codes + template_codes)

    facts = {
        "owners": {row["key"]: row["owner_role"] for row in rows},
        "due_times": {row["key"]: row["due_time"] for row in rows},
        "included": [r.get("key") for r in in_scope],
        "excluded": [r.get("key") for r in out_scope],
        "scope_total": len(in_scope),
        "full_total": len(requirements),
        "full_tender_complete": False,
    }
    late = [row["key"] for row in rows if row["late"]]
    if late:
        facts["late_requirements"] = late
    if unmapped:
        facts["unmapped_columns"] = unmapped
    if version:
        facts["template_version"] = version

    return {
        "schema_version": RESULT_VERSION,
        "module": request.get("module", "M07"),
        "case_id": request.get("case_id"),
        "source_mode": request.get("source_mode"),
        "status": status_for(codes),
        "facts": facts,
        "issue_codes": codes,
        "real_submission_authorized": False,
    }
