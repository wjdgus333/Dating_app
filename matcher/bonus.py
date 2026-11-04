"""추가 점수 규칙 — "이 카테고리에서 이 값에 해당하면 +5·10·15·20점".

예) MBTI가 ENFP·INFP면 +15 / 관심사에 등산·캠핑이 있으면 +10 / 키 175 이상이면 +5 / 지역이 서울이면 +5

- 관심사는 목록 중 겹친 관심사 하나당 점수를 준다 (등산·캠핑·카페 +10 규칙에 둘이 겹치면 +20). 감점도 같다.
- 상대가 그 항목을 입력하지 않았으면 해당하지 않는다.
"""

from . import config as C
from .models import BonusRule, Profile


def times(rule: BonusRule, other: Profile) -> int:
    """규칙이 몇 번 적용되는지: 관심사는 겹친 개수, 나머지는 해당하면 1."""
    if rule.field == "interests":
        return sum(1 for t in rule.value if t in (other.interests or []))
    return 1 if check(rule, other) else 0


def check(rule: BonusRule, other: Profile) -> str | None:
    """해당하면 근거 문장, 아니면 None."""
    value = getattr(other, rule.field, None)
    if value is None or value == []:
        return None

    if rule.field == "interests":
        hit = [t for t in rule.value if t in value]
        return f"관심사에 {', '.join(hit)} 있음" if hit else None

    if rule.op == "in":
        return f"{C.BONUS_FIELDS[rule.field][0]} '{value}'" if value in rule.value else None

    if rule.field == "education":
        order = C.EDUCATION
        ok = order.index(value) >= order.index(rule.value)
    else:
        ok = value >= rule.value if rule.op == "min" else value <= rule.value
    return f"{C.BONUS_FIELDS[rule.field][0]} {value}" if ok else None
