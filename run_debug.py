from app.main import app
from uvicorn import run

if __name__ == "__main__":
    run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="debug",
        loop="asyncio",
        http="h11",
    )