"""웹 버전(local-api.js)이 Python 엔진과 같은 결과를 내는지 비교할 기준값 만들기.

사용법:
    python scripts/parity_reference.py <출력 파일>

샘플 데이터(60명)로 모든 사용자의 추천 결과(일반·쌍방·조건 바꾼 경우), 문장 해석, 캐릭터 그림을 계산해 JSON으로 저장한다.
브라우저에서 같은 계산을 해서 이 값과 비교한다 (tests/web_parity.html 참고).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matcher import persist, textrules  # noqa: E402
from matcher.avatar import avatar_svg  # noqa: E402
from matcher.models import Dealbreaker, Profile  # noqa: E402
from matcher.pipeline import recommend  # noqa: E402

# 조건을 바꿔서도 비교한다 (거르기·추가 점수·감점·중요도가 모두 들어가게)
OVERRIDE = {
    "target_genders": [],
    "dealbreakers": [
        {"field": "interests", "op": "exclude", "value": ["골프"]},
        {"field": "education", "op": "min", "value": "전문대졸"},
        {"field": "height", "op": "max", "value": 185},
    ],
    "weights": {"interests": 20, "bio": 15, "region": 5, "mbti": 0, "religion": 15},
    "bonus_rules": [
        {"field": "mbti", "op": "in", "value": ["ENFP", "INFP", "INFJ"], "points": 15},
        {"field": "interests", "op": "in", "value": ["등산", "캠핑", "카페"], "points": 10},
        {"field": "height", "op": "min", "value": 175, "points": 5},
        {"field": "drinking", "op": "in", "value": ["자주"], "points": -10},
        {"field": "education", "op": "min", "value": "석사", "points": -5},
    ],
}
TEXTS = [
    "담배 피우는 사람은 싫어요. 술 자주 마시는 사람도 별로고, 게임 좋아하는 사람은 패스. 27살 이상이었으면 좋겠어요.",
    "비흡연자만 만나고 싶어요\n등산이나 캠핑 좋아하는 사람이면 좋겠어요\n25~33살\n키 175 이상\n교회 다니는 분은 어려워요",
    "술 안 마시는 사람만요! 운동 좋아하는 분이요, 성격 좋은 사람",
]


def main(out: str):
    from matcher.models import Preferences

    sample = persist.read_json(persist.PROJECT_DATA / "sample_profiles.json")
    people = [Profile.model_validate(p) for p in sample]
    override = Preferences.model_validate(OVERRIDE)
    cases = []
    for me in people:
        for mutual in (False, True):
            cases.append({"user_id": me.id, "mutual": mutual, "preferences": None, "result": recommend(me, people, mutual=mutual)})
        cases.append(
            {"user_id": me.id, "mutual": True, "preferences": OVERRIDE, "result": recommend(me, people, preferences=override, mutual=True)}
        )
    # top_k를 작게 해서 ② 임베딩 후보 추리기도 비교
    cases.append({"user_id": 1, "mutual": False, "preferences": None, "top_k": 3, "result": recommend(people[0], people, top_k=3)})

    parses = []
    for t in TEXTS:
        r = textrules.parse(t)
        for rule in r["rules"]:
            rule["text"] = Dealbreaker(**{k: rule[k] for k in ("field", "op", "value")}).describe()
        parses.append({"text": t, "result": r})

    avatars = [{"seed": s, "gender": g, "svg": avatar_svg(s, g)} for s in ("1-김민준", "abc", "7f3a9", "2-이도현") for g in ("남성", "여성", None)]

    Path(out).write_text(json.dumps({"cases": cases, "parses": parses, "avatars": avatars}, ensure_ascii=False), encoding="utf-8")
    print(f"기준값 {len(cases)}개 추천 · {len(parses)}개 문장 · {len(avatars)}개 캐릭터 → {out}")


if __name__ == "__main__":
    main(sys.argv[1])
