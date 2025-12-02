from sqlalchemy.orm import Session
from typing import Optional
from app.models.pipeline import Experiment


class PipelineCRUD:
    def create_experiment(
            self,
            db: Session,
            train_name: Optional[str],
            description: Optional[str],
            model_id: int,
            dataset_id: int,
            hyperparameters: dict,
            created_by: str
    ) -> Experiment:
        """학습 실험 생성"""
        db_experiment = Experiment(
            train_name=train_name,
            description=description,
            model_id=model_id,
            dataset_id=dataset_id,
            hyperparameters=hyperparameters,
            status="RUNNING",
            created_by=created_by
        )
        db.add(db_experiment)
        db.commit()
        db.refresh(db_experiment)
        return db_experiment

    def get_experiment(self, db: Session, experiment_id: int) -> Optional[Experiment]:
        """실험 조회"""
        return db.query(Experiment).filter(Experiment.id == experiment_id).first()

    def update_experiment_status(
            self,
            db: Session,
            experiment_id: int,
            status: str,
            mlflow_run_id: Optional[str] = None
    ) -> Optional[Experiment]:
        """실험 상태 업데이트"""
        db_experiment = self.get_experiment(db, experiment_id)
        if db_experiment:
            db_experiment.status = status
            if mlflow_run_id:
                db_experiment.mlflow_run_id = mlflow_run_id
            db.commit()
            db.refresh(db_experiment)
        return db_experiment


# 전역 CRUD 인스턴스
pipeline_crud = PipelineCRUD()