"""문장 → 벡터(좌표) 변환 = 임베딩.

비슷한 의미의 문장은 가까운 좌표에 놓이므로, 벡터 사이의 코사인 유사도로 '얼마나 비슷한 사람인지'를 잰다.

- HashingEmbedder (기본값): 설치 없이 동작. 글자 2~3개 조각(n-gram)을 세는 방식이라
  '같은 단어를 쓰는지'를 본다. 의미까지는 잘 모른다.
- SentenceTransformerEmbedder: `pip install -r requirements-ai.txt` 후 환경변수
  EMBEDDER=sbert 로 켜면 진짜 의미 기반 임베딩(multilingual-e5-small)을 쓴다.
"""

import math
import os
from collections import Counter
from functools import lru_cache


def fnv1a(text: str) -> int:
    """FNV-1a 32비트 해시. 웹 버전(local-api.js)에서도 똑같이 계산할 수 있어서 결과가 일치한다."""
    h = 0x811C9DC5
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


class HashingEmbedder:
    name = "hashing-ngram"

    def __init__(self, dim: int = 2048):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for gram, count in self._ngrams(text).items():
            idx = fnv1a(gram) % self.dim
            vec[idx] += 1 + math.log(count)
        return _normalize(vec)

    @staticmethod
    def _ngrams(text: str) -> Counter:
        grams: Counter = Counter()
        for word in text.lower().split():
            word = "".join(ch for ch in word if ch.isalnum())
            if not word:
                continue
            padded = f"<{word}>"
            for n in (2, 3):
                for i in range(len(padded) - n + 1):
                    grams[padded[i : i + n]] += 1
        return grams


class SentenceTransformerEmbedder:
    name = "multilingual-e5-small"

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        from sentence_transformers import SentenceTransformer  # 선택 설치

        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode([f"query: {t}" for t in texts], normalize_embeddings=True)
        return [v.tolist() for v in vectors]


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    """두 벡터 모두 정규화되어 있으므로 내적 = 코사인 유사도."""
    return sum(x * y for x, y in zip(a, b))


@lru_cache(maxsize=1)
def get_embedder():
    if os.getenv("EMBEDDER", "").lower() == "sbert":
        try:
            return SentenceTransformerEmbedder()
        except ImportError:
            print("[embedding] sentence-transformers가 없어 기본 임베더를 사용합니다.")
    return HashingEmbedder()


class EmbeddingCache:
    """프로필 텍스트가 바뀌지 않았으면 벡터를 다시 계산하지 않는다."""

    def __init__(self):
        self._cache: dict[str, list[float]] = {}

    def get(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            for t, v in zip(missing, get_embedder().embed(missing)):
                self._cache[t] = v
        return [self._cache[t] for t in texts]


embedding_cache = EmbeddingCache()
