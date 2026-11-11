"""FastAPI interface for the CodeInsight AI pipeline."""

from pathlib import PurePath
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from app.pipeline import run_pipeline


app = FastAPI(
    title="CodeInsight AI API",
    description="AI-powered code review, repair and verification backend.",
    version="1.0.0",
)

# Allow the local React development server to access this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ReviewRequest(BaseModel):
    """Input accepted by the code review endpoint."""

    code: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="Python source code to review.",
    )
    filename: str = Field(
        default="snippet.py",
        min_length=1,
        max_length=100,
    )
    max_attempts: int = Field(default=3, ge=1, le=3)
    test_code: str | None = Field(default=None, max_length=50_000)
    extra_context: str | None = Field(default=None, max_length=20_000)
    context_level: str | None = Field(default=None, max_length=100)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Python code cannot be empty.")
        return value

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        value = value.strip()

        if (
            not value
            or "/" in value
            or "\\" in value
            or PurePath(value).name != value
            or not value.lower().endswith(".py")
        ):
            raise ValueError(
                "Filename must be a simple Python filename, such as main.py."
            )

        return value


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Welcome to CodeInsight AI API",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "CodeInsight AI API",
        "version": "1.0.0",
    }


@app.post("/api/review")
def review_code(request: ReviewRequest) -> dict[str, Any]:
    """Run the existing review, filtering, repair and verification pipeline."""

    try:
        result = run_pipeline(
            code=request.code,
            file=request.filename,
            max_attempts=request.max_attempts,
            test_code=request.test_code,
            extra_context=request.extra_context,
            context_level=request.context_level,
        )

        return {
            "success": not bool(result.get("pipeline_errors")),
            "data": result,
        }

    except Exception as exc:
        # Do not expose internal exception details to API clients.
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the review.",
        ) from exc
