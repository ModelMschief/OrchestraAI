from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
VECTOR_DIR = DATA_DIR / "vectors"
DB_PATH = DATA_DIR / "orchestra.sqlite3"

EMBEDDING_MODEL = os.getenv("ORCHESTRA_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIMENSION = int(os.getenv("ORCHESTRA_EMBEDDING_DIMENSION", "384"))

for directory in (DATA_DIR, UPLOAD_DIR, VECTOR_DIR):
    directory.mkdir(parents=True, exist_ok=True)
