import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from feishu_project_executor import (
    build_script_summary_content,
    validate_script_summary_content,
    validate_script_summary_latest_batches,
)


class ScriptSummaryGuardrailsTest(unittest.TestCase):
    def test_builds_summary_from_batch_body_not_links(self):
        manifest = {
            "project_title": "酒席见人心",
            "steps": [
                {
                    "doc_kind": "script_batch",
                    "start_episode": 1,
                    "end_episode": 2,
                    "content": "EP001：开席\n1-1　酒店大厅　日　内\n△张三推开门。\n张三（冷笑）：开席。\n\nEP002：翻桌\n2-1　包厢　夜　内\n△李四摔下筷子。\n李四（压火）：别装了。",
                },
                {
                    "doc_kind": "script_batch",
                    "start_episode": 3,
                    "end_episode": 3,
                    "content": "EP003：散席\n3-1　酒店门口　夜　外\n△雨水砸在红毯上。\n王五（低声）：结束了。",
                },
            ],
        }
        content = build_script_summary_content(manifest)
        self.assertIn("剧本汇总 EP001-EP003", content)
        self.assertIn("## EP001-EP002", content)
        self.assertIn("EP003：散席", content)
        self.assertFalse(validate_script_summary_content(content), content)

    def test_rejects_link_only_script_summary(self):
        bad = """# 《酒席见人心》剧本汇总 V2
当前推荐剧本批次
EP001-006 V3｜剧本EP001-006
https://m9cfu49348.feishu.cn/wiki/Nx7hw3QLmi9WUVkUa0ZcfMg8ndd
EP006-010 V3｜剧本EP006-010
https://m9cfu49348.feishu.cn/wiki/C52qwYlEkidpwLkUFhLc9TaUnVh
"""
        issues = validate_script_summary_content(bad)
        self.assertTrue(any("batch 链接" in i or "链接目录" in i for i in issues), issues)

    def test_rejects_summary_missing_known_active_batch(self):
        manifest = {
            "steps": [
                {"doc_kind": "script_batch", "start_episode": 1, "end_episode": 5, "content": "EP001：开席\n1-1　酒店　日　内\n△张三进门。\n张三（冷）：开始。"},
            ]
        }
        docs = {
            "script_batch:EP001-005": {"active_version": "V2", "versions": [{"version": "V2", "doc_kind": "script_batch"}]},
            "script_batch:EP006-010": {"active_version": "V3", "versions": [{"version": "V3", "doc_kind": "script_batch"}]},
        }
        issues = validate_script_summary_latest_batches(manifest, docs)
        self.assertTrue(any("缺少已登记最新批次正文" in i and "EP006-010" in i for i in issues), issues)

    def test_accepts_summary_when_all_active_batches_are_in_manifest(self):
        manifest = {
            "steps": [
                {"doc_kind": "script_batch", "start_episode": 1, "end_episode": 5, "content": "EP001：开席\n1-1　酒店　日　内\n△张三进门。\n张三（冷）：开始。"},
                {"doc_kind": "script_batch", "start_episode": 6, "end_episode": 10, "content": "EP006：翻桌\n6-1　包厢　夜　内\n△李四拍桌。\n李四（怒）：够了。"},
            ]
        }
        docs = {
            "script_batch:EP001-005": {"active_version": "V2", "versions": [{"version": "V2", "doc_kind": "script_batch"}]},
            "script_batch:EP006-010": {"active_version": "V3", "versions": [{"version": "V3", "doc_kind": "script_batch"}]},
        }
        self.assertFalse(validate_script_summary_latest_batches(manifest, docs))


if __name__ == "__main__":
    unittest.main()
