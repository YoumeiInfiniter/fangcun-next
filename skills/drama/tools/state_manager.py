"""fangcun-drama 状态管理器：跟踪 pipeline 进度，支持断点续传。"""

import json
import os
import tempfile
from pathlib import Path
from datetime import datetime


class StateManager:
    """管理 fangcun-drama pipeline 的持久化状态。"""

    PHASE_ORDER = ["event", "skeleton", "skeleton_review", "adaptation", "adaptation_review", "script", "export"]

    def __init__(self, output_dir):
        self.state_path = Path(output_dir) / "state.json"
        self._state = None

    def _now(self):
        return datetime.now().isoformat(timespec="seconds")

    def load(self):
        if self.state_path.exists():
            try:
                self._state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._state = None
        if self._state is None:
            self._state = {
                "version": 1,
                "created": self._now(),
                "updated": self._now(),
                "phases": {},
                "episodes": {},
                "script_batches": {
                    "current": None,
                    "confirmed": [],
                },
                "human_reviews": {
                    "pending": None,
                    "confirmed": [],
                },
            }
        self._state.setdefault("script_batches", {"current": None, "confirmed": []})
        self._state["script_batches"].setdefault("confirmed", [])
        if "current" not in self._state["script_batches"]:
            self._state["script_batches"]["current"] = None
        self._state.setdefault("human_reviews", {"pending": None, "confirmed": []})
        self._state["human_reviews"].setdefault("confirmed", [])
        if "pending" not in self._state["human_reviews"]:
            self._state["human_reviews"]["pending"] = None
        return self._state

    def save(self):
        if self._state is None:
            return
        self._state["updated"] = self._now()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.state_path, self._state)

    @property
    def state(self):
        if self._state is None:
            self.load()
        return self._state

    # ─── Phase 管理 ───

    def phase_start(self, phase_name):
        self.state["phases"][phase_name] = {
            "status": "running",
            "started": self._now(),
        }
        self.save()

    def phase_done(self, phase_name, extra=None):
        entry = self.state["phases"].get(phase_name, {})
        entry["status"] = "done"
        entry["finished"] = self._now()
        if extra:
            entry.update(extra)
        self.state["phases"][phase_name] = entry
        self.save()

    def phase_failed(self, phase_name, error=""):
        entry = self.state["phases"].get(phase_name, {})
        entry["status"] = "failed"
        entry["finished"] = self._now()
        entry["error"] = str(error)
        self.state["phases"][phase_name] = entry
        self.save()

    def is_phase_done(self, phase_name):
        return self.state["phases"].get(phase_name, {}).get("status") == "done"

    def get_resume_phase(self):
        """找到第一个未完成的 phase，用于断点续传。"""
        if self.has_pending_human_review():
            return "human_review_confirmation"
        if self.has_pending_script_confirmation():
            return "script_confirmation"
        for phase in self.PHASE_ORDER:
            status = self.state["phases"].get(phase, {}).get("status", "pending")
            if status != "done":
                return phase
        return None

    # ─── Episode 管理 ───

    def episode_completed(self, ep_num, chars=0):
        self.state["episodes"][str(ep_num)] = {
            "status": "completed",
            "chars": chars,
            "timestamp": self._now(),
        }

    def episode_failed(self, ep_num, error=""):
        self.state["episodes"][str(ep_num)] = {
            "status": "failed",
            "error": str(error),
            "timestamp": self._now(),
        }

    def is_episode_done(self, ep_num):
        return self.state["episodes"].get(str(ep_num), {}).get("status") == "completed"

    def get_completed_episodes(self):
        return sorted(
            int(k) for k, v in self.state["episodes"].items()
            if v.get("status") == "completed"
        )

    def get_failed_episodes(self):
        return sorted(
            int(k) for k, v in self.state["episodes"].items()
            if v.get("status") == "failed"
        )

    # ─── Human Review Gate 管理 ───

    def mark_human_review_required(self, target, report_path, unlock_phase):
        reviews = self.state.setdefault("human_reviews", {"pending": None, "confirmed": []})
        reviews.setdefault("confirmed", [])
        reviews["pending"] = {
            "target": str(target),
            "report_path": str(report_path),
            "unlock_phase": str(unlock_phase),
            "status": "waiting_human_review",
            "created": self._now(),
        }
        self.save()

    def get_pending_human_review(self):
        reviews = self.state.setdefault("human_reviews", {"pending": None, "confirmed": []})
        reviews.setdefault("confirmed", [])
        if "pending" not in reviews:
            reviews["pending"] = None
        return reviews.get("pending")

    def has_pending_human_review(self):
        return bool(self.get_pending_human_review())

    def confirm_human_review(self, target, decision="approved", notes=""):
        pending = self.get_pending_human_review()
        if not pending:
            return False
        if pending.get("target") != str(target):
            return False
        pending["status"] = "confirmed"
        pending["decision"] = str(decision)
        pending["notes"] = str(notes)
        pending["confirmed"] = self._now()
        reviews = self.state.setdefault("human_reviews", {"pending": None, "confirmed": []})
        reviews.setdefault("confirmed", []).append(pending)
        reviews["pending"] = None
        self.save()
        return True

    # ─── Script Batch 管理 ───

    def start_script_batch(self, batch_id, episodes):
        self.state["script_batches"]["current"] = {
            "batch_id": batch_id,
            "episodes": list(episodes),
            "episode_reviews": {},
            "rewrite_attempts": {},
            "awaiting_confirmation": False,
            "batch_summary_path": "",
            "started": self._now(),
        }
        self.save()

    def set_episode_review(self, episode_num, verdict, blocked, severe_count):
        current = self.get_pending_script_batch()
        if current is None:
            return
        current["episode_reviews"][str(episode_num)] = {
            "verdict": verdict,
            "blocked": bool(blocked),
            "severe_count": int(severe_count),
            "timestamp": self._now(),
        }
        self.save()

    def mark_episode_rewrite_attempt(self, episode_num):
        current = self.get_pending_script_batch()
        if current is None:
            return 0
        key = str(episode_num)
        attempts = current.setdefault("rewrite_attempts", {})
        attempts[key] = int(attempts.get(key, 0)) + 1
        self.save()
        return attempts[key]

    def mark_batch_waiting_confirmation(self, batch_summary_path):
        current = self.get_pending_script_batch()
        if current is None:
            return
        current["awaiting_confirmation"] = True
        current["batch_summary_path"] = str(batch_summary_path)
        current["finished"] = self._now()
        self.save()

    def confirm_script_batch(self, promoted_paths):
        """Legacy name: internally promote the current reviewed draft batch.

        This is NOT user confirmation. Keep the historical `confirmed` field for
        backward compatibility, but write explicit promotion/user-confirmation
        fields so final delivery gates can distinguish the two states.
        """
        current = self.get_pending_script_batch()
        if current is None:
            return
        now = self._now()
        current["confirmed"] = now  # legacy: internal promotion timestamp
        current["promoted"] = now
        current["internal_promoted"] = True
        current["user_confirmed"] = False
        current["confirmation_note"] = "Internal draft promotion only; waiting for user confirmation."
        current["promoted_paths"] = list(promoted_paths)
        self.state["script_batches"]["confirmed"].append(current)
        self.state["script_batches"]["current"] = None
        self.save()

    def confirm_latest_script_batch_by_user(self, message_id: str = "", notes: str = ""):
        batches = self.state.setdefault("script_batches", {"current": None, "confirmed": []}).setdefault("confirmed", [])
        if not batches:
            return None
        batch = batches[-1]
        now = self._now()
        batch["user_confirmed"] = True
        batch["user_confirmed_at"] = now
        if message_id:
            batch["user_confirmed_message_id"] = message_id
        if notes:
            batch["user_confirmation_notes"] = notes
        batch["awaiting_confirmation"] = False
        self.save()
        return batch

    def mark_project_finished_by_user(self, message_id: str = "", finish_text: str = "", notes: str = ""):
        """Record explicit project-finished intent.

        Script batch confirmation only means the delivered episodes are accepted.
        The project is finished only when the user explicitly says one of the
        configured finish phrases (剧本完结/剧本结束/项目结束).
        """
        finished = self.state.setdefault("project_finished", {})
        now = self._now()
        finished.update({
            "status": "confirmed",
            "user_confirmed": True,
            "user_confirmed_at": now,
            "finish_text": str(finish_text or ""),
        })
        if message_id:
            finished["user_confirmed_message_id"] = message_id
        if notes:
            finished["notes"] = str(notes)
        self.save()
        return finished

    def get_pending_script_batch(self):
        batches = self.state.setdefault("script_batches", {"current": None, "confirmed": []})
        batches.setdefault("confirmed", [])
        if "current" not in batches:
            batches["current"] = None
        return batches.get("current")

    def has_pending_script_confirmation(self):
        current = self.get_pending_script_batch()
        return bool(current and current.get("awaiting_confirmation"))

    # ─── 状态摘要 ───

    def summary(self):
        s = self.state
        phases = {k: v.get("status", "?") for k, v in s.get("phases", {}).items()}
        completed = len(self.get_completed_episodes())
        failed = len(self.get_failed_episodes())
        return f"phases={phases} episodes={completed}ok/{failed}fail"

    def print_status(self):
        print(f"\n项目状态:")
        print(f"  状态文件: {self.state_path}")
        for phase, info in self.state.get("phases", {}).items():
            status = info.get("status", "?")
            extra = ""
            if "completed" in info:
                extra = f" ({info['completed']}章)"
            if "error" in info:
                extra = f" (错误: {info['error'][:50]})"
            print(f"  {phase}: {status}{extra}")
        human_review = self.get_pending_human_review()
        if human_review:
            print(f"  human review confirmation: {human_review['target']} -> {human_review['unlock_phase']} pending")
            print(f"    report: {human_review.get('report_path', '')}")
        pending = self.get_pending_script_batch()
        if pending:
            print(f"  草稿批次: {pending['batch_id']} awaiting_confirmation={pending.get('awaiting_confirmation')}")
        completed = self.get_completed_episodes()
        failed = self.get_failed_episodes()
        if completed or failed:
            print(f"  剧本: {len(completed)} 完成, {len(failed)} 失败")
            if failed:
                print(f"  失败集数: {failed}")


def _atomic_write_json(path, data):
    """原子写入 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".state_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path, data):
    """原子写入 JSON（公开别名）。"""
    _atomic_write_json(path, data)


def atomic_write_text(path, text):
    """原子写入文本文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=".write_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
