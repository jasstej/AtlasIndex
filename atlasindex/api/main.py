import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from atlasindex.storage.database import init_db
from atlasindex.watcher.monitor import CodebaseWatcher
from atlasindex.api.routes import router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Global watcher instance
watcher = CodebaseWatcher()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("Initializing AtlasIndex database...")
    init_db()

    logger.info("Starting codebase file system watcher...")
    try:
        watcher.start()
    except Exception as e:
        logger.error(f"Failed to start filesystem watcher: {e}")

    yield

    # Shutdown actions
    logger.info("Stopping codebase file system watcher...")
    try:
        watcher.stop()
    except Exception as e:
        logger.error(f"Error stopping watcher during shutdown: {e}")

app = FastAPI(
    title="AtlasIndex API",
    description="Intelligent Code Indexer & Server Project Registry API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Policy - Strict localhost lock for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000", "http://localhost:3000",
        "http://127.0.0.1:3005", "http://localhost:3005",
        "http://127.0.0.1:50481", "http://localhost:50481"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# Add Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
    return response

# Include routes
app.include_router(router)
