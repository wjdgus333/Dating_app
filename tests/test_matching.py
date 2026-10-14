import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from matcher import filters, scoring
from matcher.models import Dealbreaker, Preferences, Profile, ProfileCreate
from matcher.pipeline import recommend
from matcher.similarity import overlap


def make(id, **kw) -> Profile:
    base = dict(name=f"user{id}", gender="여성", education="대졸", occupation="회사원", age=28, city="서울")
    base.update(kw)
    return Profile(id=id, **base)


# ── 관심사: 겹칠 때마다 중요도만큼 ───────────────────────
def test_overlap_counts_each_shared_interest():
    assert overlap(["등산", "카페", "영화"], ["등산", "카페", "영화", "와인"])[0] == 3
    assert overlap(["등산"], ["게임"])[0] == 0


def test_interest_points_are_count_times_importance():
    me = make(1, interests=["등산", "카페", "영화"], preferences=Preferences(weights={"interests": 15}))
    other = make(2, interests=["등산", "카페", "와인"])
    s = scoring.score(me, other)
    cat = next(c for c in s.categories if c.key == "interests")
    assert cat.matches == 2 and cat.points == 30


def test_other_items_score_only_when_same():
    me = make(1, religion="무교", exercise="주 1~2회", preferences=Preferences(weights={"religion": 20}))
    other = make(2, religion="무교", exercise="주 3회 이상")
    cats = {c.key: c for c in scoring.score(me, other).categories}
    assert cats["religion"].points == 20
    assert cats["exercise"].points == 0  # 비슷해도 다르면 0점


# ── ① 거르기 ─────────────────────────────────────────────
def test_dealbreaker_eliminates_even_perfect_match():
    me = make(1, gender="남성", smoking="비흡연", interests=["등산"],
              preferences=Preferences(target_genders=["여성"],
                                      dealbreakers=[Dealbreaker(field="smoking", op="exclude", value=["흡연"])]))
    twin_but_smoker = make(2, smoking="흡연", interests=["등산"])
    result = recommend(me, [me, twin_but_smoker])
    assert result["ranking"] == []
    assert result["eliminated"][0]["id"] == 2
    assert result["eliminated"][0]["would_be_score"] > 0  # 점수는 있었지만 탈락


def test_missing_info_fails_dealbreaker():
    me = make(1, preferences=Preferences(dealbreakers=[Dealbreaker(field="smoking", op="exclude", value=["흡연"])]))
    unknown = make(2)  # 흡연 정보 미입력
    res = filters.check(me, unknown)
    assert not res.passed and "미입력" in res.reasons[0]


def test_filter_is_mutual():
    me = make(1, religion="무교")
    other = make(2, preferences=Preferences(dealbreakers=[Dealbreaker(field="religion", op="require", value=["기독교"])]))
    res = filters.check(me, other)
    assert not res.passed and res.reasons[0].startswith("[상대 조건]")


def test_gender_preference_is_out_of_scope():
    me = make(1, gender="남성", preferences=Preferences(target_genders=["여성"]))
    other = make(2, gender="남성")
    res = filters.check(me, other)
    assert not res.passed and res.out_of_scope


def test_interest_dealbreakers():
    exclude_game = Dealbreaker(field="interests", op="exclude", value=["게임"])
    assert filters.check_dealbreaker(exclude_game, make(2, interests=["게임", "카페"])) is not None
    assert filters.check_dealbreaker(exclude_game, make(2, interests=["카페"])) is None
    assert filters.check_dealbreaker(exclude_game, make(2)) is None  # 관심사가 없으면 '게임'도 없음

    need_outdoor = Dealbreaker(field="interests", op="require", value=["등산", "캠핑"])
    assert filters.check_dealbreaker(need_outdoor, make(2, interests=["캠핑"])) is None
    assert filters.check_dealbreaker(need_outdoor, make(2, interests=["게임"])) is not None


def test_drinking_dealbreaker():
    rule = Dealbreaker(field="drinking", op="exclude", value=["자주"])
    assert filters.check_dealbreaker(rule, make(2, drinking="자주")) is not None
    assert filters.check_dealbreaker(rule, make(2, drinking="가끔")) is None


def test_invalid_dealbreaker_value():
    with pytest.raises(ValidationError):
        Dealbreaker(field="interests", op="exclude", value=["없는관심사"])


def test_smoking_and_drinking_are_not_scored():
    from matcher import config as C

    assert "smoking" not in C.SCORE_CATEGORIES and "drinking" not in C.SCORE_CATEGORIES
    with pytest.raises(ValidationError):
        Preferences(weights={"smoking": 20})


# ── 문장 → 거르기 조건 ───────────────────────────────────
def test_parse_sentence_rules():
    from matcher.textrules import parse

    res = parse("담배 피우는 사람은 싫어요. 술 자주 마시는 사람도 별로고, 게임 좋아하는 사람은 패스. 27살 이상이었으면 좋겠어요.")
    got = {(r["field"], r["op"]): r["value"] for r in res["rules"]}
    assert got[("smoking", "require")] == ["비흡연"]
    assert got[("drinking", "exclude")] == ["자주"]
    assert got[("interests", "exclude")] == ["게임"]
    assert got[("age", "min")] == 27
    assert res["unmatched"] == []


def test_parse_require_and_range():
    from matcher.textrules import parse

    res = parse("등산이나 캠핑 좋아하는 사람이면 좋겠어요\n25~33살\n술 안 마시는 사람만요")
    got = {(r["field"], r["op"]): r["value"] for r in res["rules"]}
    assert got[("interests", "require")] == ["등산", "캠핑"]
    assert got[("age", "min")] == 25 and got[("age", "max")] == 33
    assert got[("drinking", "require")] == ["안 마심"]


def test_parse_reports_unmatched():
    from matcher.textrules import parse

    assert parse("성격 좋은 사람이요")["unmatched"] == ["성격 좋은 사람이요"]


def test_education_min():
    rule = Dealbreaker(field="education", op="min", value="대졸")
    assert filters.check_dealbreaker(rule, make(2, education="석사")) is None
    assert filters.check_dealbreaker(rule, make(2, education="전문대졸")) is not None


# ── ③ 가중치 ─────────────────────────────────────────────
def test_weights_change_ranking():
    me = make(1, gender="남성", interests=["등산", "카페", "영화"], religion="무교", relationship_goal="진지한 연애")
    # a: 관심사 3개 겹침, 나머지 다름 / b: 관심사 1개 겹침, 지역·종교·관계 같음
    a = make(2, city="부산", interests=["등산", "카페", "영화"], religion="기독교", relationship_goal="가벼운 만남")
    b = make(3, interests=["등산", "게임"], religion="무교", relationship_goal="진지한 연애")

    default = recommend(me, [me, a, b])
    assert default["ranking"][0]["id"] == 3  # a 40점 < b 50점

    boosted = recommend(me, [me, a, b], preferences=Preferences(weights={"interests": 20}))
    assert boosted["ranking"][0]["id"] == 2  # a 70점 > b 60점
    assert boosted["ranking"][0]["rank_with_default_weights"] == 2
    assert any("순위가 바뀌었어요" in line for line in boosted["why_first"])


def test_no_100_point_scaling():
    me = make(1, interests=["등산", "카페", "영화"], preferences=Preferences(weights={"interests": 20}))
    other = make(2, interests=["등산", "카페", "영화"])
    # 관심사 20×3 + 지역 10 + 나이 10 = 80점 (만점 환산 없이 그대로 합산)
    assert scoring.score(me, other).total == 80


def test_zero_weight_and_missing_info_give_no_points():
    me = make(1, mbti="INFJ", preferences=Preferences(weights={"mbti": 0}))
    other = make(2, mbti="INFJ")
    s = scoring.score(me, other)
    assert next(c for c in s.categories if c.key == "mbti").points == 0  # 같아도 상관없음(0)이면 0점
    assert "운동 빈도" in s.skipped  # 둘 다 미입력


def test_score_is_sum_of_contributions():
    me = make(1, interests=["등산", "카페"], smoking="비흡연", drinking="가끔")
    other = make(2, interests=["등산"], smoking="흡연", drinking="자주")
    for mutual in (False, True):
        s = scoring.score(me, other, mutual=mutual)
        assert sum(c.contribution for c in s.categories) == pytest.approx(s.total)


def test_why_first_explains_gap():
    me = make(1, interests=["등산", "카페"])
    a = make(2, interests=["등산", "카페"])
    b = make(3, interests=["게임"])
    res = recommend(me, [me, a, b])
    assert res["ranking"][0]["id"] == 2
    assert "관심사" in "\n".join(res["why_first"])


# ── ② 후보 추리기 ────────────────────────────────────────
def test_retrieval_kicks_in_when_pool_is_large():
    me = make(1, bio="등산 좋아하고 카페 다니는 걸 좋아해요")
    pool = [make(i, bio=f"게임 좋아해요 {i}") for i in range(2, 12)]
    pool.append(make(99, bio="등산 좋아하고 카페 가는 걸 좋아해요"))
    res = recommend(me, [me, *pool], top_k=3)
    assert res["funnel"]["retrieval_used"] is True
    assert res["funnel"]["candidates"] == 3
    assert 99 in [r["id"] for r in res["ranking"]]


# ── 필수 항목 ────────────────────────────────────────────
@pytest.mark.parametrize("missing", ["name", "gender", "education", "occupation"])
def test_required_fields(missing):
    data = dict(name="홍길동", gender="남성", education="대졸", occupation="개발자", age=30, city="서울")
    data.pop(missing)
    with pytest.raises(ValidationError):
        ProfileCreate(**data)


def test_blank_name_rejected():
    with pytest.raises(ValidationError):
        ProfileCreate(name="  ", gender="남성", education="대졸", occupation="개발자", age=30, city="서울")


# ── API ──────────────────────────────────────────────────
@pytest.fixture
def client(tmp_path, monkeypatch):
    from matcher import social as social_mod
    from matcher import store as store_mod

    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "profiles.json")
    monkeypatch.setattr(social_mod, "DB_PATH", tmp_path / "social.json")
    import importlib

    import app.main as main

    importlib.reload(main)
    return TestClient(main.app)


def test_api_recommend_sample_user(client):
    res = client.post("/api/recommend", json={"user_id": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["ranking"][0]["name"] == "이서연"
    assert body["ranking"][0]["rank_with_default_weights"] != 1
    eliminated = {e["name"]: e for e in body["eliminated"]}
    assert "최하은" in eliminated  # 흡연 → 점수가 높아도 탈락
    assert eliminated["최하은"]["would_be_score"] >= body["ranking"][0]["score"]


def test_api_signup_requires_fields(client):
    res = client.post("/api/profiles", json={"name": "홍길동", "gender": "남성", "age": 30, "city": "서울"})
    assert res.status_code == 422
    missing = {e["loc"][-1] for e in res.json()["detail"]}
    assert {"education", "occupation"} <= missing

    ok = client.post("/api/profiles", json={"name": "홍길동", "gender": "남성", "education": "대졸",
                                            "occupation": "개발자", "age": 30, "city": "서울"})
    assert ok.status_code == 201 and ok.json()["id"] == 61  # 샘플 60명 다음


# ── 좋아요 · 매칭 · 채팅 ─────────────────────────────────
def test_like_back_creates_match_and_chat(client):
    # 샘플 데이터: 11번 이서연이 1번 김민준에게 한마디와 함께 좋아요를 보낸 상태
    inbox = client.get("/api/users/1/inbox").json()
    assert [r["id"] for r in inbox["received"]] == [11, 12]

    # 매칭 전에는 메시지 불가
    res = client.post("/api/chats/11", json={"sender_id": 1, "text": "안녕하세요"})
    assert res.status_code == 403

    res = client.post("/api/likes", json={"from_id": 1, "to_id": 11, "message": "반가워요!"})
    assert res.json() == {"matched": True}

    # 서로 보낸 한마디가 채팅방 첫 메시지로 들어간다
    msgs = client.get("/api/chats/1/11").json()["messages"]
    assert [m["text"] for m in msgs][0].startswith("안녕하세요! 주말에 등산")
    assert msgs[-1]["text"] == "반가워요!"

    assert client.post("/api/chats/1", json={"sender_id": 11, "text": "주말에 시간 되세요?"}).status_code == 200
    inbox = client.get("/api/users/1/inbox").json()
    assert inbox["matches"][0]["id"] == 11 and inbox["matches"][0]["unread"] == 1


def test_one_sided_like_is_not_match(client):
    res = client.post("/api/likes", json={"from_id": 2, "to_id": 17})
    assert res.json() == {"matched": False}
    assert client.post("/api/likes", json={"from_id": 2, "to_id": 17}).status_code == 400  # 중복
    assert client.post("/api/likes", json={"from_id": 2, "to_id": 2}).status_code == 400  # 자기 자신


def test_block_removes_chat_and_recommendation(client):
    # 샘플: 3번 박서준 ↔ 16번 윤채원 매칭 + 대화 중
    assert client.get("/api/chats/3/16").status_code == 200
    blocked = client.post("/api/block", json={"user_id": 3, "target_id": 16}).json()
    assert 16 in blocked["preferences"]["blocked_ids"]
    assert client.get("/api/chats/3/16").status_code == 403
    rec = client.post("/api/recommend", json={"user_id": 3}).json()
    assert 16 not in [r["id"] for r in rec["ranking"]]
    assert client.post("/api/likes", json={"from_id": 16, "to_id": 3}).status_code == 400


# ── 데이터 보존 ──────────────────────────────────────────
def _old_profile(**kw):
    base = {"id": 1, "name": "홍길동", "gender": "남성", "education": "대졸", "occupation": "개발자", "age": 30, "city": "서울"}
    base.update(kw)
    return base


def test_existing_data_is_never_overwritten_by_sample(tmp_path):
    import json

    from matcher.store import ProfileStore

    path = tmp_path / "profiles.json"
    path.write_text(json.dumps([_old_profile()], ensure_ascii=False), encoding="utf-8")
    store = ProfileStore(path)
    assert [p.name for p in store.all()] == ["홍길동"]  # 샘플 20명으로 바뀌지 않음


def test_old_format_is_repaired_without_losing_profile(tmp_path):
    import json

    from matcher.store import ProfileStore

    old = _old_profile(
        smoking="흡연",
        interests=["등산", "없어진관심사"],
        district="없는구",
        old_field="예전 버전에만 있던 칸",
        preferences={
            "weights": {"smoking": 20, "interests": 30},  # smoking은 이제 점수 항목이 아님
            "dealbreakers": [
                {"field": "smoking", "op": "exclude", "value": ["흡연"]},
                {"field": "삭제된항목", "op": "exclude", "value": ["x"]},
            ],
        },
    )
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps([old], ensure_ascii=False), encoding="utf-8")

    store = ProfileStore(path)
    p = store.get(1)
    # 큰 틀(이름·나이·직업·흡연)은 그대로
    assert (p.name, p.age, p.occupation, p.smoking) == ("홍길동", 30, "개발자", "흡연")
    assert p.interests == ["등산"]
    assert p.district is None
    assert p.preferences.weights == {"interests": 30}
    assert len(p.preferences.dealbreakers) == 1
    assert store.repair_notes
    # 원본은 백업에 남아 있음
    backups = list((tmp_path / "backups").glob("profiles-*-before-repair.json"))
    assert backups and "없어진관심사" in backups[0].read_text(encoding="utf-8")


def test_unreadable_profile_is_kept_aside_not_deleted(tmp_path):
    import json

    from matcher.store import ProfileStore

    path = tmp_path / "profiles.json"
    path.write_text(json.dumps([_old_profile(), _old_profile(id=2, gender="알수없음")], ensure_ascii=False), encoding="utf-8")
    store = ProfileStore(path)
    assert [p.id for p in store.all()] == [1]
    kept = json.loads((tmp_path / "profiles_보류.json").read_text(encoding="utf-8"))
    assert kept[0]["id"] == 2


def test_reset_makes_backup_first(tmp_path):
    import json

    from matcher.store import ProfileStore

    path = tmp_path / "profiles.json"
    path.write_text(json.dumps([_old_profile(name="내데이터")], ensure_ascii=False), encoding="utf-8")
    store = ProfileStore(path)
    kept = store.reset()
    assert len(store.all()) == 60  # 샘플: 손으로 만든 20명 + 랜덤 40명
    assert "내데이터" in kept.read_text(encoding="utf-8")


def test_safe_write_leaves_no_temp_file(tmp_path):
    from matcher import persist

    target = tmp_path / "x.json"
    persist.write_json(target, {"a": 1})
    persist.write_json(target, {"a": 2})
    assert persist.read_json(target) == {"a": 2}
    assert not list(tmp_path.glob("*.tmp"))


# ── 추가 점수 규칙 ───────────────────────────────────────
def test_bonus_rules_add_points():
    from matcher.models import BonusRule

    rules = [
        BonusRule(field="mbti", op="in", value=["ENFP", "INFP"], points=15),
        BonusRule(field="interests", op="in", value=["등산", "캠핑"], points=10),
        BonusRule(field="height", op="min", value=175, points=5),
        BonusRule(field="religion", op="in", value=["불교"], points=20),  # 해당 없음
    ]
    me = make(1, preferences=Preferences(bonus_rules=rules, weights={k: 0 for k in __import__("matcher.config").config.SCORE_CATEGORIES}))
    other = make(2, mbti="INFP", interests=["캠핑", "요리"], height=178, religion="무교")
    s = scoring.score(me, other)
    bonus = [c for c in s.categories if c.key.startswith("bonus:")]
    assert [c.points for c in bonus] == [15, 10, 5]
    assert s.total == 30  # 중요도는 모두 0이라 추가 점수만


def test_bonus_rule_changes_ranking_and_is_explained():
    from matcher.models import BonusRule

    me = make(1, gender="남성")
    a = make(2, mbti="ENFP")
    b = make(3, mbti="ISTJ", verified=True)  # 동점이면 인증 회원이 먼저
    assert recommend(me, [me, a, b])["ranking"][0]["id"] == 3
    prefs = Preferences(bonus_rules=[BonusRule(field="mbti", op="in", value=["ENFP"], points=5)])
    res = recommend(me, [me, a, b], preferences=prefs)
    assert res["ranking"][0]["id"] == 2
    assert any("추가 점수" in line for line in res["why_first"])


def test_bonus_points_must_be_allowed_value():
    from matcher.models import BonusRule

    with pytest.raises(ValidationError):
        BonusRule(field="mbti", op="in", value=["ENFP"], points=7)
    with pytest.raises(ValidationError):
        BonusRule(field="age", op="in", value=["30"], points=5)  # 나이는 이상/이하만


def test_mutual_mode_counts_their_bonus_rules():
    from matcher.models import BonusRule

    me = make(1, mbti="ENFP")
    other = make(2, preferences=Preferences(bonus_rules=[BonusRule(field="mbti", op="in", value=["ENFP"], points=20)]))
    s = scoring.score(me, other, mutual=True)
    assert s.their_score - scoring.score(me, other.model_copy(update={"preferences": Preferences()}), mutual=True).their_score == 20
    assert sum(c.contribution for c in s.categories) == pytest.approx(s.total)


# ── 감점 규칙 ────────────────────────────────────────────
def test_penalty_rules_subtract_points():
    from matcher.models import BonusRule

    rules = [
        BonusRule(field="drinking", op="in", value=["자주"], points=-15),
        BonusRule(field="interests", op="in", value=["게임"], points=-5),
        BonusRule(field="mbti", op="in", value=["ENFP"], points=10),
    ]
    me = make(1, preferences=Preferences(bonus_rules=rules))
    other = make(2, drinking="자주", interests=["게임", "카페"], mbti="ENFP")
    base = scoring.score(me.model_copy(update={"preferences": Preferences()}), other).total
    s = scoring.score(me, other)
    assert s.total == base - 15 - 5 + 10
    labels = sorted(c.label for c in s.categories if c.key.startswith("bonus:"))
    assert labels == ["감점", "감점", "추가 점수"]


def test_penalty_changes_ranking_and_shows_split():
    from matcher.models import BonusRule

    me = make(1, gender="남성")
    a = make(2, drinking="자주", verified=True)
    b = make(3, drinking="가끔")
    assert recommend(me, [me, a, b])["ranking"][0]["id"] == 2
    prefs = Preferences(bonus_rules=[BonusRule(field="drinking", op="in", value=["자주"], points=-10)])
    res = recommend(me, [me, a, b], preferences=prefs)
    assert res["ranking"][0]["id"] == 3
    loser = next(r for r in res["ranking"] if r["id"] == 2)
    assert loser["penalty_score"] == -10 and loser["bonus_score"] == 0
    assert loser["base_score"] + loser["penalty_score"] == loser["score"]
    assert any("감점" in w for w in loser["weak_points"])


def test_penalty_points_allowed_values():
    from matcher.models import BonusRule

    assert BonusRule(field="mbti", op="in", value=["ENFP"], points=-20).describe().endswith("-20점")
    with pytest.raises(ValidationError):
        BonusRule(field="mbti", op="in", value=["ENFP"], points=-7)


# ── 프로필 사진 ──────────────────────────────────────────
def test_every_profile_gets_a_cartoon_avatar(client):
    res = client.get("/api/profiles/1/photo")
    assert res.status_code == 200 and res.headers["content-type"].startswith("image/svg+xml")
    assert res.text.startswith("<svg") and res.text == client.get("/api/profiles/1/photo").text  # 같은 사람은 같은 캐릭터
    assert res.text != client.get("/api/profiles/2/photo").text


def test_shuffle_avatar_changes_character(client):
    before = client.get("/api/profiles/1/photo").text
    updated = client.post("/api/profiles/1/avatar").json()
    assert updated["photo"].startswith("avatar:")
    assert client.get("/api/profiles/1/photo").text != before


def test_upload_photo(client):
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    res = client.put("/api/profiles/1/photo", json={"data_url": data_url})
    assert res.status_code == 200 and res.json()["photo"] == "upload"
    got = client.get("/api/profiles/1/photo")
    assert got.headers["content-type"] == "image/png" and got.content == png

    bad = client.put("/api/profiles/1/photo", json={"data_url": "data:text/plain;base64," + base64.b64encode(b"hello").decode()})
    assert bad.status_code == 400
