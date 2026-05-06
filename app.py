from __future__ import annotations

import uvicorn

from medical_rag.server import app


if __name__ == "__main__":
    uvicorn.run("medical_rag.server:app", host="127.0.0.1", port=8000, reload=False)
