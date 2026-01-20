from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List
from slowapi import Limiter
from slowapi.util import get_remote_address

from db.dependencies import get_db
from db import service
from models import users as user_schema
from service.security import (
    verify_password,
    create_access_token,
    create_password_reset_token,
    verify_password_reset_token,
)
from service.email import email_service
from core.config import settings
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


@router.post("/change-password")
@limiter.limit("5/hour")
async def change_password(
    request: Request,
    password_data: user_schema.PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: user_schema.User = Depends(get_current_active_user)
) -> Any:
    """
    Change the password for the currently logged-in user.

    Requires the current password and a new password.

    **Rate Limiting:** This endpoint is rate-limited to 5 attempts per hour per IP address.
    """
    # Fetch the full user object from the database to get the hashed password
    db_user = await service.get_user_by_email(db, email=current_user.email)

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Verify the current password
    if not verify_password(password_data.current_password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Update with the new password
    await service.update_user_password(db, db_user, password_data.new_password)

    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
@limiter.limit("3/hour")
async def forgot_password(
    request: Request,
    forgot_data: user_schema.ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Request a password reset email.

    If the email exists in the system, a password reset link will be sent.
    For security reasons, this endpoint always returns success even if the email doesn't exist.

    **Rate Limiting:** This endpoint is rate-limited to 3 requests per hour per IP address.
    """
    user = await service.get_user_by_email(db, email=forgot_data.email)

    # Always return success to prevent email enumeration attacks
    if not user:
        return {"message": "If an account with that email exists, a password reset link has been sent."}

    # Generate password reset token
    reset_token = create_password_reset_token(email=user.email)

    # Send password reset email
    try:
        reset_link = f"https://your-frontend-url.com/reset-password?token={reset_token}"

        email_body = f"""
Hello {user.name},

You requested a password reset for your Portfolio Tracker account.

Click the link below to reset your password (valid for {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes):

{reset_link}

If you didn't request this password reset, please ignore this email.

Best regards,
Portfolio Tracker Team
"""

        html_body = f"""
<html>
<body>
<p>Hello {user.name},</p>
<p>You requested a password reset for your Portfolio Tracker account.</p>
<p>Click the link below to reset your password (valid for {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes):</p>
<p><a href="{reset_link}">Reset Your Password</a></p>
<p>If you didn't request this password reset, please ignore this email.</p>
<p>Best regards,<br>Portfolio Tracker Team</p>
</body>
</html>
"""

        email_service.send_email(
            to_emails=[user.email],
            subject="Password Reset Request - Portfolio Tracker",
            body=email_body,
            html_body=html_body
        )
    except Exception:
        # Log the error but don't expose it to the user
        pass

    return {"message": "If an account with that email exists, a password reset link has been sent."}


@router.post("/reset-password")
@limiter.limit("5/hour")
async def reset_password(
    request: Request,
    reset_data: user_schema.ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Reset password using a valid reset token.

    The token is sent to the user's email via the forgot-password endpoint.

    **Rate Limiting:** This endpoint is rate-limited to 5 attempts per hour per IP address.
    """
    # Verify the reset token
    email = verify_password_reset_token(reset_data.token)

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token"
        )

    # Get the user
    user = await service.get_user_by_email(db, email=email)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is inactive"
        )

    # Update the password
    await service.update_user_password(db, user, reset_data.new_password)

    return {"message": "Password has been reset successfully"}
