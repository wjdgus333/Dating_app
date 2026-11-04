"""가상 인물끼리 좋아요를 미리 보내 두기 → 기본 데이터(data/sample_social.json) 만들기.

사용법:
    python scripts/generate_social.py                 # sample_social.json 새로 만들기
    python scripts/generate_social.py --apply-live    # 지금 쓰는 data/social.json 도 이걸로 바꾸기 (백업 후)

규칙
  - 가상 인물(기본 60명)마다 1~2명에게 좋아요를 보낸다. 받는 사람은 '그 사람의 추천 순위 상위 6명' 중에서 고른다
    → 거르기 조건·원하는 성별을 지키고, 잘 맞는 사람끼리 좋아요가 오간다.
  - 좋아요의 70%에는 한마디가 붙는다 (공통 관심사·데이트 스타일을 넣어서).
  - 서로 좋아요를 보낸 쌍은 처음부터 매칭 → 채팅방에는 서로 보낸 한마디만 들어 있다 (그 뒤 대화는 없음).
  - 예전부터 있던 사례(이서연·박지우 → 김민준, 박서준 ↔ 윤채원)는 그대로 둔다.
  - 같은 --seed 면 항상 같은 결과.
"""

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from matcher import persist  # noqa: E402
from matcher.models import Profile  # noqa: E402
from matcher.pipeline import recommend  # noqa: E402

SAMPLE_SOCIAL = persist.PROJECT_DATA / "sample_social.json"

# 예전부터 있던 확인용 사례 (README에 나오는 것)
CURATED = [
    {"from": 11, "to": 1, "message": "안녕하세요! 주말에 등산하고 카페 가는 거 저랑 똑같아서 좋아요 눌렀어요 :)"},
    {"from": 12, "to": 1, "message": ""},
    {"from": 3, "to": 16, "message": "등산 좋아하신다니 반가워요!"},
    {"from": 16, "to": 3, "message": ""},
]


def one_liner(rng: random.Random, me: Profile, other: Profile) -> str:
    """좋아요와 함께 보낼 한마디 (30%는 한마디 없이)."""
    if rng.random() < 0.3:
        return ""
    shared = [t for t in me.interests if t in other.interests]
    options = ["프로필 보고 대화해 보고 싶어서 좋아요 눌렀어요 :)", "안녕하세요! 프로필 인상 깊게 봤어요 ㅎㅎ"]
    if shared:
        t = rng.choice(shared)
        options += [f"{t} 좋아하신다고 해서 좋아요 눌렀어요! 😊", f"저도 {t} 좋아해요! 얘기 나눠 보고 싶어요"]
    if me.date_style and me.date_style == other.date_style:
        options.append(f"'{me.date_style}' 데이트 좋아하시는 거 저랑 똑같아요 ㅎㅎ")
    if me.relationship_goal and me.relationship_goal == other.relationship_goal:
        options.append(f"저도 {me.relationship_goal} 생각하고 있어요. 천천히 알아가 봐요!")
    return rng.choice(options)


def generate(seed: int) -> dict:
    people = [Profile.model_validate(p) for p in persist.read_json(persist.PROJECT_DATA / "sample_profiles.json")]
    by_id = {p.id: p for p in people}
    rng = random.Random(seed)
    clock = datetime(2026, 11, 1, 9, 0, 0)

    def tick() -> str:
        nonlocal clock
        clock += timedelta(minutes=rng.randint(7, 55))
        return clock.isoformat(timespec="seconds")

    likes = [{**l, "at": tick()} for l in CURATED]
    sent = {(l["from"], l["to"]) for l in likes}
    for me in people:
        top = [r["id"] for r in recommend(me, people, top_n=6)["ranking"]]
        # 예전 사례는 그대로 두려고, 사례 속 좋아요에는 답하지 않는다 (예: 민준은 서연·박지우의 좋아요를 받은 상태로 남김)
        curated = {(c["from"], c["to"]) for c in CURATED}
        candidates = [t for t in top if (me.id, t) not in sent and (t, me.id) not in curated]
        for t in rng.sample(candidates, min(rng.choice([1, 2]), len(candidates))):
            likes.append({"from": me.id, "to": t, "message": one_liner(rng, me, by_id[t]), "at": tick()})
            sent.add((me.id, t))

    # 서로 좋아요 → 매칭: 서로 보낸 한마디만 채팅방에 (그 뒤 대화는 없음)
    messages: dict[str, list] = {}
    for l in likes:
        back = next((x for x in likes if x["from"] == l["to"] and x["to"] == l["from"]), None)
        if not back or l["from"] > l["to"]:
            continue
        pair = f"{min(l['from'], l['to'])}-{max(l['from'], l['to'])}"
        firsts = sorted((l, back), key=lambda x: x["at"])
        messages[pair] = [
            {"from": x["from"], "to": x["to"], "text": x["message"], "at": x["at"], "read": False} for x in firsts if x["message"]
        ]
    return {"likes": likes, "messages": messages}


def server_running(port: int = 8000) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/options", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--apply-live", action="store_true", help="지금 쓰는 data/social.json 도 바꾼다 (백업 후)")
    args = parser.parse_args()

    data = generate(args.seed)
    persist.write_json(SAMPLE_SOCIAL, data)

    likes = data["likes"]
    pairs = {(l["from"], l["to"]) for l in likes}
    matches = sum(1 for a, b in pairs if a < b and (b, a) in pairs)
    received = {}
    for a, b in pairs:
        if (b, a) not in pairs:
            received[b] = received.get(b, 0) + 1
    print(f"기본 데이터: 좋아요 {len(likes)}개 · 처음부터 매칭 {matches}쌍 · 받은 좋아요가 있는 사람 {len(received)}명 → {SAMPLE_SOCIAL}")

    if args.apply_live:
        live = persist.data_dir() / "social.json"
        if server_running():
            sys.exit("서버가 켜져 있어요. 끄고 다시 실행하세요 (켜진 서버가 예전 데이터로 덮어쓸 수 있어요).")
        kept = persist.backup(live, "before-generate-social")
        persist.write_json(live, data)
        print(f"지금 데이터도 바꿨어요 → {live} (백업: {kept})")


if __name__ == "__main__":
    main()
