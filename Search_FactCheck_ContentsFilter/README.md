# Search FactCheck ContentsFilter

AI 응답의 정확성과 안전성을 보장하기 위한 팩트체크 및 콘텐츠 필터링 기능을 제공하는 Model Context Protocol (MCP) 서버입니다.

## 프로젝트 구조

```
Search_FactCheck_ContentsFilter/
├── agents/                           # AI 에이전트 모듈 (각각 독립 gRPC 서버)
│   ├── enhanced_content_filter.py    # 고급 콘텐츠 필터 (HalluService 내부 모듈)
│   ├── fact_checker.py               # 팩트체크 에이전트 (Tavily 검색) — 포트 50053
│   ├── final_response.py             # 최종 응답 생성 에이전트 — 포트 50055
│   ├── hallucination_filter.py       # 환각 필터 에이전트 — 포트 50054
│   ├── question_refiner.py           # 질문 정제 + 오케스트레이터 — 포트 50051
│   ├── responder.py                  # 응답 생성 에이전트 — 포트 50052
│   └── runtime_config.py             # 런타임 설정 로더 (runtime_config.json 읽기)
├── agents.proto              # gRPC 서비스 정의
├── agents_pb2.py             # 생성된 gRPC Python 코드
├── agents_pb2_grpc.py        # 생성된 gRPC 서비스 스텁
├── call_mcp.py               # MCP stdio 클라이언트 (gradio_ui.py가 subprocess로 호출)
├── gradio_ui.py              # Gradio 웹 UI (http://127.0.0.1:7860)
├── mcp_server.py             # MCP 서버 (Cursor 등 외부 클라이언트 진입점)
├── runtime_config.json       # 에이전트 런타임 설정 (Gradio UI에서 편집·저장)
├── pyproject.toml            # 프로젝트 설정 및 의존성
└── README.md                 # 프로젝트 개요
```

## 주요 기능

- **질문 정제**: 사용자 질문을 핵심 개념에 집중하도록 정제
- **응답 생성**: OpenAI의 LLM을 사용하여 응답 생성
- **팩트체크**: Tavily 검색을 사용하여 정보 검증
- **콘텐츠 필터링**: 환각 현상 및 부적절한 콘텐츠 감지
- **최종 응답**: 모든 결과를 안전하고 팩트체크된 응답으로 통합
- **Gradio 웹 UI**: 질문 입력·결과 확인·에이전트 설정을 브라우저에서 실시간으로 조작
- **런타임 설정**: 에이전트 재시작 없이 프롬프트·파라미터를 즉시 변경

## 설치 방법

1. **의존성 설치**:
   ```bash
   pip install -r requirements.txt
   ```

2. **API 키 발급**:
   - **OpenAI API Key**: [OpenAI Platform](https://platform.openai.com/api-keys)에서 발급
   - **Tavily API Key**: [Tavily](https://tavily.com/)에서 발급

3. **환경 변수 설정**:
   - `.env.example`을 `.env`로 복사
   - `.env` 파일에 API 키 추가:
     ```
     OPENAI_API_KEY=your_openai_api_key_here
     TAVILY_API_KEY=your_tavily_api_key_here
     ```

4. **서버 실행**:
   ```bash
   python mcp_server.py
   ```

## Gradio 웹 UI

브라우저 기반 테스트 인터페이스입니다. gRPC 에이전트가 실행 중인 상태에서 아래 명령으로 시작합니다.

```bash
# 프로젝트 루트의 venv 사용 (권장)
/path/to/.venv/bin/python3.13 gradio_ui.py
```

실행 후 <http://127.0.0.1:7860> 접속.

### UI 구성

| 영역 | 설명 |
| --- | --- |
| 질문 입력 | 질문 텍스트 입력, 실행·재생성 버튼 |
| 진행 상태 | 실행 중 0.5초마다 현재 파이프라인 단계와 경과 시간 표시 |
| 결과 — 최종 요약 | LLM이 생성한 최종 요약 |
| 결과 — 신뢰도·환각 수준 | 팩트 검증 상태 및 환각 수준 뱃지 |
| 상세 분석 | 팩트 출처 목록, 환각 수준 기준, 원본 JSON 응답 |
| ⚙️ 에이전트 설정 | 에이전트별 프롬프트·파라미터 실시간 편집 (아래 참고) |

### 실시간 진행 상태 표시

실행 버튼 클릭 직후부터 완료까지 경과 시간과 현재 추정 단계를 표시합니다.

| 경과 시간 | 표시 메시지 |
| --- | --- |
| 0s~ | 🔍 질문 정제 중... |
| 30s~ | 🌐 Tavily 웹 검색 수행 중... |
| 60s~ | 🤖 LLM 답변 생성 중... |
| 100s~ | 🔬 환각 필터 분석 중... |
| 150s~ | 📝 최종 응답 조합 중... |

## 런타임 설정 (runtime_config.json)

Gradio UI의 **⚙️ 에이전트 설정** 아코디언을 열면 에이전트별 파라미터를 편집하고 저장할 수 있습니다.
저장된 값은 `runtime_config.json`에 기록되며, **에이전트 재시작 없이 다음 요청부터 즉시 반영**됩니다.

| 설정 항목 | 키 경로 | 설명 |
| --- | --- | --- |
| Refiner 프롬프트 | `refiner.prompt_template` | `{question}` 자리에 사용자 질문 삽입 |
| Responder 프롬프트 | `responder.prompt_template` | `{refined}` 자리에 정제 질문+검색 결과 삽입 |
| Responder Temperature | `responder.temperature` | 0.0(보수적) ~ 1.0(창의적), 기본값 0.3 |
| FactChecker 검색 결과 수 | `fact_checker.max_results` | Tavily 최대 검색 결과 수, 기본값 10 |
| 검색 쿼리 접두어 | `fact_checker.search_query_prefix` | 예: `최신 뉴스` → 쿼리 앞에 자동 추가 |
| 환각 필터 재생성 임계값 | `hallucination_filter.revision_threshold` | `low` / `medium` / `high` — 이 수준 이상이면 답변 재생성 |

`runtime_config.json`을 직접 편집해도 동일하게 적용됩니다.

```json
{
  "refiner":              { "prompt_template": "..." },
  "responder":            { "prompt_template": "...", "temperature": 0.3 },
  "fact_checker":         { "max_results": 10, "search_query_prefix": "" },
  "hallucination_filter": { "revision_threshold": "high" }
}
```

## 로컬 개발 빠른 실행 (권장: gRPC 에이전트만)

Cursor에서 MCP 서버(`mcp_server.py`)는 별도로 실행되므로, 로컬에서는 gRPC 에이전트 5개만 `honcho + Procfile.agents`로 기동하는 것을 권장합니다.

1. **의존성 설치**
   ```bash
   pip install honcho
   ```

2. **gRPC 에이전트 실행**
   ```bash
   ./scripts/devctl.sh up
   ```

3. **상태 확인**
   ```bash
   ./scripts/devctl.sh status
   ```

4. **통합 로그 보기**
   ```bash
   ./scripts/devctl.sh logs
   ```

5. **전체 종료**
   ```bash
   ./scripts/devctl.sh down
   ```

> 로그 파일은 `.runtime/dev.log` 에 저장됩니다.

## MCP 도구

- `ask`: 질문에서 안전한 응답까지의 전체 파이프라인 실행
  - 추가 지시가 없으면 `기술 트렌드 / 공급망 변화 / 시장 전망` 3개 항목을 중심으로 요약하도록 설계됨

## 사용 방법

이 MCP 서버는 Cursor와 같은 MCP 호환 클라이언트에서 사용하도록 설계되었습니다. MCP 클라이언트 설정에서 이 서버를 구성하여 팩트체크 및 콘텐츠 필터링 도구에 접근할 수 있습니다.

`ask` 도구는 가능한 경우 다음 3개 항목을 명시적으로 포함하는 요약을 생성합니다:
- 기술 트렌드
- 공급망 변화
- 시장 전망

요청 시 해당 항목을 직접 명시하면 더 일관된 구조화된 응답을 얻을 수 있습니다.

## 아키텍처

Search_FactCheck_ContentsFilter의 주요 컴포넌트는 MCP 서버, 여러 gRPC 기반 에이전트, 그리고 최종 응답 조합 단계로 구성됩니다. MCP 서버(mcp_server.py)는 외부 클라이언트(Cursor 등)와 연결되는 진입점으로, 모든 처리를 단일 엔드포인트인 `ask` 도구를 통해 수행하도록 설계되어 있습니다. 이 도구는 질문을 입력받아 Refiner의 Process 메서드를 호출하여 전체 파이프라인을 시작합니다. 실제 오케스트레이션은 에이전트 간 직접 통신으로 이루어지며, MCP 서버는 단순히 진입점 역할만 담당합니다. 에이전트들은 각각 독립적인 gRPC 서버로 실행되며, 서로 직접 gRPC 호출을 통해 통신합니다.

Question Refiner(agents/question_refiner.py)는 사용자의 질문을 핵심 정보 중심으로 단순화하고 불필요한 표현을 제거하여, 이후 단계에서 처리하기 쉬운 형태로 변환합니다. Refiner는 오케스트레이터 역할을 담당하며, Process 메서드에서 전체 파이프라인을 조율합니다. 정제된 질문은 Responder와 Fact Checker에 병렬로 전달되며, 두 에이전트의 결과를 받아 HalluService의 AnalyzeAndFinalize를 호출합니다.

Responder(agents/responder.py)는 OpenAI GPT-5.1 모델을 활용해 사실 기반의 초안 응답을 생성합니다. temperature를 0.3으로 설정해 안정성을 확보하며, 생성된 응답은 Hallucination Filter로 전달되어 추가 검증과 환각 감지에 활용됩니다. 환각이 감지된 경우 HalluService에 의해 Revise 메서드가 호출되어 답변을 더 보수적으로 수정합니다.

Fact Checker(agents/fact_checker.py)는 Tavily Search API를 사용하여 정제된 질문에 대한 실시간 검증을 수행합니다. 검색된 문서에서 추출한 핵심 사실, 출처 URL, 검증 상태(verified / unverifiable)를 생성해 Refiner에 반환함으로써 응답의 신뢰성을 보완합니다. Fact Checker는 MCP 서버가 아닌 Refiner에 직접 결과를 반환합니다.

Hallucination Filter(agents/hallucination_filter.py)는 Responder가 생성한 초안 응답이 사실과 불일치하거나 위험 패턴을 포함하는지 평가합니다. Enhanced Content Filter를 내부 모듈로 사용하여 안전성을 검사하며, GPT 기반 판단을 결합하여 환각 가능성을 단계별로 평가합니다. 문제가 감지되면 Responder 서비스를 직접 호출하여 자동으로 응답을 수정합니다. 최종적으로 HalluService는 Finalizer를 직접 호출하여 최종 응답을 생성합니다.

Enhanced Content Filter(agents/enhanced_content_filter.py)는 독립적인 gRPC 서버가 아닌 HalluService 내부에서 사용되는 모듈입니다. 정규식 기반의 빠른 스캔과 LLM 기반의 정밀 분석이 결합된 하이브리드 필터링을 수행합니다. 자해, 자살, 폭력, 극단주의 등 고위험 요소를 카테고리별로 분류하고, 위험 콘텐츠가 감지되면 안전한 대체 응답을 제시합니다. 한국어 사용자에게 적합한 안전 메시지 템플릿을 제공하며, LLM 호출이 실패했을 때 지수 백오프 방식으로 재시도하여 안정성을 높입니다.

마지막으로 Final Response(agents/final_response.py)는 HalluService에 의해 호출됩니다. HalluResponse와 FactCheckResponse를 종합하여 최종 답변을 구성합니다. 최종 출력에는 신뢰도 평가 메시지(검증 상태 기반), 환각 수준 정보, 참고 소스 URL이 포함됩니다.

이 시스템의 특징은 중앙 오케스트레이터 없이 각 에이전트가 필요한 다른 에이전트를 직접 gRPC로 호출하는 에이전트 간 직접 통신 구조입니다. Refiner가 Responder와 FactChecker를 병렬로 호출하여 성능을 최적화하며, 각 에이전트가 독립적인 gRPC 서버로 실행되어 확장성과 유지보수성을 향상시킵니다.



## 이 시스템이 적합한 상황

| 상황 | 대상 |
| --- | --- |
| 외부 노출 답변 품질 관리 | 고객지원 챗봇, 사내 지식봇, 공공/교육 안내 |
| 환각 리스크 최소화 | 출처 제시가 필요한 정보성 응답 |
| 안전성 필터 필요 | 자해·폭력·위험 주제 차단, 안전 대체 응답 |
| 컴포넌트 독립 실험 | 모델팀/정책팀 분리 운영, 에이전트별 독립 교체 |

## 고도화 포인트

### 1. 답변 품질 향상

- `question_refiner.py` — 질문 유형(정의/절차/비교)별 정제 프롬프트 분기
- `responder.py` — 답변 스타일 가이드 추가(간결형/상세형), 불확실 정보에 “확인 필요” 문장 강제
- `final_response.py` — 출력 포맷 고정 (요약 → 본문 → 주의사항 → 출처)

### 2. 환각·사실성 강화

- `fact_checker.py` — 출처 도메인 allowlist, 다중 출처 교차 검증 로직
- `hallucination_filter.py` — `medium` 수준에도 조건부 재작성 경로 추가
- `final_response.py` — 출처 부족 시 신뢰도 자동 하향, 근거 요약 함께 노출

### 3. 안전성 필터 고도화

- `enhanced_content_filter.py` — 카테고리별 패턴 세분화(자해/폭력/혐오), 문맥 점수화
- `hallucination_filter.py` — unsafe 탐지 시 로그 이벤트 표준화 (감지 카테고리·차단 여부)

### 4. 운영 확장성

- `mcp_server.py` — `ask` 입력 스키마 확장 (모드: fast/safe, strict_safety 등)
- `question_refiner.py` — `Process()` 타임아웃·재시도·fallback 경로 정책화
- 에이전트 공통 응답 메타데이터 표준화 (model, latency_ms, decision_reason)

## MCP 연동 가이드

`mcp_server.py`는 `mcp.run(transport=”stdio”)`로 동작하는 단일 진입점입니다.  
Cursor 등 MCP 호환 클라이언트가 로컬 프로세스를 실행해 `ask` 도구를 호출하는 구조입니다.

**호출 흐름:**

```
클라이언트
  └─▶ mcp_server.py (ask)
        └─▶ Refiner :50051
              ├─▶ FactChecker :50053
              ├─▶ Responder   :50052
              └─▶ HalluService :50054
                    └─▶ Finalizer :50055
                          └─▶ 최종 응답 반환
```

**연동 체크리스트:**

1. MCP 클라이언트 설정에 `mcp_server.py` 실행 명령 등록
2. gRPC 에이전트 5개 (포트 50051~50055) 먼저 기동
3. `ask` 도구에 `{“question”: “...”}` 형태로 질문 전달
4. 응답의 `final` 필드에서 최종 텍스트 사용

**제약 사항:**

- `ask` 단일 엔드포인트만 제공
- gRPC 에이전트가 모두 기동된 상태여야 정상 응답
- OpenAI / Tavily API 키 및 네트워크 상태에 영향 받음

