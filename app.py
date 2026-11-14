from __future__ import annotations

from pathlib import Path

import uvicorn
from dotenv import load_dotenv

if __name__ == "__main__":
    # Read local settings such as the Clerk keys from .env; real environment variables win.
    # This must happen before the server module is imported, since it builds the app.
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    uvicorn.run("medical_rag.server:app", host="127.0.0.1", port=8000, reload=False)
