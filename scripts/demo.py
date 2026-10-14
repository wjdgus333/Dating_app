"""터미널에서 추천 결과 보기.

사용법:
    python scripts/demo.py            # 1번 사용자(김민준) 기준
    python scripts/demo.py 11         # 11번 사용자 기준
    python scripts/demo.py 1 --mutual # 쌍방 모드
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from matcher.envfile import load_env  # noqa: E402

load_env()  # .env 의 MATCH_DATA_DIR 등을 저장소보다 먼저 읽는다.

from matcher.pipeline import recommend  # noqa: E402
from matcher.store import ProfileStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id", nargs="?", type=int, default=1)
    parser.add_argument("--mutual", action="store_true", help="상대 입장 점수도 반영")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--llm", action="store_true", help="ANTHROPIC_API_KEY가 있으면 LLM 설명 추가")
    args = parser.parse_args()

    store = ProfileStore()
    me = store.get(args.user_id)
    if not me:
        sys.exit(f"{args.user_id}번 사용자가 없습니다.")

    result = recommend(me, store.all(), mutual=args.mutual, top_n=args.top, use_llm=args.llm)

    print(f"\n=== {me.display_name}님({me.age}세, {me.city})을 위한 추천 ===\n")
    print("[로직 흐름]")
    for line in result["trace"]:
        print(" ", line)

    print("\n[순위]")
    for r in result["ranking"]:
        moved = ""
        if r["rank_with_default_weights"] != r["rank"]:
            moved = f"  (중요도가 모두 보통이었다면 {r['rank_with_default_weights']}위)"
        print(f"  {r['rank']}위 {r['name']} ({r['age']}세, {r['region']}, {r['occupation']}) — {r['score']}점{moved}")
        for h in r["highlights"]:
            print(f"       + {h}")
        for w in r["weak_points"]:
            print(f"       - {w}")
        if r["llm_summary"]:
            print(f"       💬 {r['llm_summary']}")

    print("\n[왜 1위인가]")
    for line in result["why_first"]:
        print(" ", line)

    if result["ranking"]:
        top = result["ranking"][0]
        print(f"\n[1위 점수 계산식] {top['formula']}")
        print(f"  {'항목':<10}{'중요도':>6}{'겹침':>6}{'획득':>8}   근거")
        for b in top["breakdown"]:
            print(f"  {b['label']:<10}{b['weight']:>6}{b['matches']:>6}{b['points']:>8g}   {b['detail']}")

    if result["eliminated"]:
        print("\n[절대조건으로 탈락 — 점수와 무관]")
        for e in result["eliminated"]:
            print(f"  {e['name']} (점수였다면 {e['would_be_score']}점)")
            for reason in e["reasons"]:
                print(f"       ✕ {reason}")
    print()


if __name__ == "__main__":
    main()
