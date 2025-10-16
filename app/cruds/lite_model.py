from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, func
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
import json
import hashlib

from app.models.any_cloud import AnyCloudData, AnyCloudCache


class LiteModelCRUD:
    """Lite Model 데이터 관련 CRUD 작업"""

    # === LiteModelData 관련 메서드 ===

# 싱글톤 인스턴스
any_cloud_crud = LiteModelCRUD()