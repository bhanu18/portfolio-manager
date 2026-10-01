import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from core.config import settings

# Password Hashing Context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against its hashed version."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hashes a plain password."""
    return pwd_context.hash(password)


def create_user_access_token(email: str, hashed_password: str) -> str:
    """
    Creates a login token for a user.

    Like reset tokens, it carries a fingerprint of the current password hash, so
    every outstanding token stops working when the password changes.
    """
    return create_access_token(data={"sub": email, "pwd": password_fingerprint(hashed_password)})


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    """Creates a new JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def password_fingerprint(hashed_password: str) -> str:
    """Short digest of the stored hash; changes whenever the password does."""
    return hashlib.sha256(hashed_password.encode()).hexdigest()[:16]


def create_password_reset_token(email: str, hashed_password: str) -> str:
    """
    Creates a JWT token for password reset.

    The token carries a fingerprint of the current password hash, so it stops
    working as soon as the password is changed (i.e. it is single-use).
    """
    expire = datetime.now(UTC) + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
    to_encode = {
        "sub": email,
        "exp": expire,
        "type": "password_reset",
        "pwd": password_fingerprint(hashed_password),
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_password_reset_token(token: str) -> tuple[str, str] | None:
    """
    Verifies a password reset token's signature, expiry and type.
    Returns (email, password fingerprint), or None if the token is invalid or expired.
    Callers must check the fingerprint with `fingerprint_matches_password`.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
    email = payload.get("sub")
    fingerprint = payload.get("pwd")
    if (
        not isinstance(email, str)
        or not isinstance(fingerprint, str)
        or payload.get("type") != "password_reset"
    ):
        return None
    return email, fingerprint


def fingerprint_matches_password(fingerprint: str, hashed_password: str) -> bool:
    """True if the token was issued for the user's current password."""
    return hmac.compare_digest(fingerprint, password_fingerprint(hashed_password))
