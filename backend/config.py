"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# -- Paths ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = BASE_DIR / "skills"
# Overridable so tests can import the app without writing into the working tree
GENERATED_DIR = Path(os.getenv("BUILDER_GENERATED_DIR") or BASE_DIR / "generated")
AGENTS_DIR = GENERATED_DIR / "agents"
WORKFLOWS_DIR = GENERATED_DIR / "workflows"

# Ensure output dirs exist
AGENTS_DIR.mkdir(parents=True, exist_ok=True)
WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

# -- Azure OpenAI -----------------------------------------------------------
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")

# -- Weekend Saver ----------------------------------------------------------
# "1" runs the Weekend Saver workflow against an in-memory fake of Azure
WEEKEND_SAVER_DEMO = os.getenv("WEEKEND_SAVER_DEMO", "") == "1"
# Pages allowed to drive the Weekend Saver workflow; the first one is used in the
# one-time link printed at start-up
FRONTEND_ORIGINS = tuple(
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
)
