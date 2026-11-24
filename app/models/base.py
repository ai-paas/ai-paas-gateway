from sqlalchemy.orm import declarative_base

Base = declarative_base()

# registered_via 값. 조회 경로의 자동 등록이 소유자를 짐작해 만든 매핑이라는 표시다.
# 생성 요청은 이 표시가 있는 행만 넘겨받는다.
REGISTERED_VIA_AUTO = "auto"
