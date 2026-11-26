"""Quiz endpoints. A quiz builds in the background; the client polls it like a teach-back.

Routes:
  POST /study/quizzes                    create a quiz and start writing its questions
  GET  /study/quizzes/{id}               the quiz, the questions written so far, results once done
  POST /study/quizzes/{id}/answers       answer one question; feedback at once in practice mode
  POST /study/quizzes/{id}/finish        end the quiz and summarise it
  POST /study/quizzes/{id}/retake        a new quiz of the questions missed or guessed
  POST /study/quiz-items/{id}/to-card    a grounded flashcard from a single-answer question
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.quiz import (
    QuizAnswerRequest,
    QuizAnswerResponse,
    QuizCreateRequest,
    QuizItemCardResponse,
    QuizResponse,
)
from app.services import quiz_service

router = APIRouter(prefix="/study", tags=["quiz"])


@router.post("/quizzes", response_model=QuizResponse, status_code=201)
async def create_quiz(
    req: QuizCreateRequest, session: AsyncSession = Depends(get_db)
) -> QuizResponse:
    return await quiz_service.create(session, req)


@router.get("/quizzes/{quiz_id}", response_model=QuizResponse)
async def get_quiz(quiz_id: str, session: AsyncSession = Depends(get_db)) -> QuizResponse:
    return await quiz_service.view(session, quiz_id)


@router.post("/quizzes/{quiz_id}/answers", response_model=QuizAnswerResponse)
async def answer_question(
    quiz_id: str, req: QuizAnswerRequest, session: AsyncSession = Depends(get_db)
) -> QuizAnswerResponse:
    return await quiz_service.answer(session, quiz_id, req)


@router.post("/quizzes/{quiz_id}/finish", response_model=QuizResponse)
async def finish_quiz(quiz_id: str, session: AsyncSession = Depends(get_db)) -> QuizResponse:
    return await quiz_service.finish(session, quiz_id)


@router.post("/quizzes/{quiz_id}/retake", response_model=QuizResponse, status_code=201)
async def retake_quiz(quiz_id: str, session: AsyncSession = Depends(get_db)) -> QuizResponse:
    return await quiz_service.retake(session, quiz_id)


@router.post("/quiz-items/{item_id}/to-card", response_model=QuizItemCardResponse, status_code=201)
async def quiz_item_to_card(
    item_id: str, session: AsyncSession = Depends(get_db)
) -> QuizItemCardResponse:
    return await quiz_service.item_to_card(session, item_id)
