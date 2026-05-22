# 질문 정제 에이전트 모듈
# 사용자의 질문을 핵심 정보 중심으로 단순화하고 불필요한 표현을 제거합니다.

import os, sys
# 상위 디렉토리를 Python 경로에 추가하여 agents_pb2 모듈을 import할 수 있도록 함
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv

# 현재 파일 기준 상위 폴더의 .env를 항상 로드
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import asyncio
import grpc
import re
from openai import AsyncOpenAI
from runtime_config import load as load_cfg

import agents_pb2
import agents_pb2_grpc

class RefinerService(agents_pb2_grpc.RefinerServiceServicer):
    """
    질문 정제 서비스 클래스
    gRPC 서비스로 구현되어 있으며, 사용자 질문을 정제하는 역할을 담당합니다.
    """
    def __init__(self, model="gpt-5.2"):
        """서비스 초기화 - OpenAI API 키 검증 및 클라이언트 생성"""
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        # 비동기 OpenAI 클라이언트 생성
        self.client = AsyncOpenAI(api_key=key)
        # 사용할 GPT 모델 지정
        self.model = model
        
        # 다른 에이전트 서비스에 대한 gRPC 스텁 생성
        # 에이전트 간 직접 통신을 위해 사용됩니다
        self.responder = agents_pb2_grpc.ResponderServiceStub(
            grpc.aio.insecure_channel("localhost:50052")
        )
        self.fact_checker = agents_pb2_grpc.FactCheckerServiceStub(
            grpc.aio.insecure_channel("localhost:50053")
        )
        self.hallu = agents_pb2_grpc.HalluServiceStub(
            grpc.aio.insecure_channel("localhost:50054")
        )

    async def Process(self, request, context):
        """
        전체 파이프라인 처리 메서드
        질문 정제부터 최종 응답 생성까지 전체 파이프라인을 실행합니다.
        에이전트 간 직접 통신을 통해 처리됩니다.
        """
        # 1단계: 질문 정제 (runtime_config.json에서 프롬프트 로드)
        cfg = load_cfg()["refiner"]
        refined_q = request.user_question.strip()
        prompt = cfg["prompt_template"].replace("{question}", refined_q)
        r = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        refined = r.choices[0].message.content.strip()
        # 사용자 요청에 포함된 웹 검색/문서 수집 지시를 제거하고,
        # 제품 기획 근거 요약 질문으로 정제합니다.
        refined = re.sub(
            r"(?i)(구글|네이버|웹\s*검색|실시간\s*검색|상위\s*5개|문서\s*전체|스크랩|수집|추출|검색 결과)",
            "",
            refined,
        )
        refined = re.sub(r"\s+", " ", refined).strip()
        refined = (
            f"{refined}\n\n"
            "다음 3가지 항목으로만 간결하게 요약해 주세요:\n"
            "1. 기술 트렌드\n"
            "2. 공급망 변화\n"
            "3. 시장 전망\n"
            "광고나 불필요한 인트로 문구는 제외하세요."
        )
        
        # 2단계: FactChecker로 검증/출처 기반 정보를 확보하고,
        # 그 결과를 Responder에게 전달해 근거 기반 요약을 생성합니다.
        facts = await self.fact_checker.Check(
            agents_pb2.FactCheckRequest(refined=refined)
        )

        fact_items = []
        for idx, fact in enumerate(facts.facts[:5], start=1):
            content = fact.content.replace("\n", " ").strip()
            if content:
                fact_items.append(f"{idx}. {content} [출처: {fact.url}]")
        fact_summary = "\n".join(fact_items) if fact_items else "관련 검색 결과가 없습니다."

        responder_prompt = (
            f"{refined}\n\n"
            "아래 검색 결과를 근거로 답변을 생성하세요:\n"
            f"{fact_summary}\n\n"
            "각 항목별로 핵심 내용만 간결하게 정리하고, 광고성 인트로는 제외하세요."
        )

        answer = await self.responder.Answer(
            agents_pb2.AnswerRequest(refined=responder_prompt)
        )
        
        # 3단계: HalluService의 AnalyzeAndFinalize를 호출
        # 이 메서드는 내부에서 Finalizer를 호출하여 최종 응답을 생성합니다
        final = await self.hallu.AnalyzeAndFinalize(
            agents_pb2.HalluRequest(answer=answer.answer, fact_data=facts)
        )
        
        return final

async def serve():
    """
    gRPC 서버 실행 함수
    질문 정제 서비스를 gRPC 서버로 실행합니다.
    """
    # 비동기 gRPC 서버 생성
    server = grpc.aio.server()
    # RefinerService를 서버에 등록
    agents_pb2_grpc.add_RefinerServiceServicer_to_server(
        RefinerService(), server
    )
    # 포트 50051에서 서비스 시작 (모든 인터페이스에서 수신)
    server.add_insecure_port("[::]:50051")
    await server.start()
    print("RefinerService ON 50051")
    # 서버 종료 대기
    await server.wait_for_termination()

if __name__ == "__main__":
    # 직접 실행 시 서버 시작
    asyncio.run(serve())
