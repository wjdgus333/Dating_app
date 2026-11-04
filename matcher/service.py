"""화면 요청을 처리하는 공통 로직.

FastAPI 서버(app/main.py)와 브라우저 안의 Python(web/pyodide_api.py)이 같은 함수를 쓴다.
→ 두 버전의 동작이 어긋나지 않는다.
"""

from functools import lru_cache

from . import autoreply, persist, textrules
from .avatar import new_seed
from .models import Dealbreaker, Profile
from .social import SocialError, SocialStore
from .store import ProfileStore


class ServiceError(Exception):
    """화면에 보여 줄 오류. status는 HTTP 상태 코드."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def user(store: ProfileStore, user_id: int) -> Profile:
    p = store.get(user_id)
    if not p:
        raise ServiceError(404, "프로필을 찾을 수 없습니다.")
    return p


@lru_cache(maxsize=1)
def default_ids() -> frozenset[int]:
    """기본 데이터(가상 인물)의 id. 이 사람들은 좋아요를 자동으로 돌려주고 메시지에 자동으로 답한다."""
    return frozenset(p["id"] for p in persist.read_json(persist.PROJECT_DATA / "sample_profiles.json"))


def is_bot(profile_id: int) -> bool:
    return profile_id in default_ids()


def card(p: Profile) -> dict:
    return {
        "id": p.id,
        "name": p.display_name,
        "age": p.age,
        "region": f"{p.city} {p.district or ''}".strip(),
        "occupation": p.occupation,
        "photo": p.photo,
        "bot": is_bot(p.id),  # 가상 인물(자동 답장)
    }


def parse_dealbreakers(text: str) -> dict:
    """문장 → 절대조건 후보. 바로 적용하지 않고 후보만 돌려준다."""
    result = textrules.parse(text)
    for rule in result["rules"]:
        rule["text"] = Dealbreaker(**{k: rule[k] for k in ("field", "op", "value")}).describe()
    return result


def like(store: ProfileStore, social: SocialStore, from_id: int, to_id: int, message: str = "") -> dict:
    me, other = user(store, from_id), user(store, to_id)
    if other.id in me.preferences.blocked_ids or me.id in other.preferences.blocked_ids:
        raise ServiceError(400, "차단된 사용자예요.")
    try:
        result = social.like(me.id, other.id, message)
    except SocialError as e:
        raise ServiceError(400, str(e))

    # 가상 인물은 좋아요를 받으면 자동으로 돌려준다 → 바로 매칭
    auto = False
    if not result["matched"] and is_bot(other.id) and other.id != me.id:
        result = social.like(other.id, me.id, "")
        auto = True
    # 매칭되면 가상 인물이 먼저 말을 건다: 한마디를 받았으면 거기에 답하고, 없으면 인사
    if result["matched"] and is_bot(other.id) and other.id != me.id:
        turn = social.conversation_length(me.id, other.id)
        text = autoreply.reply(other, me, message, turn) if message.strip() else autoreply.opener(other, me, turn)
        social.send(other.id, me.id, text)
    return {"matched": result["matched"], "auto": auto}


def inbox(store: ProfileStore, social: SocialStore, user_id: int) -> dict:
    """받은 좋아요 · 매칭 목록 · 보낸 좋아요."""
    user(store, user_id)
    likes = social.likes_of(user_id)
    # 프로필이 보류(읽을 수 없음) 상태인 사람은 목록에서만 빼고, 좋아요·대화 기록은 지우지 않는다.
    received = [
        {**card(store.get(l["from"])), "message": l["message"], "at": l["at"]}
        for l in likes["received"]
        if store.get(l["from"])
    ]
    matches = []
    for other_id in social.matches_of(user_id):
        if not store.get(other_id):
            continue
        last = social.last_message(user_id, other_id)
        matches.append({**card(store.get(other_id)), "last": last, "unread": social.unread_count(user_id, other_id)})
    matches.sort(key=lambda m: m["last"]["at"] if m["last"] else "", reverse=True)
    return {"received": received, "matches": matches, "sent": likes["sent"]}


def messages(store: ProfileStore, social: SocialStore, user_id: int, other_id: int) -> dict:
    user(store, user_id)
    other = user(store, other_id)
    try:
        return {"with": card(other), "messages": social.messages(user_id, other_id)}
    except SocialError as e:
        raise ServiceError(403, str(e))


def send_message(store: ProfileStore, social: SocialStore, sender_id: int, other_id: int, text: str) -> dict:
    me = user(store, sender_id)
    other = user(store, other_id)
    try:
        msg = social.send(sender_id, other_id, text)
    except SocialError as e:
        raise ServiceError(403, str(e))
    # 가상 인물에게 보낸 메시지에는 자동으로 답한다
    auto_reply = is_bot(other_id) and other_id != sender_id
    if auto_reply:
        turn = social.conversation_length(sender_id, other_id)
        social.send(other_id, sender_id, autoreply.reply(other, me, text, turn))
    return {**msg, "auto_reply": auto_reply}


def block(store: ProfileStore, social: SocialStore, user_id: int, target_id: int) -> Profile:
    """차단: 좋아요·대화를 지우고, 서로 추천에서도 빠지게 한다."""
    me = user(store, user_id)
    user(store, target_id)
    blocked = sorted(set(me.preferences.blocked_ids) | {target_id})
    social.unmatch(user_id, target_id)
    return store.update_preferences(me.id, me.preferences.model_copy(update={"blocked_ids": blocked}))


def shuffle_avatar(store: ProfileStore, profile_id: int) -> Profile:
    user(store, profile_id)
    return store.update_photo(profile_id, f"avatar:{new_seed()}")


def avatar_seed(p: Profile) -> str:
    """이 프로필의 캐릭터 그림을 만드는 seed (고른 캐릭터가 없으면 id-이름)."""
    return p.photo.split(":", 1)[1] if p.photo and p.photo.startswith("avatar:") else f"{p.id}-{p.name}"
