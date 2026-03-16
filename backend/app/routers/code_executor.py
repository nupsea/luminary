"""Code execution sandbox endpoint.

POST /code/execute  — run a code snippet in an isolated subprocess, compare to expected output.
"""
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import get_session_factory
from app.models import PredictionEventModel
from app.services.code_executor import CodeExecutorService, get_code_executor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/code", tags=["code"])


class CodeExecuteRequest(BaseModel):
    code: str = Field(min_length=1)
    language: str = "python"
    timeout_ms: int = Field(default=10_000, ge=100, le=30_000)
    expected_output: str | None = None
    # Optional context for PredictionEvent persistence
    chunk_id: str | None = None
    document_id: str | None = None


class CodeExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    elapsed_ms: int
    prediction_correct: bool | None = None
    prediction_diff: str | None = None


@router.post("/execute", response_model=CodeExecuteResponse)
async def execute_code(req: CodeExecuteRequest) -> CodeExecuteResponse:
    """Execute code in a sandboxed subprocess and compare to expected output.

    Returns stdout, stderr, exit_code, elapsed_ms.
    If expected_output is provided, also returns prediction_correct and prediction_diff.
    prediction_correct uses strip() comparison -- trailing newlines are normalized
    (expected='hello', actual='hello\\n' yields prediction_correct=True).

    JavaScript returns HTTP 503 if Node.js is not installed.
    """
    service: CodeExecutorService = get_code_executor_service()
    try:
        result = service.execute(
            code=req.code,
            language=req.language,
            timeout_ms=req.timeout_ms,
            expected_output=req.expected_output,
        )
    except LookupError:
        raise HTTPException(
            status_code=503,
            detail="Install Node.js (nodejs.org) to run JavaScript snippets",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Persist prediction event when expected_output is provided
    if req.expected_output is not None:
        async with get_session_factory()() as session:
            event = PredictionEventModel(
                id=str(uuid.uuid4()),
                chunk_id=req.chunk_id,
                document_id=req.document_id,
                code_content=req.code[:2000],
                expected=req.expected_output,
                actual=result.stdout,
                correct=bool(result.prediction_correct),
                language=req.language,
                created_at=datetime.now(UTC),
            )
            session.add(event)
            await session.commit()

    return CodeExecuteResponse(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        elapsed_ms=result.elapsed_ms,
        prediction_correct=result.prediction_correct,
        prediction_diff=result.prediction_diff,
    )
