from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List
from slowapi import Limiter
from slowapi.util import get_remote_address

from db.dependencies import get_db
from db import service
from models import users as user_schema
from service.security import verify_password, create_access_token
from db.dependencies import get_current_active_admin_user, get_current_active_user

router = APIRouter(tags=["Authentication"])

# Initialize rate limiter for this router
limiter = Limiter(key_func=get_remote_address)

@router.post("/register", response_model=user_schema.User)
@limiter.limit("3/hour")
async def register_new_user(
    request: Request,
    user_in: user_schema.UserCreate,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Create a new user.

    **Rate Limiting:** This endpoint is rate-limited to 3 registrations per hour per IP address
    to prevent spam account creation.
    """
    user = await service.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="A user with this email already exists.",
        )
    new_user = await service.create_user(db, user=user_in)
    return new_user


@router.post("/login/access-token")
@limiter.limit("5/minute")
async def login_for_access_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, get an access token for future requests.

    **Rate Limiting:** This endpoint is rate-limited to 5 attempts per minute per IP address
    to prevent brute force attacks. If you exceed this limit, you'll receive a 429 error
    and must wait before trying again.
    """
    user = await service.get_user_by_email(db, email=form_data.username) # form_data.username is the email
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/users", response_model=List[user_schema.User], tags=["Admin"])
async def read_all_users(
    db: AsyncSession = Depends(get_db),
    current_admin_user: user_schema.User = Depends(get_current_active_admin_user)
):
    """
    Retrieve all users. Access is restricted to admin users.
    """
    users = await service.get_all_users(db)
    return users

@router.get("/users/me", response_model=user_schema.User)
async def read_users_me(
    current_user: user_schema.User = Depends(get_current_active_user)
):
    """
    Get the profile for the currently logged-in user.
    
    This is the ideal place for a frontend to get the user's details
    and their list of group memberships after logging in.
    """
    # The get_current_active_user dependency already fetches the user object.
    # Because we updated our service function, the 'groups' attribute will
    # already be populated. We just need to return it.
    return current_user
