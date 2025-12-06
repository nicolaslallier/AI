# Testing Setup Guide

## Prerequisites

### Python Environment

The testing framework requires Python 3.10+ with pip. Choose one of the following setup methods:

### Option 1: Using Homebrew (Recommended for macOS)

```bash
# Install Python
brew install python3

# Verify installation
python3 --version
pip3 --version
```

### Option 2: Using pyenv

```bash
# Install pyenv
brew install pyenv

# Install Python 3.10 or higher
pyenv install 3.10.0
pyenv global 3.10.0

# Add to your shell profile (~/.zshrc)
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
echo 'eval "$(pyenv init -)"' >> ~/.zshrc

# Reload shell
source ~/.zshrc
```

### Option 3: Using Python.org Installer

Download and install from: https://www.python.org/downloads/

## Installation Steps

### 1. Install Python Dependencies

Once Python is installed, run:

```bash
# Using pip3 (recommended)
pip3 install -r tests/requirements.txt

# Or using python3 -m pip
python3 -m pip install -r tests/requirements.txt

# Or create a virtual environment (best practice)
python3 -m venv venv
source venv/bin/activate
pip install -r tests/requirements.txt
```

### 2. Setup Test Environment

```bash
make test-setup
```

This will:
- Create necessary directories
- Install Python dependencies (if not already installed)
- Start Docker containers
- Verify services are running

### 3. Verify Setup

```bash
# Check Python installation
python3 --version
pip3 --version

# Check pytest installation
pytest --version

# List available tests
pytest --collect-only tests/unit/nginx
```

## Running Tests

### Without Python (Docker-only tests)

Even without Python locally installed, you can run tests inside Docker:

```bash
# Run tests in Docker container
docker-compose -f docker-compose.test.yml run --rm playwright pytest tests/unit/nginx -v
```

### With Python Installed

```bash
# Run all tests
make test

# Run specific test suites
make test-unit
make test-nginx

# Run with coverage
pytest tests/unit/nginx --cov --cov-report=html
```

## Troubleshooting

### Issue: "pip: command not found"

**Solution**: Install Python 3 using one of the methods above.

### Issue: "pytest: command not found"

**Solution**: 
```bash
pip3 install pytest
# Or
python3 -m pip install pytest
```

### Issue: Permission denied

**Solution**:
```bash
# Use --user flag
pip3 install --user -r tests/requirements.txt
```

### Issue: Docker not running

**Solution**:
```bash
# Start Docker Desktop
open -a Docker

# Verify Docker is running
docker ps
```

## Alternative: Docker-Based Testing

If you prefer not to install Python locally, run tests entirely in Docker:

```bash
# Build test container
docker build -t ai-infra-tests -f tests/Dockerfile .

# Run tests
docker run --rm ai-infra-tests pytest tests/unit/nginx -v
```

## Quick Reference

```bash
# Install dependencies
pip3 install -r tests/requirements.txt

# Setup environment
make test-setup

# Run tests
make test

# View reports
open tests/reports/coverage-html/index.html
```

## Support

For issues or questions:
1. Check `TESTING.md` for general testing guide
2. See `TESTING_COMPLETE.md` for implementation details
3. Review example tests in `tests/unit/nginx/`

