"""M04 source mutations and actual file handoffs, independent of teacher oracles."""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fdex_tender.core import (InputError, digest_file, load_context, read_json,
                              stable_id, validate_envelope, write_json)
from fdex_tender.modules import (read_tender, register, response_matrix, material_index,
                                 match_materials, selection_fingerprint)
from fdex_tender.pipeline import run, rerun_module
from fdex_tender.requirements import extract_requirements

ROOT = Path(__file__).resolve().parents[1]
PLAIN = (ROOT / "samples/modules/M04/plain.md").read_text(encoding="utf-8")


class M04Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="m04-")
        self.root = Path(self.temp.name)
        self.ctx = {"input_root": str(self.root), "project_id": "OTHER-PROJECT", "lot_id": "LOT-B",
                    "source_mode": "DEMO", "run_id": "TEST"}

    def tearDown(self):
        self.temp.cleanup()

    def extract(self, text=PLAIN, previous=None, name="text.md", version="1.0"):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        source = {"source_id": "SRC-DYNAMIC", "relative_path": name, "version": version, "sha256": digest_file(path)}
        return extract_requirements(self.ctx, [source], previous)

    def test_plain_twelve_requirements_have_actual_evidence_and_unknowns(self):
        value = self.extract()
        validate_envelope(value)
        self.assertEqual(value["processing_status"], "COMPLETE")
        self.assertEqual(value["data"]["personnel_rule"], {"count": 3, "qualification": "示例专业服务", "valid_on": "2026-11-01"})
        self.assertEqual(len(value["data"]["requirements"]), 12)
        self.assertFalse(value["data"]["coverage"]["full_tender_read"])
        for r in value["data"]["requirements"]:
            self.assertIsNone(r["score"])
            self.assertIsNone(r["disqualifying"])
            ref = r["evidence_refs"][0]
            self.assertEqual(ref["quote"], PLAIN.splitlines()[ref["locator"]["line"] - 1])
            self.assertEqual(ref["relative_path"], "text.md")

    def test_values_are_extracted_instead_of_copied(self):
        text = PLAIN.replace("3名", "7名").replace("2026-11-01", "2027-03-15").replace("示例专业服务", "另一专业")
        value = self.extract(text)
        self.assertEqual(value["data"]["personnel_rule"], {"count": 7, "qualification": "另一专业", "valid_on": "2027-03-15"})

    def test_chinese_numbers_and_paraphrase_keep_identity(self):
        before = self.extract()
        after = self.extract(PLAIN.replace("人员不少于3名", "人员至少五人"), before, version="1.1")
        self.assertEqual(after["data"]["personnel_rule"]["count"], 5)
        self.assertEqual(before["data"]["requirements"][0]["requirement_id"], after["data"]["requirements"][0]["requirement_id"])
        self.assertEqual([m["change"] for m in after["data"]["version_mapping"]].count("CHANGED"), 1)

    def test_bare_count_synonyms_are_not_skipped(self):
        for text in ("人员不低于6人。", "人员等于六名。", "人员至多十人。"):
            with self.subTest(text=text):
                value = self.extract(text)
                self.assertEqual(len(value["data"]["requirements"]), 1)
                self.assertEqual(value["data"]["requirements"][0]["semantic_kind"], "personnel_count")

    def test_number_change_has_history_and_other_ids_stay_stable(self):
        before = self.extract()
        after = self.extract(PLAIN.replace("3名", "4名"), before, name="revision.md", version="1.1")
        self.assertEqual({r["requirement_id"] for r in before["data"]["requirements"]}, {r["requirement_id"] for r in after["data"]["requirements"]})
        changed = [m for m in after["data"]["version_mapping"] if m["change"] == "CHANGED"]
        self.assertEqual(len(changed), 1)
        self.assertNotEqual(changed[0]["previous_revision_id"], changed[0]["revision_id"])
        self.assertEqual(changed[0]["previous_version"], "1.0")
        self.assertIn("3名", changed[0]["previous_evidence_refs"][0]["quote"])
        self.assertIn("4名", changed[0]["evidence_refs"][0]["quote"])

    def test_reorder_and_blank_lines_do_not_change_ids(self):
        before = self.extract()
        after = self.extract("\n\n" + "\n".join(reversed(PLAIN.splitlines()[3:])), before)
        self.assertEqual({r["requirement_id"] for r in before["data"]["requirements"]}, {r["requirement_id"] for r in after["data"]["requirements"]})
        self.assertTrue(all(m["change"] == "UNCHANGED" for m in after["data"]["version_mapping"]))

    def test_conflicting_counts_keep_both_quotes_and_no_effective_value(self):
        value = self.extract(PLAIN + "\n补充要求：人员人数恰为2名，上述要求保留。\n")
        self.assertEqual(value["processing_status"], "REVIEW")
        self.assertIsNone(value["data"]["personnel_rule"]["count"])
        conflict = next(i for i in value["issues"] if i["code"] == "CLAUSE_CONFLICT")
        self.assertEqual(len(conflict["evidence_refs"]), 2)
        self.assertEqual(value["data"]["conflicts"][0]["values"], [3, 2])
        self.assertEqual(len(value["data"]["requirements"]), 13)

    def test_compatible_bounds_are_not_a_conflict(self):
        value = self.extract(PLAIN + "\n人员不超过5名。\n")
        self.assertEqual(value["processing_status"], "COMPLETE")
        self.assertEqual(value["data"]["personnel_rule"]["count"], 3)

    def test_conflicting_bounds_on_one_line_are_all_checked(self):
        value = self.extract(PLAIN.replace("人员不少于3名", "人员不少于3名且人员不超过2名"))
        self.assertIsNone(value["data"]["personnel_rule"]["count"])
        self.assertEqual(value["data"]["conflicts"][0]["values"], [3, 2])
        self.assertEqual(value["processing_status"], "REVIEW")

    def test_conflicting_qualification_is_not_last_value_wins(self):
        value = self.extract(PLAIN + "\n每名人员必须持有其他专业证书。\n")
        self.assertIsNone(value["data"]["personnel_rule"]["qualification"])
        self.assertTrue(any(i["code"] == "CLAUSE_CONFLICT" for i in value["issues"]))

    def test_repeated_identical_clause_merges_evidence(self):
        value = self.extract(PLAIN + "\n" + PLAIN.splitlines()[3])
        self.assertEqual(len(value["data"]["requirements"]), 12)
        self.assertEqual(len(value["data"]["requirements"][0]["evidence_refs"]), 2)

    def test_ambiguous_same_role_has_distinct_ids_and_review(self):
        value = self.extract(PLAIN + "\n人员不少于4名，人员表必须列出姓名和本次职责。\n")
        self.assertEqual(value["processing_status"], "REVIEW")
        identities = [r["requirement_id"] for r in value["data"]["requirements"]]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertTrue(any(i["code"] == "AMBIGUOUS_REQUIREMENT_IDENTITY" for i in value["issues"]))

    def test_explicit_score_and_disqualification_only_when_supported(self):
        text = PLAIN.replace("全本评分包括服务方案；本节选未公布分值，不得补造分数。", "服务方案评分为10分。")
        text = text.replace("每名所选人员必须持有示例专业服务证书。", "每名所选人员必须持有示例专业服务证书，否则否决。")
        value = self.extract(text)
        self.assertEqual(next(r["score"] for r in value["data"]["requirements"] if r["semantic_kind"] == "scoring"), 10)
        self.assertTrue(next(r["disqualifying"] for r in value["data"]["requirements"] if r["semantic_kind"] == "qualification"))

    def test_unknown_obligation_is_preserved_for_review(self):
        value = self.extract(PLAIN + "\n必须提交数据保密承诺书。\n")
        self.assertEqual(value["processing_status"], "REVIEW")
        self.assertEqual(value["data"]["requirements"][-1]["category"], "未知")

    def test_invalid_date_stays_unknown(self):
        value = self.extract(PLAIN.replace("2026-11-01", "2026-99-99"))
        self.assertIsNone(value["data"]["personnel_rule"]["valid_on"])
        self.assertEqual(value["processing_status"], "REVIEW")

    def test_expiration_is_not_a_checking_reference_date(self):
        value = self.extract(PLAIN.replace("证书有效期以2026-11-01为基准，必须仍在有效期内。", "证书有效期必须到2027-06-30。"))
        self.assertIsNone(value["data"]["personnel_rule"]["valid_on"])
        self.assertEqual(value["processing_status"], "REVIEW")

    def test_unreadable_and_no_body_are_blocked(self):
        for text in ("# 文件节选\n[正文读取失败]", "", "# 文件\n项目编号 DEMO-ONLY"):
            with self.subTest(text=text):
                value = self.extract(text)
                self.assertEqual(value["processing_status"], "BLOCKED")
                self.assertEqual(value["data"]["requirements"], [])
                self.assertIn("BODY_UNREADABLE", [i["code"] for i in value["issues"]])

    def test_invalid_utf8_is_blocked(self):
        path = self.root / "binary.md"
        path.write_bytes(b"\xff\xfe\x00\x01")
        value = extract_requirements(self.ctx, [{"source_id": "SRC", "relative_path": path.name, "version": "1", "sha256": digest_file(path)}])
        self.assertEqual(value["processing_status"], "BLOCKED")

    def test_path_escape_hash_drift_and_real_mode_are_rejected(self):
        self.extract()
        src = {"source_id": "SRC", "relative_path": "../outside.md", "version": "1", "sha256": "0" * 64}
        with self.assertRaises(InputError):
            extract_requirements(self.ctx, [src])
        with self.assertRaises(InputError):
            extract_requirements(self.ctx, [{**src, "relative_path": "text.md"}])
        with self.assertRaises(InputError):
            extract_requirements({**self.ctx, "source_mode": "REAL"}, [])

    def test_cross_project_previous_output_is_rejected(self):
        previous = self.extract()
        previous["project_id"] = "UNRELATED"
        with self.assertRaises(InputError):
            self.extract(previous=previous)

    def test_two_sentences_on_one_line_retain_full_line_evidence(self):
        raw = "人员不少于3名。每名所选人员必须持有示例专业服务证书。"
        value = self.extract(raw)
        self.assertEqual(len(value["data"]["requirements"]), 2)
        self.assertTrue(all(r["evidence_refs"][0]["quote"] == raw for r in value["data"]["requirements"]))

    def test_labelled_and_plain_clauses_can_coexist(self):
        text = PLAIN.replace("人员不少于3名", "[R-01][人员] 人员不少于3名", 1)
        value = self.extract(text)
        self.assertEqual(len(value["data"]["requirements"]), 12)
        self.assertEqual(value["data"]["requirements"][0]["requirement_id"], stable_id("REQ", self.ctx["project_id"], self.ctx["lot_id"], "R-01"))

    def test_actual_m03_file_handoff_and_m07_table_mapping(self):
        source = self.root / "input"
        shutil.copytree(ROOT / "samples/e2e/core-normal", source)
        (source / "tender/tender.md").write_text(PLAIN, encoding="utf-8")
        upstream = self.root / "upstream"
        run(source, upstream, stop="M03")
        values = rerun_module("M04", upstream, self.root / "m04-rerun")
        self.assertEqual(values["M04"]["input_refs"], read_json(upstream / "source_manifest.json")["input_refs"][:1])
        ctx = read_json(self.root / "m04-rerun/.context.json")
        matrix = response_matrix(ctx, values["M04"])
        self.assertEqual(matrix["data"]["coverage"]["scope_total"], 8)
        self.assertEqual([r["field_id"] for r in matrix["data"]["responses"][:4]], ["PERSONNEL-TABLE"] * 4)

    def test_exact_count_cannot_approve_too_many_selected_people(self):
        source = self.root / "input"
        shutil.copytree(ROOT / "samples/e2e/core-normal", source)
        (source / "tender/tender.md").write_text(PLAIN.replace("不少于3名", "恰为2名"), encoding="utf-8")
        ctx = load_context(source, "TEST")
        registered = register(ctx)
        tender = read_tender(ctx, registered)
        matrix = response_matrix(ctx, tender)
        index = material_index(ctx, registered)
        record = read_json(source / "selection.json")
        # Synthetic test confirmation bound to this exact input, still 3 people.
        record["target_digest"] = selection_fingerprint(ctx, tender, index, record["person_ids"], record["roles"])
        write_json(source / "selection.json", record)
        matched = match_materials(ctx, tender, matrix, index)
        self.assertEqual(matched["data"]["selected"], [])
        self.assertIn("SELECTION_INVALID", [i["code"] for i in matched["issues"]])

    def test_new_count_operator_invalidates_prior_confirmation(self):
        source = self.root / "input"
        shutil.copytree(ROOT / "samples/e2e/core-normal", source)
        (source / "tender/tender.md").write_text(PLAIN.replace("不少于3名", "恰为3名"), encoding="utf-8")
        ctx = load_context(source, "TEST")
        registered = register(ctx)
        tender = read_tender(ctx, registered)
        matched = match_materials(ctx, tender, response_matrix(ctx, tender), material_index(ctx, registered))
        self.assertEqual(matched["data"]["confirmation"]["status"], "STALE")
        self.assertEqual(matched["data"]["selected"], [])

    def test_acceptance_adapter_does_not_read_oracles_or_branch_on_case_id(self):
        spec = importlib.util.spec_from_file_location("adapter_m04", ROOT / "adapters/m04.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        (self.root / "source.md").write_text(PLAIN, encoding="utf-8")
        request = {"module": "M04", "source_mode": "DEMO", "case_id": "arbitrary-name", "project_id": "P", "lot_id": "L",
                   "payload": {"document": "source.md", "source_id": "SRC", "coverage": "excerpt_only"}}
        write_json(self.root / "input.json", request)
        write_json(self.root / "case.json", {"inputs": [{"path": "input.json"}, {"path": "source.md"}]})
        write_json(self.root / "expected.json", {"trap": "never read"})
        original = Path.read_text

        def guard(path, *args, **kwargs):
            self.assertNotEqual(path.name, "expected.json")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", guard):
            result = adapter.run_adapter(self.root / "input.json", self.root / "result", self.root)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["facts"]["requirement_count"], 12)
        self.assertEqual(result["input_hashes"]["source.md"], digest_file(self.root / "source.md"))
        self.assertEqual(result["case_id"], "arbitrary-name")


if __name__ == "__main__":
    unittest.main()
