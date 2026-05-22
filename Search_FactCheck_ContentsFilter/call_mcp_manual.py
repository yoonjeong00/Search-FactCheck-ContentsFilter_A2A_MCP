import json
import selectors
import subprocess
import time
from pathlib import Path


def drain(selector, timeout=1.0):
    end = time.time() + timeout
    lines = []
    while time.time() < end:
        events = selector.select(timeout=0.1)
        if not events:
            continue
        for key, _ in events:
            line = key.fileobj.readline()
            if not line:
                continue
            source = "stdout" if key.fileobj is proc.stdout else "stderr"
            lines.append((source, line.rstrip("\n")))
    return lines


if __name__ == "__main__":
    path = Path(__file__).resolve().parent
    python = "/Users/admin/Desktop/A2A_MCP/.venv/bin/python3.13"
    args = [python, "-u", str(path / "mcp_server.py")]

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

        question = (
            "구글이나 네이버에서 '2026년 상반기 글로벌 반도체 트렌드'를 검색해서 "
            "나오는 상위 5개 문서의 전체 내용을 긁어와줘. 분석 에이전트는 광고나 "
            "쓸데없는 인트로 문구를 다 제외하고, [기술 트렌드 / 공급망 변화 / 시장 전망] "
            "3가지 항목으로만 핵심 내용을 요약해줘."
        )

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
        print("RECV CALL", drain(sel, timeout=120.0))
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        sel.close()
