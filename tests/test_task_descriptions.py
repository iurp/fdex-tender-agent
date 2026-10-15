import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from task_descriptions import task_specs, render, HEADINGS, maintenance, KIT_REF, DESCRIPTION_MARKER, START, END
from sync_task_descriptions import desired, metadata


class TaskDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.tasks, self.briefs = task_specs()

    def test_all_19_tasks_have_specific_business_materials_and_examples(self):
        self.assertEqual(len(self.tasks), 19)
        stories, examples = [], []
        for task in self.tasks:
            brief = self.briefs[task["module"]]
            self.assertGreater(len(brief["business"]), 50)
            self.assertGreaterEqual(len(brief["steps"]), 5)
            self.assertGreaterEqual(len(brief["deliverables"]), 2)
            self.assertTrue(brief["materials"])
            stories.append(brief["business"]); examples.append(brief["example"])
        self.assertEqual(len(set(stories)), 19)
        self.assertEqual(len(set(examples)), 19)

    def test_sections_read_business_first_and_technical_last(self):
        for task in self.tasks:
            doc = render(task, self.briefs[task["module"]])
            self.assertEqual(doc, (ROOT / f"docs/tasks/{task['module']}.md").read_text())
            offsets = [doc.index("## " + h) for h in HEADINGS]
            self.assertEqual(offsets, sorted(offsets))
            self.assertNotIn("公共信封", doc)
            self.assertNotIn("读取一次实际生成上游", doc)
            self.assertNotIn("文档模块必须交付实际DOCX", doc)

    def test_ready_inputs_exist_backlog_does_not_claim_complete_dataset(self):
        for task in self.tasks:
            brief = self.briefs[task["module"]]
            for _, path, _ in brief["materials"]:
                if path:
                    self.assertTrue((ROOT / path).exists(), path)
            doc = render(task, brief)
            if task["status"] == "ready":
                self.assertIn(f"--module {task['module']}", doc)
                self.assertIn("材料完整不等于功能完成", doc)
            else:
                self.assertIn("暂未开放，不要认领", doc)
                self.assertIn("维护者", doc)
                self.assertNotIn("task_acceptance.py run", doc)

    def test_m03_starts_from_files_and_does_not_require_word(self):
        task = next(t for t in self.tasks if t["module"] == "M03")
        doc = render(task, self.briefs["M03"])
        for phrase in ("至少3名", "至少4名", "内容完全相同", "本任务不生成新Word", "直接从文件列表开始", "缺件"):
            self.assertIn(phrase, doc)

    def test_task_ids_statuses_and_difficulty_are_unchanged(self):
        expected_ready = {"M03", "M04", "M06", "M07", "M08", "M09", "M12", "M13", "M14", "M18", "X01"}
        self.assertEqual({t["module"] for t in self.tasks if t["status"] == "ready"}, expected_ready)
        for task in self.tasks:
            self.assertEqual(task["id"], task["module"] + "-01")
            self.assertTrue(task["title"].startswith(f"[{task['module']}] "))
        for module in ("M03", "M07", "M18"):
            self.assertEqual(next(t["difficulty"] for t in self.tasks if t["module"] == module), "beginner")

    def test_issue_render_uses_absolute_links_and_preserves_meta(self):
        task = next(t for t in self.tasks if t["module"] == "M03")
        meta = '<!-- tender-task-meta:{"id":"M03-01","module":"M03","difficulty":"beginner"} -->'
        item = {"number": 3, "body": meta + "\n\nold owner-authored task"}
        title, body = desired(item, KIT_REF)
        self.assertTrue(body.startswith(meta))
        self.assertEqual(title, task["title"])
        self.assertIn(f"https://github.com/iurp/fdex-tender-agent/blob/{KIT_REF}/", body)
        self.assertNotIn("](../../", body)
        self.assertIn(DESCRIPTION_MARKER, body)

    def test_later_sync_preserves_external_notes_and_is_idempotent(self):
        item = {"number": 3, "body": '<!-- tender-task-meta:{"id":"M03-01","module":"M03","difficulty":"beginner"} -->\nold'}
        title, body = desired(item, KIT_REF)
        item["body"] = body + "\n用户补充：请保留这段备注。\n"
        title2, body2 = desired(item, KIT_REF)
        self.assertEqual((title2, body2), (title, item["body"]))
        self.assertEqual(body2.count(START), 1)
        self.assertEqual(body2.count(END), 1)

    def test_unknown_issue_identity_is_not_overwritten(self):
        with self.assertRaises(ValueError):
            desired({"number": 99, "body": "external issue"}, KIT_REF)
        with self.assertRaises(ValueError):
            desired({"number": 20, "body": '<!-- tender-task-meta:{"id":"KIT-01","module":"KIT","difficulty":"advanced"} -->'}, KIT_REF)
        with self.assertRaises(ValueError):
            desired({"number": 99, "body": '<!-- tender-task-meta:{"id":"M03-01","module":"M03","difficulty":"beginner"} -->'}, KIT_REF)

    def test_maintenance_and_closed_ops_are_not_student_assignments(self):
        for n in (20, 22):
            title, body = maintenance(n)
            self.assertIn(DESCRIPTION_MARKER, body)
            self.assertIn("学员", body)
            self.assertEqual([body.index("## " + h) for h in HEADINGS], sorted(body.index("## " + h) for h in HEADINGS))
        self.assertIn("已经关闭", maintenance(20)[1])
        self.assertIn("不计入学员", maintenance(20)[1])
        self.assertIn("不绕过保护分支", maintenance(22)[1])


if __name__ == "__main__":
    unittest.main()
