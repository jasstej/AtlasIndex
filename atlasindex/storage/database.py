import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Default to local SQLite database in the workspace directory.
DEFAULT_DB_URL = "sqlite:///atlasindex.db"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB_URL)

# For SQLite, we enable check_same_thread=False to support multiple threads/watchers safely.
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """Create all tables in the database if they do not exist."""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency for obtaining database sessions in API or watcher loops."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
