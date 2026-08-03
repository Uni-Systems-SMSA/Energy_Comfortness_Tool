"""Migration: Create jobs table for tracking async job execution

This migration creates the jobs table to track metadata, status, progress,
results, and error messages for asynchronous jobs.

Table schema:
- id (String(50), primary key) — job_id
- user_id (String(50), nullable) — for tracking which user submitted
- status (String(20), default="queued") — queued, running, completed, failed, cancelled
- job_type (String(50)) — "ml_predict", "eplus_simulate", "weather_process"
- input_params (JSON) — Request parameters
- result_data (JSON, nullable) — Results when completed
- progress (Integer, default=0) — 0-100
- error_message (Text, nullable) — Error details
- created_at (DateTime, default=datetime.utcnow)
- started_at (DateTime, nullable)
- completed_at (DateTime, nullable)
- Indexes: on status, user_id, created_at

Run this script to apply the migration.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    JSON,
    Text,
    create_engine,
    MetaData,
    Index,
    text,
)
try:
    from sqlalchemy.orm import declarative_base
except ImportError:
    from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Setup database
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)
Base = declarative_base(metadata=metadata)


def get_database_url():
    """Get the database URL from environment variables."""
    postgres_user = os.environ.get('POSTGRES_USER', 'ect_admin')
    postgres_password = os.environ.get('POSTGRES_PASSWORD', 'ect_pwd')
    postgres_host = os.environ.get('POSTGRES_HOST', 'localhost')
    postgres_port = os.environ.get('POSTGRES_PORT', '5432')
    postgres_db = os.environ.get('POSTGRES_DB', 'ect_db')

    return (
        f"postgresql+psycopg2://{postgres_user}:"
        f"{postgres_password}@"
        f"{postgres_host}:{postgres_port}/"
        f"{postgres_db}"
    )


def get_engine():
    """Create and return the database engine."""
    database_url = get_database_url()
    return create_engine(database_url, echo=False)


class Job(Base):
    """ORM model for tracking async job execution."""

    __tablename__ = "jobs"

    # Primary key: job_id (String(50))
    id = Column(String(50), primary_key=True, nullable=False)

    # User tracking (nullable)
    user_id = Column(String(50), nullable=True)

    # Job status (default: "queued")
    # Valid values: queued, running, completed, failed, cancelled
    status = Column(String(20), nullable=False, default="queued")

    # Job type (required)
    # Valid values: "ml_predict", "eplus_simulate", "weather_process"
    job_type = Column(String(50), nullable=False)

    # Input parameters (JSON)
    input_params = Column(JSON, nullable=False)

    # Results when completed (nullable JSON)
    result_data = Column(JSON, nullable=True)

    # Progress tracking (0-100, default 0)
    progress = Column(Integer, nullable=False, default=0)

    # Error message (nullable Text)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        # Indexes for common queries
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_user_id", "user_id"),
        Index("ix_jobs_created_at", "created_at"),
    )


def run_migration():
    """Apply the migration: create jobs table with indexes."""

    try:
        engine = get_engine()

        # Create tables
        Base.metadata.create_all(bind=engine)
        print("✓ Created jobs table")

        # Verify table was created
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if "jobs" not in tables:
            print("✗ Failed: jobs table not found after creation")
            sys.exit(1)

        columns = [col["name"] for col in inspector.get_columns("jobs")]
        required_columns = [
            "id", "user_id", "status", "job_type", "input_params",
            "result_data", "progress", "error_message",
            "created_at", "started_at", "completed_at"
        ]

        missing = [col for col in required_columns if col not in columns]
        if missing:
            print(f"✗ Failed: missing columns: {missing}")
            sys.exit(1)

        print("✓ Verified all required columns")

        # Check indexes
        indexes = inspector.get_indexes("jobs")
        index_names = [idx["name"] for idx in indexes]

        required_indexes = ["ix_jobs_status", "ix_jobs_user_id", "ix_jobs_created_at"]
        missing_indexes = [idx for idx in required_indexes if idx not in index_names]

        if missing_indexes:
            print(f"⚠ Warning: missing indexes: {missing_indexes}")
        else:
            print("✓ Verified all indexes")

        print("\n✓ Migration completed successfully!")
        print("  - Table: jobs")
        print("  - Columns: 11")
        print("  - Indexes: 3 (status, user_id, created_at)")

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def rollback():
    """Rollback the migration: drop jobs table."""

    try:
        engine = get_engine()

        with engine.begin() as conn:
            print("Rolling back migration: add_jobs_table")

            # Drop table if it exists
            conn.execute(text("DROP TABLE IF EXISTS jobs CASCADE"))

            print("✓ Rolled back successfully!")

    except Exception as e:
        print(f"✗ Rollback failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create jobs table for async job tracking")
    parser.add_argument("--rollback", action="store_true", help="Rollback the migration")
    args = parser.parse_args()

    if args.rollback:
        rollback()
    else:
        run_migration()
