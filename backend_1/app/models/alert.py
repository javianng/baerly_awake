from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Alert(BaseModel):
    id: Optional[str] = None
    transaction_id: str
    alert_type: str
    severity: str
    message: str
    timestamp: datetime
    status: str = "active"
    assigned_to: Optional[str] = None
