"""에이전트들이 요청마다 읽는 런타임 설정 로더.
Gradio UI → runtime_config.json → 각 에이전트 (재시작 불필요)
"""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "runtime_config.json"

DEFAULTS: dict = {
    "refiner": {
        "prompt_template": (
            "다음 질문을 웹 검색 요청에서 분리하여, 제품 기획 근거로 사용할 수 있는 "
            "간결한 요약 질문으로 정제하세요:\n{question}"
        )
    },
    "responder": {
        "prompt_template": (
            "질문: {refined}\n"
            "다음 세 항목으로만 간결하게 답변하세요:\n"
            "- 기술 트렌드\n"
            "- 공급망 변화\n"
            "- 시장 전망\n"
            "광고성 인트로와 쓸데없는 부연설명은 제외하고, 각 항목을 핵심만 요약하세요."
        ),
        "temperature": 0.3,
    },
    "fact_checker": {
        "max_results": 10,
        "search_query_prefix": "",
    },
    "hallucination_filter": {
        "revision_threshold": "high",
    },
}


def load() -> dict:
    """설정 파일을 읽어 반환한다. 파일이 없거나 깨지면 기본값 사용."""
    if not CONFIG_PATH.exists():
        return {k: dict(v) for k, v in DEFAULTS.items()}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        result = {}
        for key, defaults in DEFAULTS.items():
            result[key] = {**defaults, **saved.get(key, {})}
        return result
    except Exception:
        return {k: dict(v) for k, v in DEFAULTS.items()}
