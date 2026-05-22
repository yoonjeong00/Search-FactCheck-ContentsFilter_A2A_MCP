import json
import selectors
import subprocess
import sys
import time
from pathlib import Path


DRAIN_TIMEOUT = 270.0  # gradio_ui의 MCP_TIMEOUT(300s)보다 짧게 유지


def drain(selector, timeout=1.0, stop_on_jsonrpc=False):
    """stdout/stderr를 timeout 동안 수집한다.
    stop_on_jsonrpc=True이면 JSON-RPC 응답 줄을 받는 즉시 반환한다.
    """
    end = time.time() + timeout
    lines = []
    while time.time() < end:
        events = selector.select(timeout=0.1)
        if not events:
            continue
        for key, _ in events:
            line = key.fileobj.readline()
            if not line:            # EOF
                return lines
            source = "stdout" if key.fileobj is proc.stdout else "stderr"
            decoded = line.rstrip("\n")
            lines.append((source, decoded))
            # JSON-RPC 응답은 stdout 한 줄에 실린다 — 받자마자 반환
            if stop_on_jsonrpc and source == "stdout" and '"jsonrpc"' in decoded and '"result"' in decoded:
                return lines
    return lines


if __name__ == "__main__":
    path = Path(__file__).resolve().parent
    python = "/Users/admin/Desktop/A2A_MCP/.venv/bin/python3.13"
    args = [python, "-u", str(path / "mcp_server.py")]

    # CLI 인수로 질문을 받음 (gradio_ui.py가 sys.argv[1]로 전달)
    question = sys.argv[1] if len(sys.argv) > 1 else (
        "구글이나 네이버에서 '2026년 상반기 글로벌 반도체 트렌드'를 검색해서 "
        "나오는 상위 5개 문서의 전체 내용을 긁어와줘. 분석 에이전트는 광고나 "
        "쓸데없는 인트로 문구를 다 제외하고, [기술 트렌드 / 공급망 변화 / 시장 전망] "
        "3가지 항목으로만 핵심 내용을 요약해줘."
    )

    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    sel.register(proc.stderr, selectors.EVENT_READ)

    try:
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2.0",
                "capabilities": {
                    "sampling": None,
                    "elicitation": None,
                    "experimental": None,
                    "roots": None,
                    "tasks": None,
                },
                "clientInfo": {"name": "call_mcp_manual", "version": "0.1.0"},
            },
        }
        proc.stdin.write(json.dumps(init) + "\n")
        proc.stdin.flush()
        print("SEND INIT")
        print("RECV INIT", drain(sel, timeout=2.0))

        init_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": None,
        }
        proc.stdin.write(json.dumps(init_notif) + "\n")
        proc.stdin.flush()
        print("SEND INITIALIZED")
        print("RECV INITIALIZED", drain(sel, timeout=2.0))

        call = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "ask",
                "arguments": {
                    "input": {
                        "question": question,
                    }
                },
            },
        }
        proc.stdin.write(json.dumps(call) + "\n")
        proc.stdin.flush()
        print("SEND CALL")
        recv = drain(sel, timeout=DRAIN_TIMEOUT, stop_on_jsonrpc=True)
        print("RECV CALL", recv)
        # JSON-RPC 응답을 별도 라인으로 출력 — gradio_ui.py가 regex 없이 파싱
        for src, content in recv:
            if src == "stdout" and '"jsonrpc"' in content and '"result"' in content:
                print("JSONRPC_RESPONSE:" + content)
                break
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        sel.close()
