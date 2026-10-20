"""GitHub Pages(웹 버전)용 docs/ 폴더 만들기.

사용법:
    python scripts/build_pages.py

만드는 것
  docs/index.html            app/static/index.html + local-api.js(브라우저 안의 엔진) 연결
  docs/static/*.js, *.css    화면 파일 복사
  docs/static/web-data.json  Python 설정(선택지·점수 항목·문장 규칙·캐릭터 색) + 샘플 데이터
  docs/.nojekyll             GitHub Pages가 파일을 그대로 쓰게 하는 표시

화면이나 설정, 샘플 데이터를 바꾸면 이 스크립트를 다시 실행하고 커밋·푸시하면 된다.
깃허브 저장소 Settings → Pages → Branch: main, 폴더: /docs 로 한 번만 설정해 두면
https://<아이디>.github.io/<저장소>/ 에서 열린다.
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from matcher import avatar, persist, textrules  # noqa: E402
from matcher import config as C  # noqa: E402

STATIC = ROOT / "app" / "static"
DOCS = ROOT / "docs"


def engine_config() -> dict:
    """local-api.js 가 쓰는 설정 — Python 설정에서 그대로 뽑아서 두 버전이 어긋나지 않게 한다."""
    return {
        "OPTIONS": C.options_payload(),
        "GENDERS": C.GENDERS,
        "EDUCATION": C.EDUCATION,
        "REGIONS": C.REGIONS,
        "INTERESTS": C.INTERESTS,
        "MAX_INTERESTS": C.MAX_INTERESTS,
        "SCORE_CATEGORIES": C.SCORE_CATEGORIES,
        "DEFAULT_WEIGHT": C.DEFAULT_WEIGHT,
        "MAX_WEIGHT": C.MAX_WEIGHT,
        "AGE_MATCH_YEARS": C.AGE_MATCH_YEARS,
        "BIO_MATCH_THRESHOLD": C.BIO_MATCH_THRESHOLD,
        "DEALBREAKER_FIELDS": C.DEALBREAKER_FIELDS,
        "DEALBREAKER_CHOICES": C.DEALBREAKER_CHOICES,
        "BONUS_FIELDS": C.BONUS_FIELDS,
        "BONUS_POINTS": C.BONUS_POINTS,
        "MAX_BONUS_RULES": C.MAX_BONUS_RULES,
        "CANDIDATE_TOP_K": C.CANDIDATE_TOP_K,
        "DEFAULT_TOP_N": C.DEFAULT_TOP_N,
        "TEXTRULES": {"NEGATIVE": textrules.NEGATIVE, "REQUIRE": textrules.REQUIRE, "RELIGION_WORDS": textrules.RELIGION_WORDS},
        "AVATAR": {
            "BACKGROUNDS": avatar.BACKGROUNDS,
            "SKINS": avatar.SKINS,
            "HAIR": avatar.HAIR,
            "ANIME_HAIR": avatar.ANIME_HAIR,
            "EYES": avatar.EYES,
            "SHIRTS": avatar.SHIRTS,
        },
    }


def build(out: Path = DOCS) -> Path:
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)

    for name in ("app.js", "style.css", "local-api.js"):
        shutil.copy(STATIC / name, out / "static" / name)

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    marker = '<script src="static/app.js"></script>'
    assert marker in html, "index.html 에서 app.js 를 찾지 못했어요"
    html = html.replace(marker, '<script src="static/local-api.js"></script>\n' + marker)
    # 웹 버전 안내: 종료 화면 문구는 쓰지 않으므로 그대로 둔다.
    (out / "index.html").write_text(html, encoding="utf-8")

    data = {
        "config": engine_config(),
        "sample_profiles": persist.read_json(persist.PROJECT_DATA / "sample_profiles.json"),
        "sample_social": persist.read_json(persist.PROJECT_DATA / "sample_social.json"),
    }
    (out / "static" / "web-data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return out


if __name__ == "__main__":
    out = build()
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    print(f"웹 버전을 만들었어요 → {out}")
    for f in files:
        print("  ", f)
