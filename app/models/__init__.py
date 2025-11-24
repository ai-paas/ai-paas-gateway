# app/models/__init__.py
from sqlalchemy.ext.declarative import declarative_base

# Base 객체를 한 곳에서 정의
Base = declarative_base()

# 모든 모델들을 import (이렇게 해야 metadata에 포함됨)
from .member import Member
from .service import Service
from .workflow import Workflow
from .model import Model
from .dataset import Dataset
from .hub_connect import HubConnection