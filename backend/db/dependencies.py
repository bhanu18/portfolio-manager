from db.session import AsyncSessionLocal
from models import users as user_schema
from db.orm_models import UserRole, GroupMemberRole, Group
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from db import service
from models import users as user_schema
from models.token import TokenData
from core.config import settings

# This object is what FastAPI uses to find the token in the request's header.
# The tokenUrl points to your login endpoint.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login/access-token")

async def get_db():
    async with AsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()

async def get_current_user(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
) -> user_schema.User:
    """
    Decodes the JWT token to get the user's email, then fetches the user from the DB.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decode the JWT
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        # The 'sub' (subject) of our token is the user's email
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        # This catches errors like expired tokens or invalid signatures
        raise credentials_exception
    
    # Fetch the user from the database
    user = await service.get_user_by_email(db, email=token_data.email)
    if user is None:
        raise credentials_exception
    
    return user

async def get_current_active_user(
    current_user: user_schema.User = Depends(get_current_user)
) -> user_schema.User:
    """

    Checks if the user fetched from the token is active.
    This is the main dependency you will use to protect endpoints.
    """
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
           
def get_current_active_admin_user(
    current_user: user_schema.User = Depends(get_current_active_user),
) -> user_schema.User:
    """
    Dependency that checks if the current user is active AND is an admin.
    If not, it raises an HTTPException.
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user does not have sufficient privileges",
        )
    return current_user

def get_current_active_regular_user(
    current_user: user_schema.User = Depends(get_current_active_user),
) -> user_schema.User:
    """
    Dependency that checks if the current user is active AND has USER role only.
    This excludes ADMIN users from accessing the endpoint.
    If the user is not a regular USER, it raises an HTTPException.
    """
    if current_user.role != UserRole.USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only accessible to users with USER role",
        )
    return current_user

async def get_group_from_path(group_id: int, db: AsyncSession = Depends(get_db)) -> Group:
    """Dependency to fetch a group by ID from the path."""
    group = await service.get_group_by_id(db, group_id=group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group

async def get_current_group_admin(
    current_user: user_schema.User = Depends(get_current_active_user),
    group: Group = Depends(get_group_from_path)
) -> Group:
    """
    Dependency that checks if the current user is an admin of the specified group.
    Returns the group object if authorized.
    """
    # Find the association for this user and group
    association = next((assoc for assoc in current_user.group_associations if assoc.group_id == group.id), None)
    
    if not association or association.role != GroupMemberRole.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="User is not an admin of this group",
        )
    return group