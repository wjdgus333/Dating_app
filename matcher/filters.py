"""① 거르기 — 절대조건에 걸리면 점수가 아무리 높아도 탈락.

양방향으로 검사한다.
  - 내 절대조건에 상대가 걸리는가?
  - 상대의 절대조건에 내가 걸리는가?  (상대가 거절할 사람을 추천해 봐야 의미가 없으므로)
"""

from dataclasses import dataclass, field

from . import config as C
from .models import Dealbreaker, Profile


@dataclass
class FilterResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    # 성별·차단처럼 '애초에 대상이 아닌' 경우. 이런 사람은 '아깝게 탈락' 목록에 보여 주지 않는다.
    out_of_scope: bool = False


def _value_of(profile: Profile, field_name: str):
    return getattr(profile, field_name, None)


def check_dealbreaker(rule: Dealbreaker, other: Profile) -> str | None:
    """조건을 통과하면 None, 걸리면 탈락 사유를 돌려준다."""
    label = C.DEALBREAKER_FIELDS[rule.field][0]
    value = _value_of(other, rule.field)

    # 관심사는 목록: 제외 = 하나라도 있으면 탈락, 필수 = 하나도 없으면 탈락
    if rule.field == "interests":
        hit = sorted(set(value or []) & set(rule.value))
        if rule.op == "exclude":
            return f"관심사에 {', '.join(hit)} 있음 (조건: {rule.describe()})" if hit else None
        return None if hit else f"관심사에 {', '.join(rule.value)} 없음 (조건: {rule.describe()})"

    # 정보를 입력하지 않은 사람은 '절대조건을 만족한다'고 확인할 수 없으므로 탈락시킨다.
    if value is None:
        return f"{label} 정보 미입력 (조건: {rule.describe()})"

    if rule.op in ("min", "max"):
        if rule.field == "education":
            order = C.EDUCATION
            ok = order.index(value) >= order.index(rule.value) if rule.op == "min" else order.index(value) <= order.index(rule.value)
        else:
            ok = value >= rule.value if rule.op == "min" else value <= rule.value
    elif rule.op == "require":
        ok = value in rule.value
    else:  # exclude
        ok = value not in rule.value

    return None if ok else f"{label} '{value}' (조건: {rule.describe()})"


def one_way(viewer: Profile, other: Profile) -> list[str]:
    """viewer의 조건으로 other를 검사."""
    prefs = viewer.preferences
    reasons = []
    for rule in prefs.dealbreakers:
        reason = check_dealbreaker(rule, other)
        if reason:
            reasons.append(reason)
    return reasons


def check(me: Profile, other: Profile) -> FilterResult:
    if me.id == other.id:
        return FilterResult(False, ["본인"], out_of_scope=True)

    scope = []
    if me.preferences.target_genders and other.gender not in me.preferences.target_genders:
        scope.append("내가 원하는 성별이 아님")
    if other.preferences.target_genders and me.gender not in other.preferences.target_genders:
        scope.append("상대가 원하는 성별이 아님")
    if other.id in me.preferences.blocked_ids or me.id in other.preferences.blocked_ids:
        scope.append("차단한/차단된 사용자")
    if scope:
        return FilterResult(False, scope, out_of_scope=True)

    reasons = [f"[내 조건] {r}" for r in one_way(me, other)]
    reasons += [f"[상대 조건] 내가 상대의 조건에 맞지 않음 — {r}" for r in one_way(other, me)]
    return FilterResult(not reasons, reasons)
