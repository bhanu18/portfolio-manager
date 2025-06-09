from pydantic import BaseModel, EmailStr
from datetime import datetime
from db.orm_models import UserRole
from models.groups import Group
from typing import List

# Properties to receive via API on user creation
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

# Properties shared by all models
class UserBase(BaseModel):
    id: int
    name: str
    email: EmailStr

# Properties to return to client
class User(UserBase):
    role: UserRole
    is_active: bool
    groups: List[Group] = []
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True # Changed from orm_mode in Pydantic v2

# Properties stored in DB
class UserInDB(UserBase):
    hashed_password: str