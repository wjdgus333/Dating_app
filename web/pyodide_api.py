"""브라우저 안에서 도는 Python 서버 (Pyodide 버전).

FastAPI 서버(app/main.py)와 같은 주소(/api/...)·같은 응답을 돌려주되, 네트워크 대신 함수 호출로 동작한다.
매칭·저장·채팅은 전부 matcher/ 의 Python 코드를 그대로 쓴다.

- 데이터 파일(profiles.json, social.json)은 Pyodide의 가상 파일 시스템에 저장되고,
  화면 쪽(pyodide-api.js)이 요청마다 브라우저 localStorage 로 옮겨 적어서 새로고침해도 남는다.
- 올린 사진은 JS 쪽이 localStorage 에 data URL 로 따로 보관한다 (여기서는 photo="upload" 표시만).
"""

import json

from pydantic import BaseModel, Field, ValidationError

from matcher import config as C
from matcher import service
from matcher.avatar import avatar_svg
from matcher.models import Preferences, ProfileCreate
from matcher.pipeline import recommend
from matcher.service import ServiceError
from matcher.social import MAX_MESSAGE, SocialStore
from matcher.store import ProfileStore

store: ProfileStore | None = None
social: SocialStore | None = None


def start() -> None:
    """데이터 파일을 읽어 저장소를 연다 (처음·백업 불러오기 후)."""
    global store, social
    store = ProfileStore()
    social = SocialStore()


# ── 요청 본문 모델 (app/main.py 와 같음) ─────────────────────
class RecommendRequest(BaseModel):
    user_id: int
    preferences: Preferences | None = None
    mutual: bool = False
    top_n: int = Field(C.DEFAULT_TOP_N, ge=1, le=50)
    top_k: int = Field(C.CANDIDATE_TOP_K, ge=1, le=1000)
    use_llm: bool = False


class LikeRequest(BaseModel):
    from_id: int
    to_id: int
    message: str = Field("", max_length=MAX_MESSAGE)


class MessageRequest(BaseModel):
    sender_id: int
    text: str = Field(min_length=1, max_length=MAX_MESSAGE)


class BlockRequest(BaseModel):
    user_id: int
    target_id: int


class PhotoUpload(BaseModel):
    data_url: str = Field(pattern=r"^data:image/(jpeg|png|webp);base64,", max_length=4 * 1024 * 1024)


class ParseRequest(BaseModel):
    text: str = Field(max_length=500)


def _dump(x):
    return x.model_dump(mode="json") if isinstance(x, BaseModel) else x


# ── 라우터 ─────────────────────────────────────────────────
def route(method: str, path: str, body: dict):
    parts = [p for p in path.split("?")[0].split("/") if p][1:]  # "/api/..." → [...]
    key = (method, *["{n}" if p.isdigit() else p for p in parts])
    nums = [int(p) for p in parts if p.isdigit()]

    if key == ("GET", "options"):
        return C.options_payload()
    if key == ("GET", "profiles"):
        return store.all()
    if key == ("GET", "profiles", "{n}"):
        return service.user(store, nums[0])
    if key == ("POST", "profiles"):
        return store.create(ProfileCreate.model_validate(body))
    if key == ("PUT", "profiles", "{n}", "preferences"):
        service.user(store, nums[0])
        return store.update_preferences(nums[0], Preferences.model_validate(body))
    if key == ("POST", "recommend"):
        req = RecommendRequest.model_validate(body)
        me = service.user(store, req.user_id)
        return recommend(me, store.all(), preferences=req.preferences, mutual=req.mutual, top_n=req.top_n, top_k=req.top_k)
    if key == ("POST", "dealbreakers", "parse"):
        return service.parse_dealbreakers(ParseRequest.model_validate(body).text)
    if key == ("POST", "likes"):
        req = LikeRequest.model_validate(body)
        return service.like(store, social, req.from_id, req.to_id, req.message)
    if key == ("GET", "users", "{n}", "inbox"):
        return service.inbox(store, social, nums[0])
    if key == ("GET", "chats", "{n}", "{n}"):
        return service.messages(store, social, nums[0], nums[1])
    if key == ("POST", "chats", "{n}"):
        req = MessageRequest.model_validate(body)
        return service.send_message(store, social, req.sender_id, nums[0], req.text)
    if key == ("POST", "block"):
        req = BlockRequest.model_validate(body)
        return service.block(store, social, req.user_id, req.target_id)
    if key == ("PUT", "profiles", "{n}", "photo"):
        PhotoUpload.model_validate(body)  # 형식 검사 (사진 자체는 JS가 localStorage에 보관)
        service.user(store, nums[0])
        return store.update_photo(nums[0], "upload")
    if key == ("POST", "profiles", "{n}", "avatar"):
        return service.shuffle_avatar(store, nums[0])
    if key == ("GET", "data-status"):
        return {"data_dir": "이 브라우저", "profiles": len(store.all()), "backups": 0, "repair_notes": store.repair_notes,
                "quarantined": False, "web": True, "engine": "Python (Pyodide)"}
    if key == ("POST", "reset"):
        store.reset()
        social.reset()
        return {"ok": True, "count": len(store.all()), "backups": ["이 브라우저에 마지막 상태 1개"]}
    if key == ("POST", "shutdown"):
        raise ServiceError(400, "웹 버전은 끌 서버가 없어요. 창을 닫으면 돼요.")
    raise ServiceError(404, f"지원하지 않는 요청: {method} {path}")


LABELS = {
    "name": "이름", "gender": "성별", "education": "최종학력", "occupation": "직업", "age": "나이", "city": "시·도",
    "district": "구/시", "height": "키", "mbti": "MBTI", "interests": "관심사", "bio": "자기소개", "text": "내용",
    "message": "한마디", "data_url": "사진", "weights": "중요도", "dealbreakers": "거르기 조건", "bonus_rules": "추가 점수·감점",
}


def _korean(err: dict) -> str:
    """pydantic 오류를 화면에 보여 줄 한국어 문장으로."""
    field = next((LABELS[x] for x in reversed(err["loc"]) if x in LABELS), ".".join(map(str, err["loc"])) or "입력")
    msg = err["msg"].replace("Value error, ", "")
    if err["type"] == "missing":
        msg = "필수 항목이에요"
    elif err["type"] in ("greater_than_equal", "less_than_equal", "string_too_short", "string_too_long", "too_long"):
        msg = f"허용 범위를 벗어났어요 ({msg})"
    return f"• {field}: {msg}"


def handle(method: str, path: str, body_json: str) -> str:
    """JS에서 부르는 입구. 결과를 JSON 문자열로 돌려준다: {"ok": true, "data": ...} 또는 {"ok": false, "error": "..."}"""
    try:
        body = json.loads(body_json) if body_json else {}
        data = route(method.upper(), path, body)
        if isinstance(data, list):
            data = [_dump(x) for x in data]
        return json.dumps({"ok": True, "data": _dump(data)}, ensure_ascii=False)
    except ValidationError as e:
        msg = "\n".join(_korean(err) for err in e.errors())
    except ServiceError as e:
        msg = str(e)
    except Exception as e:  # 예상 못 한 오류도 화면에 문장으로 보여 준다
        msg = f"처리 중 오류가 났어요: {type(e).__name__}: {e}"
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


def avatar(seed: str, gender: str | None) -> str:
    return avatar_svg(seed, gender)
