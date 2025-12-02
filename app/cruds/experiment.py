from sqlalchemy.orm import Session, joinedload
from typing import Optional
from app.models.pipeline import Experiment


class ExperimentCRUD:
    """실험 CRUD 작업"""

    def get_experiment(self, db: Session, experiment_id: int) -> Optional[Experiment]:
        """
        실험 조회 (모든 관계 정보 포함)

        Args:
            db: 데이터베이스 세션
            experiment_id: 조회할 실험 ID

        Returns:
            Experiment 객체 또는 None
        """
        return db.query(Experiment).options(
            joinedload(Experiment.reference_model).joinedload('provider_info'),
            joinedload(Experiment.reference_model).joinedload('type_info'),
            joinedload(Experiment.reference_model).joinedload('format_info'),
            joinedload(Experiment.reference_model).joinedload('registry'),
            joinedload(Experiment.reference_model).joinedload('parent_model'),
            joinedload(Experiment.reference_model).joinedload('child_models'),
            joinedload(Experiment.dataset).joinedload('dataset_registry'),
            joinedload(Experiment.hyperparameters).joinedload('hyperparameter_type')
        ).filter(Experiment.id == experiment_id).first()

    def update_experiment(
            self,
            db: Session,
            experiment_id: int,
            name: Optional[str] = None,
            description: Optional[str] = None
    ) -> Optional[Experiment]:
        """
        실험 정보 수정 (name, description만)

        Args:
            db: 데이터베이스 세션
            experiment_id: 수정할 실험 ID
            name: 새로운 실험 이름 (optional)
            description: 새로운 실험 설명 (optional)

        Returns:
            수정된 Experiment 객체 또는 None
        """
        db_experiment = self.get_experiment(db, experiment_id)

        if not db_experiment:
            return None

        # 제공된 필드만 업데이트
        if name is not None:
            db_experiment.train_name = name
        if description is not None:
            db_experiment.description = description

        db.commit()
        db.refresh(db_experiment)

        # 관계 정보 포함하여 다시 조회
        return self.get_experiment(db, experiment_id)

    def update_experiment_internal(
            self,
            db: Session,
            experiment_id: int,
            status: Optional[str] = None,
            mlflow_run_id: Optional[str] = None,
            kubeflow_run_id: Optional[str] = None
    ) -> Optional[Experiment]:
        """
        실험 내부 정보 수정 (status, mlflow_run_id, kubeflow_run_id)

        Args:
            db: 데이터베이스 세션
            experiment_id: 수정할 실험 ID
            status: 실험 상태 (optional)
            mlflow_run_id: MLflow 실행 ID (optional)
            kubeflow_run_id: Kubeflow 파이프라인 실행 ID (optional)

        Returns:
            수정된 Experiment 객체 또는 None
        """
        db_experiment = self.get_experiment(db, experiment_id)

        if not db_experiment:
            return None

        # 제공된 필드만 업데이트
        if status is not None:
            db_experiment.status = status
        if mlflow_run_id is not None:
            db_experiment.mlflow_run_id = mlflow_run_id
        if kubeflow_run_id is not None:
            db_experiment.kubeflow_run_id = kubeflow_run_id

        db.commit()
        db.refresh(db_experiment)

        # 관계 정보 포함하여 다시 조회
        return self.get_experiment(db, experiment_id)

    def delete_experiment(self, db: Session, experiment_id: int) -> bool:
        """
        실험 삭제

        Args:
            db: 데이터베이스 세션
            experiment_id: 삭제할 실험 ID

        Returns:
            삭제 성공 여부
        """
        db_experiment = db.query(Experiment).filter(
            Experiment.id == experiment_id
        ).first()

        if not db_experiment:
            return False

        db.delete(db_experiment)
        db.commit()
        return True


# 전역 CRUD 인스턴스
experiment_crud = ExperimentCRUD()