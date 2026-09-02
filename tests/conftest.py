"""
테스트 공통 fixture

DB 전략:
- 기본: SQLite in-memory (빠른 CRUD 단위 테스트)
- 선택: TEST_DATABASE_URL 환경변수로 PostgreSQL 전환 가능
"""
import os

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

# 모든 모델을 import해야 Base.metadata에 등록됨
from app.models import (
    Member
)
from app.models.base import Base


def get_test_engine():
    """테스트 DB 엔진 생성 (환경변수 기반 백엔드 전환)"""
    test_db_url = os.environ.get("TEST_DATABASE_URL")

    if test_db_url:
        # PostgreSQL 테스트 DB
        engine = create_engine(test_db_url)
    else:
        # SQLite in-memory (기본)
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False}
        )
        # SQLite에서 FK 제약 활성화
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


# 모듈 레벨 엔진 (세션 전체에서 재사용)
_engine = get_test_engine()


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """세션 시작 시 테이블 생성, 종료 시 정리"""
    # postgresql_where 등 PostgreSQL 전용 인덱스는 SQLite에서 무시됨
    # SQLAlchemy가 자동으로 처리하므로 별도 조치 불필요
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture
def db():
    """
    각 테스트마다 독립된 DB 세션 제공 (트랜잭션 롤백으로 격리)

    흐름:
    1. connection 생성
    2. transaction 시작
    3. session 바인딩
    4. yield → 테스트 실행
    5. session.close()
    6. transaction.rollback() → 테스트 데이터 롤백
    7. connection.close()
    """
    connection = _engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def sample_member(db):
    """FK 의존성 해결용 기본 Member 레코드"""
    member = Member(
        name="테스트유저",
        member_id="testuser",
        email="test@example.com",
        password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
        role="user",
        is_active=True
    )
    db.add(member)
    db.flush()
    return member


@pytest.fixture
def admin_member(db):
    """관리자 Member 레코드"""
    member = Member(
        name="관리자",
        member_id="admin",
        email="admin@example.com",
        password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
        role="admin",
        is_active=True
    )
    db.add(member)
    db.flush()
    return member
