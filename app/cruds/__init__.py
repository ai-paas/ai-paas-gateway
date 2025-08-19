# app/cruds/__init__.py
from .member import MemberCRUD, member_crud
from .service import ServiceCRUD, service_crud
from .workflow import WorkflowCRUD, workflow_crud
from .model import ModelCRUD, model_crud

__all__ = [
    "ModelCRUD", "model_crud",
    "MemberCRUD", "member_crud",
    "ServiceCRUD", "service_crud",
    "WorkflowCRUD", "workflow_crud"
]