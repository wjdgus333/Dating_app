"""프로필 저장소 (JSON 파일).

데이터를 잃지 않기 위한 원칙
  1. 데이터 파일(profiles.json)이 없을 때만 샘플(가상 프로필 20명)로 시작한다. 있으면 절대 덮어쓰지 않는다.
  2. 코드가 바뀌어 예전 데이터와 맞지 않는 값이 생겨도(선택지·점수 항목 삭제 등) 서버가 멈추지 않는다.
     맞지 않는 값만 정리하고 프로필(이름·나이·직업 같은 큰 틀)은 그대로 둔다. 정리하기 전에 원본을 백업한다.
  3. 필수 항목이 깨져서 도저히 읽을 수 없는 프로필은 지우지 않고 profiles_보류.json 으로 옮겨 둔다.
  4. 저장은 안전 저장(persist.write_json), 초기화 전에는 자동 백업.

나중에 DB(PostgreSQL 등)로 바꾸려면 이 파일만 교체하면 된다.
"""

import copy
import threading
from pathlib import Path

from pydantic import ValidationError

from . import config as C
from . import persist
from .models import Preferences, Profile, ProfileCreate

SAMPLE_PATH = persist.PROJECT_DATA / "sample_profiles.json"
DB_PATH = persist.data_dir() / "profiles.json"

REQUIRED = {"id", "name", "gender", "education", "occupation", "age", "city"}


def _presanitize(data: dict) -> list[str]:
    """목록 전체가 한 번에 거부되는 값들을 미리 정리 (관심사·가중치·지역)."""
    notes = []
    if isinstance(data.get("interests"), list):
        valid = [t for t in dict.fromkeys(data["interests"]) if t in C.INTERESTS][: C.MAX_INTERESTS]
        if valid != data["interests"]:
            notes.append(f"관심사 정리: {data['interests']} → {valid}")
            data["interests"] = valid
    if data.get("city") in C.REGIONS and data.get("district") and data["district"] not in C.REGIONS[data["city"]]:
        notes.append(f"구/시 정리: {data['district']} → 없음")
        data["district"] = None
    prefs = data.get("preferences")
    if isinstance(prefs, dict) and isinstance(prefs.get("weights"), dict):
        valid = {k: max(0, min(C.MAX_WEIGHT, int(v))) for k, v in prefs["weights"].items() if k in C.SCORE_CATEGORIES and isinstance(v, (int, float))}
        if valid != prefs["weights"]:
            notes.append(f"중요도 정리: {prefs['weights']} → {valid}")
            prefs["weights"] = valid
    return notes


def _drop(data: dict, loc: tuple) -> bool:
    """오류가 난 값 하나만 지운다. 필수 항목이면 지우지 않고 False."""
    if not loc or (len(loc) == 1 and loc[0] in REQUIRED):
        return False
    node = data
    for key in loc[:-1]:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            return False
    last = loc[-1]
    try:
        if isinstance(node, list):
            node.pop(last)
        else:
            del node[last]
    except (KeyError, IndexError, TypeError):
        return False
    return True


def repair(raw: dict) -> tuple[Profile | None, list[str]]:
    """예전 형식의 프로필을 지금 형식에 맞춘다. 고칠 수 없으면 (None, 이유)."""
    data = copy.deepcopy(raw)
    notes = _presanitize(data)
    for _ in range(100):
        try:
            return Profile.model_validate(data), notes
        except ValidationError as e:
            err = e.errors()[0]
            loc = tuple(err["loc"])
            # 'preferences.weights.smoking' 처럼 고칠 수 있는 위치까지 줄여 가며 지운다.
            if not _drop(data, loc):
                return None, notes + [f"{'.'.join(map(str, loc)) or '프로필'}: {err['msg']}"]
            notes.append(f"{'.'.join(map(str, loc))} 값 삭제 ({err['msg']})")
    return None, notes + ["정리 횟수 초과"]


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or DB_PATH
        self._lock = threading.Lock()
        persist.ensure_file(self.path, SAMPLE_PATH)
        persist.backup(self.path, "start")
        self.repair_notes: list[str] = []
        self._profiles = self._load()

    @property
    def quarantine_path(self) -> Path:
        return self.path.with_name(f"{self.path.stem}_보류.json")

    def _load(self) -> dict[int, Profile]:
        raw_list = persist.read_json(self.path)
        profiles: dict[int, Profile] = {}
        broken = []
        notes = []
        known = set(Profile.model_fields)
        for raw in raw_list:
            profile, fixes = repair(raw)
            removed = set(raw) - known
            if removed:
                fixes.append(f"더 이상 쓰지 않는 항목 {sorted(removed)}")
            if profile is None:
                broken.append(raw)
                notes.append(f"[보류] id {raw.get('id')}: {'; '.join(fixes)}")
                continue
            profiles[profile.id] = profile
            if fixes:
                notes.append(f"[정리] id {profile.id} {profile.name}: {'; '.join(fixes)}")

        if notes:
            # 원본을 남겨 두고, 정리된 내용으로 저장한다.
            kept = persist.backup(self.path, "before-repair")
            if broken:
                existing = persist.read_json(self.quarantine_path) if self.quarantine_path.exists() else []
                persist.write_json(self.quarantine_path, existing + broken)
            self._profiles = profiles
            self._save()
            self.repair_notes = notes
            print(f"[store] 예전 형식 데이터를 정리했어요. 원본 백업: {kept}")
            for n in notes:
                print("   ", n)
        return profiles

    def _save(self) -> None:
        persist.write_json(self.path, [p.model_dump(mode="json") for p in self._profiles.values()])

    def all(self) -> list[Profile]:
        return list(self._profiles.values())

    def get(self, profile_id: int) -> Profile | None:
        return self._profiles.get(profile_id)

    def create(self, data: ProfileCreate) -> Profile:
        with self._lock:
            new_id = max(self._profiles, default=0) + 1
            profile = Profile(id=new_id, **data.model_dump())
            self._profiles[new_id] = profile
            self._save()
            return profile

    def update_preferences(self, profile_id: int, prefs: Preferences) -> Profile:
        with self._lock:
            profile = self._profiles[profile_id].model_copy(update={"preferences": prefs})
            self._profiles[profile_id] = profile
            self._save()
            return profile

    def update_photo(self, profile_id: int, photo: str | None) -> Profile:
        with self._lock:
            profile = self._profiles[profile_id].model_copy(update={"photo": photo})
            self._profiles[profile_id] = profile
            self._save()
            return profile

    def reset(self) -> Path | None:
        """가상 데이터로 되돌리기. 지우기 전에 반드시 백업한다."""
        with self._lock:
            kept = persist.backup(self.path, "before-reset")
            persist.write_json(self.path, persist.read_json(SAMPLE_PATH))
            self._profiles = {p["id"]: Profile.model_validate(p) for p in persist.read_json(self.path)}
            return kept
