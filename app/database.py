from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def commit_or_rollback(db):
    """commit 실패 시 rollback 후 예외를 다시 올린다.

    호출자가 예외를 삼키고 같은 세션을 계속 써도 PendingRollbackError 가 나지 않게 한다.
    """
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


# DB 세션 의존성
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()