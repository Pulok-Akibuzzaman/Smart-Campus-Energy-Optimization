"""
main.py - Root Entrypoint Proxy for FastAPI App.
Enables running 'uvicorn main:app' or 'python main.py' directly from the workspace root.
"""
import os
import uvicorn
from src.main import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
