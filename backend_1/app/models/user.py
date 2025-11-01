from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    id: Optional[str] = None
    username: str
    email: str
    role: str = "user"


class UserCreate(BaseModel):
    username: str
    email: str
    role: str = "user"
