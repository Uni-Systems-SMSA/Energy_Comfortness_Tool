@echo off
REM ECE Test Runner Script (Windows)
REM This script runs all tests for the ECE scalability refactor

setlocal enabledelayedexpansion

echo.
echo ================================================
echo ECE Test Suite Runner
echo ================================================
echo.

REM Parse arguments
set TEST_TYPE=%1
if "%TEST_TYPE%"=="" set TEST_TYPE=all

REM Check if docker-compose is running
echo [i] Checking Docker Compose services...

docker-compose ps | findstr "postgres" >nul
if errorlevel 1 (
    echo [X] PostgreSQL is not running. Please start it with: docker-compose up -d
    exit /b 1
)

docker-compose ps | findstr "redis" >nul
if errorlevel 1 (
    echo [X] Redis is not running. Please start it with: docker-compose up -d
    exit /b 1
)

echo [OK] Docker Compose services are running
echo.

REM Install test dependencies
echo [i] Installing test dependencies...
pip install -r requirements-test.txt
echo [OK] Test dependencies installed
echo.

REM Run tests based on type
if "%TEST_TYPE%"=="unit" (
    echo [i] Running unit tests...
    pytest tests/backend/test_api.py -v --tb=short
    if errorlevel 1 exit /b 1
    echo [OK] Unit tests completed
) else if "%TEST_TYPE%"=="integration" (
    echo [i] Running integration tests...
    pytest tests/integration/test_job_lifecycle.py -v --tb=short
    if errorlevel 1 exit /b 1
    echo [OK] Integration tests completed
) else if "%TEST_TYPE%"=="load" (
    echo [i] Running load tests for 1 minute with 6 users...
    locust -f tests/load/locustfile.py --host=http://localhost:8000 --users=6 --spawn-rate=2 --run-time=1m --headless
    if errorlevel 1 exit /b 1
    echo [OK] Load tests completed
) else if "%TEST_TYPE%"=="all" (
    echo [i] Running unit tests...
    pytest tests/backend/test_api.py -v --tb=short
    if errorlevel 1 exit /b 1
    echo [OK] Unit tests completed
    echo.
    echo [i] Running integration tests...
    pytest tests/integration/test_job_lifecycle.py -v --tb=short
    if errorlevel 1 exit /b 1
    echo [OK] Integration tests completed
    echo.
    echo [i] Running load tests for 1 minute with 6 users...
    locust -f tests/load/locustfile.py --host=http://localhost:8000 --users=6 --spawn-rate=2 --run-time=1m --headless
    if errorlevel 1 exit /b 1
    echo [OK] Load tests completed
) else (
    echo [X] Unknown test type: %TEST_TYPE%
    echo.
    echo Usage: %0 [unit^|integration^|load^|all]
    echo.
    echo Examples:
    echo   %0 unit          # Run unit tests only
    echo   %0 integration   # Run integration tests only
    echo   %0 load          # Run load tests only
    echo   %0 all           # Run all tests (default)
    exit /b 1
)

echo.
echo [OK] All tests completed successfully!
echo.

endlocal
