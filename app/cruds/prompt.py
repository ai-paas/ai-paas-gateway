from sqlalchemy.orm import Session
from typing import List, Optional, Tuple
from app.models.prompt import Prompt
from app.schemas.prompt import PromptCreate


class PromptCRUD:
    def create_prompt(
            self,
            db: Session,
            prompt: PromptCreate,
            created_by: str,
            surro_prompt_id: int,
            external_prompt_variables: Optional[List[dict]] = None  # 외부 API 응답 추가
    ) -> Prompt:
        """프롬프트 생성 (외부 API 호출 후 우리 DB 저장)"""
        # 외부 API에서 받은 prompt_variable 저장 (딕셔너리 형태 유지)
        prompt_variables = None
        if external_prompt_variables:
            # PromptVariableReadSchema 객체를 딕셔너리로 변환
            prompt_variables = [
                {
                    "id": var.id,
                    "name": var.name,
                    "prompt_id": var.prompt_id
                } if hasattr(var, 'id') else var
                for var in external_prompt_variables
            ]

        db_prompt = Prompt(
            name=prompt.prompt.name,
            description=prompt.prompt.description,
            content=prompt.prompt.content,
            prompt_variable=prompt_variables,  # 딕셔너리 리스트로 저장
            created_by=created_by,
            surro_prompt_id=surro_prompt_id
        )
        db.add(db_prompt)
        db.commit()
        db.refresh(db_prompt)
        return db_prompt

    def get_prompt(self, db: Session, prompt_id: int) -> Optional[Prompt]:
        """내부 ID로 조회"""
        return db.query(Prompt).filter(Prompt.id == prompt_id).first()

    def get_prompt_by_surro_id(self, db: Session, surro_prompt_id: int) -> Optional[Prompt]:
        """외부 API ID로 조회"""
        return db.query(Prompt).filter(Prompt.surro_prompt_id == surro_prompt_id).first()

    def get_prompts(
            self,
            db: Session,
            skip: Optional[int] = None,
            limit: Optional[int] = None,
            search: Optional[str] = None
    ) -> Tuple[List[Prompt], int]:
        """프롬프트 목록 조회"""
        query = db.query(Prompt)

        total = query.count()

        # 페이지네이션 적용 (skip, limit이 있을 때만)
        if skip is not None and limit is not None:
            prompts = query.offset(skip).limit(limit).all()
        else:
            # 전체 데이터 조회 (최대 10000개)
            prompts = query.limit(10000).all()

        return prompts, total

    def delete_prompt(self, db: Session, prompt_id: int) -> bool:
        """내부 ID로 프롬프트 삭제"""
        db_prompt = self.get_prompt(db, prompt_id)
        if db_prompt:
            db.delete(db_prompt)
            db.commit()
            return True
        return False

    def delete_prompt_by_surro_id(self, db: Session, surro_prompt_id: int) -> bool:
        """외부 ID로 프롬프트 삭제"""
        db_prompt = self.get_prompt_by_surro_id(db, surro_prompt_id)
        if db_prompt:
            db.delete(db_prompt)
            db.commit()
            return True
        return False


# 전역 CRUD 인스턴스
prompt_crud = PromptCRUD()