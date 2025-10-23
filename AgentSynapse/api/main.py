from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from config.settings import settings
from utils.logger import setupLogger, getLogger
from utils.exceptions import ACEException
from api.routes import agentRoutes, toolRoutes, memoryRoutes

setupLogger()
logger = getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ace_framework_starting", version=settings.app.version)
    yield
    logger.info("ace_framework_shutdown")


app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    description="ACE (Agentic Context Engineering) Framework API",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agentRoutes.router, prefix="/api/v1")
app.include_router(toolRoutes.router, prefix="/api/v1")
app.include_router(memoryRoutes.router, prefix="/api/v1")


@app.exception_handler(ACEException)
async def aceExceptionHandler(request: Request, exc: ACEException):
    logger.error("ace_exception", code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(
        status_code=400,
        content={
            "error": exc.code,
            "message": exc.message,
            "details": exc.details
        }
    )


@app.exception_handler(Exception)
async def generalExceptionHandler(request: Request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
            "details": {"error": str(exc)}
        }
    )


@app.get("/health")
async def healthCheck():
    return {
        "status": "healthy",
        "service": settings.app.name,
        "version": settings.app.version,
        "environment": settings.app.environment
    }


@app.get("/")
async def root():
    return {
        "service": settings.app.name,
        "version": settings.app.version,
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app.environment == "development"
    )
