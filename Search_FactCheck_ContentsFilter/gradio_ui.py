#!/usr/bin/env python3
"""
Gradio UI for MCP Search FactCheck ContentsFilter
실시간 질문, 에이전트 상태, 시스템 프롬프트 수정, 작업 흐름, 결과 표시
"""

import os
import sys
import json
import subprocess
import re
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple

import gradio as gr

# ===== 상수 =====
PROJECT_ROOT = Path(__file__).parent
VENV_PYTHON = str(Path(__file__).parent.parent.parent / ".venv" / "bin" / "python3.13")
MCP_CLIENT = str(PROJECT_ROOT / "call_mcp.py")

# ===== MCP 호출 래퍼 =====

MCP_TIMEOUT = 300  # 전체 파이프라인 최대 대기 시간 (초)


def call_mcp_ask(question: str) -> Dict[str, Any]:
    """
    MCP ask 도구 호출 및 결과 파싱

    Returns:
        {
            "success": bool,
            "ok": bool,
            "final": str (최종 응답),
            "raw_json": str (원본 JSON),
            "error": str (에러 메시지)
        }
    """
    try:
        # 질문을 CLI 인수로 전달
        proc = subprocess.Popen(
            [VENV_PYTHON, MCP_CLIENT, question],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            text=True,
            bufsize=1
        )

        # 표준 출력/에러 수집
        stdout_lines = []
        stderr_lines = []

        # 프로세스 실행 및 출력 대기
        try:
            stdout, stderr = proc.communicate(timeout=MCP_TIMEOUT)
            stdout_lines = stdout.split("\n")
            stderr_lines = stderr.split("\n")
        except subprocess.TimeoutExpired:
            proc.kill()
            return {
                "success": False,
                "error": f"MCP call timeout (>{MCP_TIMEOUT}s) — 파이프라인이 너무 오래 걸렸습니다.",
                "ok": False,
                "final": "",
                "raw_json": ""
            }

        # JSONRPC_RESPONSE: 라인에서 JSON 직접 추출 (regex 없음)
        result_json = None
        for line in stdout_lines:
            if line.startswith("JSONRPC_RESPONSE:"):
                try:
                    result_json = json.loads(line[len("JSONRPC_RESPONSE:"):])
                    break
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"JSON-RPC 응답 파싱 실패: {e}\n원문: {line[:200]}",
                        "ok": False,
                        "final": "",
                        "raw_json": "\n".join(stdout_lines)
                    }

        if not result_json:
            return {
                "success": False,
                "error": "MCP 응답을 찾지 못했습니다. 파이프라인 오류 또는 gRPC 서비스 미기동 가능성이 있습니다.",
                "ok": False,
                "final": "",
                "raw_json": "\n".join(stdout_lines)
            }

        # JSON-RPC 응답에서 결과 추출
        try:
            content = result_json.get("result", {}).get("content", [])
            if content and len(content) > 0:
                text_content = content[0].get("text", "{}")
                # 이중 이스케이프 처리
                inner_json = json.loads(text_content)
                return {
                    "success": True,
                    "ok": inner_json.get("ok", False),
                    "final": inner_json.get("final", ""),
                    "raw_json": json.dumps(inner_json, ensure_ascii=False, indent=2),
                    "error": None
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Parse error: {str(e)}",
                "ok": False,
                "final": "",
                "raw_json": json.dumps(result_json, ensure_ascii=False, indent=2)
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Subprocess error: {str(e)}",
            "ok": False,
            "final": "",
            "raw_json": ""
        }


def parse_final_response(final_text: str) -> Dict[str, Any]:
    """
    최종 응답 텍스트 파싱
    
    구조:
    신뢰도 메시지
    
    [최종 요약]
    내용...
    
    [환각 수준] level
    
    [출처]
    - URL1
    - URL2
    """
    result = {
        "trust_message": "",
        "summary": "",
        "hallucination_level": "unknown",
        "sources": []
    }

    if not final_text:
        return result

    # 신뢰도 메시지 (첫 줄)
    lines = final_text.split("\n")
    if lines:
        result["trust_message"] = lines[0].strip()

    # [최종 요약] 섹션 추출
    summary_match = re.search(
        r'\[최종 요약\](.*?)(?=\[환각|$)',
        final_text,
        re.DOTALL
    )
    if summary_match:
        result["summary"] = summary_match.group(1).strip()

    # [환각 수준] 추출
    hallu_match = re.search(r'\[환각 수준\]\s*(\w+)', final_text)
    if hallu_match:
        result["hallucination_level"] = hallu_match.group(1)

    # [출처] 섹션 추출
    sources_match = re.search(
        r'\[출처\](.*?)$',
        final_text,
        re.DOTALL
    )
    if sources_match:
        sources_text = sources_match.group(1).strip()
        # - URL 형식 추출
        urls = re.findall(r'- (https?://[^\s]+)', sources_text)
        result["sources"] = urls

    return result


# ===== 파이프라인 단계별 시간 추정 (gpt-5.2 기준) =====
_PIPELINE_STEPS = [
    (0,   "🔍 질문 정제 중..."),
    (30,  "🌐 Tavily 웹 검색 수행 중..."),
    (60,  "🤖 LLM 답변 생성 중..."),
    (100, "🔬 환각 필터 분석 중..."),
    (150, "📝 최종 응답 조합 중..."),
]
_SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _build_results(response: Dict[str, Any]) -> Tuple[str, str, str, str, str, str]:
    """응답 dict → (status, summary, trust, halluc_html, facts_html, raw_json) 튜플 반환"""
    if not response["success"]:
        error_msg = response.get("error", "Unknown error")
        return (
            f"❌ 오류 발생",
            f"**오류:** {error_msg}",
            "",
            "",
            "",
            response.get("raw_json", "")
        )

    parsed = parse_final_response(response["final"])

    # 팩트 목록 HTML
    if parsed["sources"]:
        rows = ""
        for i, source in enumerate(parsed["sources"], 1):
            rows += (
                f"<tr style='border-bottom:1px solid rgba(111,126,229,0.15);'>"
                f"<td style='padding:10px 14px;'>"
                f"<a href='{source}' target='_blank' style='color:#818cf8; text-decoration:none; font-size:0.9em;'>"
                f"{i}. {source[:70]}...</a></td></tr>"
            )
        facts_html = (
            "<table style='width:100%; border-collapse:collapse;'>"
            "<tr style='background:rgba(111,126,229,0.2); border-bottom:2px solid #6f7ee5;'>"
            "<th style='padding:10px 14px; text-align:left; color:#a5b4fc; font-weight:600;'>출처</th></tr>"
            + rows + "</table>"
        )
    else:
        facts_html = "<p style='color:rgba(255,255,255,0.35); font-style:italic; padding:8px;'>검색 결과 없음</p>"

    # 환각 수준 뱃지
    level = parsed["hallucination_level"]
    _level_styles = {
        "low":    ("✅", "#34d399", "rgba(16,185,129,0.15)", "rgba(52,211,153,0.4)"),
        "medium": ("⚠️", "#fbbf24", "rgba(245,158,11,0.15)", "rgba(251,191,36,0.4)"),
        "high":   ("❌", "#f87171", "rgba(239,68,68,0.15)",  "rgba(248,113,113,0.4)"),
    }
    icon, txt_col, bg_col, bd_col = _level_styles.get(
        level, ("❓", "rgba(255,255,255,0.5)", "rgba(255,255,255,0.07)", "rgba(255,255,255,0.2)")
    )
    halluc_html = (
        f"<div style='display:inline-flex; align-items:center; gap:8px; padding:8px 18px; "
        f"background:{bg_col}; border:1.5px solid {bd_col}; border-radius:20px; "
        f"color:{txt_col}; font-weight:700; font-size:1.05em; margin-top:4px;'>"
        f"{icon} {level.upper()}</div>"
    )

    return (
        "✅ 완료",
        parsed["summary"],
        parsed["trust_message"],
        halluc_html,
        facts_html,
        response.get("raw_json", "")
    )


# ===== Gradio 콜백 함수 (제너레이터 — 실시간 진행 표시) =====

def on_execute_click(question: str, temperature: float, max_results: int):
    """실행 버튼: yield로 진행 상태를 실시간 갱신하고 완료 시 결과를 반환합니다."""
    EMPTY = ("", "", "", "", "")

    if not question.strip():
        yield ("⚠️ 질문을 입력해주세요.", *EMPTY)
        return

    # 백그라운드 스레드에서 MCP 호출
    result: Dict[str, Any] = {}

    def _run():
        result["data"] = call_mcp_ask(question)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    # 진행 중 — 0.5초마다 상태 갱신
    start = time.time()
    spin_i = 0
    while thread.is_alive():
        elapsed = int(time.time() - start)
        step_msg = _PIPELINE_STEPS[0][1]
        for threshold, msg in _PIPELINE_STEPS:
            if elapsed >= threshold:
                step_msg = msg
        spin = _SPIN[spin_i % len(_SPIN)]
        status = (
            f"<div style='padding:12px 16px; background:rgba(111,126,229,0.12); "
            f"border:1px solid rgba(111,126,229,0.3); border-radius:10px; "
            f"color:#a5b4fc; font-size:0.95em;'>"
            f"{spin} <b>{step_msg}</b> &nbsp;|&nbsp; {elapsed}초 경과</div>"
        )
        yield (status, *EMPTY)
        time.sleep(0.5)
        spin_i += 1

    thread.join()
    yield _build_results(result.get("data", {"success": False, "error": "스레드 오류", "ok": False, "final": "", "raw_json": ""}))


def on_regenerate_click(question: str, temperature: float):
    """재생성 버튼: on_execute_click과 동일한 제너레이터 흐름."""
    if not question.strip():
        yield ("", "", "", "", "", "")
        return
    yield from on_execute_click(question, temperature, 10)


# ===== 런타임 설정 저장/로드 =====

CONFIG_PATH = PROJECT_ROOT / "runtime_config.json"

_CFG_DEFAULTS: Dict[str, Any] = {
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


def _load_cfg() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {k: dict(v) for k, v in _CFG_DEFAULTS.items()}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        return {k: {**dict(v), **saved.get(k, {})} for k, v in _CFG_DEFAULTS.items()}
    except Exception:
        return {k: dict(v) for k, v in _CFG_DEFAULTS.items()}


def save_settings(
    refiner_prompt: str,
    responder_prompt: str,
    responder_temp: float,
    fc_max_results: int,
    fc_prefix: str,
    hallu_threshold: str,
) -> str:
    cfg = {
        "refiner":              {"prompt_template": refiner_prompt},
        "responder":            {"prompt_template": responder_prompt, "temperature": float(responder_temp)},
        "fact_checker":         {"max_results": int(fc_max_results), "search_query_prefix": fc_prefix.strip()},
        "hallucination_filter": {"revision_threshold": hallu_threshold},
    }
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return "✅ 저장 완료 — 다음 실행부터 즉시 반영됩니다."
    except Exception as e:
        return f"❌ 저장 실패: {e}"


def reset_settings() -> Tuple[str, str, float, int, str, str, str]:
    d = _CFG_DEFAULTS
    return (
        d["refiner"]["prompt_template"],
        d["responder"]["prompt_template"],
        d["responder"]["temperature"],
        d["fact_checker"]["max_results"],
        d["fact_checker"]["search_query_prefix"],
        d["hallucination_filter"]["revision_threshold"],
        "🔄 기본값으로 초기화했습니다. 저장 버튼을 누르면 적용됩니다.",
    )


# ===== Gradio UI 구성 =====

def create_ui():
    """Gradio 인터페이스 생성"""

    with gr.Blocks(
        title="MCP FactCheck Agent UI"
    ) as demo:
        # ===== 헤더 =====
        with gr.Group(elem_classes="title-section"):
            gr.Markdown("""
            # 🔍 MCP FactCheck Agent UI
            
            **기능**: 질문 입력 → 검색 → 팩트 검증 → 환각 필터 → 최종 응답
            
            실시간으로 에이전트의 동작 과정과 결과를 확인하세요.
            """, elem_id="header_title")

        # ===== 입력 섹션 =====
        with gr.Group(elem_classes="param-box"):
            gr.Markdown("### 📝 질문 입력 & 설정")
            
            with gr.Row():
                question_input = gr.Textbox(
                    label="질문",
                    placeholder="예: 2026년 상반기 글로벌 반도체 트렌드 요약해줘",
                    lines=3,
                    scale=3
                )
            
            with gr.Row():
                temperature = gr.Slider(
                    label="Responder Temperature",
                    minimum=0.0,
                    maximum=1.0,
                    value=0.3,
                    step=0.1,
                    info="낮을수록 보수적, 높을수록 창의적"
                )
                max_results = gr.Slider(
                    label="FactChecker Max Results",
                    minimum=5,
                    maximum=20,
                    value=10,
                    step=1,
                    info="검색 결과 개수 (향후 적용)"
                )
            
            with gr.Row():
                execute_btn = gr.Button(
                    "🚀 실행",
                    variant="primary",
                    scale=1,
                    size="lg"
                )
                regenerate_btn = gr.Button(
                    "🔄 재생성",
                    scale=1,
                    size="lg"
                )

        # ===== 진행 상태 표시 =====
        status_output = gr.HTML(
            value="",
            label="진행 상태",
            visible=True
        )

        # ===== 결과 섹션 =====
        with gr.Group(elem_classes="result-box"):
            gr.Markdown("### 📊 결과")

            # 최종 요약 (가장 중요)
            with gr.Accordion("✅ 최종 요약", open=True):
                summary_output = gr.Markdown(label="최종 요약")

            # 신뢰도 & 환각 수준
            with gr.Row():
                with gr.Column():
                    trust_output = gr.Markdown(label="신뢰도 메시지")
                with gr.Column():
                    halluc_output = gr.HTML(label="환각 수준")

        # ===== 상세 분석 (Tabs 제거 — Group 안 Tabs+Code 중첩이 브라우저 렉 원인) =====
        with gr.Group(elem_classes="section-box"):
            gr.Markdown("### 📋 상세 분석")

            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("**🔗 팩트 출처** *(Tavily 검색 결과)*")
                    facts_output = gr.HTML()

                with gr.Column(scale=1):
                    gr.Markdown(
                        "**🔬 환각 수준 기준**\n\n"
                        "- `low` — 팩트와 일치\n"
                        "- `medium` — 일부 불명확\n"
                        "- `high` — 불일치·허위 가능성"
                    )

            gr.Markdown("**{ } 원본 JSON 응답**")
            json_output = gr.Textbox(
                label="Raw JSON",
                lines=10,
                max_lines=30,
                interactive=False,
            )

        # ===== 에이전트 설정 패널 (Accordion 안에 Tabs 중첩 금지 — 브라우저 렉 원인) =====
        with gr.Accordion("⚙️ 에이전트 설정", open=False):
            _cfg = _load_cfg()

            with gr.Row():
                # ── 왼쪽 열: 프롬프트 편집 ──
                with gr.Column(scale=3):
                    gr.Markdown("**🔍 Refiner 프롬프트** — `{question}` 자리에 사용자 질문 삽입")
                    refiner_prompt = gr.Textbox(
                        label="Refiner 프롬프트",
                        value=_cfg["refiner"]["prompt_template"],
                        lines=4,
                        show_label=False,
                    )
                    gr.Markdown("**🤖 Responder 프롬프트** — `{refined}` 자리에 정제 질문+검색결과 삽입")
                    responder_prompt = gr.Textbox(
                        label="Responder 프롬프트",
                        value=_cfg["responder"]["prompt_template"],
                        lines=7,
                        show_label=False,
                    )

                # ── 오른쪽 열: 수치 설정 ──
                with gr.Column(scale=2):
                    gr.Markdown("**🤖 Responder Temperature**")
                    responder_temp = gr.Slider(
                        minimum=0.0, maximum=1.0,
                        value=_cfg["responder"]["temperature"],
                        step=0.05,
                        label="Temperature",
                        info="낮을수록 보수적",
                    )
                    gr.Markdown("**🌐 FactChecker 검색 결과 수**")
                    fc_max_results = gr.Slider(
                        minimum=1, maximum=20,
                        value=_cfg["fact_checker"]["max_results"],
                        step=1,
                        label="Max Results",
                    )
                    gr.Markdown("**🌐 검색 쿼리 접두어** *(선택 — 예: `최신 뉴스`)*")
                    fc_prefix = gr.Textbox(
                        value=_cfg["fact_checker"]["search_query_prefix"],
                        placeholder="빈칸 = 접두어 없음",
                        lines=1,
                        label="쿼리 접두어",
                        show_label=False,
                    )
                    gr.Markdown("**🔬 환각 필터 재생성 임계값**  \n이 수준 *이상*이면 답변 재생성")
                    hallu_threshold = gr.Dropdown(
                        choices=["low", "medium", "high"],
                        value=_cfg["hallucination_filter"]["revision_threshold"],
                        label="Revision Threshold",
                        show_label=False,
                    )

            # ── 저장 / 초기화 버튼 ──
            with gr.Row():
                save_btn  = gr.Button("💾 저장", variant="primary")
                reset_btn = gr.Button("↩️ 기본값 초기화")
            cfg_status = gr.Markdown(value="")

            _cfg_inputs  = [refiner_prompt, responder_prompt, responder_temp,
                            fc_max_results, fc_prefix, hallu_threshold]
            _cfg_outputs = [refiner_prompt, responder_prompt, responder_temp,
                            fc_max_results, fc_prefix, hallu_threshold, cfg_status]

            save_btn.click(
                fn=save_settings,
                inputs=_cfg_inputs,
                outputs=cfg_status,
            )
            reset_btn.click(
                fn=reset_settings,
                inputs=[],
                outputs=_cfg_outputs,
            )

        # ===== 콜백 연결 =====
        _outputs = [status_output, summary_output, trust_output, halluc_output, facts_output, json_output]

        execute_btn.click(
            fn=on_execute_click,
            inputs=[question_input, temperature, max_results],
            outputs=_outputs,
        )

        regenerate_btn.click(
            fn=on_regenerate_click,
            inputs=[question_input, temperature],
            outputs=_outputs,
        )

        # ===== 예제 =====
        with gr.Group(elem_classes="section-box"):
            gr.Markdown("### 💡 예제 질문")
            gr.Examples(
                examples=[
                    ["2026년 상반기 글로벌 반도체 트렌드 요약해줘"],
                    ["생성형 AI의 최신 동향과 시장 규모는?"],
                    ["한국 경제의 주요 이슈는 무엇인가?"]
                ],
                inputs=[question_input],
                outputs=None,
                run_on_click=False
            )

    return demo


# ===== 메인 =====

if __name__ == "__main__":
    print("🎨 Gradio UI 시작 중...")
    print(f"📁 프로젝트 경로: {PROJECT_ROOT}")
    print(f"🐍 Python: {VENV_PYTHON}")
    print(f"📜 MCP 클라이언트: {MCP_CLIENT}")
    print()

    # Gradio UI 생성 및 실행
    demo = create_ui()
    
    print("✅ UI 준비 완료!")
    print("🌐 http://127.0.0.1:7860 에서 접속 가능")
    print()
    
    # Gradio 서버 실행
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        show_error=True,
        theme=gr.themes.Base(
            primary_hue="purple",
            secondary_hue="slate",
            neutral_hue="slate",
            spacing_size="lg",
            radius_size="lg"
        ),
        css="""
        .gradio-container, .main { background: transparent !important; }

        /* ── 헤더 ── */
        .title-section {
            background: linear-gradient(135deg, #5b6ee8 0%, #9b7fd4 100%) !important;
            padding: 25px !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 20px rgba(91, 110, 232, 0.4) !important;
        }
        .title-section > div,
        .title-section .wrap,
        .title-section [data-testid="markdown"],
        .title-section .prose {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            padding: 0 !important;
        }
        .title-section h1,
        .title-section p,
        .title-section strong,
        .title-section span {
            color: white !important;
            text-shadow: 0 1px 3px rgba(0,0,0,0.3);
        }

        /* ── 카드 외곽 (1단) ── */
        .param-box, .result-box, .section-box {
            background: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid rgba(111, 126, 229, 0.25) !important;
            border-left: 4px solid #6f7ee5 !important;
            border-radius: 12px !important;
            padding: 22px !important;
            margin-top: 14px !important;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3) !important;
        }

        /* ── 카드 내부 Gradio 래퍼 전부 투명화 (2단 제거) ── */
        .param-box > div, .param-box .form, .param-box .gap,
        .result-box > div, .result-box .form, .result-box .gap,
        .section-box > div, .section-box .form, .section-box .gap {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        .param-box .block,
        .result-box .block,
        .section-box .block {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }
        """
    )
