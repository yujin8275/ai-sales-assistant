"""Ollama 로컬 임베딩. DB 저장 전 호출하며, 외부 클라우드를 사용하지 않습니다."""
import math
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')


def embed_chunks(chunks, model=None, batch_size=8):
    """청크마다 실수 벡터를 생성합니다. Ollama /api/embed 사용."""
    model = model or os.getenv('OLLAMA_EMBED_MODEL', 'qwen3-embedding:0.6b')
    base = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    results = []
    dim = None
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        try:
            response = requests.post(
                base + '/api/embed',
                json={'model': model, 'input': [item['content'] for item in batch]},
                timeout=180,
            )
            response.raise_for_status()
            embeddings = response.json()['embeddings']
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise RuntimeError(
                f'Ollama 임베딩 오류: {exc}\n'
                f'로컬 Ollama 실행과 `ollama pull {model}` 설치 여부를 확인하세요.'
            ) from exc
        if len(embeddings) != len(batch):
            raise ValueError('Ollama 임베딩 응답 수가 입력 청크 수와 다릅니다.')
        for vec in embeddings:
            if not vec or any(not math.isfinite(float(x)) for x in vec):
                raise ValueError('비어 있거나 숫자가 아닌 임베딩이 반환되었습니다.')
            if dim is None:
                dim = len(vec)
            if len(vec) != dim:
                raise ValueError('임베딩 차원이 일정하지 않습니다.')
            results.append([float(x) for x in vec])
    return results
