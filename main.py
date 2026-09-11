import os
import io
import re
import uuid
import hashlib
import secrets
import asyncio
import smtplib

from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from email.message import EmailMessage

import anthropic
import httpx
from pypdf import PdfReader

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    Response,
)

from pydantic import BaseModel

from sqlalchemy import (
    Boolean,
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Integer,
    create_engine,
    inspect,
    or_,
    text,
)

from sqlalchemy.exc import IntegrityError

from sqlalchemy.orm import (
    Session,
    declarative_base,
    relationship,
    sessionmaker,
)


# =========================================================
# ENVIRONMENT
# =========================================================

DATABASE_URL = (
    os.getenv("DATABASE_CONNECTION_URI", "").strip()
    or os.getenv("DATABASE_URL", "").strip()
)

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./saas_stores.db"


# Supabase/PostgreSQL compatibility
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1,
    )

if DATABASE_URL.startswith("postgresql://"):
    if "sslmode=" not in DATABASE_URL:
        separator = "&" if "?" in DATABASE_URL else "?"
        DATABASE_URL += f"{separator}sslmode=require"


ANTHROPIC_API_KEY = (
    os.getenv("ANTHROPIC_API_KEY", "").strip()
)

ANTHROPIC_MODEL = (
    os.getenv(
        "ANTHROPIC_MODEL",
        os.getenv(
            "CLAUDE_MODEL",
            "claude-sonnet-4-5",
        ),
    ).strip()
)


EVOLUTION_API_URL = (
    os.getenv(
        "EVOLUTION_API_URL",
        "",
    )
    .strip()
    .rstrip("/")
)

EVOLUTION_GLOBAL_KEY = (
    os.getenv(
        "EVOLUTION_GLOBAL_KEY",
        "",
    ).strip()
)

if not EVOLUTION_GLOBAL_KEY:
    EVOLUTION_GLOBAL_KEY = (
        os.getenv(
            "EVOLUTION_API_KEY",
            "",
        ).strip()
    )

if not EVOLUTION_GLOBAL_KEY:
    EVOLUTION_GLOBAL_KEY = (
        os.getenv(
            "AUTHENTICATION_API_KEY",
            "",
        ).strip()
    )


# Render automatically exposes the public URL through RENDER_EXTERNAL_URL.
WEBHOOK_BASE_URL = (
    os.getenv(
        "WEBHOOK_BASE_URL",
        os.getenv("RENDER_EXTERNAL_URL", ""),
    )
    .strip()
    .rstrip("/")
)


# =========================================================
# EMAIL VERIFICATION CONFIGURATION
# =========================================================

EMAIL_VERIFICATION_REQUIRED = (
    os.getenv(
        "EMAIL_VERIFICATION_REQUIRED",
        "true",
    )
    .strip()
    .lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)

SMTP_HOST = (
    os.getenv(
        "SMTP_HOST",
        "smtp.gmail.com",
    )
    .strip()
)

try:
    SMTP_PORT = int(
        os.getenv(
            "SMTP_PORT",
            "587",
        )
    )
except ValueError:
    SMTP_PORT = 587

SMTP_USERNAME = (
    os.getenv(
        "SMTP_USERNAME",
        "",
    )
    .strip()
)

SMTP_PASSWORD = (
    os.getenv(
        "SMTP_PASSWORD",
        "",
    )
    .strip()
)

SMTP_FROM_EMAIL = (
    os.getenv(
        "SMTP_FROM_EMAIL",
        SMTP_USERNAME,
    )
    .strip()
)

SMTP_FROM_NAME = (
    os.getenv(
        "SMTP_FROM_NAME",
        "FastSAS",
    )
    .strip()
)

try:
    EMAIL_CODE_TTL_MINUTES = int(
        os.getenv(
            "EMAIL_CODE_TTL_MINUTES",
            "15",
        )
    )
except ValueError:
    EMAIL_CODE_TTL_MINUTES = 15

if EMAIL_CODE_TTL_MINUTES < 1:
    EMAIL_CODE_TTL_MINUTES = 15


# =========================================================
# DATABASE
# =========================================================

if DATABASE_URL.startswith("sqlite"):

    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "check_same_thread": False
        },
    )

else:

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Smart AI Store Assistant",
    version="2.1.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# DATABASE MODELS
# =========================================================

class StoreModel(Base):

    __tablename__ = "stores"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    store_name = Column(
        String(255),
        nullable=False,
    )

    store_url = Column(
        String(500),
        nullable=True,
    )

    whatsapp_number = Column(
        String(50),
        nullable=True,
    )

    agent_notes = Column(
        Text,
        nullable=True,
    )

    catalog_text = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    users = relationship(
        "UserModel",
        back_populates="store",
        cascade="all, delete-orphan",
    )

    logs = relationship(
        "ChatLogModel",
        back_populates="store",
        cascade="all, delete-orphan",
    )


class UserModel(Base):

    __tablename__ = "users"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    store_id = Column(
        String(36),
        ForeignKey("stores.id"),
        nullable=False,
        unique=True,
    )

    username = Column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
    )

    email = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )

    password_hash = Column(
        String(500),
        nullable=False,
    )

    # =====================================================
    # EMAIL VERIFICATION
    # =====================================================

    email_verified = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    verification_code_hash = Column(
        String(128),
        nullable=True,
    )

    verification_expires_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    store = relationship(
        "StoreModel",
        back_populates="users",
    )


class SessionModel(Base):

    __tablename__ = "auth_sessions"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    user_id = Column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
    )

    token_hash = Column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ChatLogModel(Base):

    __tablename__ = "chat_logs"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    store_id = Column(
        String(36),
        ForeignKey("stores.id"),
        nullable=False,
    )

    sender_id = Column(
        String(255),
        nullable=True,
    )

    user_message = Column(
        Text,
        nullable=False,
    )

    bot_response = Column(
        Text,
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    store = relationship(
        "StoreModel",
        back_populates="logs",
    )


# =========================================================
# CREATE DATABASE
# =========================================================

try:

    Base.metadata.create_all(
        bind=engine
    )

except Exception as exc:

    print(
        "DATABASE CREATE ERROR:",
        repr(exc),
    )


# =========================================================
# DATABASE MIGRATION
# =========================================================

def ensure_database_schema():

    try:

        inspector = inspect(engine)

        tables = inspector.get_table_names()

        if "users" not in tables:
            return

        columns = inspector.get_columns(
            "users"
        )

        column_names = {
            column["name"]
            for column in columns
        }

        if "email" not in column_names:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN email VARCHAR(255)
                        """
                    )
                )

        if "email_verified" not in column_names:
            with engine.begin() as connection:
                if engine.dialect.name == "postgresql":
                    connection.execute(
                        text(
                            """
                            ALTER TABLE users
                            ADD COLUMN email_verified
                            BOOLEAN NOT NULL DEFAULT FALSE
                            """
                        )
                    )
                else:
                    connection.execute(
                        text(
                            """
                            ALTER TABLE users
                            ADD COLUMN email_verified
                            BOOLEAN NOT NULL DEFAULT 0
                            """
                        )
                    )

        if "verification_code_hash" not in column_names:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN verification_code_hash
                        VARCHAR(128)
                        """
                    )
                )

        if "verification_expires_at" not in column_names:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        ALTER TABLE users
                        ADD COLUMN verification_expires_at
                        TIMESTAMP
                        """
                    )
                )

        if engine.dialect.name == "postgresql":
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS
                        ix_users_email_unique
                        ON users(email)
                        WHERE email IS NOT NULL
                        """
                    )
                )

        elif engine.dialect.name == "sqlite":
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS
                        ix_users_email_unique
                        ON users(email)
                        """
                    )
                )

    except Exception as exc:

        print(
            "DATABASE MIGRATION WARNING:",
            repr(exc),
        )


ensure_database_schema()


# =========================================================
# DB DEPENDENCY
# =========================================================

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()


# =========================================================
# PASSWORD
# =========================================================

PBKDF2_ITERATIONS = 240000


def hash_password(
    password: str,
) -> str:

    salt = secrets.token_bytes(16)

    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )

    return (
        "pbkdf2_sha256$"
        f"{PBKDF2_ITERATIONS}$"
        f"{salt.hex()}$"
        f"{key.hex()}"
    )


def verify_password(
    password: str,
    stored_hash: str,
) -> bool:

    try:

        parts = stored_hash.split("$")

        if len(parts) != 4:
            return False

        algorithm = parts[0]
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])

        if algorithm != "pbkdf2_sha256":
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )

        return secrets.compare_digest(
            actual,
            expected,
        )

    except Exception:

        return False


# =========================================================
# EMAIL VERIFICATION
# =========================================================

def generate_verification_code() -> str:

    return f"{secrets.randbelow(1000000):06d}"


def hash_verification_code(
    user_id: str,
    code: str,
) -> str:

    raw = (
        f"{user_id}:{code}"
    ).encode("utf-8")

    return hashlib.sha256(
        raw
    ).hexdigest()


def is_email_verified(
    user: UserModel,
) -> bool:

    if not EMAIL_VERIFICATION_REQUIRED:
        return True

    return bool(
        user.email_verified
    )


def email_configuration_ready() -> bool:

    return bool(
        SMTP_HOST
        and SMTP_PORT
        and SMTP_USERNAME
        and SMTP_PASSWORD
        and SMTP_FROM_EMAIL
    )


def send_verification_email(
    recipient_email: str,
    verification_code: str,
):

    if not email_configuration_ready():
        raise RuntimeError(
            "إعدادات SMTP غير مكتملة. "
            "تأكد من إعداد SMTP_HOST و SMTP_PORT و "
            "SMTP_USERNAME و SMTP_PASSWORD و "
            "SMTP_FROM_EMAIL"
        )

    message = EmailMessage()
    message["Subject"] = "رمز تأكيد البريد الإلكتروني - FastSAS"
    message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    message["To"] = recipient_email

    message.set_content(
        f"""
مرحباً،

شكراً لتسجيلك في {SMTP_FROM_NAME}.

رمز تأكيد البريد الإلكتروني الخاص بك هو:

{verification_code}

صلاحية هذا الرمز {EMAIL_CODE_TTL_MINUTES} دقيقة.

إذا لم تقم بإنشاء هذا الحساب، يمكنك تجاهل هذه الرسالة.

تحياتنا،
فريق {SMTP_FROM_NAME}
""".strip()
    )

    try:
        # التعامل الذكي مع نوع الاتصال بناءً على المنفذ
        if SMTP_PORT == 465:
            # منفذ 465 يستخدم SSL صريح من البداية
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
        else:
            # المنافذ الأخرى مثل 587 و 25 تستخدم TLS
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp.send_message(message)
    except Exception as e:
        print(f"SMTP SEND ERROR: {repr(e)}")
        raise RuntimeError(f"فشل إرسال البريد الإلكتروني. التفاصيل: {str(e)}")


def prepare_verification_code(
    user: UserModel,
) -> str:

    code = generate_verification_code()

    user.verification_code_hash = (
        hash_verification_code(
            user.id,
            code,
        )
    )

    user.verification_expires_at = (
        datetime.now(timezone.utc)
        + timedelta(
            minutes=EMAIL_CODE_TTL_MINUTES
        )
    )

    user.email_verified = False

    return code


def verification_expired(
    user: UserModel,
) -> bool:

    if not user.verification_expires_at:
        return True

    expires_at = (
        user.verification_expires_at
    )

    if expires_at.tzinfo is None:

        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    return (
        expires_at
        < datetime.now(timezone.utc)
    )


def email_verification_response(
    email: str,
    message: str,
    status_code: int = 403,
):

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "verification_required",
            "success": False,
            "requires_email_verification": True,
            "email": email,
            "message": message,
            "detail": message,
        },
    )


# =========================================================
# SESSION
# =========================================================

SESSION_COOKIE = "ai_store_session"

SESSION_DAYS = 30


def hash_session_token(
    token: str,
) -> str:

    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def create_session(
    db: Session,
    user: UserModel,
) -> str:

    token = secrets.token_urlsafe(48)

    session = SessionModel(
        user_id=user.id,
        token_hash=hash_session_token(
            token
        ),
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(days=SESSION_DAYS)
        ),
    )

    db.add(session)
    db.commit()

    return token


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):

    token = request.cookies.get(
        SESSION_COOKIE
    )

    if not token:

        raise HTTPException(
            status_code=401,
            detail="غير مسجل الدخول",
        )

    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.token_hash
            == hash_session_token(token)
        )
        .first()
    )

    if not session:

        raise HTTPException(
            status_code=401,
            detail="جلسة غير صالحة",
        )

    expires_at = session.expires_at

    if expires_at.tzinfo is None:

        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    if expires_at < datetime.now(
        timezone.utc
    ):

        db.delete(session)
        db.commit()

        raise HTTPException(
            status_code=401,
            detail="انتهت الجلسة",
        )

    user = (
        db.query(UserModel)
        .filter(
            UserModel.id
            == session.user_id
        )
        .first()
    )

    if not user:

        raise HTTPException(
            status_code=401,
            detail="المستخدم غير موجود",
        )

    # =====================================================
    # SECURITY:
    # Prevent old sessions from bypassing verification.
    # =====================================================

    if (
        EMAIL_VERIFICATION_REQUIRED
        and not user.email_verified
    ):

        db.delete(session)
        db.commit()

        raise HTTPException(
            status_code=403,
            detail={
                "requires_email_verification": True,
                "email": user.email,
                "message": (
                    "يجب تأكيد البريد الإلكتروني أولاً"
                ),
            },
        )

    return user


def set_session_cookie(
    response: JSONResponse,
    token: str,
):

    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=(
            SESSION_DAYS
            * 24
            * 60
            * 60
        ),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


# =========================================================
# HELPERS
# =========================================================

def normalize_phone(
    value: str,
) -> str:

    if not value:
        return ""

    value = str(value).strip()

    value = (
        value
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if value.startswith("00"):
        value = value[2:]

    return re.sub(
        r"\D",
        "",
        value,
    )


def make_instance_name(
    store_id: str,
    ) -> str:

    clean = re.sub(
        r"[^A-Za-z0-9]",
        "",
        str(store_id),
    )

    return f"store_{clean}"


def safe_json(
    response: httpx.Response,
) -> Any:

    try:

        return response.json()

    except Exception:

        return {
            "raw": response.text
        }


def first_value(
    *values,
):

    for value in values:

        if value is not None and value != "":
            return value

    return None


# =========================================================
# PDF
# =========================================================

def extract_pdf_text(
    content: bytes,
) -> str:

    try:

        reader = PdfReader(
            io.BytesIO(content)
        )

        parts = []

        for page in reader.pages:

            try:

                value = (
                    page.extract_text()
                    or ""
                )

                if value:
                    parts.append(value)

            except Exception:
                continue

        result = "\n\n".join(parts)

        if len(result) > 500000:
            result = result[:500000]

        return result.strip()

    except Exception as exc:

        print(
            "PDF ERROR:",
            repr(exc),
        )

        return ""


# =========================================================
# STORE
# =========================================================

def store_to_dict(
    store: StoreModel,
):

    return {
        "id": store.id,
        "store_name": store.store_name,
        "store_url": store.store_url,
        "whatsapp_number": store.whatsapp_number,
        "agent_notes": store.agent_notes,
        "has_catalog": bool(
            store.catalog_text
        ),
        "created_at": (
            store.created_at.isoformat()
            if store.created_at
            else None
        ),
    }


# =========================================================
# QR HELPERS
# =========================================================

def normalize_qr(
    value: Any,
) -> Optional[str]:

    if not value:
        return None

    if isinstance(value, dict):

        value = first_value(
            value.get("base64"),
            value.get("base64Image"),
            value.get("qrcode"),
            value.get("qrCode"),
            value.get("code"),
            value.get("qr"),
        )

    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    if value.startswith(
        "data:image"
    ):

        return value

    if value.startswith(
        "http://"
    ) or value.startswith(
        "https://"
    ):

        return value

    return (
        "data:image/png;base64,"
        + value
    )


def extract_qr_code(
    data: Any,
) -> Optional[str]:

    if not isinstance(data, dict):
        return None

    candidates = []

    candidates.extend(
        [
            data.get("qrcode"),
            data.get("qrCode"),
            data.get("base64"),
            data.get("base64Image"),
            data.get("code"),
            data.get("qr"),
        ]
    )

    nested_data = data.get("data")

    if isinstance(
        nested_data,
        dict,
    ):

        candidates.extend(
            [
                nested_data.get("qrcode"),
                nested_data.get("qrCode"),
                nested_data.get("base64"),
                nested_data.get("base64Image"),
                nested_data.get("code"),
                nested_data.get("qr"),
            ]
        )

    instance = data.get(
        "instance"
    )

    if isinstance(
        instance,
        dict,
    ):

        candidates.extend(
            [
                instance.get("qrcode"),
                instance.get("qrCode"),
                instance.get("base64"),
                instance.get("base64Image"),
                instance.get("code"),
                instance.get("qr"),
            ]
        )

    for candidate in candidates:

        qr = normalize_qr(candidate)

        if qr:
            return qr

    return None


def extract_connection_state(
    data: Any,
) -> Optional[str]:

    if not isinstance(data, dict):
        return None

    values = [
        data.get("state"),
        data.get("status"),
        data.get("connectionStatus"),
    ]

    nested = data.get("instance")

    if isinstance(
        nested,
        dict,
    ):

        values.extend(
            [
                nested.get("state"),
                nested.get("status"),
                nested.get(
                    "connectionStatus"
                ),
            ]
        )

    nested_data = data.get("data")

    if isinstance(
        nested_data,
        dict,
    ):

        values.extend(
            [
                nested_data.get("state"),
                nested_data.get("status"),
                nested_data.get(
                    "connectionStatus"
                ),
            ]
        )

    for value in values:

        if value:
            return str(value)

    return None


# =========================================================
# EVOLUTION CONFIG
# =========================================================

def require_evolution_config():

    if not EVOLUTION_API_URL:

        raise HTTPException(
            status_code=500,
            detail=(
                "EVOLUTION_API_URL غير مضبوط في Render"
            ),
        )

    if not EVOLUTION_GLOBAL_KEY:

        raise HTTPException(
            status_code=500,
            detail=(
                "EVOLUTION_GLOBAL_KEY غير مضبوط في Render"
            ),
        )


def evolution_headers():

    return {
        "apikey": EVOLUTION_GLOBAL_KEY,
        "Content-Type": "application/json",
    }


# =========================================================
# EVOLUTION CREATE INSTANCE
# =========================================================

async def evolution_create_instance(
    client: httpx.AsyncClient,
    instance_name: str,
):

    url = f"{EVOLUTION_API_URL}/instance/create"

    payload = {
        "instanceName": instance_name,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }

    try:
        response = await client.post(
            url,
            headers=evolution_headers(),
            json=payload,
        )
        data = safe_json(response)

        print(
            "EVOLUTION CREATE:",
            response.status_code,
            data,
        )

        return {
            "status_code": response.status_code,
            "data": data,
            "qr": extract_qr_code(data),
        }

    except Exception as exc:

        print(
            "EVOLUTION CREATE EXCEPTION:",
            repr(exc),
        )

        return {
            "status_code": 0,
            "data": {"error": str(exc)},
            "qr": None,
        }


# =========================================================
# EVOLUTION CONNECT
# =========================================================

async def evolution_connect(
    client: httpx.AsyncClient,
    instance_name: str,
):

    url = (
        f"{EVOLUTION_API_URL}"
        f"/instance/connect/"
        f"{instance_name}"
    )

    try:

        response = await client.get(
            url,
            headers=evolution_headers(),
        )

        data = safe_json(response)

        print(
            "EVOLUTION CONNECT:",
            response.status_code,
            data,
        )

        return {
            "status_code": response.status_code,
            "data": data,
            "qr": extract_qr_code(data),
        }

    except Exception as exc:

        print(
            "EVOLUTION CONNECT EXCEPTION:",
            repr(exc),
        )

        return {
            "status_code": 0,
            "data": {
                "error": str(exc)
            },
            "qr": None,
        }


# =========================================================
# EVOLUTION STATUS
# =========================================================

async def evolution_status(
    client: httpx.AsyncClient,
    instance_name: str,
):

    url = (
        f"{EVOLUTION_API_URL}"
        f"/instance/connectionState/"
        f"{instance_name}"
    )

    try:

        response = await client.get(
            url,
            headers=evolution_headers(),
        )

        data = safe_json(response)

        print(
            "EVOLUTION STATUS:",
            response.status_code,
            data,
        )

        return {
            "status_code": response.status_code,
            "data": data,
            "state": extract_connection_state(
                data
            ),
        }

    except Exception as exc:

        print(
            "EVOLUTION STATUS EXCEPTION:",
            repr(exc),
        )

        return {
            "status_code": 0,
            "data": {
                "error": str(exc)
            },
            "state": None,
        }


# =========================================================
# EVOLUTION DELETE INSTANCE
# =========================================================

async def evolution_delete_instance(
    client: httpx.AsyncClient,
    instance_name: str,
):

    url = (
        f"{EVOLUTION_API_URL}"
        f"/instance/logout/"
        f"{instance_name}"
    )

    try:

        response = await client.delete(
            url,
            headers=evolution_headers(),
        )

        return {
            "status_code": response.status_code,
            "data": safe_json(response),
        }

    except Exception as exc:

        return {
            "status_code": 0,
            "data": {
                "error": str(exc)
            },
        }


# =========================================================
# ENSURE INSTANCE
# =========================================================

async def ensure_instance(
    client: httpx.AsyncClient,
    store: StoreModel,
):

    instance_name = make_instance_name(
        store.id
    )

    status = await evolution_status(
        client,
        instance_name,
    )

    state = (
        status.get("state") or ""
    ).lower()

    if state in {
        "open",
        "connected",
        "online",
    }:

        return {
            "instance_name": instance_name,
            "created": False,
            "create": None,
            "status": status,
        }

    create_result = (
        await evolution_create_instance(
            client,
            instance_name,
        )
    )

    if create_result[
        "status_code"
    ] not in (
        200,
        201,
        409,
    ):

        print(
            "INSTANCE CREATE FAILED:",
            create_result,
        )

    if create_result[
        "status_code"
    ] == 409:

        status = await evolution_status(
            client,
            instance_name,
        )

    return {
        "instance_name": instance_name,
        "created": (
            create_result[
                "status_code"
            ] in (200, 201)
        ),
        "create": create_result,
        "status": status,
    }
