from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.prompt import Prompt
from app.schemas.prompt import PromptCreate

_MISSING = object()


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


class PromptCRUD:
    def create_prompt(
            self,
            db: Session,
            prompt: PromptCreate,
            created_by: str,
            surro_prompt_id: int,
            external_prompt_variables: Optional[List[dict]] = None
    ) -> Prompt:
        """프롬프트 생성 (external 생성 후 로컬 캐시/매핑 저장)."""
        prompt_variables = _variables_to_dicts(external_prompt_variables)

        db_prompt = Prompt(
            name=prompt.prompt.name,
            description=prompt.prompt.description,
            content=prompt.prompt.content,
            prompt_variable=prompt_variables,
            created_by=created_by,
            surro_prompt_id=surro_prompt_id,
            is_active=True,
            deleted_at=None,
            deleted_by=None,
        )
        db.add(db_prompt)
        db.commit()
        db.refresh(db_prompt)
        return db_prompt

    def get_prompt(self, db: Session, prompt_id: int, include_deleted: bool = False) -> Optional[Prompt]:
        """로컬 PK로 조회."""
        query = db.query(Prompt).filter(Prompt.id == prompt_id)
        if not include_deleted:
            query = query.filter(and_(Prompt.deleted_at.is_(None), Prompt.is_active == True))
        return query.first()

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
        return query.first()

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
    ) -> Prompt:
        """external prompt 기준 로컬 매핑 upsert/revive."""
        existing = self.get_prompt_by_surro_id(db, surro_prompt_id, include_deleted=True)
        if existing:
            existing.name = name
            existing.description = description
            existing.content = content
            existing.prompt_variable = _variables_to_dicts(prompt_variable)
            existing.is_active = True
            existing.deleted_at = None
            existing.deleted_by = None
            existing.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(existing)
            return existing

        db_prompt = Prompt(
            name=name,
            description=description,
            content=content,
            prompt_variable=_variables_to_dicts(prompt_variable),
            created_by=member_id,
            surro_prompt_id=surro_prompt_id,
            is_active=True,
        )
        db.add(db_prompt)
        db.commit()
        db.refresh(db_prompt)
        return db_prompt

    def backfill_cache_if_changed(
            self,
            db: Session,
            surro_prompt_id: int,
            name: Any = _MISSING,
            description: Any = _MISSING,
            content: Any = _MISSING,
            prompt_variable: Any = _MISSING,
    ) -> bool:
        """외부 응답 기준 로컬 캐시를 갱신하고 soft-delete 상태면 복구한다."""
        mapping = self.get_prompt_by_surro_id(db, surro_prompt_id, include_deleted=True)
        if not mapping:
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
            if mapping.prompt_variable != new_vars:
                mapping.prompt_variable = new_vars
                changed = True

        if mapping.deleted_at is not None or mapping.deleted_by is not None or mapping.is_active is False:
            mapping.deleted_at = None
            mapping.deleted_by = None
            mapping.is_active = True
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
    ) -> int:
        """외부에서 사라진 활성 매핑을 soft delete 처리."""
        active_id_set = set(active_surro_prompt_ids)
        targets = db.query(Prompt).filter(
            and_(Prompt.deleted_at.is_(None), Prompt.is_active == True)
        ).all()

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
