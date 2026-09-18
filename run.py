"""One-command starter for GridWise service."""

import uvicorn
from app.config import settings

if __name__ == "__main__":
    print(f"Starting GridWise service on {settings.host}:{settings.port}...")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        ws="none",
        log_level="info"
    )
