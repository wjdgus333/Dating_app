"""프로필·선호 설정 데이터 모델 (pydantic으로 입력값 검증)."""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import config as C

Gender = Literal[tuple(C.GENDERS)]
Education = Literal[tuple(C.EDUCATION)]
Smoking = Literal[tuple(C.SMOKING)]
Drinking = Literal[tuple(C.DRINKING)]
Exercise = Literal[tuple(C.EXERCISE)]
Religion = Literal[tuple(C.RELIGION)]
ContactFrequency = Literal[tuple(C.CONTACT_FREQUENCY)]
DateStyle = Literal[tuple(C.DATE_STYLES)]
RelationshipGoal = Literal[tuple(C.RELATIONSHIP_GOALS)]

MBTI_RE = re.compile(r"^[EI][NS][TF][JP]$")


class Dealbreaker(BaseModel):
    """절대조건 하나. 걸리면 점수와 상관없이 탈락."""

    field: str
    op: Literal["min", "max", "require", "exclude"]
    value: int | str | list[str]

    @model_validator(mode="after")
    def _check(self):
        if self.field not in C.DEALBREAKER_FIELDS:
            raise ValueError(f"절대조건으로 쓸 수 없는 항목입니다: {self.field}")
        allowed_ops = C.DEALBREAKER_FIELDS[self.field][1]
        if self.op not in allowed_ops:
            raise ValueError(f"'{self.field}'에는 {allowed_ops} 조건만 쓸 수 있습니다.")
        if self.op in ("require", "exclude"):
            if isinstance(self.value, str):
                self.value = [self.value]
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("require/exclude 조건에는 값 목록이 필요합니다.")
            choices = C.DEALBREAKER_CHOICES[self.field]
            unknown = [v for v in self.value if v not in choices]
            if unknown:
                raise ValueError(f"'{self.field}'에 없는 값입니다: {unknown}")
        elif self.field == "education":
            if self.value not in C.EDUCATION:
                raise ValueError(f"학력 값은 {C.EDUCATION} 중 하나여야 합니다.")
        elif not isinstance(self.value, int):
            raise ValueError("min/max 조건에는 숫자가 필요합니다.")
        return self

    def describe(self) -> str:
        label = C.DEALBREAKER_FIELDS[self.field][0]
        if self.op == "min":
            return f"{label} {self.value} 이상"
        if self.op == "max":
            return f"{label} {self.value} 이하"
        values = ", ".join(self.value)
        if self.field == "interests":
            if self.op == "require":
                return f"관심사에 {values} 중 하나 이상 필수"
            return f"관심사에 {values} 있으면 제외"
        return f"{label}: {values}만 허용" if self.op == "require" else f"{label}: {values} 제외"


class BonusRule(BaseModel):
    """추가 점수(+) 또는 감점(−) 규칙 하나. 상대가 해당하면 points만큼 더한다 (감점은 음수)."""

    field: str
    op: Literal["in", "min", "max"]
    value: int | str | list[str]
    points: int

    @model_validator(mode="after")
    def _check(self):
        if self.field not in C.BONUS_FIELDS:
            raise ValueError(f"추가 점수에 쓸 수 없는 항목입니다: {self.field}")
        allowed_ops = C.BONUS_FIELDS[self.field][1]
        if self.op not in allowed_ops:
            raise ValueError(f"'{self.field}'에는 {allowed_ops} 조건만 쓸 수 있습니다.")
        if abs(self.points) not in C.BONUS_POINTS:
            raise ValueError(f"추가 점수·감점은 ±{C.BONUS_POINTS} 중 하나여야 합니다.")
        if self.op == "in":
            if isinstance(self.value, str):
                self.value = [self.value]
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("값을 하나 이상 골라 주세요.")
            unknown = [v for v in self.value if v not in C.DEALBREAKER_CHOICES[self.field]]
            if unknown:
                raise ValueError(f"'{self.field}'에 없는 값입니다: {unknown}")
        elif self.field == "education":
            if self.value not in C.EDUCATION:
                raise ValueError(f"학력 값은 {C.EDUCATION} 중 하나여야 합니다.")
        elif not isinstance(self.value, int):
            raise ValueError("이상/이하 조건에는 숫자가 필요합니다.")
        return self

    def describe(self) -> str:
        label = C.BONUS_FIELDS[self.field][0]
        if self.op == "min":
            cond = f"{label} {self.value} 이상"
        elif self.op == "max":
            cond = f"{label} {self.value} 이하"
        elif self.field == "interests":
            cond = f"관심사에 {', '.join(self.value)}"
        else:
            cond = f"{label} {', '.join(self.value)}"
        return f"{cond} → {self.points:+d}점"

    @property
    def is_penalty(self) -> bool:
        return self.points < 0


class Preferences(BaseModel):
    """내가 원하는 상대 조건 + 항목별 가중치."""

    target_genders: list[Gender] = Field(default_factory=list, description="비어 있으면 성별 무관")
    dealbreakers: list[Dealbreaker] = Field(default_factory=list)
    bonus_rules: list[BonusRule] = Field(
        default_factory=list, max_length=C.MAX_BONUS_RULES, description="해당하면 추가 점수(+) 또는 감점(−)"
    )
    dealbreaker_text: str = Field("", max_length=500, description="문장으로 적은 거르는 조건 (조건 후보를 만드는 데 사용)")
    weights: dict[str, int] = Field(default_factory=dict, description="항목별 점수. 없으면 기본 10점")
    blocked_ids: list[int] = Field(default_factory=list)

    @field_validator("weights")
    @classmethod
    def _check_weights(cls, v: dict[str, int]):
        for key, w in v.items():
            if key not in C.SCORE_CATEGORIES:
                raise ValueError(f"알 수 없는 점수 항목입니다: {key}")
            if not 0 <= w <= C.MAX_WEIGHT:
                raise ValueError(f"가중치는 0~{C.MAX_WEIGHT} 사이여야 합니다: {key}={w}")
        return v

    def effective_weights(self) -> dict[str, int]:
        """설정하지 않은 항목은 기본값(10점)으로 채운 가중치."""
        return {key: self.weights.get(key, C.DEFAULT_WEIGHT) for key in C.SCORE_CATEGORIES}


class ProfileBase(BaseModel):
    # ── 필수 ──
    name: str = Field(min_length=1, max_length=20, description="이름 (필수)")
    gender: Gender = Field(description="성별 (필수)")
    education: Education = Field(description="최종학력 (필수)")
    occupation: str = Field(min_length=1, max_length=30, description="직업 (필수)")
    age: int = Field(ge=19, le=80, description="나이 (필수, 만 19세 이상)")
    city: str = Field(description="시·도 (필수)")

    # ── 선택 ──
    nickname: str | None = None
    district: str | None = None
    height: int | None = Field(None, ge=130, le=220)
    company: str | None = None
    verified: bool = False

    smoking: Smoking | None = None
    drinking: Drinking | None = None
    religion: Religion | None = None
    exercise: Exercise | None = None
    mbti: str | None = None

    interests: list[str] = Field(default_factory=list)
    contact_frequency: ContactFrequency | None = None
    date_style: DateStyle | None = None
    relationship_goal: RelationshipGoal | None = None

    # 프로필 사진: None = 자동 캐릭터, "avatar:<seed>" = 고른 캐릭터, "upload" = 올린 사진(data/photos/<id>.*)
    photo: str | None = Field(None, pattern=r"^(avatar:[0-9a-zA-Z-]{1,40}|upload)$")

    bio: str = Field("", max_length=1000)
    prompts: dict[str, str] = Field(default_factory=dict, description='질문형 소개 {"주말에 주로 하는 일은?": "..."}')

    preferences: Preferences = Field(default_factory=Preferences)

    @field_validator("name", "occupation")
    @classmethod
    def _not_blank(cls, v: str):
        if not v.strip():
            raise ValueError("빈 값은 입력할 수 없습니다.")
        return v.strip()

    @field_validator("city")
    @classmethod
    def _check_city(cls, v: str):
        if v not in C.REGIONS:
            raise ValueError(f"지역은 {list(C.REGIONS)} 중 하나여야 합니다.")
        return v

    @field_validator("mbti")
    @classmethod
    def _check_mbti(cls, v: str | None):
        if v is None or v == "":
            return None
        v = v.upper()
        if not MBTI_RE.match(v):
            raise ValueError("MBTI 형식이 올바르지 않습니다 (예: ENFP).")
        return v

    @field_validator("interests")
    @classmethod
    def _check_interests(cls, v: list[str]):
        cleaned = list(dict.fromkeys(tag.strip() for tag in v if tag.strip()))
        unknown = [tag for tag in cleaned if tag not in C.INTERESTS]
        if unknown:
            raise ValueError(f"목록에 없는 관심사입니다: {unknown}")
        if len(cleaned) > C.MAX_INTERESTS:
            raise ValueError(f"관심사는 최대 {C.MAX_INTERESTS}개까지 선택할 수 있습니다.")
        return cleaned

    @model_validator(mode="after")
    def _check_district(self):
        if self.district and self.district not in C.REGIONS[self.city]:
            raise ValueError(f"{self.city}에 없는 구/시입니다: {self.district}")
        return self


class ProfileCreate(ProfileBase):
    """회원가입(프로필 등록) 요청."""


class Profile(ProfileBase):
    id: int

    @property
    def display_name(self) -> str:
        return self.nickname or self.name
