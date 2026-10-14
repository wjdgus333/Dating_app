"""소개팅 매칭 엔진: ① 거르기 → ② 후보 추리기 → ③ 점수·순위 → ④ 설명."""

from .pipeline import recommend

__all__ = ["recommend"]
