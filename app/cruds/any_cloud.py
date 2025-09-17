from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import json
import hashlib

from app.models.any_cloud import AnyCloudData, AnyCloudCache


class AnyCloudCRUD:
    """Any Cloud 데이터 관련 CRUD 작업"""

    # === AnyCloudData 관련 메서드 ===

    def create_data_record(
            self,
            db: Session,
            request_path: str,
            request_method: str,
            response_status: int,
            response_data: Dict[str, Any],
            member_id: str,
            request_params: Optional[Dict[str, Any]] = None,
            request_body: Optional[Dict[str, Any]] = None,
            response_headers: Optional[Dict[str, str]] = None,
            user_role: Optional[str] = None,
            user_name: Optional[str] = None,
            processing_time_ms: Optional[int] = None,
            is_cached: bool = False,
            cache_key: Optional[str] = None,
            tags: Optional[List[str]] = None,
            category: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None
    ) -> AnyCloudData:
        """Any Cloud API 요청/응답 데이터 기록"""
        db_data = AnyCloudData(
            request_path=request_path,
            request_method=request_method,
            request_params=request_params,
            request_body=request_body,
            response_status=response_status,
            response_data=response_data,
            response_headers=response_headers,
            member_id=member_id,
            user_role=user_role,
            user_name=user_name,
            processing_time_ms=processing_time_ms,
            is_cached=is_cached,
            cache_key=cache_key,
            tags=tags,
            category=category,
            metadata=metadata
        )
        db.add(db_data)
        db.commit()
        db.refresh(db_data)
        return db_data

    def get_data_by_id(self, db: Session, data_id: int) -> Optional[AnyCloudData]:
        """ID로 데이터 조회"""
        return db.query(AnyCloudData).filter(AnyCloudData.id == data_id).first()

    def get_data_by_member(
            self,
            db: Session,
            member_id: str,
            limit: int = 100,
            offset: int = 0,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None
    ) -> List[AnyCloudData]:
        """사용자별 데이터 조회"""
        query = db.query(AnyCloudData).filter(AnyCloudData.member_id == member_id)

        if start_date:
            query = query.filter(AnyCloudData.created_at >= start_date)
        if end_date:
            query = query.filter(AnyCloudData.created_at <= end_date)

        return query.order_by(desc(AnyCloudData.created_at)).offset(offset).limit(limit).all()

    def get_data_by_path(
            self,
            db: Session,
            request_path: str,
            request_method: Optional[str] = None,
            limit: int = 50
    ) -> List[AnyCloudData]:
        """경로별 데이터 조회"""
        query = db.query(AnyCloudData).filter(AnyCloudData.request_path == request_path)

        if request_method:
            query = query.filter(AnyCloudData.request_method == request_method)

        return query.order_by(desc(AnyCloudData.created_at)).limit(limit).all()

    def get_data_by_status(
            self,
            db: Session,
            response_status: int,
            limit: int = 100
    ) -> List[AnyCloudData]:
        """응답 상태별 데이터 조회"""
        return db.query(AnyCloudData).filter(
            AnyCloudData.response_status == response_status
        ).order_by(desc(AnyCloudData.created_at)).limit(limit).all()

    def get_data_by_category(
            self,
            db: Session,
            category: str,
            limit: int = 100
    ) -> List[AnyCloudData]:
        """카테고리별 데이터 조회"""
        return db.query(AnyCloudData).filter(
            AnyCloudData.category == category
        ).order_by(desc(AnyCloudData.created_at)).limit(limit).all()

    def search_data(
            self,
            db: Session,
            search_filters: Dict[str, Any],
            limit: int = 100,
            offset: int = 0
    ) -> Tuple[List[AnyCloudData], int]:
        """범용 데이터 검색"""
        query = db.query(AnyCloudData)

        # 동적 필터 적용
        if 'member_id' in search_filters:
            query = query.filter(AnyCloudData.member_id == search_filters['member_id'])

        if 'request_path' in search_filters:
            query = query.filter(AnyCloudData.request_path.contains(search_filters['request_path']))

        if 'request_method' in search_filters:
            query = query.filter(AnyCloudData.request_method == search_filters['request_method'])

        if 'response_status' in search_filters:
            query = query.filter(AnyCloudData.response_status == search_filters['response_status'])

        if 'category' in search_filters:
            query = query.filter(AnyCloudData.category == search_filters['category'])

        if 'start_date' in search_filters:
            query = query.filter(AnyCloudData.created_at >= search_filters['start_date'])

        if 'end_date' in search_filters:
            query = query.filter(AnyCloudData.created_at <= search_filters['end_date'])

        # 총 개수 조회
        total_count = query.count()

        # 페이징 및 정렬
        results = query.order_by(desc(AnyCloudData.created_at)).offset(offset).limit(limit).all()

        return results, total_count

    def delete_old_data(
            self,
            db: Session,
            days_old: int = 90
    ) -> int:
        """오래된 데이터 삭제"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)

        deleted_count = db.query(AnyCloudData).filter(
            AnyCloudData.created_at < cutoff_date
        ).delete()

        db.commit()
        return deleted_count

    # === AnyCloudCache 관련 메서드 ===

    def _generate_cache_key(
            self,
            request_path: str,
            request_method: str,
            request_params: Optional[Dict[str, Any]] = None,
            request_body: Optional[Dict[str, Any]] = None,
            member_id: Optional[str] = None
    ) -> Tuple[str, str]:
        """캐시 키 생성"""
        # 요청 시그니처 생성
        signature_data = {
            'path': request_path,
            'method': request_method,
            'params': request_params or {},
            'body': request_body or {},
            'member': member_id or ''
        }
        signature = json.dumps(signature_data, sort_keys=True)

        # 해시를 사용한 캐시 키 생성
        cache_key = hashlib.md5(signature.encode()).hexdigest()

        return cache_key, signature

    def get_cache(
            self,
            db: Session,
            request_path: str,
            request_method: str,
            request_params: Optional[Dict[str, Any]] = None,
            request_body: Optional[Dict[str, Any]] = None,
            member_id: Optional[str] = None
    ) -> Optional[AnyCloudCache]:
        """캐시 조회"""
        cache_key, _ = self._generate_cache_key(
            request_path, request_method, request_params, request_body, member_id
        )

        cache = db.query(AnyCloudCache).filter(
            and_(
                AnyCloudCache.cache_key == cache_key,
                AnyCloudCache.is_active == True,
                or_(
                    AnyCloudCache.expires_at.is_(None),
                    AnyCloudCache.expires_at > datetime.utcnow()
                )
            )
        ).first()

        # 캐시 히트 업데이트
        if cache:
            cache.hit_count += 1
            cache.last_hit_at = datetime.utcnow()
            db.commit()

        return cache

    def set_cache(
            self,
            db: Session,
            request_path: str,
            request_method: str,
            response_data: Dict[str, Any],
            response_status: int,
            request_params: Optional[Dict[str, Any]] = None,
            request_body: Optional[Dict[str, Any]] = None,
            member_id: Optional[str] = None,
            expires_in_minutes: Optional[int] = None
    ) -> AnyCloudCache:
        """캐시 설정"""
        cache_key, signature = self._generate_cache_key(
            request_path, request_method, request_params, request_body, member_id
        )

        expires_at = None
        if expires_in_minutes:
            expires_at = datetime.utcnow() + timedelta(minutes=expires_in_minutes)

        # 기존 캐시가 있다면 업데이트, 없다면 생성
        existing_cache = db.query(AnyCloudCache).filter(
            AnyCloudCache.cache_key == cache_key
        ).first()

        if existing_cache:
            existing_cache.cached_response = response_data
            existing_cache.response_status = response_status
            existing_cache.expires_at = expires_at
            existing_cache.is_active = True
            existing_cache.updated_at = datetime.utcnow()
            cache = existing_cache
        else:
            cache = AnyCloudCache(
                cache_key=cache_key,
                request_signature=signature,
                cached_response=response_data,
                response_status=response_status,
                expires_at=expires_at
            )
            db.add(cache)

        db.commit()
        db.refresh(cache)
        return cache

    def clear_expired_cache(self, db: Session) -> int:
        """만료된 캐시 정리"""
        deleted_count = db.query(AnyCloudCache).filter(
            and_(
                AnyCloudCache.expires_at.isnot(None),
                AnyCloudCache.expires_at < datetime.utcnow()
            )
        ).delete()

        db.commit()
        return deleted_count

    def get_cache_stats(self, db: Session) -> Dict[str, Any]:
        """캐시 통계 조회"""
        total_cache = db.query(func.count(AnyCloudCache.id)).scalar()
        active_cache = db.query(func.count(AnyCloudCache.id)).filter(
            AnyCloudCache.is_active == True
        ).scalar()
        total_hits = db.query(func.sum(AnyCloudCache.hit_count)).scalar() or 0

        return {
            'total_cache_entries': total_cache,
            'active_cache_entries': active_cache,
            'total_cache_hits': total_hits,
            'average_hits_per_entry': round(total_hits / max(total_cache, 1), 2)
        }

    # === 통계 관련 메서드 ===

    def get_api_usage_stats(
            self,
            db: Session,
            member_id: Optional[str] = None,
            days: int = 30
    ) -> Dict[str, Any]:
        """API 사용 통계"""
        start_date = datetime.utcnow() - timedelta(days=days)
        query = db.query(AnyCloudData).filter(AnyCloudData.created_at >= start_date)

        if member_id:
            query = query.filter(AnyCloudData.member_id == member_id)

        total_requests = query.count()

        # 메소드별 통계
        method_stats = db.query(
            AnyCloudData.request_method,
            func.count(AnyCloudData.id)
        ).filter(AnyCloudData.created_at >= start_date).group_by(
            AnyCloudData.request_method
        ).all()

        # 상태 코드별 통계
        status_stats = db.query(
            AnyCloudData.response_status,
            func.count(AnyCloudData.id)
        ).filter(AnyCloudData.created_at >= start_date).group_by(
            AnyCloudData.response_status
        ).all()

        return {
            'total_requests': total_requests,
            'period_days': days,
            'method_breakdown': dict(method_stats),
            'status_breakdown': dict(status_stats),
            'cache_stats': self.get_cache_stats(db)
        }


# 싱글톤 인스턴스
any_cloud_crud = AnyCloudCRUD()