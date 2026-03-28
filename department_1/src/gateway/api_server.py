"""
FastAPI Gateway Server - Phase 7 통합 API
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lib.core.logger import get_logger
from llm_gateway import get_llm_gateway, LLMRequest, generate_text

logger = get_logger(__name__)

# 전역 상태
app_state: Dict[str, Any] = {
    "llm_gateway": None,
    "started_at": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 생명주기 관리"""
    # 시작
    logger.info("Starting API Gateway...")
    app_state["llm_gateway"] = get_llm_gateway()
    app_state["started_at"] = asyncio.get_event_loop().time()
    logger.info("API Gateway started")

    yield

    # 종료
    logger.info("Shutting down API Gateway...")


app = FastAPI(
    title="OZ_A2M Gateway",
    description="AI-Powered Multi-Agent Trading System Gateway",
    version="0.2.0",
    lifespan=lifespan
)


# 요청/응답 모델
class LLMGenerateRequest(BaseModel):
    prompt: str
    task: str = Field(default="quick", description="analysis, complex, quick, cost_sensitive")
    stream: bool = False


class LLMGenerateResponse(BaseModel):
    content: str
    provider: str
    model: str
    latency_ms: float
    cached: bool = False


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    llm_providers: Dict[str, Any]


# 라우트
@app.get("/", response_model=Dict[str, str])
async def root():
    """루트 엔드포인트"""
    return {
        "name": "OZ_A2M Gateway",
        "version": "0.2.0",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    """상태 체크"""
    llm_gateway = app_state["llm_gateway"]
    uptime = asyncio.get_event_loop().time() - app_state["started_at"]

    return HealthResponse(
        status="healthy",
        version="0.2.0",
        uptime_seconds=uptime,
        llm_providers=llm_gateway.get_health() if llm_gateway else {}
    )


@app.post("/llm/generate", response_model=LLMGenerateResponse)
async def llm_generate(request: LLMGenerateRequest):
    """LLM 텍스트 생성"""
    try:
        llm_gateway = app_state["llm_gateway"]
        llm_request = LLMRequest(
            task=request.task,
            prompt=request.prompt,
            stream=request.stream
        )

        response = await llm_gateway.generate(llm_request)

        return LLMGenerateResponse(
            content=response.content,
            provider=response.provider,
            model=response.model,
            latency_ms=response.latency_ms,
            cached=response.cached
        )

    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/llm/analyze")
async def llm_analyze(data: Dict[str, str]):
    """데이터 분석 요청"""
    try:
        market_data = data.get("market_data", "")
        prompt = f"""Analyze the following market data and provide trading insights:

{market_data}

Provide a brief analysis including:
1. Trend direction
2. Key levels
3. Risk assessment"""

        result = await generate_text(prompt, task="analysis")
        return {"analysis": result}

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/llm/providers")
async def list_providers():
    """사용 가능한 LLM 제공자 목록"""
    llm_gateway = app_state["llm_gateway"]
    return llm_gateway.get_health()


@app.post("/llm/providers/{name}/recover")
async def recover_provider(name: str):
    """제공자 복구 시도"""
    llm_gateway = app_state["llm_gateway"]
    success = await llm_gateway.recover_provider(name)

    if success:
        return {"status": "recovered", "provider": name}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to recover {name}")


def main():
    """개발용 실행"""
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
