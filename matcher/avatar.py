"""애니메이션 캐릭터 프로필 사진(SVG)을 코드로 그린다.

seed(문자열)가 같으면 항상 같은 캐릭터가 나오고, seed를 바꾸면 다른 캐릭터가 나온다.
외부 서비스·인터넷 없이 동작하며, 머리 모양·머리색·피부·눈·표정·안경·볼터치·옷 색을 랜덤 조합한다.
"""

import random

from .embedding import fnv1a

BACKGROUNDS = ["#FFE3E8", "#E3F0FF", "#E8F8EC", "#FFF4D6", "#EFE6FF", "#FFE9D9", "#DDF6F6", "#F3F0EA"]
SKINS = ["#FFE0C7", "#F9D3B4", "#F1C29E", "#E4AE85", "#C98E66", "#A86F4C"]
HAIR = ["#2B2321", "#3D2B23", "#5A3B28", "#7A4E2D", "#A9744A", "#D8B06A", "#E9C78F", "#8C8C99"]
ANIME_HAIR = ["#E86A92", "#6C8CE8", "#8E6CE8", "#4FB6A6", "#F08A4B"]  # 가끔 나오는 애니 색
EYES = ["#3B2A20", "#5A3E2B", "#2E4C7A", "#3D6B4F", "#6B3D7A", "#7A4A2E"]
SHIRTS = ["#F2476B", "#5B8DEF", "#47B881", "#F5A623", "#9B6CF0", "#2EC4B6", "#EF7A5B", "#3A4A6B"]


class _Rng:
    """mulberry32 난수. 웹 버전(local-api.js)과 똑같은 순서로 같은 값이 나와서 같은 캐릭터가 그려진다."""

    def __init__(self, seed: str):
        self.a = fnv1a(seed)

    def random(self) -> float:
        m = 0xFFFFFFFF
        self.a = (self.a + 0x6D2B79F5) & m
        a = self.a
        t = ((a ^ (a >> 15)) * (1 | a)) & m
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & m)) & m) ^ t
        return ((t ^ (t >> 14)) & m) / 4294967296

    def choice(self, items):
        return items[int(self.random() * len(items))]


def _rng(seed: str) -> _Rng:
    return _Rng(seed)


def _hair_back(style: str, color: str) -> str:
    """얼굴 뒤로 가는 머리 (긴 머리·단발·묶음)."""
    if style == "long":
        return f'<path d="M24 58 Q22 22 60 20 Q98 22 96 58 L100 112 Q60 122 20 112 Z" fill="{color}"/>'
    if style == "bob":
        return f'<path d="M26 56 Q24 22 60 20 Q96 22 94 56 L96 88 Q86 96 76 90 L44 90 Q34 96 24 88 Z" fill="{color}"/>'
    if style == "ponytail":
        return f'<path d="M88 40 Q112 52 104 92 Q100 100 94 92 Q100 64 84 50 Z" fill="{color}"/>'
    if style == "bun":
        return f'<circle cx="60" cy="18" r="13" fill="{color}"/>'
    return ""


def _hair_front(style: str, color: str) -> str:
    """앞머리·윗머리."""
    if style in ("long", "bob", "ponytail", "bun"):
        return (
            f'<path d="M30 54 Q28 24 60 22 Q92 24 90 54 Q84 40 72 36 Q66 46 52 44 Q44 50 36 46 Q32 50 30 54 Z" fill="{color}"/>'
        )
    if style == "spiky":
        return (
            f'<path d="M30 52 L28 34 L38 38 L40 22 L50 32 L58 16 L64 30 L74 18 L78 34 L90 28 L90 52 '
            f'Q80 40 60 40 Q40 40 30 52 Z" fill="{color}"/>'
        )
    if style == "side":
        return f'<path d="M30 54 Q26 24 60 22 Q94 24 90 50 Q74 34 46 38 Q36 42 30 54 Z" fill="{color}"/>'
    if style == "curly":
        bumps = "".join(f'<circle cx="{x}" cy="{y}" r="9" fill="{color}"/>' for x, y in [(34, 40), (44, 30), (56, 26), (68, 26), (80, 30), (88, 40)])
        return bumps + f'<path d="M28 50 Q30 34 60 32 Q90 34 92 50 Q76 42 60 42 Q44 42 28 50 Z" fill="{color}"/>'
    # buzz
    return f'<path d="M32 50 Q30 26 60 24 Q90 26 88 50 Q74 40 60 40 Q46 40 32 50 Z" fill="{color}" opacity=".9"/>'


def _eyes(kind: str, color: str) -> str:
    if kind == "happy":  # 웃는 눈 ^^
        return (
            '<path d="M42 64 Q47 58 52 64" stroke="#2B2321" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
            '<path d="M68 64 Q73 58 78 64" stroke="#2B2321" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
        )
    if kind == "dot":
        return '<circle cx="47" cy="63" r="3.4" fill="#2B2321"/><circle cx="73" cy="63" r="3.4" fill="#2B2321"/>'
    # anime: 큰 눈 + 하이라이트
    eye = ""
    for cx in (47, 73):
        eye += (
            f'<ellipse cx="{cx}" cy="63" rx="6" ry="7.5" fill="#fff"/>'
            f'<ellipse cx="{cx}" cy="64" rx="4.6" ry="6" fill="{color}"/>'
            f'<ellipse cx="{cx}" cy="65" rx="2.4" ry="3.2" fill="#1d1414"/>'
            f'<circle cx="{cx + 1.8}" cy="61" r="1.8" fill="#fff"/>'
            f'<path d="M{cx - 6.5} 57 Q{cx} 54 {cx + 6.5} 57" stroke="#2B2321" stroke-width="2" fill="none" stroke-linecap="round"/>'
        )
    return eye


def _mouth(kind: str) -> str:
    if kind == "open":
        return '<path d="M53 78 Q60 88 67 78 Z" fill="#B5414F"/><path d="M55 79 Q60 82 65 79" fill="#fff"/>'
    if kind == "small":
        return '<ellipse cx="60" cy="80" rx="3" ry="2.4" fill="#C2505E"/>'
    if kind == "cat":
        return '<path d="M53 78 Q56.5 82 60 78 Q63.5 82 67 78" stroke="#8A3B44" stroke-width="2" fill="none" stroke-linecap="round"/>'
    return '<path d="M52 77 Q60 85 68 77" stroke="#8A3B44" stroke-width="2.4" fill="none" stroke-linecap="round"/>'


def avatar_svg(seed: str, gender: str | None = None) -> str:
    r = _rng(seed)
    bg = r.choice(BACKGROUNDS)
    skin = r.choice(SKINS)
    hair_color = r.choice(ANIME_HAIR) if r.random() < 0.15 else r.choice(HAIR)
    if gender == "남성":
        style = r.choice(["spiky", "side", "curly", "buzz", "side", "spiky"])
    elif gender == "여성":
        style = r.choice(["long", "bob", "ponytail", "bun", "long", "curly"])
    else:
        style = r.choice(["spiky", "side", "curly", "long", "bob", "ponytail"])
    eyes = r.choice(["anime", "anime", "anime", "happy", "dot"])
    mouth = r.choice(["smile", "smile", "open", "small", "cat"])
    shirt = r.choice(SHIRTS)
    blush = r.random() < 0.6
    glasses = r.random() < 0.2
    earrings = gender == "여성" and r.random() < 0.35

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">',
        f'<rect width="120" height="120" fill="{bg}"/>',
        _hair_back(style, hair_color),
        # 목 · 옷
        f'<rect x="52" y="86" width="16" height="14" fill="{skin}"/>',
        f'<path d="M22 120 Q24 98 52 96 L68 96 Q96 98 98 120 Z" fill="{shirt}"/>',
        f'<path d="M52 96 L60 106 L68 96" fill="{skin}"/>',
        # 귀 · 얼굴
        f'<ellipse cx="31" cy="64" rx="5" ry="7" fill="{skin}"/><ellipse cx="89" cy="64" rx="5" ry="7" fill="{skin}"/>',
        f'<ellipse cx="60" cy="60" rx="29" ry="31" fill="{skin}"/>',
    ]
    if earrings:
        parts.append('<circle cx="31" cy="73" r="2.6" fill="#F5C542"/><circle cx="89" cy="73" r="2.6" fill="#F5C542"/>')
    parts.append(_eyes(eyes, r.choice(EYES)))
    if blush:
        parts.append('<ellipse cx="40" cy="74" rx="5.5" ry="3" fill="#FF8FA3" opacity=".45"/>'
                     '<ellipse cx="80" cy="74" rx="5.5" ry="3" fill="#FF8FA3" opacity=".45"/>')
    parts.append(_mouth(mouth))
    if glasses:
        parts.append(
            '<g fill="none" stroke="#2B2321" stroke-width="2"><circle cx="47" cy="64" r="9"/><circle cx="73" cy="64" r="9"/>'
            '<path d="M56 64 L64 64"/></g>'
        )
    parts.append(_hair_front(style, hair_color))
    parts.append("</svg>")
    return "".join(parts)


def new_seed() -> str:
    return f"{random.getrandbits(40):x}"
