#!/bin/bash

# 가상환경 활성화 (필요한 경우)
# source venv/bin/activate

# 패키지 설치
echo "Installing dependencies..."
pip install -r requirements.txt

# 데이터베이스 마이그레이션 초기화 (처음 실행 시만)
if [ ! -d "alembic" ]; then
    echo "Initializing Alembic..."
    alembic init alembic
fi

# 마이그레이션 파일 생성
echo "Creating migration..."
alembic revision --autogenerate -m "Initial migration"

# 마이그레이션 실행
echo "Running migration..."
alembic upgrade head

# 서버 실행
echo "Starting FastAPI server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload