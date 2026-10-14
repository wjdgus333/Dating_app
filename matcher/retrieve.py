"""② 후보 추리기 — 임베딩으로 '대략 비슷한 사람'만 남긴다.

거르기 후 남은 사람이 많으면(수천 명) 모두를 정밀 채점하기 부담스럽다.
프로필 전체 글(자기소개 + 질문 답변 + 관심사 + 데이트 스타일)을 벡터로 바꿔
나와 가까운 top_k명만 ③ 단계로 넘긴다. 인원이 top_k 이하라면 이 단계는 건너뛴다.
"""

from .embedding import cosine, embedding_cache
from .models import Profile


def profile_text(p: Profile) -> str:
    parts = [p.bio, " ".join(p.prompts.values()), " ".join(p.interests)]
    if p.date_style:
        parts.append(p.date_style)
    if p.relationship_goal:
        parts.append(p.relationship_goal)
    return " ".join(x for x in parts if x).strip() or p.occupation


def retrieve(me: Profile, pool: list[Profile], top_k: int) -> tuple[list[Profile], dict[int, float], bool]:
    """(후보 목록, id별 유사도, 이 단계를 실제로 사용했는지)."""
    texts = [profile_text(me)] + [profile_text(p) for p in pool]
    vectors = embedding_cache.get(texts)
    mine, others = vectors[0], vectors[1:]
    sims = {p.id: cosine(mine, v) for p, v in zip(pool, others)}

    if len(pool) <= top_k:
        return pool, sims, False
    ranked = sorted(pool, key=lambda p: sims[p.id], reverse=True)
    return ranked[:top_k], sims, True
