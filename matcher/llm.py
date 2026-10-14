"""④-2 (선택) LLM으로 매칭 이유를 자연스러운 문장으로 다듬기.

- ANTHROPIC_API_KEY가 있고 `anthropic` 패키지가 설치된 경우에만 동작한다. 없으면 None을 돌려주고
  화면에는 규칙 기반 설명(explain.py)만 보인다.
- 개인정보(이름·연락처·회사)는 보내지 않고 '점수와 공통점'만 보낸다.
- 같은 쌍은 한 번만 호출하도록 메모리에 캐싱한다.
"""

import os

MODEL = os.getenv("MATCH_LLM_MODEL", "claude-opus-5-5")

_cache: dict[tuple[int, int, str], str] = {}


def _client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic()


def summarize(me_id: int, other_id: int, facts: list[str]) -> str | None:
    key = (me_id, other_id, "|".join(facts))
    if key in _cache:
        return _cache[key]

    client = _client()
    if client is None:
        return None

    prompt = (
        "소개팅 앱에서 두 사람이 왜 잘 맞을 수 있는지 2문장으로 친근하게 설명해 주세요.\n"
        "아래 데이터에 없는 내용은 절대 지어내지 말고, 점수 숫자는 언급하지 마세요.\n\n" + "\n".join(f"- {f}" for f in facts)
    )
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=1024,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # 네트워크·인증 오류여도 추천 자체는 계속 동작해야 한다.
        print(f"[llm] 설명 생성 실패: {exc}")
        return None

    if response.stop_reason == "refusal":
        return None
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if text:
        _cache[key] = text
    return text or None
