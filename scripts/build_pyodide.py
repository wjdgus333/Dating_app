"""Pyodide(브라우저 안 Python) 버전을 index.html 한 파일로 만들기.

사용법:
    python scripts/build_pyodide.py            # → web/dist/index.html

이 파일 하나를 깃허브 저장소 맨 위에 올리고 GitHub Pages를 켜면,
주소만 쳐서 브라우저 안에서 matcher/ 의 Python 코드가 그대로 돌아간다.

들어가는 것
  - 화면: app/static/index.html · style.css · app.js (서버 버전과 같은 화면)
  - 연결부: web/pyodide-api.js (Python 실행기 로딩, 요청 전달, localStorage 저장)
  - Python 소스: matcher/*.py, web/pyodide_api.py
  - 샘플 데이터: data/sample_profiles.json, data/sample_social.json
Python 실행기(Pyodide)와 pydantic은 처음 열 때 jsDelivr에서 내려받는다.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

STATIC = ROOT / "app" / "static"
OUT = ROOT / "web" / "dist" / "index.html"

# 브라우저에서 필요 없는 모듈은 뺀다 (envfile: .env 읽기 / 서버 전용)
SKIP = {"matcher/envfile.py"}


def bundle_files() -> dict[str, str]:
    files = {}
    for path in sorted((ROOT / "matcher").glob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel not in SKIP:
            files[rel] = path.read_text(encoding="utf-8")
    for rel in ("web/__init__.py", "web/pyodide_api.py", "data/sample_profiles.json", "data/sample_social.json"):
        files[rel] = (ROOT / rel).read_text(encoding="utf-8")
    return files


def build_html() -> str:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    glue = (ROOT / "web" / "pyodide-api.js").read_text(encoding="utf-8")
    bundle = json.dumps({"files": bundle_files()}, ensure_ascii=False).replace("</", "<\\/")

    def swap(tag: str, new: str):
        nonlocal html
        assert tag in html, f"index.html 에서 {tag} 를 찾지 못했어요"
        html = html.replace(tag, new)

    swap("<title>소개팅 매칭</title>", "<title>소개팅 매칭 (Python)</title>")
    swap('<link rel="stylesheet" href="static/style.css">', f"<style>\n{css}\n</style>")
    swap(
        '<script src="static/app.js"></script>',
        f"<script>window.PY_BUNDLE = {bundle};</script>\n<script>\n{glue}\n</script>\n<script>\n{app}\n</script>",
    )
    return html


def build(out: Path = OUT) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(), encoding="utf-8")
    return out


if __name__ == "__main__":
    out = build()
    print(f"Pyodide 버전을 만들었어요 → {out} ({out.stat().st_size // 1024}KB)")
    print("Python 소스:", ", ".join(k for k in bundle_files() if k.endswith(".py")))
