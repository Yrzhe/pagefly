"""Start the FastAPI server."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
from src.shared.config import API_PORT
from src.storage.db import init_db

if __name__ == "__main__":
    init_db()
    uvicorn.run("src.channels.api:app", host="0.0.0.0", port=API_PORT, reload=False)
