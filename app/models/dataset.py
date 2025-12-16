from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index
from sqlalchemy.sql import func
from . import Base


class Dataset(Base):
    """
    간소화된 데이터셋 매핑 테이블
    - 외부 API의 데이터셋 ID와 Inno 사용자 매핑만 저장
    - 나머지 상세 정보는 외부 API에서 실시간 조회
    """
    __tablename__ = "datasets"

    # 기본 키
    id = Column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True,
        comment="Inno DB 내부 ID"
    )

    # 핵심 매핑 정보
    surro_dataset_id = Column(
        Integer,
        nullable=False,
        index=True,
        comment="외부 API 데이터셋 ID"
    )
    created_by = Column(
        String(50),
        nullable=False,
        index=True,
        comment="생성자 member_id"
    )

    # 선택적 캐시 정보 (성능 최적화용)
    name = Column(
        String(255),
        nullable=True,
        comment="데이터셋 이름 (캐시용)"
    )

    # 메타데이터
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="생성 시간"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="수정 시간"
    )
    updated_by = Column(
        String(50),
        nullable=True,
        comment="수정자 member_id"
    )

    # 소프트 삭제
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="삭제 시간"
    )
    deleted_by = Column(
        String(50),
        nullable=True,
        comment="삭제자 member_id"
    )
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="활성화 상태"
    )

    # 인덱스 정의
    __table_args__ = (
        # 복합 인덱스: 사용자별 데이터셋 조회 최적화
        Index('idx_datasets_member_active', 'created_by', 'is_active', 'deleted_at'),

        # 복합 인덱스: 외부 API 데이터셋 ID + 사용자 ID (소유권 확인용)
        Index('idx_datasets_surro_member', 'surro_dataset_id', 'created_by'),

        # 복합 인덱스: 생성 시간 기반 조회
        Index('idx_datasets_created_member', 'created_by', 'created_at'),

        # 유니크 제약: 동일한 외부 데이터셋을 같은 사용자가 중복 매핑하는 것 방지
        Index(
            'idx_datasets_unique_mapping',
            'surro_dataset_id',
            'created_by',
            unique=True,
            postgresql_where=Column('deleted_at').is_(None)
        ),

        {'comment': '사용자별 외부 API 데이터셋 매핑 테이블'}
    )

    def __repr__(self):
        return (
            f"<Dataset(id={self.id}, surro_id={self.surro_dataset_id}, "
            f"member={self.created_by})>"
        )

    def to_dict(self):
        """딕셔너리 형태로 변환"""
        return {
            'id': self.id,
            'surro_dataset_id': self.surro_dataset_id,
            'created_by': self.created_by,
            'name': self.name,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'updated_by': self.updated_by,
            'deleted_at': self.deleted_at,
            'deleted_by': self.deleted_by,
            'is_active': self.is_active
        }

    @property
    def is_deleted(self):
        """삭제 여부 확인"""
        return self.deleted_at is not None

    @classmethod
    def create_mapping(
            cls,
            surro_dataset_id: int,
            member_id: str,
            dataset_name: str = None
    ):
        """새 매핑 생성을 위한 헬퍼 메서드"""
        return cls(
            surro_dataset_id=surro_dataset_id,
            created_by=member_id,
            updated_by=member_id,
            name=dataset_name
        )