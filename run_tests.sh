#!/bin/bash

# ECE Test Runner Script
# This script runs all tests for the ECE scalability refactor

set -e

echo "================================================"
echo "ECE Test Suite Runner"
echo "================================================"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_info() {
    echo -e "${YELLOW}[i]${NC} $1"
}

# Check if docker-compose is running
check_docker_compose() {
    print_info "Checking Docker Compose services..."

    if ! docker-compose ps | grep -q "postgres"; then
        print_error "PostgreSQL is not running. Please start it with: docker-compose up -d"
        return 1
    fi

    if ! docker-compose ps | grep -q "redis"; then
        print_error "Redis is not running. Please start it with: docker-compose up -d"
        return 1
    fi

    print_status "Docker Compose services are running"
    return 0
}

# Install test dependencies
install_test_deps() {
    print_info "Installing test dependencies..."
    pip install -r requirements-test.txt
    print_status "Test dependencies installed"
}

# Run unit tests
run_unit_tests() {
    print_info "Running unit tests..."
    pytest tests/backend/test_api.py -v --tb=short
    print_status "Unit tests completed"
}

# Run integration tests
run_integration_tests() {
    print_info "Running integration tests..."
    pytest tests/integration/test_job_lifecycle.py -v --tb=short
    print_status "Integration tests completed"
}

# Run load tests
run_load_tests() {
    print_info "Running load tests for 1 minute with 6 users..."
    locust -f tests/load/locustfile.py --host=http://localhost:8000 \
            --users=6 --spawn-rate=2 --run-time=1m --headless
    print_status "Load tests completed"
}

# Main script logic
main() {
    echo ""

    # Parse arguments
    TEST_TYPE="${1:-all}"

    case $TEST_TYPE in
        unit)
            check_docker_compose || exit 1
            install_test_deps
            run_unit_tests
            ;;
        integration)
            check_docker_compose || exit 1
            install_test_deps
            run_integration_tests
            ;;
        load)
            check_docker_compose || exit 1
            install_test_deps
            run_load_tests
            ;;
        all)
            check_docker_compose || exit 1
            install_test_deps
            run_unit_tests
            echo ""
            run_integration_tests
            echo ""
            run_load_tests
            ;;
        *)
            print_error "Unknown test type: $TEST_TYPE"
            echo ""
            echo "Usage: $0 [unit|integration|load|all]"
            echo ""
            echo "Examples:"
            echo "  $0 unit          # Run unit tests only"
            echo "  $0 integration   # Run integration tests only"
            echo "  $0 load          # Run load tests only"
            echo "  $0 all           # Run all tests (default)"
            exit 1
            ;;
    esac

    echo ""
    print_status "All tests completed successfully!"
    echo ""
}

main "$@"
