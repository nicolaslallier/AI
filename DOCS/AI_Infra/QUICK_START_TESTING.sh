#!/bin/bash

# Quick Start Script for Testing Setup
# This handles the Python 3.14 issue automatically

set -e

echo "🔍 Checking Python version..."

PYTHON_VERSION=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')

if [[ "$PYTHON_VERSION" == "3.14" ]]; then
    echo "❌ Python 3.14 detected - this is too new for our dependencies!"
    echo ""
    echo "📦 Installing Python 3.12..."
    
    if command -v brew &> /dev/null; then
        brew install python@3.12 || echo "Python 3.12 might already be installed"
        
        echo ""
        echo "✅ Python 3.12 installed!"
        echo ""
        echo "🔧 Setting up test environment with Python 3.12..."
        
        rm -rf venv
        python3.12 -m venv venv
        source venv/bin/activate
        
        echo "📦 Installing dependencies..."
        pip install --upgrade pip setuptools wheel
        pip install -r tests/requirements.txt
        
        echo ""
        echo "✅ Setup complete!"
        echo ""
        echo "To run tests:"
        echo "  source venv/bin/activate"
        echo "  pytest tests/unit/nginx -v"
        
    else
        echo "❌ Homebrew not found. Please install Python 3.12 manually:"
        echo "   brew install python@3.12"
        echo "   OR visit: https://www.python.org/downloads/"
    fi
    
elif [[ "$PYTHON_VERSION" =~ ^3\.(10|11|12|13)$ ]]; then
    echo "✅ Python $PYTHON_VERSION detected - compatible!"
    echo ""
    echo "🔧 Setting up test environment..."
    
    rm -rf venv
    python3 -m venv venv
    source venv/bin/activate
    
    echo "📦 Installing dependencies..."
    pip install --upgrade pip setuptools wheel
    pip install -r tests/requirements.txt
    
    echo ""
    echo "✅ Setup complete!"
    echo ""
    echo "To run tests:"
    echo "  source venv/bin/activate"
    echo "  pytest tests/unit/nginx -v"
    
else
    echo "⚠️  Python version $PYTHON_VERSION detected"
    echo "Recommended: Python 3.10-3.13"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        python3 -m venv venv
        source venv/bin/activate
        pip install -r tests/requirements.txt
    fi
fi
