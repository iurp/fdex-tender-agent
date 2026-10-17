"""M07 责任与任务期限的回归测试。

三层：
1) AssignmentUnitTests —— 纯逻辑：角色/期限解析、业务时限判定、模板列判定。
2) AcceptanceCaseTests —— 验收包 M07 的四个公开用例（正常/复核/异常/变更）。
   断言值是公开预期，但全部由真实函数算出，不是按 case_id 查表。
3) PipelineIntegrationTests —— 把分工配置接进真实基座链：先跑通 core-normal
   取得实际上游，再注入配置看 M07 实际产出。

另外用输入变异锁住"没有硬编码参考预期"：换项目、换人、换日期、换顺序之后，
结论必须跟着规则走，而不是跟着样例走。
"""
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fdex_tender.assignment import check_template_columns, compute_assignment, resolve_assignments
from fdex_tender.core import validate_envelope
from fdex_tender.pipeline import run

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_TIME = "2026-10-13T09:00:00+08:00"
BUSINESS_DEADLINE = "2026-11-01T10:00:00+08:00"
STANDARD_COLUMNS = ["角色", "人员", "证书编号", "有效期", "原件位置"]

# 基座 core-normal 里 R-01..R-08 的类别：人员 / 资格 / 格式（见 tender/tender.md）。
CORE_ROLES = {"人员": "资料管理员", "资格": "资料管理员", "格式": "文档负责人"}
CORE_DUE_TIMES = {
    "R-01": "2026-10-30T18:00:00+08:00", "R-02": "2026-10-30T18:00:00+08:00",
    "R-03": "2026-10-30T18:00:00+08:00", "R-04": "2026-10-31T18:00:00+08:00",
    "R-05": "2026-10-31T18:00:00+08:00", "R-06": "2026-10-30T18:00:00+08:00",
    "R-07": "2026-10-31T18:00:00+08:00", "R-08": "2026-10-31T18:00:00+08:00",
}


def requirement(key, category, deadline=BUSINESS_DEADLINE):
    return {"key": key, "category": category, "mandatory": True, "deadline": deadline}


def acceptance_request(case_id, payload):
    return {"schema_version": "bid-training.acceptance-input.v1", "module": "M07", "case_id": case_id,
            "source_mode": "DEMO", "project_id": "DEMO-BID-001", "lot_id": "LOT-001",
            "analysis_time": ANALYSIS_TIME, "payload": payload}


BASE_REQUIREMENTS = [requirement("R-PERSON", "personnel"),
                     requirement("R-FORMAT", "format"),
                     requirement("R-PRICE", "price")]


def base_payload():
    return {"requirements": [dict(r) for r in BASE_REQUIREMENTS],
            "roles": {"personnel": "资料管理员", "format": "文档负责人"},
            "due_times": {"R-PERSON": "2026-10-30T18:00:00+08:00", "R-FORMAT": "2026-10-31T18:00:00+08:00"},
            "included_categories": ["personnel", "format"],
            "template_columns": list(STANDARD_COLUMNS)}


class AssignmentUnitTests(unittest.TestCase):
    def test_owner_and_due_time_come_from_the_configuration(self):
        rows, codes = resolve_assignments(
            [requirement("R-A", "personnel"), requirement("R-B", "format")],
            {"personnel": "资料管理员", "format": "文档负责人"},
            {"R-A": "2026-10-30T18:00:00+08:00", "R-B": "2026-10-31T18:00:00+08:00"})
        self.assertEqual(codes, [])
        self.assertEqual([r["owner_role"] for r in rows], ["资料管理员", "文档负责人"])
        self.assertEqual([r["due_time"] for r in rows],
                         ["2026-10-30T18:00:00+08:00", "2026-10-31T18:00:00+08:00"])
        self.assertEqual([r["late"] for r in rows], [False, False])

    def test_missing_owner_and_due_time_stay_unknown_not_defaulted(self):
        # 未知就留 None：不沿用固定角色，也不把"还不知道"填成当天。
        rows, codes = resolve_assignments([requirement("R-A", "personnel")], {}, {})
        self.assertEqual(codes, ["OWNER_MISSING", "DUE_TIME_MISSING"])
        self.assertIsNone(rows[0]["owner_role"])
        self.assertIsNone(rows[0]["due_time"])
        self.assertNotEqual(rows[0]["due_time"], ANALYSIS_TIME)
        self.assertNotEqual(rows[0]["due_time"], date.today().isoformat())

    def test_due_time_equal_to_deadline_is_allowed_but_later_is_blocked(self):
        on_time, ok = resolve_assignments([requirement("R-A", "personnel")],
                                          {"personnel": "资料管理员"}, {"R-A": BUSINESS_DEADLINE})
        self.assertEqual(ok, [])
        self.assertFalse(on_time[0]["late"])

        late, blocked = resolve_assignments([requirement("R-A", "personnel")],
                                            {"personnel": "资料管理员"}, {"R-A": "2026-11-01T10:00:01+08:00"})
        self.assertEqual(blocked, ["DUE_AFTER_DEADLINE"])
        self.assertTrue(late[0]["late"])

    def test_unparseable_or_timezoneless_due_time_is_invalid_not_missing(self):
        # "给错了"和"没给"必须分开：非法时间是数据错误，不能排进"还没配"的队列。
        for bad in ("明天下午", "2026-13-45T99:00:00+08:00", "2026-10-30T18:00:00", 42, True):
            rows, codes = resolve_assignments([requirement("R-A", "personnel")],
                                              {"personnel": "资料管理员"}, {"R-A": bad})
            self.assertEqual(codes, ["DUE_TIME_INVALID"], "%r 应判为非法" % (bad,))
            self.assertIsNone(rows[0]["due_time"])

    def test_due_time_is_compared_against_its_own_deadline(self):
        # 每条要求用**自己**的截止：同一天里两个不同截止必须分别判定。
        rows, codes = resolve_assignments(
            [requirement("R-EARLY", "personnel", "2026-10-20T00:00:00+08:00"),
             requirement("R-LATE", "personnel", "2026-12-01T00:00:00+08:00")],
            {"personnel": "资料管理员"},
            {"R-EARLY": "2026-10-25T00:00:00+08:00", "R-LATE": "2026-10-25T00:00:00+08:00"})
        self.assertEqual(codes, ["DUE_AFTER_DEADLINE"])
        self.assertEqual([r["late"] for r in rows], [True, False])

    def test_due_time_is_compared_as_an_absolute_moment_across_timezones(self):
        # 比较的是**绝对时刻**，不是字符串：+00:00 的 16:00 就是 +08:00 的次日 00:00，
        # 恰等于截止 → 不算超期；-04:00 的 16:30 绝对时刻已晚于截止，
        # 虽然字面上的"时分"看起来更小，也必须判超期。
        deadline = "2026-11-02T00:00:00+08:00"
        rows, codes = resolve_assignments(
            [requirement("R-SAME", "personnel", deadline),
             requirement("R-LATE", "personnel", deadline)],
            {"personnel": "资料管理员"},
            {"R-SAME": "2026-11-01T16:00:00+00:00", "R-LATE": "2026-11-01T16:30:00-04:00"})
        self.assertEqual([r["late"] for r in rows], [False, True])
        self.assertEqual(codes, ["DUE_AFTER_DEADLINE"])
        self.assertEqual(rows[0]["due_time"], "2026-11-01T16:00:00+00:00")

    def test_template_mapping_only_judged_when_supported_columns_are_declared(self):
        unmapped, codes, version = check_template_columns(STANDARD_COLUMNS, None, None)
        self.assertEqual((unmapped, codes, version), ([], [], None))

        unmapped, codes, version = check_template_columns(
            ["角色", "人员", "资格类型", "证书编号", "有效期", "原件位置"], STANDARD_COLUMNS, "1.1")
        self.assertEqual(unmapped, ["资格类型"])
        self.assertEqual(codes, ["TEMPLATE_MAPPING_REQUIRED"])
        self.assertEqual(version, "1.1")

        unmapped, codes, _ = check_template_columns(STANDARD_COLUMNS, STANDARD_COLUMNS, "1.0")
        self.assertEqual((unmapped, codes), ([], []))


class AcceptanceCaseTests(unittest.TestCase):
    """验收包 samples/acceptance/M07 的四个公开用例。"""

    def test_normal_configures_owner_and_due_time_and_splits_the_scope(self):
        result = compute_assignment(acceptance_request("normal", base_payload()))
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["issue_codes"], [])
        facts = result["facts"]
        self.assertEqual(facts["owners"], {"R-PERSON": "资料管理员", "R-FORMAT": "文档负责人"})
        self.assertEqual(facts["due_times"],
                         {"R-PERSON": "2026-10-30T18:00:00+08:00", "R-FORMAT": "2026-10-31T18:00:00+08:00"})
        self.assertEqual(facts["included"], ["R-PERSON", "R-FORMAT"])
        self.assertEqual(facts["excluded"], ["R-PRICE"])
        self.assertEqual((facts["scope_total"], facts["full_total"]), (2, 3))
        self.assertFalse(facts["full_tender_complete"])
        self.assertFalse(result["real_submission_authorized"])

    def test_review_leaves_missing_owner_and_due_time_as_null(self):
        payload = base_payload()
        payload["roles"] = {"format": "文档负责人"}   # personnel 没配角色
        payload["due_times"] = {"R-FORMAT": "2026-10-31T18:00:00+08:00"}  # R-PERSON 没定期限
        result = compute_assignment(acceptance_request("review", payload))
        self.assertEqual(result["status"], "REVIEW")
        self.assertEqual(result["issue_codes"], ["OWNER_MISSING", "DUE_TIME_MISSING"])
        self.assertIsNone(result["facts"]["owners"]["R-PERSON"])
        self.assertIsNone(result["facts"]["due_times"]["R-PERSON"])

    def test_abnormal_due_time_later_than_business_deadline_blocks(self):
        payload = base_payload()
        payload["due_times"]["R-PERSON"] = "2026-11-02T09:00:00+08:00"
        result = compute_assignment(acceptance_request("abnormal", payload))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["issue_codes"], ["DUE_AFTER_DEADLINE"])
        self.assertEqual(result["facts"]["late_requirements"], ["R-PERSON"])

    def test_change_reports_unmapped_column_instead_of_filling_by_position(self):
        payload = base_payload()
        payload["template_columns"] = ["角色", "人员", "资格类型", "证书编号", "有效期", "原件位置"]
        payload["supported_columns"] = list(STANDARD_COLUMNS)
        payload["template_version"] = "1.1"
        result = compute_assignment(acceptance_request("change", payload))
        self.assertEqual(result["status"], "REVIEW")
        self.assertEqual(result["issue_codes"], ["TEMPLATE_MAPPING_REQUIRED"])
        self.assertEqual(result["facts"]["unmapped_columns"], ["资格类型"])
        self.assertEqual(result["facts"]["template_version"], "1.1")

    def test_case_id_is_not_used_as_a_lookup_table(self):
        # 同一个 case_id 换掉全部输入，结论必须跟着输入变——锁住"没有按 case_id 查表"。
        payload = base_payload()
        payload["roles"] = {"personnel": "商务经理", "format": "文档负责人"}
        payload["due_times"] = {"R-PERSON": "2026-11-05T09:00:00+08:00", "R-FORMAT": "2026-10-31T18:00:00+08:00"}
        result = compute_assignment(acceptance_request("normal", payload))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["issue_codes"], ["DUE_AFTER_DEADLINE"])
        self.assertEqual(result["facts"]["owners"]["R-PERSON"], "商务经理")

    def test_mutated_keys_categories_dates_and_order_still_follow_the_rules(self):
        payload = {
            "requirements": [requirement("Q-9", "format", "2026-12-31T23:59:59+08:00"),
                             requirement("Q-2", "personnel", "2026-12-01T00:00:00+08:00"),
                             requirement("Q-7", "price", "2026-12-01T00:00:00+08:00"),
                             requirement("Q-5", "personnel", "2026-12-01T00:00:00+08:00")],
            "roles": {"personnel": "商务经理", "format": "文档负责人"},
            "due_times": {"Q-9": "2026-12-20T09:00:00+08:00", "Q-2": "2026-12-05T09:00:00+08:00",
                          "Q-5": "2026-11-20T09:00:00+08:00"},
            "included_categories": ["format", "personnel"],
            "template_columns": list(STANDARD_COLUMNS),
        }
        result = compute_assignment(acceptance_request("normal", payload))
        facts = result["facts"]
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["issue_codes"], ["DUE_AFTER_DEADLINE"])
        self.assertEqual(facts["late_requirements"], ["Q-2"])
        self.assertEqual(facts["included"], ["Q-9", "Q-2", "Q-5"])   # 保持输入顺序
        self.assertEqual(facts["excluded"], ["Q-7"])
        self.assertEqual((facts["scope_total"], facts["full_total"]), (3, 4))
        self.assertEqual(facts["owners"]["Q-5"], "商务经理")

    def test_missing_requirement_deadline_leaves_the_check_undecided(self):
        # 要求自己没给截止时无法判定"是否超期"，不得凭空当它不超期也不当它超期。
        payload = base_payload()
        payload["requirements"] = [{"key": "R-PERSON", "category": "personnel", "mandatory": True}]
        result = compute_assignment(acceptance_request("normal", payload))
        self.assertEqual(result["issue_codes"], [])
        self.assertEqual(result["status"], "COMPLETE")
        self.assertNotIn("late_requirements", result["facts"])


class PipelineIntegrationTests(unittest.TestCase):
    """把配置接进真实基座链：整链跑 core-normal，再注入分工配置看 M07 实际产出。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tender-m07-")
        self.base = Path(self.temp.name)
        self.source = self.base / "input"
        shutil.copytree(ROOT / "samples/e2e/core-normal", self.source)

    def tearDown(self):
        self.temp.cleanup()

    def write_assignment(self, assignment):
        (self.source / "task-assignment.json").write_text(
            json.dumps(assignment, ensure_ascii=False), encoding="utf-8")

    def generate(self, name="run"):
        target = self.base / name
        return target, run(self.source, target)

    def configured(self, **overrides):
        assignment = {"business_deadline": BUSINESS_DEADLINE,
                      "roles": dict(CORE_ROLES), "due_times": dict(CORE_DUE_TIMES)}
        assignment.update(overrides)
        return assignment

    def test_absent_config_keeps_the_baseline_behaviour(self):
        # 零回归前提：没给配置时，行为必须和改动前一模一样。
        _, values = self.generate()
        matrix = values["M07"]
        self.assertEqual(matrix["processing_status"], "COMPLETE")
        self.assertEqual(matrix["issues"], [])
        self.assertTrue(all(r["owner_role"] == "资料管理员" for r in matrix["data"]["responses"]))
        self.assertTrue(all(r["due_time"] is None for r in matrix["data"]["responses"]))
        self.assertEqual(matrix["data"]["coverage"]["scope_total"], 8)
        self.assertFalse(matrix["data"]["task_assignment"]["configured"])

    def test_config_reaches_rows_read_from_the_generated_upstream(self):
        # 真正读一次实际生成的上游：M04 的 tender_brief 由整链跑出来，M07 再去读它。
        self.write_assignment(self.configured())
        output, values = self.generate()
        matrix = values["M07"]
        self.assertEqual(matrix["processing_status"], "COMPLETE")
        self.assertEqual(matrix["issues"], [])
        rows = matrix["data"]["responses"]
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r["owner_role"] for r in rows), "每条都应有责任角色")
        self.assertTrue(all(r["due_time"] for r in rows), "每条都应有任务期限")
        self.assertEqual({r["owner_role"] for r in rows}, {"资料管理员", "文档负责人"})
        self.assertEqual(matrix["data"]["task_assignment"]["source"], "CONFIGURED")
        self.assertEqual(matrix["data"]["task_assignment"]["late_requirements"], [])
        validate_envelope(matrix)
        # 计划这一份也要落到 task_plan.json，供下游按同一矩阵读数。
        self.assertTrue((output / "task_plan.json").exists())

    def test_upstream_requirements_are_actually_read_not_hardcoded(self):
        # 改上游原文（人数 3→4）后，M07 仍能按实际读到的要求逐条派活。
        text = self.source / "tender/tender.md"
        text.write_text(text.read_text(encoding="utf-8").replace("人员不少于3名", "人员不少于4名"), encoding="utf-8")
        self.write_assignment(self.configured())
        _, values = self.generate()
        self.assertEqual(values["M04"]["data"]["personnel_rule"]["count"], 4)
        self.assertEqual(len(values["M07"]["data"]["responses"]), 8)
        self.assertTrue(all(r["due_time"] for r in values["M07"]["data"]["responses"]))

    def test_late_due_time_blocks_and_no_document_is_produced(self):
        self.write_assignment(self.configured(due_times={**CORE_DUE_TIMES, "R-01": "2026-11-02T09:00:00+08:00"}))
        output, values = self.generate()
        matrix = values["M07"]
        self.assertEqual(matrix["processing_status"], "BLOCKED")
        self.assertIn("DUE_AFTER_DEADLINE", {i["code"] for i in matrix["issues"]})
        self.assertEqual(matrix["data"]["task_assignment"]["late_requirements"], ["R-01"])
        self.assertFalse((output / "personnel-chapter.docx").exists())

    def test_missing_role_becomes_review_without_a_substitute_owner(self):
        self.write_assignment(self.configured(roles={"人员": "资料管理员", "资格": "资料管理员"}))
        _, values = self.generate()
        matrix = values["M07"]
        self.assertEqual(matrix["processing_status"], "REVIEW")
        self.assertIn("OWNER_MISSING", {i["code"] for i in matrix["issues"]})
        by_field = {}
        for row in matrix["data"]["responses"]:
            by_field.setdefault(row["owner_role"], 0)
            by_field[row["owner_role"]] += 1
        self.assertIn(None, by_field, "格式类要求没配角色，必须留成未知而不是补一个默认角色")

    def test_unknown_due_time_is_never_filled_with_the_analysis_time(self):
        self.write_assignment(self.configured(due_times={}))
        _, values = self.generate()
        matrix = values["M07"]
        self.assertEqual(matrix["processing_status"], "REVIEW")
        self.assertIn("DUE_TIME_MISSING", {i["code"] for i in matrix["issues"]})
        self.assertTrue(all(r["due_time"] is None for r in matrix["data"]["responses"]))
        self.assertNotIn(ANALYSIS_TIME, {r["due_time"] for r in matrix["data"]["responses"]})

    def test_unparseable_due_time_is_blocked_and_leaves_the_row_unknown(self):
        self.write_assignment(self.configured(due_times={**CORE_DUE_TIMES, "R-03": "下周一之前"}))
        output, values = self.generate()
        matrix = values["M07"]
        self.assertEqual(matrix["processing_status"], "BLOCKED")
        self.assertIn("DUE_TIME_INVALID", {i["code"] for i in matrix["issues"]})
        broken = next(r for r in matrix["data"]["responses"] if r["owner_role"] is None or r["due_time"] is None)
        self.assertIsNone(broken["due_time"])
        self.assertFalse((output / "personnel-chapter.docx").exists())

    def test_per_requirement_deadline_overrides_the_global_business_deadline(self):
        # 单条截止优先：给 R-01 更早的截止，R-01 就该被判超期。
        self.write_assignment(self.configured(deadlines={"R-01": "2026-10-29T00:00:00+08:00"}))
        _, values = self.generate()
        matrix = values["M07"]
        self.assertEqual(matrix["processing_status"], "BLOCKED")
        self.assertEqual(matrix["data"]["task_assignment"]["late_requirements"], ["R-01"])

    def test_changed_assignment_file_does_not_silently_reuse_an_old_release(self):
        # 配置是输入的一部分：改配置后旧放行不能继续成立。
        from fdex_tender.pipeline import release
        from fdex_tender.core import InputError

        self.write_assignment(self.configured())
        output, _ = self.generate()
        release(output, "DEMO reviewer")
        self.write_assignment(self.configured(roles={"人员": "商务经理"}))
        with self.assertRaises(InputError):
            release(output, "DEMO reviewer")

    def test_template_with_an_unmapped_extra_column_is_flagged_in_production(self):
        # 验收交接第 1 点：模板新增列且没有映射时，生产链必须明确提示适配。
        # 本用例由**当前实现**在真实生产链上跑出来（复用基座 TEMPLATE_MAPPING_UNSUPPORTED），
        # 不是只凭旧代码存在就宣称覆盖。
        manifest_path = self.source / "template-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "1.0")
        manifest["columns"] = manifest["columns"] + ["资格类型"]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output, values = self.generate()
        matrix = values["M07"]
        self.assertEqual(matrix["processing_status"], "BLOCKED")
        self.assertIn("TEMPLATE_MAPPING_UNSUPPORTED", {i["code"] for i in matrix["issues"]})
        # 映射关系本身仍完整保留，修好模板后无需重跑上游
        self.assertEqual(len(matrix["data"]["responses"]), 8)
        self.assertTrue(all(r["requirement_ids"] for r in matrix["data"]["responses"]))
        self.assertFalse((output / "personnel-chapter.docx").exists())


if __name__ == "__main__":
    unittest.main()
