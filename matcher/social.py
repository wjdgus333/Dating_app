"""좋아요 · 매칭 · 채팅 저장소 (JSON 파일).

규칙
  - 좋아요는 누구에게나 보낼 수 있다 (한마디 메시지를 함께 보낼 수 있음).
  - 서로 좋아요를 누르면 '매칭' → 그때부터 채팅 가능.
  - 매칭되지 않은 사람에게는 메시지를 보낼 수 없다 (원치 않는 메시지 방지).
  - 차단하면 매칭·채팅이 끊기고 추천에서도 빠진다 (차단 목록은 Preferences.blocked_ids).
"""

import threading
from datetime import datetime
from pathlib import Path

from . import persist

SAMPLE_PATH = persist.PROJECT_DATA / "sample_social.json"
DB_PATH = persist.data_dir() / "social.json"

MAX_MESSAGE = 500


class SocialError(ValueError):
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _pair(a: int, b: int) -> str:
    return f"{min(a, b)}-{max(a, b)}"


class SocialStore:
    def __init__(self, path: Path | None = None):
        self.path = path or DB_PATH
        self._lock = threading.Lock()
        persist.ensure_file(self.path, SAMPLE_PATH)  # 없을 때만 샘플로 시작
        persist.backup(self.path, "start")
        self._data = persist.read_json(self.path)
        # 예전 버전 파일에 없는 칸이 있어도 멈추지 않게
        self._data.setdefault("likes", [])
        self._data.setdefault("messages", {})

    def _save(self) -> None:
        persist.write_json(self.path, self._data)

    def reset(self) -> Path | None:
        with self._lock:
            kept = persist.backup(self.path, "before-reset")
            self._data = persist.read_json(SAMPLE_PATH)
            self._save()
            return kept

    # ── 좋아요 ───────────────────────────────────────────
    def _like(self, from_id: int, to_id: int) -> dict | None:
        return next((l for l in self._data["likes"] if l["from"] == from_id and l["to"] == to_id), None)

    def is_match(self, a: int, b: int) -> bool:
        return self._like(a, b) is not None and self._like(b, a) is not None

    def like(self, from_id: int, to_id: int, message: str = "") -> dict:
        if from_id == to_id:
            raise SocialError("자기 자신에게는 좋아요를 보낼 수 없어요.")
        message = message.strip()[:MAX_MESSAGE]
        with self._lock:
            if self._like(from_id, to_id):
                raise SocialError("이미 좋아요를 보냈어요.")
            self._data["likes"].append({"from": from_id, "to": to_id, "message": message, "at": _now()})
            matched = self.is_match(from_id, to_id)
            if matched:
                # 매칭되면 서로 보낸 한마디를 채팅방 첫 메시지로 옮긴다.
                for l in sorted((self._like(to_id, from_id), self._like(from_id, to_id)), key=lambda x: x["at"]):
                    if l["message"]:
                        self._add_message(l["from"], l["to"], l["message"], at=l["at"])
            self._save()
        return {"matched": matched}

    def likes_of(self, user_id: int) -> dict:
        sent = [l for l in self._data["likes"] if l["from"] == user_id]
        received = [l for l in self._data["likes"] if l["to"] == user_id]
        return {
            "sent": [l["to"] for l in sent],
            # 아직 내가 응답하지 않은 받은 좋아요
            "received": [l for l in received if not self._like(user_id, l["from"])],
        }

    def matches_of(self, user_id: int) -> list[int]:
        return [l["to"] for l in self._data["likes"] if l["from"] == user_id and self._like(l["to"], user_id)]

    # ── 채팅 ─────────────────────────────────────────────
    def _add_message(self, sender: int, receiver: int, text: str, at: str | None = None) -> dict:
        msg = {"from": sender, "to": receiver, "text": text, "at": at or _now(), "read": False}
        self._data["messages"].setdefault(_pair(sender, receiver), []).append(msg)
        return msg

    def send(self, sender: int, receiver: int, text: str) -> dict:
        text = text.strip()
        if not text:
            raise SocialError("메시지를 입력해 주세요.")
        if len(text) > MAX_MESSAGE:
            raise SocialError(f"메시지는 {MAX_MESSAGE}자까지 보낼 수 있어요.")
        with self._lock:
            if not self.is_match(sender, receiver):
                raise SocialError("서로 좋아요를 눌러 매칭된 사람에게만 메시지를 보낼 수 있어요.")
            msg = self._add_message(sender, receiver, text)
            self._save()
        return msg

    def messages(self, viewer: int, other: int) -> list[dict]:
        if not self.is_match(viewer, other):
            raise SocialError("매칭된 사람과의 대화만 볼 수 있어요.")
        with self._lock:
            msgs = self._data["messages"].get(_pair(viewer, other), [])
            changed = False
            for m in msgs:
                if m["to"] == viewer and not m["read"]:
                    m["read"] = True
                    changed = True
            if changed:
                self._save()
            return list(msgs)

    def last_message(self, a: int, b: int) -> dict | None:
        msgs = self._data["messages"].get(_pair(a, b), [])
        return msgs[-1] if msgs else None

    def unread_count(self, viewer: int, other: int) -> int:
        return sum(1 for m in self._data["messages"].get(_pair(viewer, other), []) if m["to"] == viewer and not m["read"])

    # ── 차단 ─────────────────────────────────────────────
    def unmatch(self, a: int, b: int) -> None:
        """차단 시 좋아요·대화를 지운다."""
        with self._lock:
            self._data["likes"] = [
                l for l in self._data["likes"] if not ({l["from"], l["to"]} == {a, b})
            ]
            self._data["messages"].pop(_pair(a, b), None)
            self._save()
