from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from db.dependencies import (
    get_db,
    get_current_active_user,
    get_current_active_admin_user,
    get_current_group_admin,
)
from db import service
from models import groups as group_schema
from models import users as user_schema
from db.orm_models import Group, UserGroupAssociation, GroupMemberRole

router = APIRouter(prefix="/groups", tags=["Groups"])


@router.post("/", response_model=group_schema.Group, status_code=status.HTTP_201_CREATED)
async def create_group(
    group_in: group_schema.GroupCreate,
    db: AsyncSession = Depends(get_db),
    current_admin_user: user_schema.User = Depends(get_current_active_admin_user),
):
    """Creates a new group and assigns the creator as the 'group_admin'."""
    return await service.create_group(db=db, group=group_in, owner=current_admin_user)


@router.get("/{group_id}", response_model=group_schema.GroupWithMembers)
async def get_group_details(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_user),
):
    """
    Get details for a specific group, including its list of members.
    Only accessible to members of the group.
    """
    group = await service.get_group_by_id(db, group_id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # Check if the current user is a member of the group
    if not any(member.id == current_user.id for member in group.members):
        raise HTTPException(status_code=403, detail="Not authorized to access this group's details")

    return group


@router.post(
    "/{group_id}/members/{user_id}", response_model=group_schema.GroupWithMembers, tags=["Admin"]
)
async def add_or_update_group_member(
    group_id: int,
    user_id: int,
    role: GroupMemberRole,  # The role to assign, sent in the request body
    group: Group = Depends(get_current_group_admin),  # <-- This dependency protects the route
    db: AsyncSession = Depends(get_db),
):
    """
    Add or update a user's role in a group.
    Only accessible to admins of this specific group.
    """
    group = await service.get_group_by_id(db, group_id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # This call now returns a "complete" user object with its groups loaded
    user_to_add = await service.get_user_by_id(db, user_id=user_id)
    if not user_to_add:
        raise HTTPException(status_code=404, detail="User to add not found")

    # Now, we pass these complete objects to the service function, which will work correctly
    return await service.add_or_update_user_in_group(db, user=user_to_add, group=group, role=role)


@router.delete(
    "/{group_id}/members/{user_id}", response_model=group_schema.GroupWithMembers, tags=["Admin"]
)
async def remove_group_member(
    group_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: user_schema.User = Depends(get_current_active_admin_user),
):
    """
    Remove a user from a group. (Admin Only)
    """
    group = await service.get_group_by_id(db, group_id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    user_to_remove = await service.get_user_by_id(db, user_id=user_id)
    if not user_to_remove:
        raise HTTPException(status_code=404, detail="User to remove not found")

    remaining_members = await service.remove_user_from_group(db, user=user_to_remove, group=group)

    return {"status": "success", "remaining_members": remaining_members}


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Admin"])
async def delete_a_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: user_schema.User = Depends(get_current_active_admin_user),
):
    """
    Delete a group. Fails if the group still contains assets. (Admin Only)
    """
    group = await service.get_group_by_id(db, group_id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    success = await service.delete_group(db, group=group)
    if not success:
        raise HTTPException(
            status_code=400, detail="Cannot delete group. It may still contain members."
        )

    return {"detail": "Group deleted successfully."}


@router.put("/{group_id}", response_model=group_schema.Group, tags=["Admin"])
async def update_group(
    group_id: int,
    group_in: group_schema.GroupCreate,
    db: AsyncSession = Depends(get_db),
    admin_user: user_schema.User = Depends(get_current_active_admin_user),
):
    """
    Update a group's details. (Admin Only)
    """
    group = await service.get_group_by_id(db, group_id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # return await service.update_group(db, group=group, group_in=group_in)
    return
