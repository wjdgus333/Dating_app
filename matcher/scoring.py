"""③ 점수 매기기 — 겹치는 항목마다 중요도만큼 더한다.

항목 점수 = 중요도(0·5·10·15·20점) × 겹친 횟수
  - 관심사: 겹친 개수만큼 (3개 겹치고 중요도 15점 → 45점)
  - 나머지: 같으면 1번 (같으면 중요도만큼, 다르면 0점)
총점 = 항목 점수의 합 (100점 만점으로 바꾸지 않는다)

- 둘 중 한 명이라도 정보를 입력하지 않은 항목은 겹칠 수 없으니 0점이고, '정보 없음'으로 표시한다.
- 중요도 0 = '상관없음' → 0점.
"""

from dataclasses import dataclass, field

from . import bonus
from . import config as C
from . import similarity as S
from .embedding import cosine, embedding_cache
from .models import Profile


@dataclass
class CategoryScore:
    key: str
    label: str
    matches: int  # 겹친 횟수 (관심사는 개수, 나머지는 0 또는 1)
    detail: str
    weight: int  # 내 중요도
    points: float  # 내 중요도 × 겹친 횟수
    contribution: float  # 최종 점수에 들어간 점수 (쌍방 모드면 나·상대 평균)
    their_weight: int = 0
    their_points: float = 0.0


@dataclass
class ScoreResult:
    total: float  # 순위에 쓰는 최종 점수
    my_score: float  # 내 중요도 기준 합계
    their_score: float  # 상대 중요도 기준 합계
    categories: list[CategoryScore] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def bio_text(p: Profile) -> str:
    answers = " ".join(p.prompts.values())
    return f"{p.bio} {answers}".strip()


def matches(me: Profile, other: Profile) -> tuple[dict[str, tuple[int, str]], list[str]]:
    """항목별 (겹친 횟수, 설명). 정보가 없는 항목은 skipped에 담는다."""
    result: dict[str, tuple[int, str]] = {}
    skipped: list[str] = []

    for key, (label, kind, _) in C.SCORE_CATEGORIES.items():
        if kind == "count":
            if not me.interests or not other.interests:
                skipped.append(label)
                continue
            result[key] = S.overlap(me.interests, other.interests)
        elif kind == "text":
            a, b = bio_text(me), bio_text(other)
            if not a or not b:
                skipped.append(label)
                continue
            va, vb = embedding_cache.get([a, b])
            result[key] = S.text(cosine(va, vb))
        elif kind == "region":
            result[key] = S.region(me.city, me.district, other.city, other.district)
        elif kind == "age":
            result[key] = S.age_gap(me.age, other.age)
        else:  # exact
            a, b = getattr(me, key), getattr(other, key)
            if a is None or b is None:
                skipped.append(label)
                continue
            result[key] = S.exact(a, b)
    return result, skipped


def score(me: Profile, other: Profile, mutual: bool = False, my_weights: dict[str, int] | None = None) -> ScoreResult:
    """me 입장에서 other의 점수.

    mutual=True 이면 '상대 중요도로 계산한 점수'와 평균을 낸다(쌍방 매칭).
    """
    my_w = my_weights or me.preferences.effective_weights()
    their_w = other.preferences.effective_weights()
    found, skipped = matches(me, other)

    categories = []
    for key, (n, detail) in found.items():
        mine, theirs = my_w[key] * n, their_w[key] * n
        categories.append(
            CategoryScore(
                key=key,
                label=C.SCORE_CATEGORIES[key][0],
                matches=n,
                detail=detail,
                weight=my_w[key],
                points=mine,
                contribution=(mine + theirs) / 2 if mutual else mine,
                their_weight=their_w[key],
                their_points=theirs,
            )
        )

    # 추가 점수·감점 규칙: 내가 정한 규칙에 상대가 해당하면 +점수 / −점수
    for i, rule in enumerate(me.preferences.bonus_rules):
        reason = bonus.check(rule, other)
        if reason:
            categories.append(
                CategoryScore(
                    key=f"bonus:{i}",
                    label="감점" if rule.is_penalty else "추가 점수",
                    matches=1,
                    detail=f"{reason} ({rule.describe()})",
                    weight=rule.points,
                    points=rule.points,
                    contribution=rule.points / 2 if mutual else rule.points,
                )
            )
    # 쌍방 모드: 상대가 정한 규칙에 내가 해당하면 상대 기준 점수에 더한다.
    if mutual:
        for i, rule in enumerate(other.preferences.bonus_rules):
            reason = bonus.check(rule, me)
            if reason:
                categories.append(
                    CategoryScore(
                        key=f"their_bonus:{i}",
                        label="상대의 감점" if rule.is_penalty else "상대의 추가 점수",
                        matches=1,
                        detail=f"상대 기준: 나의 {reason} ({rule.describe()})",
                        weight=0,
                        points=0,
                        contribution=rule.points / 2,
                        their_weight=rule.points,
                        their_points=rule.points,
                    )
                )

    my_score = sum(c.points for c in categories)
    their_score = sum(c.their_points for c in categories)
    total = (my_score + their_score) / 2 if mutual else my_score
    return ScoreResult(total=total, my_score=my_score, their_score=their_score, categories=categories, skipped=skipped)
