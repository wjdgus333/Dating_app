"""가상 인물(기본 데이터)의 자동 답장 — 규칙 기반.

내가 보낸 메시지에서 의도(인사·주말·관심사·만남 제안 …)를 키워드로 알아듣고,
답하는 사람의 실제 프로필(관심사·자기소개·데이트 스타일·원하는 관계·MBTI·직업·지역 …)을 넣어 답한다.

- 인터넷·API 키 없이 동작한다 (웹 버전에서도 같은 규칙: app/static/local-api.js 가 RULES 를 그대로 쓴다).
- 같은 대화 같은 차례에는 항상 같은 답이 나온다 (무작위 대신 해시로 고름 → 테스트·웹 버전과 결과 일치).
- 문장을 바꾸고 싶으면 아래 RULES 의 replies 만 고치면 된다. {name} 같은 칸은 context() 가 채운다.
"""

import re

from . import config as C
from .embedding import fnv1a
from .models import Profile

# 위에서부터 차례로 검사해서 처음 걸린 의도로 답한다.
RULES = {
    "intents": [
        {"name": "bye", "keywords": ["잘 자", "잘자", "좋은 밤", "들어가", "다음에 또", "바이", "안녕히"],
         "replies": ["네 {name}도 좋은 밤 보내세요 🌙 내일 또 얘기해요!", "오늘 얘기 즐거웠어요 ㅎㅎ {name} 푹 쉬세요!"]},
        {"name": "date", "keywords": ["만나", "만날", "볼래", "보실래", "데이트", "시간 되", "시간 괜찮", "커피 한", "밥 한", "같이 가",
                                    "가실래", "갈래", "가요?", "하실래", "놀러"],
         "replies": ["좋아요! {date_plan}", "{name}이랑이면 좋아요 ㅎㅎ {date_plan}"]},
        {"name": "greeting", "keywords": ["안녕", "반가", "처음 뵙", "하이", "hi", "hello"],
         "replies": ["안녕하세요 {name}! 연락 주셔서 반가워요 😊 {common}", "반가워요 {name}! {common}"]},
        {"name": "compliment", "keywords": ["예쁘", "이쁘", "멋지", "멋있", "귀엽", "잘생", "매력"],
         "replies": ["앗 감사해요 😳 {name}도 프로필 보고 좋은 분 같다고 생각했어요!", "칭찬 들으니까 기분 좋네요 ㅎㅎ 감사해요!"]},
        {"name": "thanks", "keywords": ["고마", "감사"], "replies": ["저야말로 감사해요 ㅎㅎ", "별말씀을요 😊"]},
        {"name": "mbti", "keywords": ["mbti", "엠비티아이"],
         "replies": ["{mbti_line}"]},
        {"name": "age", "keywords": ["몇 살", "몇살", "나이", "연세"],
         "replies": ["저는 {age}살이에요! {name}은 {partner_age}살이시죠? ㅎㅎ"]},
        {"name": "work", "keywords": ["무슨 일", "직업", "회사", "하시는 일", "일 하", "일하"],
         "replies": ["저는 {occupation} 일을 하고 있어요. {name}은 {partner_job}던데 일은 재밌으세요?"]},
        {"name": "region", "keywords": ["어디 사", "사세요", "동네", "어디세요", "어디에 사"],
         "replies": ["{region_line}"]},
        {"name": "drink", "keywords": ["술", "음주", "한잔", "한 잔"], "replies": ["{drink_line}"]},
        {"name": "smoke", "keywords": ["담배", "흡연"], "replies": ["{smoke_line}"]},
        {"name": "interest", "keywords": [], "replies": ["{interest_line}"]},  # 관심사 이름이 나오면 (keywords 대신 C.INTERESTS)
        {"name": "weekend", "keywords": ["주말", "쉬는 날", "휴일", "취미", "뭐 하세요", "뭐하세요", "뭐 해요", "뭐해요", "뭐 하고", "뭐하고"],
         "replies": ["{weekend_line} {name}은 주말에 주로 뭐 하세요?", "{weekend_line} {name}도 쉬는 날 뭐 하는지 궁금해요!"]},
        {"name": "relationship", "keywords": ["연애", "결혼", "진지", "이상형", "어떤 사람", "어떤 만남"],
         "replies": ["{goal_line} {name}은 어떤 만남을 원하세요?"]},
        {"name": "laugh", "keywords": ["ㅋㅋ", "ㅎㅎ"], "replies": ["ㅎㅎ {name} 재밌으세요 😆", "ㅋㅋㅋ 저도 웃겨요"]},
    ],
    "opener": ["좋아요 고마워요 {name}! 😊 {common}", "매칭돼서 반가워요 {name}! {common}"],
    "fallback": [
        "아 그렇군요 ㅎㅎ {name}은 요즘 뭐에 빠져 계세요?",
        "오 그렇구나! 저는 요즘 {my_interest}에 빠져 있어요 ㅎㅎ",
        "그렇군요 ㅎㅎ 더 얘기해 주세요! 궁금해요",
    ],
    "plans": {
        "맛집·카페": "맛있는 거 먹고 분위기 좋은 카페 가는 건 어때요?",
        "활동적인 야외": "날씨 좋을 때 같이 걷거나 밖에서 활동하는 건 어때요?",
        "문화생활": "전시나 영화 같이 보러 가는 건 어때요?",
        "집에서 편하게": "처음엔 조용한 카페에서 편하게 얘기해 볼까요?",
    },
    "goals": {
        "진지한 연애": "저는 진지하게 오래 만날 사람을 찾고 있어요.",
        "결혼 전제": "저는 결혼까지 생각하면서 신중하게 만나고 싶어요.",
        "가벼운 만남": "저는 부담 없이 먼저 알아가는 게 좋아요 ㅎㅎ",
        "친구부터": "저는 친구처럼 편하게 시작하는 걸 좋아해요.",
    },
    "drinks": {
        "안 마심": "저는 술은 안 마셔요. 대신 카페 데이트 좋아해요 ☕",
        "가끔": "가끔 분위기 좋은 데서 한두 잔 해요 ㅎㅎ",
        "자주": "술자리 좋아해요 ㅎㅎ 맛있는 안주 집도 많이 알아요!",
    },
    "smokes": {
        "비흡연": "저는 담배 안 피워요!",
        "가끔": "가끔 피우긴 하는데 줄이려고 하고 있어요 ㅎㅎ",
        "흡연": "저는 피우는 편이에요. 불편하시면 말씀해 주세요!",
    },
}


# ── 받침에 맞는 조사 (은/는, 이랑/랑) ───────────────────────
def has_batchim(word: str) -> bool:
    if not word:
        return False
    code = ord(word[-1])
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0


def eun(word: str) -> str:
    return word + ("은" if has_batchim(word) else "는")


def rang(word: str) -> str:
    return word + ("이랑" if has_batchim(word) else "랑")


def isi(word: str) -> str:
    """서울 → 서울이시, 부산진구 → 부산진구시 … '…이시죠/…시죠'의 앞부분."""
    return word + ("이시" if has_batchim(word) else "시")


def mentioned_interest(text: str) -> str | None:
    return next((t for t in C.INTERESTS if t in text), None)


def context(me: Profile, partner: Profile, text: str) -> dict:
    """답장 문장의 {칸}을 채울 값. me = 답하는 가상 인물, partner = 메시지를 보낸 사람."""
    name = f"{partner.nickname or partner.name}님"
    shared = [t for t in me.interests if t in partner.interests]
    my_interest = me.interests[0] if me.interests else "산책"

    if shared:
        common = f"저도 {shared[0]} 좋아해서 반가웠어요!"
    else:
        common = "프로필 재밌게 봤어요!"

    if me.mbti:
        mbti_line = f"저는 {me.mbti}예요!"
        if partner.mbti:
            same = sum(a == b for a, b in zip(me.mbti, partner.mbti))
            mbti_line += f" {name}은 {isi(partner.mbti)}던데 " + (
                f"{same}글자나 같네요 ㅎㅎ" if same >= 2 else "저랑 많이 달라서 신기해요 ㅎㅎ"
            )
        else:
            mbti_line += f" {name}은 뭐예요?"
    else:
        mbti_line = f"MBTI는 아직 검사를 안 해 봤어요 ㅎㅎ {name}은 뭐예요?"

    where = f"{me.city} {me.district}" if me.district else me.city
    if partner.city == me.city:
        region_line = f"저는 {where}에 살아요! {name}도 {isi(me.city)}죠? 가까워서 좋네요 ㅎㅎ"
    else:
        region_line = f"저는 {where}에 살아요! {name}은 {isi(partner.city)}죠? 조금 멀지만 괜찮아요 ㅎㅎ"

    topic = mentioned_interest(text)
    if topic and topic in me.interests:
        interest_line = f"{topic} 저도 정말 좋아해요! {name}은 얼마나 자주 하세요?"
    elif topic:
        interest_line = f"{eun(topic)} 아직 잘 몰라요 ㅎㅎ 재밌어요? 저는 {my_interest} 좋아해요."
    else:
        interest_line = ""

    plan = RULES["plans"].get(me.date_style or "", "편한 곳에서 커피 한잔하면서 얘기해 봐요!")
    if topic and topic in me.interests:  # 만남 제안에 활동이 나오면 그걸로 답한다
        date_plan = f"{topic} 저도 좋아해서 같이 하면 재밌겠어요 ㅎㅎ 언제가 편하세요?"
    elif topic:
        date_plan = f"{eun(topic)} 처음이라 기대돼요 ㅎㅎ 끝나고 {plan}"
    else:
        date_plan = plan

    weekend_answer = next((a for q, a in me.prompts.items() if "주말" in q and a), None)
    if weekend_answer:
        weekend_line = f"저는 주말엔 '{weekend_answer}' 이렇게 보내요 ㅎㅎ"
    elif len(me.interests) >= 2:
        weekend_line = f"저는 주말엔 주로 {rang(me.interests[0])} {me.interests[1]} 즐겨요."
    else:
        weekend_line = f"저는 주말엔 주로 {my_interest} 즐겨요."

    return {
        "name": name,
        "common": common,
        "my_interest": my_interest,
        "mbti_line": mbti_line,
        "age": me.age,
        "partner_age": partner.age,
        "occupation": me.occupation,
        "partner_job": isi(partner.occupation),
        "region_line": region_line,
        "drink_line": RULES["drinks"].get(me.drinking or "", "술은 그냥 분위기 따라 조금 마셔요 ㅎㅎ"),
        "smoke_line": RULES["smokes"].get(me.smoking or "", "그 얘긴 만나서 편하게 해요 ㅎㅎ"),
        "plan": plan,
        "date_plan": date_plan,
        "goal_line": RULES["goals"].get(me.relationship_goal or "", "천천히 알아가고 싶어요."),
        "interest_line": interest_line,
        "weekend_line": weekend_line,
    }


def detect_intent(text: str) -> str:
    low = text.lower()
    for intent in RULES["intents"]:
        if intent["name"] == "interest":
            if mentioned_interest(text):
                return "interest"
        elif any(k in low for k in intent["keywords"]):
            return intent["name"]
    return "fallback"


def _pick(options: list[str], me: Profile, partner: Profile, turn: int) -> str:
    return options[fnv1a(f"{me.id}:{partner.id}:{turn}") % len(options)]


def _fill(template: str, ctx: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(ctx[m.group(1)]), template).strip()


def reply(me: Profile, partner: Profile, text: str, turn: int) -> str:
    """me(가상 인물)가 partner의 메시지 text에 답한다. turn = 지금까지 대화 메시지 수 (답 고르기에 씀)."""
    intent = detect_intent(text)
    options = RULES["fallback"] if intent == "fallback" else next(i["replies"] for i in RULES["intents"] if i["name"] == intent)
    return _fill(_pick(options, me, partner, turn), context(me, partner, text))


def opener(me: Profile, partner: Profile, turn: int) -> str:
    """한마디 없이 좋아요만 받았을 때, 매칭되면서 가상 인물이 먼저 건네는 인사."""
    return _fill(_pick(RULES["opener"], me, partner, turn), context(me, partner, ""))
