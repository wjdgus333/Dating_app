"""항목별로 '겹치는지' 판단하는 함수.

모든 함수는 (겹친 횟수, 설명 문자열)을 돌려준다.
  - 관심사: 겹친 개수 (0, 1, 2, …)
  - 나머지: 겹치면 1, 아니면 0
점수 = 중요도 × 겹친 횟수
"""

from . import config as C


def overlap(a: list[str], b: list[str]) -> tuple[int, str]:
    """관심사: 겹친 개수만큼 점수를 준다."""
    common = sorted(set(a) & set(b), key=list(a).index)
    if not common:
        return 0, "겹치는 관심사 없음"
    return len(common), f"{len(common)}개 겹침 ({', '.join(common)})"


def exact(a: str, b: str) -> tuple[int, str]:
    if a == b:
        return 1, f"둘 다 '{a}'"
    return 0, f"'{a}' vs '{b}'"


def region(city_a: str, dist_a: str | None, city_b: str, dist_b: str | None) -> tuple[int, str]:
    if city_a != city_b:
        return 0, f"{city_a} vs {city_b}"
    if dist_a and dist_a == dist_b:
        return 1, f"같은 동네 ({city_a} {dist_a})"
    return 1, f"둘 다 {city_a}"


def age_gap(a: int, b: int) -> tuple[int, str]:
    gap = abs(a - b)
    label = "동갑" if gap == 0 else f"{gap}살 차이"
    return (1, label) if gap <= C.AGE_MATCH_YEARS else (0, f"{label} ({C.AGE_MATCH_YEARS}살 초과)")


def text(sim: float) -> tuple[int, str]:
    sim = max(0.0, min(1.0, sim))
    threshold = C.BIO_MATCH_THRESHOLD
    if sim >= threshold:
        return 1, f"자기소개 유사도 {sim:.0%} (기준 {threshold:.0%} 이상)"
    return 0, f"자기소개 유사도 {sim:.0%} (기준 {threshold:.0%} 미만)"
