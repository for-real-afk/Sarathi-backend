import datetime
import logging
import uuid
import bcrypt
import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User

logger = logging.getLogger("uvicorn.error")

# Password Hashing & Verification
def hash_password(password: str) -> str:
    """
    Hashes a password using bcrypt.
    """
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    """
    Verifies a password against its bcrypt hash.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# JWT Token Handlers
def create_access_token(data: dict) -> str:
    """
    Creates an access token signed with JWT.
    """
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire, 
        "type": "access",
        "jti": str(uuid.uuid4())
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_refresh_token(data: dict) -> str:
    """
    Creates a refresh token signed with JWT.
    """
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire, 
        "type": "refresh",
        "jti": str(uuid.uuid4())
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def verify_token(token: str) -> dict:
    """
    Decodes and validates a JWT token. Raises JWT error if invalid or expired.
    """
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


# Database Seeding Logic
def seed_database(db: Session):
    """
    Seeds permissions, roles, and default users into the database if they do not exist.
    """
    # 1. Define Permissions
    permissions_def = {
        "admin:all": "Full administrative permissions",
        "volunteers:read": "Ability to read volunteers",
        "volunteers:write": "Ability to add/update volunteers",
        "citizens:read": "Ability to view citizens profile and records",
        "citizens:write": "Ability to submit/update citizen profiles",
        "cases:read": "Ability to view cases",
        "cases:write": "Ability to register/update cases"
    }

    db_permissions = {}
    for name, desc in permissions_def.items():
        perm = db.query(Permission).filter(Permission.name == name).first()
        if not perm:
            perm = Permission(name=name, description=desc)
            db.add(perm)
            db.commit()
            db.refresh(perm)
        db_permissions[name] = perm

    # 2. Define Roles and map Permissions
    roles_def = {
        "ADMIN": ["admin:all", "volunteers:read", "volunteers:write", "citizens:read", "citizens:write", "cases:read", "cases:write"],
        "CENTRAL_HUB": ["volunteers:read", "volunteers:write", "citizens:read", "citizens:write", "cases:read", "cases:write"],
        "LOCAL_HUB": ["volunteers:read", "citizens:read", "citizens:write", "cases:read", "cases:write"],
        "VOLUNTEER": ["citizens:read", "citizens:write", "cases:read", "cases:write"],
        "CITIZEN": ["cases:read", "cases:write"]
    }

    db_roles = {}
    for rname, pnames in roles_def.items():
        role = db.query(Role).filter(Role.name == rname).first()
        if not role:
            role = Role(name=rname, description=f"{rname} Role")
            db.add(role)
            db.commit()
            db.refresh(role)
        
        # Populate permissions
        associated_perms = [db_permissions[pn] for pn in pnames]
        # Keep distinct and update relationships
        role.permissions = associated_perms
        db.commit()
        db_roles[rname] = role

    # 3. Create Default Users for testing/initial execution
    users_def = [
        ("admin", "admin@saarthi.org", "admin123", "ADMIN"),
        ("central", "central@saarthi.org", "central123", "CENTRAL_HUB"),
        ("local", "local@saarthi.org", "local123", "LOCAL_HUB"),
        ("volunteer", "volunteer@saarthi.org", "volunteer123", "VOLUNTEER"),
        ("citizen", "citizen@saarthi.org", "citizen123", "CITIZEN"),
    ]

    for username, email, pwd, role_name in users_def:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(
                username=username,
                email=email,
                hashed_password=hash_password(pwd),
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            # Reset credentials and status to default to prevent test state pollution
            user.hashed_password = hash_password(pwd)
            user.is_active = True
            db.commit()
        
        # Assign role if not already assigned
        target_role = db_roles[role_name]
        if target_role not in user.roles:
            user.roles.append(target_role)
            db.commit()

    # 4. Seed Hubs and Volunteer Profile for testing
    from app.models.hub import Hub
    from app.models.volunteer_profile import VolunteerProfile

    # Central Hub
    central_hub = db.query(Hub).filter(Hub.name == "Telangana Central Hub").first()
    if not central_hub:
        central_hub = Hub(name="Telangana Central Hub", hub_type="CENTRAL", district="Hyderabad")
        db.add(central_hub)
        db.commit()
        db.refresh(central_hub)

    # Local Hub
    local_hub = db.query(Hub).filter(Hub.name == "Rangareddy Local Hub").first()
    if not local_hub:
        local_hub = Hub(
            name="Rangareddy Local Hub", 
            hub_type="LOCAL", 
            district="Rangareddy", 
            parent_hub_id=central_hub.id
        )
        db.add(local_hub)
        db.commit()
        db.refresh(local_hub)

    # Volunteer profile for default 'volunteer' user
    volunteer_user = db.query(User).filter(User.username == "volunteer").first()
    if volunteer_user:
        vol_profile = db.query(VolunteerProfile).filter(VolunteerProfile.user_id == volunteer_user.id).first()
        if not vol_profile:
            vol_profile = VolunteerProfile(
                user_id=volunteer_user.id,
                contact_phone="9988776655",
                district="Rangareddy",
                availability=True,
                hub_id=local_hub.id
            )
            db.add(vol_profile)
            db.commit()

    logger.info("Authentication & RBAC database seeding finished successfully.")

