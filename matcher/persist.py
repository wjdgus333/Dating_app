"""데이터를 잃지 않게 저장하는 도구.

- 데이터 폴더: 기본은 프로젝트의 data/ . 환경변수 MATCH_DATA_DIR 로 다른 곳(예: 문서 폴더)을 지정할 수 있다.
  → 새 버전을 다른 폴더에 받아도 같은 데이터 폴더를 가리키면 그대로 이어서 쓸 수 있다.
- 안전 저장: 임시 파일에 다 쓴 뒤 한 번에 교체한다. 저장 도중 꺼져도 기존 파일이 깨지지 않는다.
- 백업: 서버를 켤 때와 초기화하기 전에 data/backups/ 에 복사본을 남긴다 (최근 30개 보관).
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_DATA = Path(__file__).resolve().parent.parent / "data"  # 샘플 파일이 있는 곳 (코드와 함께 배포)


def data_dir() -> Path:
    path = Path(os.getenv("MATCH_DATA_DIR") or PROJECT_DATA).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


KEEP_BACKUPS = 30


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    """안전 저장: 같은 폴더의 임시 파일에 쓰고 os.replace로 교체 (교체는 한 번에 일어난다)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def backup(path: Path, reason: str) -> Path | None:
    """path의 복사본을 backups/에 남기고 오래된 것은 정리한다."""
    if not path.exists():
        return None
    folder = path.parent / "backups"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"{path.stem}-{stamp}-{reason}{path.suffix}"
    shutil.copy2(path, target)
    old = sorted(folder.glob(f"{path.stem}-*{path.suffix}"))
    for f in old[:-KEEP_BACKUPS]:
        f.unlink()
    return target


def ensure_file(path: Path, sample: Path) -> None:
    """데이터 파일이 없을 때만 샘플로 시작한다. 이미 있으면 절대 덮어쓰지 않는다."""
    if not path.exists():
        shutil.copy(sample, path)
