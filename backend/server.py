"""
Quick start server:
    cd backend
    python server.py
"""
import uvicorn
from app.config import settings

if __name__ == "__main__":
    try:
        settings.validate_security()
    except RuntimeError as exc:
        raise SystemExit(
            f"Startup configuration error: {exc}\n"
            "Set production secrets in backend/.env, then restart the server."
        ) from None
    uvicorn.run(
        "app.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=False,
        ws="websockets-sansio",
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
