"""
FastAPI backend application.

Serves as the main entry point for the ECE scalability refactor backend.
Handles prediction and simulation job submissions with asynchronous processing.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import settings

# Initialize FastAPI app
app = FastAPI(
    title="ECE Backend API",
    description="Backend API for Energy Comfort Estimation",
    version="0.1.0"
)

# Configure CORS middleware to allow all origins for Streamlit frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    return JSONResponse(
        status_code=200,
        content={"status": "healthy"}
    )


# Include routers for various endpoints
from backend.api import predict, simulate

app.include_router(predict.router, prefix="/api/v1", tags=["predict"])
app.include_router(simulate.router, prefix="/api/v1", tags=["simulate"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True
    )
