import json
from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import commit_or_rollback
from app.models.base import REGISTERED_VIA_AUTO
from app.models.prompt import Prompt
from app.schemas.prompt import PromptCreate

_MISSING = object()

# 생성 경로가 재사용된 ID 의 옛 매핑을 정리할 때 남긴다. 동기화 경로(이름 차이로 추론)와 구분한다.
_DELETED_BY_REUSED_ON_CREATE = "system:upstream-id-reused:create"


def _variables_to_dicts(prompt_variables) -> Optional[List[dict]]:
    """External/DB prompt variables를 JSON 직렬화 가능한 dict list로 정규화."""
    if not prompt_variables:
        return None

    result = []
    for var in prompt_variables:
        if hasattr(var, "id"):
            result.append({"id": var.id, "name": var.name, "prompt_id": var.prompt_id})
        elif isinstance(var, dict):
            result.append(var)
    return result or None


def _same_variables(current, new) -> bool:
    """변수 목록을 순서와 무관하게 비교한다. 같은 변수를 다른 순서로 받아도 조회마다 쓰지 않게 한다."""
    if not isinstance(current, list) or not isinstance(new, list):
        return current == new
    key = lambda var: json.dumps(var, sort_keys=True, default=str)
    return sorted(current, key=key) == sorted(new, key=key)


class PromptCRUD:
    def create_prompt(
            self,
            db: Session,
            prompt: PromptCreate,
            created_by: str,
            surro_prompt_id: int,
            requested_at: datetime,
            external_prompt_variables: Optional[List[dict]] = None,
    ) -> Tuple[Prompt, bool]:
        """방금 MLOps 에 만든 프롬프트의 매핑을 저장한다. (매핑, 자동 등록 행을 넘겨받았는지) 를 돌려준다.

        MLOps 가 이 ID 를 새로 발급했으므로 이미 있는 활성 매핑은 둘 중 하나다.
        - 요청 뒤(requested_at 이후)에 생긴 자동 등록 행: 이 요청과 겹친 조회가 먼저 등록한 것이므로 넘겨받는다.
        - 그 밖의 행: MLOps 재설치 등으로 사라진 옛 리소스의 매핑이므로 이력으로 남기고 새 행을 만든다.
        requested_at 은 MLOps 생성 요청 전 시각(naive UTC)이다.
        """
        values = dict(
            name=prompt.prompt.name,
            description=prompt.prompt.description,
            content=prompt.prompt.content,
            prompt_variable=_variables_to_dicts(external_prompt_variables),
        )
        # 생성 경로의 조회와 INSERT 사이에 자동 등록이 끼어들면 INSERT 가 실패한다.
        # 다시 시도하면 그 행은 넘겨받을 대상이므로 두 번이면 충분하다.
        for attempt in range(2):
            claimed = db.query(Prompt).filter(
                Prompt.surro_prompt_id == surro_prompt_id,
                Prompt.deleted_at.is_(None),
                Prompt.registered_via == REGISTERED_VIA_AUTO,
                Prompt.created_at >= requested_at,
            ).update(
                {**values, "created_by": created_by, "registered_via": None,
                 "updated_at": datetime.utcnow()},
                synchronize_session=False,
            )
            commit_or_rollback(db)
            if claimed:
                return self._active_mapping(db, surro_prompt_id), True

            self._retire_active_mapping(db, surro_prompt_id)
            db_prompt = Prompt(
                **values, created_by=created_by, surro_prompt_id=surro_prompt_id, is_active=True,
            )
            db.add(db_prompt)
            try:
                commit_or_rollback(db)
            except IntegrityError:
                if attempt:
                    raise
                continue
            db.refresh(db_prompt)
            return db_prompt, False

    def _active_mapping(self, db: Session, surro_prompt_id: int) -> Prompt:
        return db.query(Prompt).filter(
            Prompt.surro_prompt_id == surro_prompt_id,
            Prompt.deleted_at.is_(None),
        ).one()

    def _retire_active_mapping(self, db: Session, surro_prompt_id: int) -> None:
        """재사용된 ID 의 옛 활성 매핑을 이력으로 돌린다. 유니크 인덱스는 deleted_at 만 보므로 is_active 와 무관하게 찾는다."""
        now = datetime.utcnow()
        db.query(Prompt).filter(
            Prompt.surro_prompt_id == surro_prompt_id,
            Prompt.deleted_at.is_(None),
        ).update(
            {"is_active": False, "deleted_at": now, "deleted_by": _DELETED_BY_REUSED_ON_CREATE,
             "updated_at": now},
            synchronize_session=False,
        )

    def get_prompt(self, db: Session, prompt_id: int, include_deleted: bool = False) -> Optional[Prompt]:
        """로컬 PK로 조회."""
        query = db.query(Prompt).filter(Prompt.id == prompt_id)
        if not include_deleted:
            query = query.filter(and_(Prompt.deleted_at.is_(None), Prompt.is_active == True))
        return query.order_by(Prompt.id.desc()).first()

    def get_prompt_by_surro_id(
            self,
            db: Session,
            surro_prompt_id: int,
            include_deleted: bool = False,
    ) -> Optional[Prompt]:
        """외부 prompt id로 조회."""
        query = db.query(Prompt).filter(Prompt.surro_prompt_id == surro_prompt_id)
        if not include_deleted:
            query = query.filter(and_(Prompt.deleted_at.is_(None), Prompt.is_active == True))
        return query.order_by(Prompt.id.desc()).first()

    def get_prompts(
            self,
            db: Session,
            skip: Optional[int] = None,
            limit: Optional[int] = None,
            search: Optional[str] = None,
            order_by: Optional[list] = None,
            member_id: Optional[str] = None,
            valid_surro_ids: Optional[set] = None,
    ) -> Tuple[List[Prompt], int]:
        """활성 prompt 목록 조회."""
        query = db.query(Prompt).filter(
            and_(Prompt.deleted_at.is_(None), Prompt.is_active == True)
        )

        if member_id is not None:
            query = query.filter(Prompt.created_by == member_id)

        if valid_surro_ids is not None:
            if not valid_surro_ids:
                return [], 0
            query = query.filter(Prompt.surro_prompt_id.in_(valid_surro_ids))

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    Prompt.name.ilike(search_filter),
                    Prompt.description.ilike(search_filter),
                    Prompt.content.ilike(search_filter),
                )
            )

        total = query.count()

        if order_by:
            query = query.order_by(*order_by)

        if skip is not None and limit is not None:
            prompts = query.offset(skip).limit(limit).all()
        else:
            prompts = query.limit(10000).all()

        return prompts, total

    def get_prompts_by_surro_ids(
            self,
            db: Session,
            surro_prompt_ids: set[int],
            include_deleted: bool = False,
    ) -> List[Prompt]:
        """surro_prompt_id 집합에 해당하는 매핑 목록 조회."""
        if not surro_prompt_ids:
            return []

        query = db.query(Prompt).filter(Prompt.surro_prompt_id.in_(surro_prompt_ids))
        if not include_deleted:
            query = query.filter(and_(Prompt.deleted_at.is_(None), Prompt.is_active == True))
        return query.all()

    def create_mapping_from_external(
            self,
            db: Session,
            surro_prompt_id: int,
            member_id: str,
            name: str,
            description: Optional[str],
            content: str,
            prompt_variable=None,
            fetched_at: Optional[datetime] = None,
            ignore_conflict: bool = False,
            registered_via: Optional[str] = None,
    ) -> Prompt:
        """external prompt 기준 활성 매핑을 갱신하거나 새 이력 행을 생성한다.

        fetched_at: 외부 응답을 요청한 시각(naive UTC). 매핑이 그 뒤에 바뀌었으면 응답이 더
            오래된 것이므로 매핑을 건드리지 않는다.
        ignore_conflict: 동시 요청이 먼저 만든 활성 매핑이 있으면 INSERT 실패 대신 그 행을 돌려준다.
        """
        existing, updated_since = self._get_mapping_for_sync(db, surro_prompt_id, fetched_at)
        if existing:
            if updated_since:
                return existing
            if existing.name != name:
                # 숫자 ID 재사용 가능성이 있으므로 기존 소유권을 새 리소스에 넘기지 않는다.
                now = datetime.utcnow()
                existing.is_active = False
                existing.deleted_at = now
                existing.deleted_by = "system:upstream-id-reused"
                existing.updated_at = now
                db.flush()
            else:
                # 조회마다 쓰지 않도록 값이 바뀐 경우에만 갱신한다
                new_vars = _variables_to_dicts(prompt_variable)
                changed = False
                if existing.description != description:
                    existing.description = description
                    changed = True
                if existing.content != content:
                    existing.content = content
                    changed = True
                if not _same_variables(existing.prompt_variable, new_vars):
                    existing.prompt_variable = new_vars
                    changed = True
                if changed:
                    existing.updated_at = datetime.utcnow()
                    db.commit()
                    db.refresh(existing)
                return existing

        values = dict(
            name=name,
            description=description,
            content=content,
            prompt_variable=_variables_to_dicts(prompt_variable),
            created_by=member_id,
            surro_prompt_id=surro_prompt_id,
            is_active=True,
            registered_via=registered_via,
        )
        dialect = db.bind.dialect.name
        if ignore_conflict and dialect in ("postgresql", "sqlite"):
            insert = pg_insert if dialect == "postgresql" else sqlite_insert
            stmt = insert(Prompt).values(**values).on_conflict_do_nothing(
                index_elements=[Prompt.surro_prompt_id],
                index_where=Prompt.deleted_at.is_(None),
            )
            db.execute(stmt)
            db.commit()
            return db.query(Prompt).filter(
                Prompt.surro_prompt_id == surro_prompt_id,
                Prompt.deleted_at.is_(None),
            ).order_by(Prompt.id.desc()).first()

        db_prompt = Prompt(**values)
        db.add(db_prompt)
        db.commit()
        db.refresh(db_prompt)
        return db_prompt

    def _get_mapping_for_sync(
            self, db: Session, surro_prompt_id: int, since: Optional[datetime],
    ) -> Tuple[Optional[Prompt], bool]:
        """활성 매핑과, 그 매핑이 since 이후에 갱신됐는지를 SELECT 한 번으로 조회한다.

        시각은 저장값과 같은 기준으로 해석되도록 DB 에서 비교한다.
        """
        if since is None:
            return self.get_prompt_by_surro_id(db, surro_prompt_id), False
        row = db.query(Prompt, Prompt.updated_at >= since).filter(
            Prompt.surro_prompt_id == surro_prompt_id,
            Prompt.deleted_at.is_(None),
            Prompt.is_active == True,
        ).order_by(Prompt.id.desc()).first()
        if row is None:
            return None, False
        return row[0], bool(row[1])

    def backfill_cache_if_changed(
            self,
            db: Session,
            surro_prompt_id: int,
            name: Any = _MISSING,
            description: Any = _MISSING,
            content: Any = _MISSING,
            prompt_variable: Any = _MISSING,
            fetched_at: Optional[datetime] = None,
    ) -> bool:
        """활성 매핑의 외부 응답 캐시를 갱신한다.

        fetched_at 이후에 바뀐 매핑은 건드리지 않는다. 오래된 응답의 이름을 되돌려 쓰면 다음
        동기화가 이름 차이를 ID 재사용으로 판단한다.
        """
        mapping, updated_since = self._get_mapping_for_sync(db, surro_prompt_id, fetched_at)
        if not mapping or updated_since:
            return False

        changed = False
        if name is not _MISSING and mapping.name != name:
            mapping.name = name
            changed = True
        if description is not _MISSING and mapping.description != description:
            mapping.description = description
            changed = True
        if content is not _MISSING and mapping.content != content:
            mapping.content = content
            changed = True
        if prompt_variable is not _MISSING:
            new_vars = _variables_to_dicts(prompt_variable)
            if not _same_variables(mapping.prompt_variable, new_vars):
                mapping.prompt_variable = new_vars
                changed = True

        if changed:
            mapping.updated_at = datetime.utcnow()
            db.commit()
        return changed

    def soft_delete_missing_mappings(
            self,
            db: Session,
            active_surro_prompt_ids: List[int],
            deleted_by: str = "admin",
            fetched_at: Optional[datetime] = None,
    ) -> int:
        """외부에서 사라진 활성 매핑을 soft delete 처리.

        fetched_at 을 주면 그보다 먼저 만든 매핑만 정리한다. 목록을 받은 뒤 만든 프롬프트는
        목록에 없어도 사라진 것이 아니다.
        """
        # 빈 목록은 "전부 삭제됨"과 "업스트림 일시 장애"를 구분할 수 없다.
        if not active_surro_prompt_ids:
            return 0
        active_id_set = set(active_surro_prompt_ids)
        query = db.query(Prompt).filter(
            and_(Prompt.deleted_at.is_(None), Prompt.is_active == True)
        )
        if fetched_at is not None:
            query = query.filter(Prompt.created_at < fetched_at)
        targets = query.all()

        now = datetime.utcnow()
        deleted_count = 0
        for prompt in targets:
            if prompt.surro_prompt_id in active_id_set:
                continue
            prompt.is_active = False
            prompt.deleted_at = now
            prompt.deleted_by = deleted_by
            prompt.updated_at = now
            deleted_count += 1

        if deleted_count:
            db.commit()
        return deleted_count

    def delete_prompt(self, db: Session, prompt_id: int, deleted_by: Optional[str] = None) -> bool:
        """로컬 PK 기준 soft delete."""
        db_prompt = self.get_prompt(db, prompt_id)
        if db_prompt:
            db_prompt.deleted_at = datetime.utcnow()
            db_prompt.deleted_by = deleted_by or db_prompt.created_by
            db_prompt.is_active = False
            db_prompt.updated_at = datetime.utcnow()
            db.commit()
            return True
        return False

    def delete_prompt_by_surro_id(
            self,
            db: Session,
            surro_prompt_id: int,
            deleted_by: Optional[str] = None,
    ) -> bool:
        """외부 ID 기준 soft delete."""
        db_prompt = self.get_prompt_by_surro_id(db, surro_prompt_id)
        if db_prompt:
            db_prompt.deleted_at = datetime.utcnow()
            db_prompt.deleted_by = deleted_by or db_prompt.created_by
            db_prompt.is_active = False
            db_prompt.updated_at = datetime.utcnow()
            db.commit()
            return True
        return False


prompt_crud = PromptCRUD()
