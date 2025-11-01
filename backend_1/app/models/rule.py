from typing import Optional

from pydantic import BaseModel


class RuleInput(BaseModel):
    rule: str
    rule_id: Optional[str] = (
        None  # Optional regulatory identifier like "MAS-Notice-626"
    )
