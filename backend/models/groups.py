from pydantic import BaseModel, ConfigDict
from typing import List, Optional


# A simplified User schema for nesting inside a Group response
class UserInGroup(BaseModel):
    id: int
    name: str
    email: str

    model_config = ConfigDict(from_attributes=True)


class GroupBase(BaseModel):
    name: str


class GroupCreate(GroupBase):
    pass


class Group(GroupBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# A new, detailed response model that includes members
class GroupWithMembers(Group):
    members: List[UserInGroup] = []
