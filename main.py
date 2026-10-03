import uvicorn

from app.core.config import settings


def main():
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8084,
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    main()
