from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.role import Role
from app.services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Pydantic Schemas for Auth
class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str
    roles: Optional[List[str]] = ["CITIZEN"]

class UserLogin(BaseModel):
    username_or_email: str
    password: str

class TokenRefreshRequest(BaseModel):
    refresh_token: str

class PasswordResetRequest(BaseModel):
    username_or_email: str
    new_password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    username: str
    roles: List[str]


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """
    Registers a new user, assigns designated roles, and returns access/refresh tokens.
    """
    # Check if username or email already exists
    existing_user = db.query(User).filter((User.username == payload.username) | (User.email == payload.email)).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email is already registered."
        )

    # Create new user record
    new_user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Assign requested roles
    role_objs = []
    for rname in payload.roles:
        role = db.query(Role).filter(Role.name == rname.upper()).first()
        if not role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role '{rname}' does not exist."
            )
        role_objs.append(role)
    
    new_user.roles = role_objs
    db.commit()

    # Generate tokens
    role_names = [r.name for r in new_user.roles]
    token_data = {"sub": str(new_user.id), "username": new_user.username, "roles": role_names}
    
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Save refresh token in DB
    new_user.refresh_token = refresh_token
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        username=new_user.username,
        roles=role_names
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """
    Authenticates user credentials and issues new access and refresh tokens.
    """
    user = db.query(User).filter(
        (User.username == payload.username_or_email) | (User.email == payload.username_or_email)
    ).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated."
        )

    # Generate tokens
    role_names = [r.name for r in user.roles]
    token_data = {"sub": str(user.id), "username": user.username, "roles": role_names}
    
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Update refresh token in DB
    user.refresh_token = refresh_token
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        username=user.username,
        roles=role_names
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: TokenRefreshRequest, db: Session = Depends(get_db)):
    """
    Issues new access and refresh tokens using a valid, non-revoked refresh token.
    """
    try:
        decoded = verify_token(payload.refresh_token)
        if decoded.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token type must be refresh."
            )
        
        user_id = decoded.get("sub")
        user = db.query(User).filter(User.id == int(user_id)).first()
        
        if not user or user.refresh_token != payload.refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked or is invalid."
            )

        # Generate fresh tokens
        role_names = [r.name for r in user.roles]
        token_data = {"sub": str(user.id), "username": user.username, "roles": role_names}
        
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)

        # Save new refresh token in DB
        user.refresh_token = new_refresh_token
        db.commit()

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            username=user.username,
            roles=role_names
        )

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token."
        )


@router.post("/logout")
def logout(payload: TokenRefreshRequest, db: Session = Depends(get_db)):
    """
    Logs out the user by revoking the refresh token in the database.
    """
    # Find user with matching refresh token and invalidate it
    user = db.query(User).filter(User.refresh_token == payload.refresh_token).first()
    if user:
        user.refresh_token = None
        db.commit()
        return {"message": "Successfully logged out."}
    
    # If not found, check decoded token to clean up
    try:
        decoded = verify_token(payload.refresh_token)
        user_id = decoded.get("sub")
        user = db.query(User).filter(User.id == int(user_id)).first()
        if user:
            user.refresh_token = None
            db.commit()
    except Exception:
        pass

    return {"message": "Token was not active or successfully cleared."}


@router.post("/password-reset")
def password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """
    Performs a password reset for the specified user.
    """
    user = db.query(User).filter(
        (User.username == payload.username_or_email) | (User.email == payload.username_or_email)
    ).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found."
        )

    # Perform password change
    user.hashed_password = hash_password(payload.new_password)
    user.refresh_token = None  # Invalidate all current sessions on reset
    db.commit()

    return {"message": f"Password reset successfully for user: {user.username}"}
