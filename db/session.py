import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

def _get_database_url():
    """Get database URL from environment variables."""
    # Use DATABASE_URL if provided (for Docker), otherwise construct from env vars
    if os.environ.get('DATABASE_URL'):
        return os.environ['DATABASE_URL']

    return (
        f"postgresql+psycopg2://{os.environ.get('POSTGRES_USER', 'user')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', 'password')}@"
        f"{os.environ.get('POSTGRES_HOST', 'localhost')}:{os.environ.get('POSTGRES_PORT', 5432)}/"
        f"{os.environ.get('POSTGRES_DB', 'ece_db')}"
    )

DB_URL = _get_database_url()
engine = create_engine(DB_URL, echo=False, pool_pre_ping=True, pool_size=20, max_overflow=40)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
