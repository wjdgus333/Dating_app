"""가상 프로필을 랜덤으로 만들어 추가하기.

사용법:
    python scripts/generate_profiles.py                    # 남녀 각 20명을 지금 데이터에 추가
    python scripts/generate_profiles.py --male 5 --female 8
    python scripts/generate_profiles.py --seed 7           # 다른 조합으로 만들기 (같은 seed면 같은 결과)
    python scripts/generate_profiles.py --sample           # 새로 받은 사람이 처음 보는 샘플(sample_profiles.json)에 추가

기존 데이터는 지우지 않고 뒤에 이어 붙인다.
  - 서버가 켜져 있으면 API(/api/profiles)로 추가한다. (파일을 직접 고치면 실행 중인 서버가 덮어쓸 수 있어서)
  - 서버가 꺼져 있으면 백업을 남기고 data/profiles.json 에 추가한다.
"""

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from matcher.envfile import load_env  # noqa: E402

load_env()

from matcher import config as C  # noqa: E402
from matcher import persist  # noqa: E402
from matcher.models import Profile, ProfileCreate  # noqa: E402

SURNAMES = list("김김김이이이박박최정강조윤장임한오서신권황안송류홍전고문양손배백허남심노하곽성차주우구민유나진")
MALE_NAMES = ["민준", "서준", "도윤", "예준", "시우", "하준", "주원", "지호", "지후", "준우", "준서", "건우", "현우", "우진", "선우",
              "연우", "유준", "정우", "승우", "승현", "시윤", "준혁", "은우", "지환", "승민", "지훈", "민재", "윤호", "태민", "성민",
              "재원", "동현", "상우", "형준", "준영", "태현", "민혁", "재현", "영훈", "진우"]
FEMALE_NAMES = ["서연", "서윤", "지우", "서현", "민서", "하은", "하윤", "윤서", "지유", "지민", "채원", "수아", "지아", "지윤", "다은",
                "은서", "예은", "수빈", "소율", "예린", "지안", "하린", "유나", "가은", "시은", "예원", "나연", "다인", "소연", "혜원",
                "수연", "민지", "유진", "은지", "현지", "세아", "보람", "아름", "정민", "소희"]

OCCUPATIONS = {
    "고졸": ["카페 사장", "헤어 디자이너", "요리사", "자영업", "물류 관리", "제빵사", "운동 트레이너"],
    "전문대졸": ["간호사", "치위생사", "물리치료사", "요리사", "바리스타", "웹 퍼블리셔", "항공 승무원", "필라테스 강사"],
    "대졸": ["백엔드 개발자", "프론트엔드 개발자", "마케터", "UX 디자이너", "공무원", "초등학교 교사", "회계 담당", "영업 관리",
             "기자", "MD", "인사 담당", "서비스 기획자", "영상 편집자", "은행원", "건축 설계사", "약사", "경찰관"],
    "석사": ["데이터 분석가", "연구원", "AI 엔지니어", "상담 심리사", "변리사", "컨설턴트", "도시 계획가"],
    "박사": ["대학 연구교수", "의사", "제약 연구원", "수의사", "연구소 책임연구원"],
}
EDU_WEIGHTS = {"고졸": 8, "전문대졸": 14, "대졸": 55, "석사": 16, "박사": 7}

# 관심사별 자기소개 문장 — 자기소개 유사도가 관심사와 어느 정도 맞도록
INTEREST_SENTENCES = {
    "여행": ["시간 날 때마다 짧게라도 여행을 떠나요.", "가 보지 않은 도시를 걷는 걸 좋아해요."],
    "맛집": ["새로 생긴 맛집 찾아다니는 게 낙이에요.", "맛있는 거 먹으러 멀리 가는 것도 괜찮아요."],
    "카페": ["조용한 카페에서 커피 마시며 쉬는 시간이 좋아요.", "동네 카페 탐방이 취미예요."],
    "영화": ["주말엔 영화 한 편 보고 이야기 나누는 걸 좋아해요.", "영화관 가는 걸 좋아하고 장르는 가리지 않아요."],
    "드라마": ["재밌는 드라마 정주행하는 게 힐링이에요.", "드라마 추천 주고받는 거 좋아해요."],
    "음악": ["출퇴근길엔 늘 음악을 들어요.", "좋아하는 노래 공유하는 걸 좋아해요."],
    "공연": ["뮤지컬이나 콘서트 보러 자주 가요.", "공연장 분위기를 좋아해요."],
    "전시": ["전시회 보러 미술관 다니는 걸 좋아해요.", "새로운 전시 소식은 꼭 챙겨 봐요."],
    "독서": ["카페에서 책 읽는 시간을 좋아해요.", "한 달에 두세 권은 꼭 읽으려고 해요."],
    "글쓰기": ["틈틈이 짧은 글을 쓰고 있어요.", "일기 쓰는 습관이 있어요."],
    "운동": ["몸 움직이는 걸 좋아해요.", "운동하고 나서 개운한 느낌을 좋아해요."],
    "헬스": ["퇴근 후 헬스장은 거의 매일 가요.", "꾸준히 헬스하면서 체력 관리해요."],
    "러닝": ["한강에서 러닝하는 게 루틴이에요.", "주말 아침엔 꼭 뛰어요."],
    "등산": ["주말에 가까운 산에 오르는 걸 좋아해요.", "정상에서 보는 풍경 때문에 등산해요."],
    "요가": ["요가로 하루를 마무리해요.", "요가하면서 마음을 정리해요."],
    "필라테스": ["필라테스 다닌 지 꽤 됐어요.", "자세 교정하려고 필라테스를 해요."],
    "수영": ["아침 수영으로 하루를 시작해요.", "수영장 가는 걸 좋아해요."],
    "자전거": ["자전거 타고 한강 따라 달리는 걸 좋아해요.", "주말엔 자전거 라이딩을 가요."],
    "캠핑": ["캠핑 가서 불멍하는 시간을 좋아해요.", "날씨 좋을 땐 캠핑을 떠나요."],
    "골프": ["요즘 골프에 빠져 있어요.", "스크린 골프도 자주 쳐요."],
    "게임": ["퇴근하고 게임 한 판 하는 게 소소한 낙이에요.", "같이 게임할 사람이면 좋겠어요."],
    "보드게임": ["친구들이랑 보드게임 카페 자주 가요.", "보드게임 규칙 설명 잘해요."],
    "요리": ["집에서 요리해 먹는 걸 좋아해요.", "새 레시피 도전하는 게 재밌어요."],
    "베이킹": ["주말엔 쿠키나 빵을 구워요.", "베이킹해서 나눠 주는 걸 좋아해요."],
    "와인": ["좋은 와인 한 잔과 대화를 좋아해요.", "와인바 찾아다니는 걸 좋아해요."],
    "사진": ["필름 카메라로 사진 찍는 게 취미예요.", "산책하면서 사진 찍는 걸 좋아해요."],
    "반려동물": ["강아지랑 함께 살고 있어요.", "고양이 집사예요."],
    "패션": ["옷 구경하고 코디하는 걸 좋아해요.", "쇼핑하러 다니는 것도 좋아해요."],
    "재테크": ["요즘 재테크 공부를 하고 있어요.", "경제 뉴스 챙겨 보는 편이에요."],
    "봉사": ["한 달에 한 번 봉사활동을 해요.", "유기견 보호소 봉사를 다녀요."],
}
STYLE_SENTENCES = {
    "활동적인 야외": "데이트는 밖에서 활동적으로 하는 걸 좋아해요.",
    "맛집·카페": "맛있는 거 먹고 카페에서 이야기하는 데이트가 좋아요.",
    "문화생활": "전시나 공연 같이 보러 가는 데이트를 좋아해요.",
    "집에서 편하게": "집에서 편하게 영화 보는 데이트도 좋아요.",
}
GOAL_SENTENCES = {
    "진지한 연애": "진지하게 만날 사람을 찾고 있어요.",
    "결혼 전제": "결혼을 생각하며 만나고 싶어요.",
    "가벼운 만남": "부담 없이 먼저 알아가고 싶어요.",
    "친구부터": "친구처럼 편하게 시작하고 싶어요.",
}
PROMPTS = ["주말에 주로 하는 일은?", "요즘 빠져 있는 것", "이상적인 데이트", "나를 한 문장으로"]


def maybe(rng: random.Random, value, missing: float = 0.1):
    """일부 항목은 일부러 비워 둔다 (정보 미입력 상황 테스트)."""
    return None if rng.random() < missing else value


def make_profile(rng: random.Random, gender: str, used_names: set[str]) -> dict:
    names = MALE_NAMES if gender == "남성" else FEMALE_NAMES
    while True:
        name = rng.choice(SURNAMES) + rng.choice(names)
        if name not in used_names:
            used_names.add(name)
            break

    age = rng.randint(23, 38)
    education = rng.choices(list(EDU_WEIGHTS), weights=list(EDU_WEIGHTS.values()))[0]
    city = rng.choices(list(C.REGIONS), weights=[50, 25, 10, 10, 5])[0]
    height = rng.randint(168, 188) if gender == "남성" else rng.randint(153, 172)
    interests = rng.sample(C.INTERESTS, rng.randint(2, 7))
    date_style = rng.choice(C.DATE_STYLES)
    goal = rng.choices(C.RELATIONSHIP_GOALS, weights=[45, 25, 10, 20])[0]

    sentences = [rng.choice(INTEREST_SENTENCES[t]) for t in rng.sample(interests, min(3, len(interests)))]
    sentences += [STYLE_SENTENCES[date_style], GOAL_SENTENCES[goal]]
    prompt_q = rng.choice(PROMPTS)
    prompt_a = rng.choice(INTEREST_SENTENCES[interests[0]]).rstrip(".")

    mbti = "".join(rng.choice(pair) for pair in ("EI", "NS", "TF", "JP"))
    target = "여성" if gender == "남성" else "남성"
    if rng.random() < 0.05:  # 소수는 동성 희망
        target = gender

    prefs = {"target_genders": [target], "dealbreakers": [], "weights": {}, "bonus_rules": []}
    # 거르기 조건 (일부만)
    if rng.random() < 0.5:
        lo = max(19, age - rng.randint(3, 6))
        prefs["dealbreakers"] += [{"field": "age", "op": "min", "value": lo}, {"field": "age", "op": "max", "value": age + rng.randint(3, 6)}]
    if rng.random() < 0.35:
        prefs["dealbreakers"].append({"field": "smoking", "op": "exclude", "value": ["흡연"]})
    if rng.random() < 0.1:
        prefs["dealbreakers"].append({"field": "interests", "op": "exclude", "value": [rng.choice(["게임", "골프", "와인"])]})
    # 중요도 (일부 항목만 바꿈)
    for key in rng.sample(list(C.SCORE_CATEGORIES), rng.randint(0, 3)):
        prefs["weights"][key] = rng.choice([0, 5, 15, 20])
    # 추가 점수 · 감점 (일부만)
    if rng.random() < 0.3:
        prefs["bonus_rules"].append({"field": "interests", "op": "in", "value": rng.sample(interests, 1), "points": rng.choice(C.BONUS_POINTS)})
    if rng.random() < 0.2:
        prefs["bonus_rules"].append({"field": "drinking", "op": "in", "value": ["자주"], "points": -rng.choice(C.BONUS_POINTS)})

    profile = {
        "name": name,
        "gender": gender,
        "age": age,
        "city": city,
        "district": maybe(rng, rng.choice(C.REGIONS[city]), 0.15),
        "height": maybe(rng, height, 0.15),
        "education": education,
        "occupation": rng.choice(OCCUPATIONS[education]),
        "verified": rng.random() < 0.5,
        "smoking": maybe(rng, rng.choices(C.SMOKING, weights=[70, 15, 15])[0]),
        "drinking": maybe(rng, rng.choices(C.DRINKING, weights=[20, 60, 20])[0]),
        "religion": maybe(rng, rng.choices(C.RELIGION, weights=[55, 20, 10, 10, 5])[0]),
        "exercise": maybe(rng, rng.choice(C.EXERCISE)),
        "mbti": maybe(rng, mbti, 0.15),
        "interests": interests,
        "contact_frequency": maybe(rng, rng.choice(C.CONTACT_FREQUENCY)),
        "date_style": date_style,
        "relationship_goal": goal,
        "bio": " ".join(sentences),
        "prompts": {prompt_q: prompt_a},
        "preferences": prefs,
    }
    ProfileCreate.model_validate(profile)  # 만든 데이터가 규칙에 맞는지 확인
    return profile


def generate(n_male: int, n_female: int, seed: int, existing_names: set[str]) -> list[dict]:
    rng = random.Random(seed)
    used = set(existing_names)
    people = [make_profile(rng, "남성", used) for _ in range(n_male)] + [make_profile(rng, "여성", used) for _ in range(n_female)]
    rng.shuffle(people)
    return people


def server_url(port: int) -> str | None:
    url = f"http://127.0.0.1:{port}"
    try:
        urllib.request.urlopen(f"{url}/api/options", timeout=2)
        return url
    except (urllib.error.URLError, OSError):
        return None


def add_via_api(url: str, people: list[dict]) -> list[int]:
    ids = []
    for p in people:
        req = urllib.request.Request(
            f"{url}/api/profiles", data=json.dumps(p, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req) as res:
            ids.append(json.loads(res.read())["id"])
    return ids


def add_to_file(path: Path, people: list[dict]) -> list[int]:
    data = persist.read_json(path)
    next_id = max((p["id"] for p in data), default=0) + 1
    ids = []
    for p in people:
        data.append(Profile(id=next_id, **p).model_dump(mode="json"))
        ids.append(next_id)
        next_id += 1
    persist.write_json(path, data)
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--male", type=int, default=20)
    parser.add_argument("--female", type=int, default=20)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--sample", action="store_true", help="data/sample_profiles.json 에 추가")
    args = parser.parse_args()

    if args.sample:
        path = persist.PROJECT_DATA / "sample_profiles.json"
        names = {p["name"] for p in persist.read_json(path)}
        people = generate(args.male, args.female, args.seed, names)
        ids = add_to_file(path, people)
        print(f"샘플 데이터에 {len(ids)}명 추가 (id {ids[0]}~{ids[-1]}) → {path}")
        return

    url = server_url(args.port)
    if url:
        names = {p["name"] for p in json.loads(urllib.request.urlopen(f"{url}/api/profiles").read())}
        people = generate(args.male, args.female, args.seed, names)
        ids = add_via_api(url, people)
        print(f"실행 중인 서버({url})에 {len(ids)}명 추가 (id {ids[0]}~{ids[-1]})")
    else:
        path = persist.data_dir() / "profiles.json"
        persist.ensure_file(path, persist.PROJECT_DATA / "sample_profiles.json")
        kept = persist.backup(path, "before-generate")
        names = {p["name"] for p in persist.read_json(path)}
        people = generate(args.male, args.female, args.seed, names)
        ids = add_to_file(path, people)
        print(f"{path}에 {len(ids)}명 추가 (id {ids[0]}~{ids[-1]}), 백업: {kept}")

    men = sum(p["gender"] == "남성" for p in people)
    print(f"  남성 {men}명 · 여성 {len(people) - men}명")


if __name__ == "__main__":
    main()
