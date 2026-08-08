"""Unit tests for business/transport format rendering."""

import tempfile
import unittest
from pathlib import Path

from scripts.format_renderer import (
    business_format,
    load_template,
    render_export,
    render_project_brief_markdown,
    wrap_xml,
)


SCRIPT = """第1集：系统绑错人

1-1 谢家书房 夜 内
人物：叶聆、谢淮舟、996

△谢淮舟将离婚协议放到叶聆面前。
谢淮舟（冷淡）：录完节目，我们离婚。
"""


class FormatRendererTests(unittest.TestCase):
    def test_business_format_unwraps_xml(self):
        xml = wrap_xml(SCRIPT, "EP001")
        self.assertEqual(business_format(xml, "legacy-scriptitem").strip(), SCRIPT.strip())

    def test_wrap_xml_roundtrip(self):
        xml = wrap_xml(SCRIPT, "EP001")
        self.assertIn("<scriptItem name=\"EP001\">", xml)
        self.assertIn("</scriptItem>", xml)

    def test_render_export_merges_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            out = render_export(project_dir, [(1, SCRIPT), (2, SCRIPT.replace("第1集", "第2集").replace("1-1", "2-1"))])
            self.assertIn("第1集", out)
            self.assertIn("第2集", out)
            with self.assertRaises(ValueError):
                render_export(project_dir, [(1, "没有分集标识的文本")])

    def test_render_export_xml_wrapper_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = render_export(Path(tmp), [(1, SCRIPT)], xml=True)
            self.assertIn("<scriptItem name=\"EP001\">", out)

    def test_templates_exist(self):
        self.assertIn("第1集", load_template("default-cn.txt"))
        self.assertIn("scriptItem", load_template("legacy-scriptitem.txt"))

    def test_project_brief_markdown(self):
        md = render_project_brief_markdown(
            {"drama_name": "测试剧", "novel_name": "测试书", "genre": ["喜剧"], "platform": "竖屏", "writer_has_final_authority": True}
        )
        self.assertIn("# 项目需求：测试剧", md)
        self.assertIn("编剧最终决定权：是", md)


if __name__ == "__main__":
    unittest.main()

