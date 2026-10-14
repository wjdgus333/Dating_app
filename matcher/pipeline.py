"""추천 파이프라인: ① 거르기 → ② 후보 추리기 → ③ 점수·순위 → ④ 설명."""

from collections import Counter

from . import config as C
from . import bonus, explain, filters, llm, retrieve, scoring
from .models import Preferences, Profile


def _brief(p: Profile) -> dict:
    return {
        "id": p.id,
        "name": p.display_name,
        "gender": p.gender,
        "age": p.age,
        "region": f"{p.city} {p.district or ''}".strip(),
        "occupation": p.occupation,
        "education": p.education,
        "verified": p.verified,
        "interests": p.interests,
        "bio": p.bio,
        "mbti": p.mbti,
        "photo": p.photo,
    }


def _rank(me: Profile, candidates: list[Profile], mutual: bool, weights: dict[str, int]):
    scored = [(p, scoring.score(me, p, mutual=mutual, my_weights=weights)) for p in candidates]
    # 동점이면 인증 회원 → 나이 차이 적은 순
    scored.sort(key=lambda x: (-round(x[1].total, 6), not x[0].verified, abs(x[0].age - me.age)))
    return scored


def recommend(
    me: Profile,
    everyone: list[Profile],
    preferences: Preferences | None = None,
    mutual: bool = False,
    top_n: int = C.DEFAULT_TOP_N,
    top_k: int = C.CANDIDATE_TOP_K,
    use_llm: bool = False,
) -> dict:
    if preferences is not None:
        me = me.model_copy(update={"preferences": preferences})
    weights = me.preferences.effective_weights()
    trace: list[str] = []

    # ── ① 거르기 ────────────────────────────────────────────
    passed, eliminated, out_of_scope = [], [], 0
    reason_counter: Counter = Counter()
    for other in everyone:
        result = filters.check(me, other)
        if result.passed:
            passed.append(other)
        elif result.out_of_scope:
            out_of_scope += 1 if other.id != me.id else 0
        else:
            eliminated.append((other, result.reasons))
            for r in result.reasons:
                reason_counter[r.split(" '")[0].split(" 정보")[0]] += 1

    total_others = len(everyone) - 1
    trace.append(
        f"① 거르기: 전체 {total_others}명 중 대상 아님(성별·차단) {out_of_scope}명, "
        f"절대조건 탈락 {len(eliminated)}명 → {len(passed)}명 통과"
    )
    if me.preferences.dealbreakers:
        trace.append("   내 절대조건: " + " / ".join(d.describe() for d in me.preferences.dealbreakers))

    # 절대조건으로 탈락한 사람도 '점수만 보면 몇 점이었는지' 계산해서, 점수와 무관하게 탈락했음을 보여 준다.
    eliminated_view = []
    for other, reasons in eliminated:
        s = scoring.score(me, other, mutual=mutual, my_weights=weights)
        eliminated_view.append({**_brief(other), "would_be_score": round(s.total, 1), "reasons": reasons})
    eliminated_view.sort(key=lambda x: x["would_be_score"], reverse=True)

    # ── ② 후보 추리기 ───────────────────────────────────────
    candidates, emb_sims, used = retrieve.retrieve(me, passed, top_k) if passed else ([], {}, False)
    if used:
        trace.append(f"② 후보 추리기: {len(passed)}명 중 프로필 글이 가장 비슷한 {len(candidates)}명만 정밀 채점 (임베딩)")
    else:
        trace.append(f"② 후보 추리기: {len(passed)}명 ≤ {top_k}명이라 생략하고 전원 정밀 채점")

    # ── ③ 점수·순위 ─────────────────────────────────────────
    scored = _rank(me, candidates, mutual, weights)
    changed = {k: v for k, v in weights.items() if v != C.DEFAULT_WEIGHT}
    weight_txt = ", ".join(f"{C.SCORE_CATEGORIES[k][0]} {v}점" for k, v in changed.items()) or "모두 보통"
    trace.append(f"③ 점수: 겹치는 항목마다 중요도만큼 더하기, 관심사는 겹친 개수 × 중요도 (변경: {weight_txt})")
    plus = [r.describe() for r in me.preferences.bonus_rules if not r.is_penalty]
    minus = [r.describe() for r in me.preferences.bonus_rules if r.is_penalty]
    if plus:
        trace.append("   추가 점수: " + " / ".join(plus))
    if minus:
        trace.append("   감점: " + " / ".join(minus))
    if mutual:
        trace.append("   쌍방 모드: (내 기준 점수 + 상대 기준 점수) ÷ 2")

    # 가중치를 모두 기본값으로 뒀다면 순위가 어땠을지 비교 → '가중치가 다르면 순위가 바뀐다'
    default_weights = {k: C.DEFAULT_WEIGHT for k in C.SCORE_CATEGORIES}
    baseline = _rank(me, candidates, mutual, default_weights) if changed else scored
    baseline_rank = {p.id: i + 1 for i, (p, _) in enumerate(baseline)}

    ranking = []
    for i, (p, s) in enumerate(scored[:top_n], start=1):
        bonus_part = sum(c.contribution for c in s.categories if "bonus:" in c.key and c.contribution > 0)
        penalty_part = sum(c.contribution for c in s.categories if "bonus:" in c.key and c.contribution < 0)
        item = {
            **_brief(p),
            "rank": i,
            "score": round(s.total, 1),
            "base_score": round(s.total - bonus_part - penalty_part, 1),  # 중요도 점수
            "bonus_score": round(bonus_part, 1),  # 추가 점수 규칙으로 더해진 점수
            "penalty_score": round(penalty_part, 1),  # 감점 규칙으로 빠진 점수 (0 또는 음수)
            # 내 추가 점수 규칙 전부를 해당/미해당으로 (점수 계산 보기에서 표시)
            "bonus_checks": [
                {"text": r.describe(), "points": r.points, "hit": (reason := bonus.check(r, p)) is not None, "reason": reason or "해당 없음"}
                for r in me.preferences.bonus_rules
            ],
            "my_score": round(s.my_score, 1),
            "their_score": round(s.their_score, 1),
            "rank_with_default_weights": baseline_rank[p.id],
            "profile_similarity": round(emb_sims.get(p.id, 0.0), 3),
            "formula": explain.score_formula(s),
            "breakdown": [
                {
                    "key": c.key,
                    "label": c.label,
                    "logic": C.SCORE_CATEGORIES[c.key][2] if c.key in C.SCORE_CATEGORIES else "해당하면 ±점수",
                    "weight": c.weight,
                    "matches": c.matches,
                    "points": round(c.points, 2),
                    "contribution": round(c.contribution, 2),
                    "their_weight": c.their_weight,
                    "detail": c.detail,
                }
                for c in sorted(s.categories, key=lambda c: c.contribution, reverse=True)
            ],
            "skipped": s.skipped,
            "highlights": explain.highlights(s),
            "weak_points": explain.weak_points(s),
            "llm_summary": None,
        }
        if use_llm and i <= 3:
            item["llm_summary"] = llm.summarize(me.id, p.id, item["highlights"] + [f"아쉬운 점: {w}" for w in item["weak_points"]])
        ranking.append(item)

    # ── ④ 설명 ──────────────────────────────────────────────
    why, why_detail = [], None
    if scored:
        first_p, first_s = scored[0]
        second_p, second_s = scored[1] if len(scored) > 1 else (None, None)
        why = explain.why_first(first_p.display_name, first_s, second_p.display_name if second_p else None, second_s)
        why_detail = {
            "first": {"name": first_p.display_name, "score": round(first_s.total, 1)},
            "second": {"name": second_p.display_name, "score": round(second_s.total, 1)} if second_p else None,
            **(explain.compare(first_s, second_s) if second_s else {"gap": None, "ahead": [], "behind": []}),
            "weight_note": None,
        }
        if changed:
            base_first = baseline[0][0]
            if base_first.id == first_p.id:
                note = f"중요도를 모두 보통({C.DEFAULT_WEIGHT}점)으로 둬도 1위는 같아요."
            else:
                note = (
                    f"중요도를 모두 보통({C.DEFAULT_WEIGHT}점)으로 뒀다면 1위는 {base_first.display_name}님이었어요. "
                    f"회원님이 바꾼 중요도({weight_txt}) 때문에 순위가 바뀌었어요."
                )
            why.append(note)
            why_detail["weight_note"] = note
        trace.append(f"④ 설명: 1위 {first_p.display_name}님 ({first_s.total:g}점)")
    else:
        trace.append("④ 결과: 조건을 모두 통과한 사람이 없어요. 절대조건을 조금 완화해 보세요.")

    return {
        "me": _brief(me),
        "settings": {
            "mutual": mutual,
            "weights": weights,
            "dealbreakers": [d.model_dump() | {"text": d.describe()} for d in me.preferences.dealbreakers],
            "top_k": top_k,
            "top_n": top_n,
        },
        "funnel": {
            "total": total_others,
            "out_of_scope": out_of_scope,
            "eliminated": len(eliminated),
            "passed_filter": len(passed),
            "candidates": len(candidates),
            "retrieval_used": used,
            "eliminated_reasons": dict(reason_counter.most_common()),
        },
        "trace": trace,
        "why_first": why,
        "why_detail": why_detail,
        "ranking": ranking,
        "eliminated": eliminated_view,
    }
