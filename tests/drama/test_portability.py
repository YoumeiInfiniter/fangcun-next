import re
import unittest
from pathlib import Path


FANGCUN_ROOT = Path(__file__).resolve().parents[2]
OPENCLAW_ROOT = r"/root/" + r"\.openclaw/"
HARDCODED_OPENCLAW_PATH = re.compile(
    OPENCLAW_ROOT + r"(?:workspaces|agents)|openclaw/" + r"workspaces|openclaw/" + r"agents"
)


class PortabilityTests(unittest.TestCase):
    def test_runtime_files_do_not_hardcode_openclaw_workspace_layouts(self):
        """Fangcun must run on claw2/4/5 workspaces and claw3 agent workspaces.

        Runtime code, prompts, tests, and tools should derive paths from cwd,
        --config, or __file__, not from a fixed OpenClaw generation layout.
        SKILL.md is the only allowed exception because it documents the rule.
        """
        violations = []
        for path in FANGCUN_ROOT.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.relative_to(FANGCUN_ROOT).as_posix() == "SKILL.md":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if HARDCODED_OPENCLAW_PATH.search(line):
                    violations.append(f"{path.relative_to(FANGCUN_ROOT)}:{line_no}:{line}")

        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
