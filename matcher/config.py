"""선택지·점수 항목·기본값 등 설정 모음.

선택지를 바꾸거나 점수 항목을 추가하고 싶으면 이 파일부터 수정하면 된다.
"""

# ── 프로필 선택지 ───────────────────────────────────────────
GENDERS = ["남성", "여성"]

# 학력은 순서가 있어서 거르기에서 '대졸 이상'처럼 쓸 수 있다.
EDUCATION = ["고졸", "전문대졸", "대졸", "석사", "박사"]
SMOKING = ["비흡연", "가끔", "흡연"]
DRINKING = ["안 마심", "가끔", "자주"]
EXERCISE = ["안 함", "주 1~2회", "주 3회 이상"]
CONTACT_FREQUENCY = ["적게", "보통", "자주"]

RELIGION = ["무교", "기독교", "천주교", "불교", "기타"]
DATE_STYLES = ["활동적인 야외", "맛집·카페", "문화생활", "집에서 편하게"]
RELATIONSHIP_GOALS = ["진지한 연애", "결혼 전제", "가벼운 만남", "친구부터"]

REGIONS = {
    "서울": ["강남구", "서초구", "송파구", "마포구", "용산구", "성동구", "관악구", "영등포구", "강서구", "노원구"],
    "경기": ["성남시", "수원시", "고양시", "용인시", "부천시", "안양시"],
    "인천": ["연수구", "남동구", "부평구"],
    "부산": ["해운대구", "수영구", "부산진구"],
    "대전": ["유성구", "서구"],
}

INTERESTS = [
    "여행", "맛집", "카페", "영화", "드라마", "음악", "공연", "전시", "독서", "글쓰기",
    "운동", "헬스", "러닝", "등산", "요가", "필라테스", "수영", "자전거", "캠핑", "골프",
    "게임", "보드게임", "요리", "베이킹", "와인", "사진", "반려동물", "패션", "재테크", "봉사",
]
MAX_INTERESTS = 10

# ── 점수 항목 ───────────────────────────────────────────────
# 점수 = 겹치는 항목마다 '중요도'만큼 더한다. (100점 만점으로 바꾸지 않고 그대로 합산)
#
# key: (화면에 보일 이름, 계산 방식, 화면에 보일 계산 설명)
#   count  : 관심사 — 겹친 개수 × 중요도   (겹칠 때마다 점수)
#   text   : 자기소개 — 문장 유사도가 기준 이상이면 중요도만큼
#   exact  : 같으면 중요도만큼
#   region : 같은 시·도면 중요도만큼
#   age    : 나이 차이가 AGE_MATCH_YEARS살 이내면 중요도만큼
#
# 흡연·음주처럼 '싫으면 아예 안 만나는' 항목은 점수에서 빼고 거르기 조건으로만 쓴다.
SCORE_CATEGORIES = {
    "interests": ("관심사", "count", "겹칠 때마다 +중요도"),
    "bio": ("자기소개", "text", "비슷하면 +중요도"),
    "relationship_goal": ("원하는 관계", "exact", "같으면 +중요도"),
    "region": ("지역", "region", "같은 시·도면 +중요도"),
    "age": ("나이 차이", "age", "3살 이내면 +중요도"),
    "date_style": ("데이트 스타일", "exact", "같으면 +중요도"),
    "contact_frequency": ("연락 빈도", "exact", "같으면 +중요도"),
    "exercise": ("운동 빈도", "exact", "같으면 +중요도"),
    "religion": ("종교", "exact", "같으면 +중요도"),
    "mbti": ("MBTI", "exact", "같으면 +중요도"),
}

# 화면의 중요도 버튼 (점수)
IMPORTANCE_LEVELS = {0: "상관없음", 5: "낮음", 10: "보통", 15: "중요", 20: "매우 중요"}

# 모든 항목의 기본 점수.
DEFAULT_WEIGHT = 10
MAX_WEIGHT = 100

AGE_MATCH_YEARS = 3  # 나이 차이가 이 안이면 '겹침'
BIO_MATCH_THRESHOLD = 0.4  # 자기소개 문장 유사도가 이 이상이면 '겹침'

# ── 절대조건(거르기)에 쓸 수 있는 항목 ──────────────────────
#   exclude : 상대 값이 목록에 있으면 탈락   (예: 흡연 → ["흡연"])
#   require : 상대 값이 목록에 없으면 탈락   (예: 원하는 관계 → ["진지한 연애", "결혼 전제"])
#   min/max : 숫자·순서형 범위를 벗어나면 탈락 (예: 나이 min 25)
# 관심사는 목록이라 의미가 조금 다르다.
#   exclude : 이 관심사 중 하나라도 있으면 탈락 (예: 게임)
#   require : 이 관심사 중 하나도 없으면 탈락   (예: 등산, 캠핑)
DEALBREAKER_FIELDS = {
    "smoking": ("흡연", ["exclude", "require"]),
    "drinking": ("음주", ["exclude", "require"]),
    "interests": ("관심사", ["exclude", "require"]),
    "age": ("나이", ["min", "max"]),
    "height": ("키", ["min", "max"]),
    "education": ("학력", ["min", "require", "exclude"]),
    "city": ("지역(시·도)", ["require", "exclude"]),
    "exercise": ("운동 빈도", ["require", "exclude"]),
    "religion": ("종교", ["require", "exclude"]),
    "relationship_goal": ("원하는 관계", ["require", "exclude"]),
    "date_style": ("데이트 스타일", ["require", "exclude"]),
    "contact_frequency": ("연락 빈도", ["require", "exclude"]),
    "mbti": ("MBTI", ["require", "exclude"]),
}

MBTI_TYPES = [a + b + c + d for a in "EI" for b in "NS" for c in "TF" for d in "JP"]

# 거르기 조건에서 고를 수 있는 값 목록
DEALBREAKER_CHOICES = {
    "smoking": SMOKING,
    "drinking": DRINKING,
    "interests": INTERESTS,
    "education": EDUCATION,
    "city": list(REGIONS),
    "exercise": EXERCISE,
    "religion": RELIGION,
    "relationship_goal": RELATIONSHIP_GOALS,
    "date_style": DATE_STYLES,
    "contact_frequency": CONTACT_FREQUENCY,
    "mbti": MBTI_TYPES,
}

# ── 추가 점수 · 감점 규칙 ──────────────────────────────────
# 거르기와 같은 항목에 "해당하면 +점수"(추가 점수) 또는 "−점수"(감점)를 준다.
# 감점은 points를 음수로 저장한다 (−5 · −10 · −15 · −20).
#   in      : 상대 값이 이 중 하나면 (관심사는 이 중 하나라도 있으면)
#   min/max : 이상 / 이하
BONUS_POINTS = [5, 10, 15, 20]
BONUS_FIELDS = {
    key: (label, ["min", "max"] if key in ("age", "height") else ["in", "min"] if key == "education" else ["in"])
    for key, (label, _) in DEALBREAKER_FIELDS.items()
}
MAX_BONUS_RULES = 40  # 추가 점수 + 감점 합계

# ── 파이프라인 ─────────────────────────────────────────────
# ② 단계: 거르기 후 남은 인원이 이보다 많을 때만 임베딩으로 후보를 줄인다.
CANDIDATE_TOP_K = 100
DEFAULT_TOP_N = 10
