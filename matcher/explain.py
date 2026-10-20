"""④ 결과 설명 — 어떤 로직을 거쳐 이 순위가 나왔는지 사람이 읽을 수 있게 정리.

LLM 없이도 항상 동작하는 '규칙 기반 설명'이다. (LLM 요약은 llm.py, 선택 사항)
"""

from . import config as C
from .scoring import ScoreResult


def highlights(result: ScoreResult, limit: int = 3) -> list[str]:
    """점수를 가장 많이 받은 겹치는 항목."""
    good = [c for c in result.categories if c.matches and c.contribution > 0]
    good.sort(key=lambda c: c.contribution, reverse=True)
    return [f"{c.label}: {c.detail} (+{c.points:g}점)" for c in good[:limit]]


def weak_points(result: ScoreResult, limit: int = 2) -> list[str]:
    """감점된 항목 + 내가 중요하게 여기는데(기본값 이상) 겹치지 않은 항목."""
    penalties = [f"감점: {c.detail} ({c.points:g}점)" for c in result.categories if c.points < 0]
    bad = [c for c in result.categories if not c.matches and c.weight >= C.DEFAULT_WEIGHT]
    bad.sort(key=lambda c: c.weight, reverse=True)
    return penalties + [f"{c.label}: {c.detail}" for c in bad[: max(0, limit - len(penalties))]]


def compare(first: ScoreResult, second: ScoreResult) -> dict:
    """1위와 2위의 항목별 점수 차이. 화면과 터미널 설명이 함께 쓴다."""
    a = {c.key: c for c in first.categories}
    b = {c.key: c for c in second.categories}
    items = []
    for key in dict.fromkeys([*a, *b]):  # 순서를 고정 (웹 버전과 같은 결과)
        ca, cb = a.get(key), b.get(key)
        diff = (ca.contribution if ca else 0) - (cb.contribution if cb else 0)
        weight = (ca or cb).weight
        is_bonus = "bonus:" in key
        note = ""
        if is_bonus:
            pass  # 추가 점수 규칙은 detail에 규칙이 함께 적혀 있다.
        elif diff > 0 and weight > C.DEFAULT_WEIGHT:
            note = f"회원님이 {weight}점(기본 {C.DEFAULT_WEIGHT}점)으로 중요하게 설정해서 차이가 {weight / C.DEFAULT_WEIGHT:g}배로 커졌어요"
        elif diff < 0 and weight < C.DEFAULT_WEIGHT:
            note = f"회원님 설정이 {weight}점이라 영향이 작았어요"
        items.append(
            {
                "key": key,
                "label": (ca or cb).label,
                "diff": round(diff, 1),
                "first": ca.detail if ca else ("해당 없음" if is_bonus else "정보 없음"),
                "second": cb.detail if cb else ("해당 없음" if is_bonus else "정보 없음"),
                "note": note,
            }
        )
    items.sort(key=lambda x: x["diff"], reverse=True)
    return {
        "gap": round(first.total - second.total, 1),
        "ahead": [i for i in items if i["diff"] > 0.05][:3],
        "behind": [i for i in reversed(items) if i["diff"] < -0.05][:2],
    }


def why_first(first_name: str, first: ScoreResult, second_name: str | None, second: ScoreResult | None) -> list[str]:
    """1위가 왜 1위인지: 2위와 항목별 점수 차이를 비교한 문장."""
    if second is None:
        return [f"거르기를 통과한 사람이 {first_name}님 한 명뿐이라 1위가 되었어요."]

    cmp = compare(first, second)
    if cmp["gap"] == 0:
        lines = [f"{first_name}님과 2위 {second_name}님이 {first.total:g}점 동점이라, 인증 회원 → 나이 차이가 적은 순으로 1위가 됐어요."]
    else:
        lines = [f"{first_name}님 {first.total:g}점 vs 2위 {second_name}님 {second.total:g}점 → {cmp['gap']:g}점 차이로 1위예요."]
    if cmp["ahead"]:
        lines.append("1위가 앞선 항목:")
        for i in cmp["ahead"]:
            note = f" ← {i['note']}" if i["note"] else ""
            lines.append(f"  · {i['label']} +{i['diff']:g}점 — 1위 [{i['first']}] / 2위 [{i['second']}]{note}")
    if cmp["behind"]:
        lines.append("2위가 앞선 항목 (그래도 1위를 뒤집지는 못했어요):")
        for i in cmp["behind"]:
            note = f" ← {i['note']}" if i["note"] else ""
            lines.append(f"  · {i['label']} {i['diff']:g}점 — 1위 [{i['first']}] / 2위 [{i['second']}]{note}")
    return lines


def score_formula(result: ScoreResult) -> str:
    """예) 관심사 15×3 + 원하는 관계 15×1 + 지역 10×1 = 70점"""
    parts = [
        f"{c.label} {c.points:+g}" if "bonus:" in c.key else f"{c.label} {c.weight}×{c.matches}"
        for c in result.categories
        if c.points and c.matches
    ]
    return f"{' + '.join(parts).replace('+ -', '- ') or '겹치는 항목 없음'} = {result.my_score:g}점"
