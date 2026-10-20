"""FastAPI 서버.

실행: uvicorn app.main:app --reload
화면: http://127.0.0.1:8000      API 문서: http://127.0.0.1:8000/docs
"""

import base64
import multiprocessing
import os
import signal
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from matcher.envfile import load_env

load_env()  # .env 의 MATCH_DATA_DIR 등을 저장소보다 먼저 읽어야 한다.

from matcher import config as C  # noqa: E402
from matcher import textrules  # noqa: E402
from matcher.avatar import avatar_svg, new_seed  # noqa: E402
from matcher.models import Dealbreaker, Preferences, Profile, ProfileCreate  # noqa: E402
from matcher.pipeline import recommend  # noqa: E402
from matcher.social import MAX_MESSAGE, SocialError, SocialStore  # noqa: E402
from matcher.store import ProfileStore  # noqa: E402

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="소개팅 매칭 API", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def no_cache_for_screen(request: Request, call_next):
    """코드를 고친 뒤 브라우저가 예전 화면(JS/CSS)을 캐시에서 쓰지 않게 한다."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
store = ProfileStore()
social = SocialStore()


class RecommendRequest(BaseModel):
    user_id: int
    preferences: Preferences | None = Field(None, description="넣으면 저장된 설정 대신 이 값으로 계산 (저장은 안 됨)")
    mutual: bool = Field(False, description="True면 상대 입장 점수도 반영(쌍방)")
    top_n: int = Field(C.DEFAULT_TOP_N, ge=1, le=50)
    top_k: int = Field(C.CANDIDATE_TOP_K, ge=1, le=1000)
    use_llm: bool = Field(False, description="ANTHROPIC_API_KEY가 있으면 상위 3명 설명을 LLM으로 다듬기")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/options")
def options():
    """화면에서 쓸 선택지 목록."""
    return C.options_payload()


@app.get("/api/profiles", response_model=list[Profile])
def list_profiles():
    return store.all()


@app.get("/api/profiles/{profile_id}", response_model=Profile)
def get_profile(profile_id: int):
    profile = store.get(profile_id)
    if not profile:
        raise HTTPException(404, "프로필을 찾을 수 없습니다.")
    return profile


@app.post("/api/profiles", response_model=Profile, status_code=201)
def create_profile(data: ProfileCreate):
    """프로필 등록. 이름·성별·학력·직업·나이·지역은 필수."""
    return store.create(data)


@app.put("/api/profiles/{profile_id}/preferences", response_model=Profile)
def save_preferences(profile_id: int, prefs: Preferences):
    if not store.get(profile_id):
        raise HTTPException(404, "프로필을 찾을 수 없습니다.")
    return store.update_preferences(profile_id, prefs)


@app.post("/api/recommend")
def run_recommend(req: RecommendRequest):
    me = store.get(req.user_id)
    if not me:
        raise HTTPException(404, "프로필을 찾을 수 없습니다.")
    return recommend(
        me,
        store.all(),
        preferences=req.preferences,
        mutual=req.mutual,
        top_n=req.top_n,
        top_k=req.top_k,
        use_llm=req.use_llm,
    )


class ParseRequest(BaseModel):
    text: str = Field(max_length=500)


@app.post("/api/dealbreakers/parse")
def parse_dealbreakers(req: ParseRequest):
    """문장 → 절대조건 후보. 바로 적용하지 않고 후보만 돌려준다."""
    result = textrules.parse(req.text)
    for rule in result["rules"]:
        rule["text"] = Dealbreaker(**{k: rule[k] for k in ("field", "op", "value")}).describe()
    return result


# ── 좋아요 · 매칭 · 채팅 ───────────────────────────────────
# 지금은 로그인 없이 화면에서 고른 사용자를 '나'로 본다. 실제 서비스에서는 로그인 정보로 바꿔야 한다.


class LikeRequest(BaseModel):
    from_id: int
    to_id: int
    message: str = Field("", max_length=MAX_MESSAGE, description="좋아요와 함께 보낼 한마디 (선택)")


class MessageRequest(BaseModel):
    sender_id: int
    text: str = Field(min_length=1, max_length=MAX_MESSAGE)


class BlockRequest(BaseModel):
    user_id: int
    target_id: int


def _user(user_id: int) -> Profile:
    p = store.get(user_id)
    if not p:
        raise HTTPException(404, "프로필을 찾을 수 없습니다.")
    return p


def _card(p: Profile) -> dict:
    return {
        "id": p.id,
        "name": p.display_name,
        "age": p.age,
        "region": f"{p.city} {p.district or ''}".strip(),
        "occupation": p.occupation,
        "photo": p.photo,
    }


# ── 프로필 사진 ─────────────────────────────────────────────
PHOTO_DIR = store.path.parent / "photos"
PHOTO_TYPES = {b"\xff\xd8\xff": ("jpg", "image/jpeg"), b"\x89PNG": ("png", "image/png"), b"RIFF": ("webp", "image/webp")}
MAX_PHOTO_BYTES = 3 * 1024 * 1024


def _photo_file(profile_id: int) -> Path | None:
    for ext, _ in PHOTO_TYPES.values():
        f = PHOTO_DIR / f"{profile_id}.{ext}"
        if f.exists():
            return f
    return None


class PhotoUpload(BaseModel):
    data_url: str = Field(description="data:image/jpeg;base64,... (화면에서 400px로 줄여서 보냄)")


@app.get("/api/profiles/{profile_id}/photo", include_in_schema=False)
def get_photo(profile_id: int):
    """올린 사진이 있으면 그 사진, 없으면 애니메이션 캐릭터(SVG)."""
    p = _user(profile_id)
    if p.photo == "upload" and (f := _photo_file(profile_id)):
        media = next(m for ext, m in PHOTO_TYPES.values() if f.suffix == f".{ext}")
        return FileResponse(f, media_type=media, headers={"Cache-Control": "no-cache"})
    seed = p.photo.split(":", 1)[1] if p.photo and p.photo.startswith("avatar:") else f"{p.id}-{p.name}"
    return Response(avatar_svg(seed, p.gender), media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})


@app.put("/api/profiles/{profile_id}/photo", response_model=Profile)
def upload_photo(profile_id: int, req: PhotoUpload):
    _user(profile_id)
    try:
        raw = base64.b64decode(req.data_url.split(",", 1)[1], validate=True)
    except (IndexError, ValueError):
        raise HTTPException(400, "사진 데이터를 읽을 수 없어요.")
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(400, "사진이 너무 커요 (최대 3MB).")
    kind = next((v for magic, v in PHOTO_TYPES.items() if raw.startswith(magic)), None)
    if kind is None or (kind[0] == "webp" and raw[8:12] != b"WEBP"):
        raise HTTPException(400, "JPG, PNG, WEBP 사진만 올릴 수 있어요.")
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    if old := _photo_file(profile_id):
        old.unlink()
    (PHOTO_DIR / f"{profile_id}.{kind[0]}").write_bytes(raw)
    return store.update_photo(profile_id, "upload")


@app.post("/api/profiles/{profile_id}/avatar", response_model=Profile)
def shuffle_avatar(profile_id: int):
    """다른 애니메이션 캐릭터로 바꾸기 (올린 사진이 있으면 지운다)."""
    _user(profile_id)
    if old := _photo_file(profile_id):
        old.unlink()
    return store.update_photo(profile_id, f"avatar:{new_seed()}")


@app.post("/api/likes")
def send_like(req: LikeRequest):
    me, other = _user(req.from_id), _user(req.to_id)
    if other.id in me.preferences.blocked_ids or me.id in other.preferences.blocked_ids:
        raise HTTPException(400, "차단된 사용자예요.")
    try:
        return social.like(me.id, other.id, req.message)
    except SocialError as e:
        raise HTTPException(400, str(e))


@app.get("/api/users/{user_id}/inbox")
def inbox(user_id: int):
    """받은 좋아요 · 매칭 목록 · 보낸 좋아요."""
    _user(user_id)
    likes = social.likes_of(user_id)
    # 프로필이 보류(읽을 수 없음) 상태인 사람은 목록에서만 빼고, 좋아요·대화 기록은 지우지 않는다.
    received = [
        {**_card(store.get(l["from"])), "message": l["message"], "at": l["at"]}
        for l in likes["received"]
        if store.get(l["from"])
    ]
    matches = []
    for other_id in social.matches_of(user_id):
        if not store.get(other_id):
            continue
        last = social.last_message(user_id, other_id)
        matches.append({**_card(store.get(other_id)), "last": last, "unread": social.unread_count(user_id, other_id)})
    matches.sort(key=lambda m: m["last"]["at"] if m["last"] else "", reverse=True)
    return {"received": received, "matches": matches, "sent": likes["sent"]}


@app.get("/api/chats/{user_id}/{other_id}")
def get_messages(user_id: int, other_id: int):
    _user(user_id)
    other = _user(other_id)
    try:
        return {"with": _card(other), "messages": social.messages(user_id, other_id)}
    except SocialError as e:
        raise HTTPException(403, str(e))


@app.post("/api/chats/{other_id}")
def send_message(other_id: int, req: MessageRequest):
    _user(req.sender_id)
    _user(other_id)
    try:
        return social.send(req.sender_id, other_id, req.text)
    except SocialError as e:
        raise HTTPException(403, str(e))


@app.post("/api/block", response_model=Profile)
def block(req: BlockRequest):
    """차단: 좋아요·대화를 지우고, 서로 추천에서도 빠지게 한다."""
    me = _user(req.user_id)
    _user(req.target_id)
    blocked = sorted(set(me.preferences.blocked_ids) | {req.target_id})
    social.unmatch(req.user_id, req.target_id)
    return store.update_preferences(me.id, me.preferences.model_copy(update={"blocked_ids": blocked}))


@app.post("/api/shutdown")
def shutdown(request: Request):
    """화면의 '종료' 버튼 — 서버를 끈다. 내 컴퓨터에서 접속한 경우에만 허용."""
    if request.client is None or request.client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "서버를 실행한 컴퓨터에서만 종료할 수 있어요.")

    def stop():
        time.sleep(0.5)  # 응답을 먼저 보내고 종료
        # --reload로 실행하면 감시 프로세스(부모)가 따로 있어서 그것까지 꺼야 터미널이 돌아온다.
        parent = multiprocessing.parent_process()
        if parent is not None:
            os.kill(parent.pid, signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=stop, daemon=True).start()
    return {"ok": True}


@app.post("/api/reset")
def reset_data():
    """가상 프로필 20명 · 샘플 좋아요/채팅 상태로 되돌리기. 지우기 전에 backups/ 에 자동 백업한다."""
    kept = [store.reset(), social.reset()]
    return {"ok": True, "count": len(store.all()), "backups": [p.name for p in kept if p]}


@app.get("/api/data-status")
def data_status():
    """데이터가 어디에 저장되는지, 예전 데이터를 정리한 기록이 있는지."""
    backups = store.path.parent / "backups"
    return {
        "data_dir": str(store.path.parent),
        "profiles": len(store.all()),
        "backups": len(list(backups.glob("*.json"))) if backups.exists() else 0,
        "repair_notes": store.repair_notes,
        "quarantined": store.quarantine_path.exists(),
    }
