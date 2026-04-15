#!/bin/bash

set -e

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Applying database migrations..."
alembic upgrade head

echo "Starting FastAPI server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
