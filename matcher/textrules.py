"""문장으로 적은 '거르는 조건'을 절대조건 후보로 바꾸기 (규칙 기반, 설치 필요 없음).

예) "담배 피우는 사람은 싫어요. 술 자주 마시는 사람도 별로고, 게임 좋아하는 사람은 패스. 27살 이상이었으면 좋겠어요."
  → 흡연: 비흡연만 허용 / 음주: 자주 제외 / 관심사에 게임 있으면 제외 / 나이 27 이상

자동으로 바로 적용하지 않고 '후보'로만 돌려준다. 사용자가 확인하고 추가해야 적용된다.
(문장을 잘못 이해해서 사람을 몰래 거르는 일을 막기 위해서)
"""

import re

from . import config as C

NEGATIVE = ["싫", "별로", "안 돼", "안돼", "사절", "제외", "패스", "노노", "거를", "거름", "거르", "빼고", "못 만나", "피하고", "어려워", "힘들", "x", "✕", "❌"]
REQUIRE = ["만 ", "만요", "만!", "만.", "필수", "꼭", "였으면", "이었으면", "했으면", "좋겠"]

RELIGION_WORDS = {"기독교": "기독교", "교회": "기독교", "천주교": "천주교", "성당": "천주교", "불교": "불교", "절에": "불교"}


def _has(sentence: str, words: list[str]) -> bool:
    s = sentence.lower() + " "
    return any(w in s for w in words)


def _split(text: str) -> list[str]:
    parts = re.split(r"[.\n!?;,]|그리고|그리구", text)
    return [p.strip() for p in parts if p.strip()]


def parse(text: str) -> dict:
    rules: list[dict] = []
    unmatched: list[str] = []

    def add(field, op, value, source):
        for r in rules:
            if r["field"] == field and r["op"] == op:
                if isinstance(value, list):
                    r["value"] = sorted(set(r["value"]) | set(value), key=C.DEALBREAKER_CHOICES[field].index)
                else:
                    r["value"] = value
                return
        rules.append({"field": field, "op": op, "value": value, "source": source})

    for sentence in _split(text):
        before = len(rules), sum(len(r["value"]) if isinstance(r["value"], list) else 1 for r in rules)
        negative = _has(sentence, NEGATIVE)
        require = _has(sentence, REQUIRE)

        # 흡연
        if "비흡연" in sentence or re.search(r"(담배|흡연)", sentence) and (negative or re.search(r"안\s?(피|펴)", sentence)):
            add("smoking", "require", ["비흡연"], sentence)

        # 음주
        if "술" in sentence or "음주" in sentence:
            if re.search(r"(안|못)\s?마시", sentence) and require:
                add("drinking", "require", ["안 마심"], sentence)
            elif re.search(r"(자주|많이|매일|좋아하는|즐기는)", sentence) and negative:
                add("drinking", "exclude", ["자주"], sentence)
            elif negative:
                add("drinking", "require", ["안 마심"], sentence)

        # 종교
        for word, religion in RELIGION_WORDS.items():
            if word in sentence:
                if negative:
                    add("religion", "exclude", [religion], sentence)
                elif require:
                    add("religion", "require", [religion], sentence)

        # 관심사
        tags = [t for t in C.INTERESTS if t in sentence]
        if tags:
            if negative:
                add("interests", "exclude", tags, sentence)
            elif require:
                add("interests", "require", tags, sentence)

        # 나이: "25~33살", "27살 이상", "35세 이하"
        m = re.search(r"(\d{2})\s?[~\-]\s?(\d{2})\s?(살|세)", sentence)
        if m:
            add("age", "min", int(m.group(1)), sentence)
            add("age", "max", int(m.group(2)), sentence)
        else:
            for num, _, direction in re.findall(r"(\d{2})\s?(살|세)\s?(이상|이하|넘|미만|까지|부터)", sentence):
                op = "min" if direction in ("이상", "부터") else "max"
                add("age", op, int(num), sentence)

        # 키: "키 175 이상"
        for num, direction in re.findall(r"키\D{0,4}(\d{3})\s?(?:cm)?\s?(이상|이하)", sentence):
            add("height", "min" if direction == "이상" else "max", int(num), sentence)

        after = len(rules), sum(len(r["value"]) if isinstance(r["value"], list) else 1 for r in rules)
        if after == before:
            unmatched.append(sentence)

    return {"rules": rules, "unmatched": unmatched}
