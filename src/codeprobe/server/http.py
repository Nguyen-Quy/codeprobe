from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException

from ..core.router import LayaDecisionRouter
from ..executor import Investigator
from ..schemas import DecisionRequest, DecisionResponse

logger = logging.getLogger(__name__)


def create_http_app() -> Any:
    """
    Factory creating the FastAPI application for codeprobe REST endpoints.
    Requires `codeprobe[http]` extras (fastapi, uvicorn).
    """
    app = FastAPI(
        title="codeprobe Decision Router API",
        version="0.2.0",
        description="REST API for AI coding agents to query routing decisions and guardrails.",
    )
    router = LayaDecisionRouter()

    @app.get("/v1/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "codeprobe", "version": "0.2.0"}

    @app.post("/v1/route", response_model=DecisionResponse)
    def route_decision(request: DecisionRequest) -> DecisionResponse:
        try:
            return router.route(request)
        except Exception as exc:
            logger.exception("Error routing decision")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/v1/evaluate")
    def evaluate_evidence(request: DecisionRequest) -> dict[str, Any]:
        try:
            response = router.route(request)
            next_action = (
                response.recommended_actions[0].action.value
                if response.recommended_actions
                else None
            )
            return {
                "is_sufficient": response.is_sufficient,
                "strategy": response.strategy,
                "confidence": response.confidence,
                "recommended_next_action": next_action,
                "reasoning": response.reasoning,
            }
        except Exception as exc:
            logger.exception("Error evaluating evidence")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/v1/investigate")
    def investigate(request: dict[str, Any]) -> dict[str, Any]:
        try:
            investigator = Investigator()
            query = request.get("query") or request.get("user_goal") or ""
            target_files = request.get("target_files")
            max_steps = request.get("max_steps", 5)
            res = investigator.explore(
                query=query, target_files=target_files, max_steps=max_steps
            )
            return res.model_dump()
        except Exception as exc:
            logger.exception("Error during investigation")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


def run_http_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """
    Launch the HTTP REST server using Uvicorn.
    """
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "Uvicorn is required to run the HTTP server. Install with: pip install 'codeprobe[http]'"
        ) from exc

    app = create_http_app()
    logger.info("Starting codeprobe HTTP REST server on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
