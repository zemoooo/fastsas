import os
import io
import re
import uuid
import hashlib
import secrets
import asyncio
import json

from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict, List

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
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Integer,
    Boolean,
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

from agent import (
    run_agent,
    execute_tool,
    get_agent_status,
    get_knowledge_base,
    TOOL_DEFINITIONS,
    build_agent_system_prompt,
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


# =========================================================
# POSTGRES COMPATIBILITY
# =========================================================

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


# =========================================================
# ANTHROPIC
# =========================================================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")).strip()


# =========================================================
# SUPABASE
# =========================================================

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip() or os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_AUTH_TIMEOUT = 30.0

OTP_MIN_DIGITS = 6
OTP_MAX_DIGITS = 8
OTP_COOLDOWN_SECONDS = 60


# =========================================================
# EVOLUTION API
# =========================================================

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").strip().rstrip("/")
EVOLUTION_GLOBAL_KEY = (
    os.getenv("EVOLUTION_GLOBAL_KEY", "").strip()
    or os.getenv("EVOLUTION_API_KEY", "").strip()
    or os.getenv("AUTHENTICATION_API_KEY", "").strip()
)


# =========================================================
# WEBHOOK
# =========================================================

WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", os.getenv("RENDER_EXTERNAL_URL", "")).strip().rstrip("/")


# =========================================================
# FRONTEND
# =========================================================

FRONTEND_URL = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
CORS_ORIGINS = [FRONTEND_URL] if FRONTEND_URL else ["*"]


# =========================================================
# DATABASE
# =========================================================

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# =========================================================
# APP
# =========================================================

app = FastAPI(title="Smart AI Store Assistant", version="4.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=bool(FRONTEND_URL),
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# MODELS
# =========================================================

class StoreModel(Base):
    __tablename__ = "stores"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    store_name = Column(String(255), nullable=False)
    store_url = Column(String(500), nullable=True)
    whatsapp_number = Column(String(50), nullable=True)
    agent_notes = Column(Text, nullable=True)
    catalog_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    users = relationship("UserModel", back_populates="store", cascade="all, delete-orphan")
    logs = relationship("ChatLogModel", back_populates="store", cascade="all, delete-orphan")


class UserModel(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False, unique=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=True, unique=True, index=True)
    email_verified = Column(Boolean, nullable=False, default=False)
    password_hash = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    store = relationship("StoreModel", back_populates="users")


class SessionModel(Base):
    __tablename__ = "auth_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ChatLogModel(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False)
    sender_id = Column(String(255), nullable=True)
    user_message = Column(Text, nullable=False)
    bot_response = Column(Text, nullable=False)
    tool_used = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    store = relationship("StoreModel", back_populates="logs")


class KnowledgeDocModel(Base):
    __tablename__ = "knowledge_docs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    store_id = Column(String(36), ForeignKey("stores.id"), nullable=False, index=True)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    source = Column(String(255), nullable=True)
    doc_type = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# =========================================================
# DATABASE CREATE + MIGRATION
# =========================================================

try:
    Base.metadata.create_all(bind=engine)
except Exception as exc:
    print("DATABASE CREATE ERROR:", repr(exc))


def ensure_database_schema():
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if "users" not in tables:
            return

        columns = inspector.get_columns("users")
        column_names = {column["name"] for column in columns}

        if "email" not in column_names:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))

        if "email_verified" not in column_names:
            with engine.begin() as connection:
                if engine.dialect.name == "postgresql":
                    connection.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE"))
                else:
                    connection.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 0"))

        if engine.dialect.name == "postgresql":
            with engine.begin() as connection:
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_unique ON users(email) WHERE email IS NOT NULL"))
        elif engine.dialect.name == "sqlite":
            with engine.begin() as connection:
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_unique ON users(email)"))

        if "chat_logs" in tables:
            log_columns = inspector.get_columns("chat_logs")
            log_col_names = {c["name"] for c in log_columns}
            if "tool_used" not in log_col_names:
                with engine.begin() as connection:
                    connection.execute(text("ALTER TABLE chat_logs ADD COLUMN tool_used VARCHAR(100)"))

    except Exception as exc:
        print("DATABASE MIGRATION WARNING:", repr(exc))


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


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
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
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return secrets.compare_digest(actual, expected)
    except Exception:
        return False


# =========================================================
# SESSION
# =========================================================

SESSION_COOKIE = "ai_store_session"
SESSION_DAYS = 30


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: UserModel) -> str:
    token = secrets.token_urlsafe(48)
    session = SessionModel(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
    )
    db.add(session)
    db.commit()
    return token


def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="غير مسجل الدخول")

    session = db.query(SessionModel).filter(SessionModel.token_hash == hash_session_token(token)).first()
    if not session:
        raise HTTPException(status_code=401, detail="جلسة غير صالحة")

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise HTTPException(status_code=401, detail="انتهت الجلسة")

    user = db.query(UserModel).filter(UserModel.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")

    if not bool(user.email_verified):
        raise HTTPException(status_code=403, detail="البريد الإلكتروني غير مؤكد")

    return user


def set_session_cookie(response: JSONResponse, token: str):
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=(
            os.getenv("COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"}
            or bool(FRONTEND_URL)
            or os.getenv("RENDER_EXTERNAL_URL", "").startswith("https://")
        ),
        samesite="none" if FRONTEND_URL else "lax",
        path="/",
    )


# =========================================================
# GENERAL HELPERS
# =========================================================

def normalize_phone(value: str) -> str:
    if not value:
        return ""
    value = str(value).strip()
    value = value.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if value.startswith("00"):
        value = value[2:]
    return re.sub(r"\D", "", value)


def make_instance_name(store_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]", "", str(store_id))
    return f"store_{clean}"


def safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def first_value(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def store_to_dict(store: StoreModel):
    return {
        "id": store.id,
        "store_name": store.store_name,
        "store_url": store.store_url,
        "whatsapp_number": store.whatsapp_number,
        "agent_notes": store.agent_notes,
        "has_catalog": bool(store.catalog_text),
        "created_at": store.created_at.isoformat() if store.created_at else None,
    }


# =========================================================
# SUPABASE CONFIG
# =========================================================

def supabase_configuration_ready() -> bool:
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def supabase_admin_ready() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def supabase_auth_headers():
    return {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}


def supabase_admin_headers():
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }


def supabase_error_message(data: Any) -> str:
    if isinstance(data, dict):
        return str(
            data.get("msg") or data.get("message") or data.get("error_description")
            or data.get("error") or data.get("error_code") or ""
        ).strip()
    if isinstance(data, str):
        return data.strip()
    return ""


def is_supabase_rate_limit_error(data: Any) -> bool:
    message = supabase_error_message(data).lower()
    return any(term in message for term in ("rate", "too many", "seconds", "429", "over_email_send_rate_limit"))


def extract_retry_after_seconds(data: Any, fallback: int = 60) -> int:
    message = supabase_error_message(data) or ""
    patterns = [r"after\s+(\d+)\s+seconds?", r"(\d+)\s+seconds?"]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            try:
                return max(1, int(match.group(1)))
            except Exception:
                pass
    return fallback


# =========================================================
# LOCAL OTP COOLDOWN
# =========================================================

otp_last_sent_at: Dict[str, datetime] = {}


def otp_remaining(email: str) -> int:
    last = otp_last_sent_at.get(email)
    if not last:
        return 0
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    remaining = OTP_COOLDOWN_SECONDS - elapsed
    if remaining <= 0:
        return 0
    return int(remaining) + 1


def mark_otp_sent(email: str):
    otp_last_sent_at[email] = datetime.now(timezone.utc)


# =========================================================
# SUPABASE ADMIN - ENSURE USER
# =========================================================

async def supabase_admin_create_user(email: str):
    if not supabase_admin_ready():
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY غير مضبوط.")

    url = f"{SUPABASE_URL}/auth/v1/admin/users"
    payload = {"email": email, "email_confirm": False}

    async with httpx.AsyncClient(timeout=SUPABASE_AUTH_TIMEOUT) as client:
        response = await client.post(url, headers=supabase_admin_headers(), json=payload)

    data = safe_json(response)

    print("SUPABASE ADMIN CREATE:", response.status_code, data)

    if response.status_code in (200, 201):
        return {"created": True, "data": data}

    if response.status_code == 422 and any(
        word in supabase_error_message(data).lower()
        for word in ("already", "exists", "duplicate")
    ):
        return {"created": False, "already_exists": True, "data": data}

    raise RuntimeError(supabase_error_message(data) or "تعذر إنشاء مستخدم Supabase.")


# =========================================================
# SUPABASE SEND OTP
# =========================================================

async def supabase_send_email_otp(email: str):
    if not supabase_configuration_ready():
        raise RuntimeError("SUPABASE_URL أو SUPABASE_ANON_KEY غير مضبوطين.")

    remaining = otp_remaining(email)
    if remaining > 0:
        error = RuntimeError(f"Please wait {remaining} seconds before requesting another OTP.")
        setattr(error, "supabase_status_code", 429)
        setattr(error, "supabase_data", {"code": 429, "error_code": "local_otp_cooldown", "msg": f"Please wait {remaining} seconds."})
        setattr(error, "retry_after", remaining)
        raise error

    url = f"{SUPABASE_URL}/auth/v1/otp"
    payload = {"email": email, "create_user": False}

    async with httpx.AsyncClient(timeout=SUPABASE_AUTH_TIMEOUT) as client:
        response = await client.post(url, headers=supabase_auth_headers(), json=payload)

    data = safe_json(response)
    print("SUPABASE OTP SEND:", response.status_code, data)

    if response.status_code not in range(200, 300):
        retry_after = extract_retry_after_seconds(data)
        error = RuntimeError(supabase_error_message(data) or "تعذر إرسال رمز OTP.")
        setattr(error, "supabase_status_code", response.status_code)
        setattr(error, "supabase_data", data)
        setattr(error, "retry_after", retry_after)
        raise error

    mark_otp_sent(email)
    return {"success": True, "retry_after": OTP_COOLDOWN_SECONDS, "data": data}


# =========================================================
# SUPABASE VERIFY OTP
# =========================================================

async def supabase_verify_email_otp(email: str, code: str):
    if not supabase_configuration_ready():
        raise RuntimeError("SUPABASE_URL أو SUPABASE_ANON_KEY غير مضبوطين.")

    url = f"{SUPABASE_URL}/auth/v1/verify"
    payload = {"email": email, "token": code, "type": "email"}

    async with httpx.AsyncClient(timeout=SUPABASE_AUTH_TIMEOUT) as client:
        response = await client.post(url, headers=supabase_auth_headers(), json=payload)

    data = safe_json(response)
    print("SUPABASE OTP VERIFY:", response.status_code, data)
    return response.status_code, data


# =========================================================
# PDF
# =========================================================

def extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            try:
                value = page.extract_text() or ""
                if value:
                    parts.append(value)
            except Exception:
                continue
        result = "\n\n".join(parts)
        if len(result) > 500000:
            result = result[:500000]
        return result.strip()
    except Exception as exc:
        print("PDF ERROR:", repr(exc))
        return ""


# =========================================================
# QR HELPERS
# =========================================================

def normalize_qr(value: Any) -> Optional[str]:
    """Normalize Evolution API QR representations to an image data URL.

    Evolution API versions can return QR data as:
    - a data:image/... URL
    - a raw base64 string
    - an object containing base64/base64Image/qrcode/qrCode/code/qr
    """
    if value is None:
        return None

    if isinstance(value, dict):
        # Prefer actual image/base64 fields over the WhatsApp pairing "code".
        for key in ("base64", "base64Image", "qrcode", "qrCode", "qr", "code"):
            if key in value:
                qr = normalize_qr(value.get(key))
                if qr:
                    return qr
        return None

    if not isinstance(value, str):
        return None

    value = value.strip()
    if not value:
        return None

    # Some versions return a quoted JSON string.
    if value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
            if decoded != value:
                return normalize_qr(decoded)
        except Exception:
            pass

    if value.startswith("data:image/"):
        return value

    # A URL may point directly to a generated QR image.
    if value.startswith(("http://", "https://")):
        return value

    # Pairing codes such as "2@..." are NOT image QR codes.
    if value.startswith("2@"):
        return None

    # Accept only plausible base64 image payloads.
    compact = re.sub(r"\s+", "", value)
    if len(compact) < 40:
        return None
    if not re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
        return None

    return "data:image/png;base64," + compact


def _walk_qr_values(value: Any, depth: int = 0):
    """Yield possible QR values from arbitrarily nested Evolution responses."""
    if depth > 6 or value is None:
        return

    if isinstance(value, dict):
        preferred = (
            "base64", "base64Image", "qrcode", "qrCode", "qr",
            "code", "image", "imageUrl", "qr_code",
        )
        for key in preferred:
            if key in value:
                yield value[key]
        for key, child in value.items():
            if key not in preferred:
                yield from _walk_qr_values(child, depth + 1)

    elif isinstance(value, list):
        for child in value:
            yield from _walk_qr_values(child, depth + 1)


def extract_qr_code(data: Any) -> Optional[str]:
    """Extract a real QR image from all common Evolution API v2 response shapes."""
    for candidate in _walk_qr_values(data):
        qr = normalize_qr(candidate)
        if qr:
            return qr
    return None


def extract_connection_state(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None

    values = [data.get("state"), data.get("status"), data.get("connectionStatus")]

    nested = data.get("instance")
    if isinstance(nested, dict):
        values.extend([nested.get("state"), nested.get("status"), nested.get("connectionStatus")])

    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        values.extend([nested_data.get("state"), nested_data.get("status"), nested_data.get("connectionStatus")])

    for value in values:
        if value:
            return str(value)
    return None


# =========================================================
# EVOLUTION API
# =========================================================

def require_evolution_config():
    if not EVOLUTION_API_URL:
        raise HTTPException(status_code=500, detail="EVOLUTION_API_URL غير مضبوط")
    if not EVOLUTION_GLOBAL_KEY:
        raise HTTPException(status_code=500, detail="EVOLUTION_GLOBAL_KEY غير مضبوط")


def evolution_headers():
    return {"apikey": EVOLUTION_GLOBAL_KEY, "Content-Type": "application/json"}


async def evolution_create_instance(client: httpx.AsyncClient, instance_name: str):
    url = f"{EVOLUTION_API_URL}/instance/create"
    payload = {
        "instanceName": instance_name,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }

    try:
        response = await client.post(url, headers=evolution_headers(), json=payload)
        data = safe_json(response)
        result = {
            "status_code": response.status_code,
            "data": data,
            "qr": extract_qr_code(data),
            "state": extract_connection_state(data),
        }
        print("EVOLUTION CREATE:", result)
        return result
    except Exception as exc:
        print("EVOLUTION CREATE EXCEPTION:", repr(exc))
        return {"status_code": 0, "data": {"error": str(exc)}, "qr": None, "state": None}


async def evolution_connect(client: httpx.AsyncClient, instance_name: str):
    """Request a fresh QR from the v2 /instance/connect/{instance} endpoint."""
    url = f"{EVOLUTION_API_URL}/instance/connect/{instance_name}"
    try:
        response = await client.get(url, headers=evolution_headers())
        data = safe_json(response)
        result = {
            "status_code": response.status_code,
            "data": data,
            "qr": extract_qr_code(data),
            "state": extract_connection_state(data),
        }
        print("EVOLUTION CONNECT:", response.status_code, "state=", result["state"], "qr=", bool(result["qr"]))
        return result
    except Exception as exc:
        print("EVOLUTION CONNECT ERROR:", repr(exc))
        return {"status_code": 0, "data": {"error": str(exc)}, "qr": None, "state": None}


async def evolution_status(client: httpx.AsyncClient, instance_name: str):
    url = f"{EVOLUTION_API_URL}/instance/connectionState/{instance_name}"
    try:
        response = await client.get(url, headers=evolution_headers())
        data = safe_json(response)
        return {
            "status_code": response.status_code,
            "data": data,
            "state": extract_connection_state(data),
            "qr": extract_qr_code(data),
        }
    except Exception as exc:
        return {"status_code": 0, "data": {"error": str(exc)}, "state": None, "qr": None}


async def ensure_instance(client: httpx.AsyncClient, store: StoreModel):
    """Ensure the per-store Evolution instance exists and is ready for QR generation."""
    instance_name = make_instance_name(store.id)

    status = await evolution_status(client, instance_name)
    state = (status.get("state") or "").strip().lower()

    if state in {"open", "connected", "online"}:
        return {
            "instance_name": instance_name,
            "created": False,
            "create": None,
            "status": status,
        }

    create_result = await evolution_create_instance(client, instance_name)

    # 409 means the instance already exists. Refresh its state before connecting.
    if create_result.get("status_code") == 409:
        status = await evolution_status(client, instance_name)

    return {
        "instance_name": instance_name,
        "created": create_result.get("status_code") in (200, 201),
        "create": create_result,
        "status": status,
    }


async def configure_webhook(client: httpx.AsyncClient, instance_name: str, store_id: str):
    if not WEBHOOK_BASE_URL:
        return {"status_code": 0, "data": {"warning": "WEBHOOK_BASE_URL غير مضبوط"}}

    webhook_url = f"{WEBHOOK_BASE_URL}/api/whatsapp/webhook/{store_id}"
    payload = {
        "webhook": {
            "enabled": True,
            "url": webhook_url,
            "webhookByEvents": False,
            "webhookBase64": False,
            "byEvents": False,
            "events": [
                "MESSAGES_UPSERT",
                "CONNECTION_UPDATE",
                "QRCODE_UPDATED",
            ],
        }
    }

    url = f"{EVOLUTION_API_URL}/webhook/set/{instance_name}"
    try:
        response = await client.post(url, headers=evolution_headers(), json=payload)
        return {"status_code": response.status_code, "data": safe_json(response)}
    except Exception as exc:
        return {"status_code": 0, "data": {"error": str(exc)}}


async def get_qr_with_retry(
    client: httpx.AsyncClient,
    instance_name: str,
    attempts: int = 12,
    delay_seconds: float = 1.5,
    initial_result: Optional[dict] = None,
):
    """Create/connect until a QR image is actually returned or the instance opens."""
    last_result = initial_result

    if initial_result:
        if initial_result.get("qr"):
            return initial_result
        initial_state = (initial_result.get("state") or "").lower()
        if initial_state in {"open", "connected", "online"}:
            return initial_result

    for attempt in range(1, attempts + 1):
        result = await evolution_connect(client, instance_name)
        last_result = result

        if result.get("qr"):
            print(f"QR RECEIVED ON ATTEMPT {attempt}")
            return result

        state = (result.get("state") or extract_connection_state(result.get("data")) or "").lower()
        if state in {"open", "connected", "online"}:
            return result

        if attempt < attempts:
            await asyncio.sleep(delay_seconds)

    return last_result or {
        "status_code": 0,
        "data": {"error": "Evolution API لم ترجع نتيجة"},
        "qr": None,
        "state": None,
    }


async def evolution_send_text(client: httpx.AsyncClient, instance_name: str, number: str, message: str):
    url = f"{EVOLUTION_API_URL}/message/sendText/{instance_name}"
    payload = {"number": number, "text": message}
    response = await client.post(url, headers=evolution_headers(), json=payload)
    data = safe_json(response)
    return {"status_code": response.status_code, "data": data}


# =========================================================
# BASIC ROUTES
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as file:
            return file.read()
    return "<html><body><h1>Smart AI Store Assistant</h1><p>Service is running.</p></body></html>"


@app.head("/")
async def head_index():
    return Response(status_code=200)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "Smart AI Store Assistant",
        "version": "4.1.0",
        "database_configured": bool(DATABASE_URL),
        "evolution_api_configured": bool(EVOLUTION_API_URL),
        "evolution_key_configured": bool(EVOLUTION_GLOBAL_KEY),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "supabase_configured": bool(supabase_configuration_ready()),
        "supabase_admin_configured": bool(supabase_admin_ready()),
        "webhook_configured": bool(WEBHOOK_BASE_URL),
        "frontend_configured": bool(FRONTEND_URL),
        "otp_mode": "SUPABASE_OTP_ONLY",
        "otp_digits": f"{OTP_MIN_DIGITS}-{OTP_MAX_DIGITS}",
        "otp_cooldown": OTP_COOLDOWN_SECONDS,
        "model": ANTHROPIC_MODEL,
        "agent": get_agent_status(),
    }


@app.get("/health/db")
async def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"status": "error", "database": "failed", "error": str(exc)})


@app.get("/widget.js", response_class=FileResponse)
async def get_widget():
    widget_path = os.path.join(os.path.dirname(__file__), "widget.js")
    if os.path.exists(widget_path):
        return FileResponse(widget_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="widget.js not found")


# =========================================================
# AGENT STATUS ENDPOINT
# =========================================================

@app.get("/api/agent/status")
async def agent_status(user: UserModel = Depends(get_current_user)):
    return get_agent_status()


@app.get("/api/agent/tools")
async def agent_tools(user: UserModel = Depends(get_current_user)):
    return {"tools": TOOL_DEFINITIONS, "count": len(TOOL_DEFINITIONS)}


# =========================================================
# KNOWLEDGE BASE ENDPOINTS
# =========================================================

@app.post("/api/knowledge/add")
async def knowledge_add(
    title: str = Form(""),
    content: str = Form(...),
    source: str = Form("manual"),
    doc_type: str = Form("text"),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = KnowledgeDocModel(
        id=str(uuid.uuid4()),
        store_id=user.store_id,
        title=title.strip() or None,
        content=content.strip(),
        source=source.strip(),
        doc_type=doc_type.strip(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    kb = get_knowledge_base(user.store_id)
    await kb.add_document(content, {"title": title, "source": source, "doc_type": doc_type})

    return {"status": "success", "doc_id": doc.id, "message": "تمت إضافة المستند لقاعدة المعرفة"}


@app.get("/api/knowledge/list")
async def knowledge_list(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    docs = (
        db.query(KnowledgeDocModel)
        .filter(KnowledgeDocModel.store_id == user.store_id)
        .order_by(KnowledgeDocModel.created_at.desc())
        .all()
    )

    return {
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "content": d.content[:500],
                "source": d.source,
                "doc_type": d.doc_type,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ],
        "count": len(docs),
    }


@app.delete("/api/knowledge/{doc_id}")
async def knowledge_delete(
    doc_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(KnowledgeDocModel)
        .filter(KnowledgeDocModel.id == doc_id, KnowledgeDocModel.store_id == user.store_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="المستند غير موجود")

    db.delete(doc)
    db.commit()

    kb = get_knowledge_base(user.store_id)
    await kb.remove(doc_id)

    return {"status": "success", "message": "تم حذف المستند"}


@app.post("/api/knowledge/search")
async def knowledge_search(
    query: str = Form(...),
    user: UserModel = Depends(get_current_user),
):
    kb = get_knowledge_base(user.store_id)
    results = await kb.search(query)
    return {
        "query": query,
        "results": [{"content": r["content"][:500], "metadata": r["metadata"]} for r in results],
        "count": len(results),
    }


@app.post("/api/knowledge/scrape")
async def knowledge_scrape(
    url: str = Form(...),
    title: str = Form(""),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scrape a URL and add its content to the knowledge base."""

    result = await execute_tool("scrape_website", {"url": url}, user.store_id)

    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    content = result.get("content", "")
    if not content:
        raise HTTPException(status_code=502, detail="لم يتم استخراج محتوى من الرابط")

    doc_title = title.strip() or result.get("title", "") or url

    doc = KnowledgeDocModel(
        id=str(uuid.uuid4()),
        store_id=user.store_id,
        title=doc_title,
        content=content[:50000],
        source=url,
        doc_type="scraped",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    kb = get_knowledge_base(user.store_id)
    await kb.add_document(content, {"title": doc_title, "source": url, "doc_type": "scraped"})

    return {"status": "success", "doc_id": doc.id, "title": doc_title, "content_length": len(content)}


# =========================================================
# REGISTER STORE
# =========================================================

@app.post("/api/register-store")
async def register_store(
    store_name: str = Form(...),
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    store_name = store_name.strip()
    username = username.strip()
    email = email.strip().lower()

    if len(store_name) < 2:
        raise HTTPException(status_code=400, detail="اسم المتجر مطلوب")

    if len(username) < 3 or len(username) > 50:
        raise HTTPException(status_code=400, detail="اسم المستخدم يجب أن يكون 3 أحرف على الأقل")

    if not re.match(r"^[A-Za-z0-9\u0600-\u06FF_.-]+$", username):
        raise HTTPException(status_code=400, detail="اسم المستخدم يحتوي على أحرف غير مسموحة")

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="البريد الإلكتروني غير صحيح")

    if len(password) < 6:
        raise HTTPException(status_code=400, detail="كلمة المرور يجب أن تكون 6 أحرف على الأقل")

    if not supabase_configuration_ready():
        raise HTTPException(status_code=500, detail="SUPABASE_URL و SUPABASE_ANON_KEY غير مضبوطين.")

    if not supabase_admin_ready():
        raise HTTPException(status_code=500, detail="SUPABASE_SERVICE_ROLE_KEY غير مضبوط.")

    existing_username = db.query(UserModel).filter(UserModel.username == username).first()
    if existing_username:
        raise HTTPException(status_code=409, detail="اسم المستخدم مستخدم مسبقًا")

    existing_email = db.query(UserModel).filter(UserModel.email == email).first()
    if existing_email:
        raise HTTPException(status_code=409, detail="البريد الإلكتروني مستخدم مسبقًا")

    try:
        await supabase_admin_create_user(email)
    except Exception as exc:
        print("SUPABASE ADMIN CREATE ERROR:", repr(exc))
        raise HTTPException(status_code=502, detail="تعذر تجهيز حساب البريد في Supabase.")

    store = StoreModel(id=str(uuid.uuid4()), store_name=store_name)
    db.add(store)
    db.flush()

    user = UserModel(
        id=str(uuid.uuid4()),
        store_id=store.id,
        username=username,
        email=email,
        email_verified=False,
        password_hash=hash_password(password),
    )
    db.add(user)

    try:
        db.commit()
        db.refresh(user)
        db.refresh(store)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="اسم المستخدم أو البريد الإلكتروني مستخدم مسبقًا")

    try:
        await supabase_send_email_otp(email)
    except Exception as exc:
        print("SUPABASE INITIAL OTP ERROR:", repr(exc))
        data = getattr(exc, "supabase_data", None)
        status = getattr(exc, "supabase_status_code", None)
        retry_after = getattr(exc, "retry_after", 60)

        if status == 429 or is_supabase_rate_limit_error(data):
            return JSONResponse(
                status_code=429,
                content={
                    "status": "verification_required",
                    "success": False,
                    "verification_required": True,
                    "otp_sent": False,
                    "retry_after": retry_after,
                    "email": email,
                    "store_id": store.id,
                    "message": "تم إنشاء الحساب، لكن Supabase يطلب الانتظار قبل إرسال OTP جديد.",
                },
            )

        return JSONResponse(
            status_code=502,
            content={
                "status": "verification_required",
                "success": False,
                "verification_required": True,
                "otp_sent": False,
                "email": email,
                "store_id": store.id,
                "message": "تم إنشاء الحساب، لكن تعذر إرسال رمز التحقق. يمكنك استخدام إعادة الإرسال.",
            },
        )

    return {
        "status": "success",
        "success": True,
        "verification_required": True,
        "otp_sent": True,
        "retry_after": OTP_COOLDOWN_SECONDS,
        "message": "تم إنشاء الحساب وإرسال رمز التحقق.",
        "store_id": store.id,
        "user": {"id": user.id, "username": user.username, "email": user.email, "email_verified": False},
        "store": store_to_dict(store),
    }


# =========================================================
# VERIFY EMAIL
# =========================================================

@app.post("/api/verify-email")
async def verify_email(
    email: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    code = code.strip()

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="البريد الإلكتروني غير صحيح")

    if not re.fullmatch(rf"\d{{{OTP_MIN_DIGITS},{OTP_MAX_DIGITS}}}", code):
        raise HTTPException(status_code=400, detail=f"رمز التحقق يجب أن يكون {OTP_MIN_DIGITS} إلى {OTP_MAX_DIGITS} أرقام.")

    user = db.query(UserModel).filter(UserModel.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")

    if bool(user.email_verified):
        token = create_session(db, user)
        response = JSONResponse(content={
            "status": "success",
            "success": True,
            "verification_required": False,
            "message": "البريد الإلكتروني مؤكد مسبقًا",
            "store_id": user.store_id,
            "user": {"id": user.id, "username": user.username, "email": user.email, "email_verified": True},
            "store": store_to_dict(user.store),
        })
        set_session_cookie(response, token)
        return response

    try:
        status_code, data = await supabase_verify_email_otp(email, code)
    except Exception as exc:
        print("SUPABASE VERIFY CONNECTION ERROR:", repr(exc))
        raise HTTPException(status_code=502, detail="تعذر الاتصال بـ Supabase.")

    print("SUPABASE OTP VERIFICATION:", email, status_code, data)

    if status_code not in range(200, 300):
        error_code = ""
        if isinstance(data, dict):
            error_code = str(data.get("error_code", "")).lower()
        message = supabase_error_message(data).lower()

        if error_code == "otp_expired" or "expired" in message:
            raise HTTPException(status_code=400, detail="الرمز غير صالح أو انتهت صلاحيته. استخدم آخر رمز وصلك فقط.")

        if "invalid" in message or "token" in message or "otp" in message:
            raise HTTPException(status_code=400, detail="رمز التحقق غير صحيح. تأكد من إدخال أحدث رمز.")

        raise HTTPException(status_code=400, detail="فشل التحقق من البريد الإلكتروني.")

    user.email_verified = True
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_session(db, user)
    response = JSONResponse(content={
        "status": "success",
        "success": True,
        "verification_required": False,
        "message": "تم تأكيد البريد الإلكتروني بنجاح",
        "store_id": user.store_id,
        "user": {"id": user.id, "username": user.username, "email": user.email, "email_verified": True},
        "store": store_to_dict(user.store),
    })
    set_session_cookie(response, token)
    return response


# =========================================================
# RESEND VERIFICATION
# =========================================================

@app.post("/api/resend-verification")
async def resend_verification(
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="البريد الإلكتروني غير صحيح")

    user = db.query(UserModel).filter(UserModel.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")

    if bool(user.email_verified):
        return {"status": "success", "success": True, "already_verified": True, "message": "البريد الإلكتروني مؤكد مسبقًا"}

    try:
        await supabase_admin_create_user(email)
    except Exception as exc:
        print("SUPABASE ENSURE USER ERROR:", repr(exc))
        raise HTTPException(status_code=502, detail="تعذر تجهيز مستخدم Supabase.")

    try:
        await supabase_send_email_otp(email)
        return {
            "status": "success",
            "success": True,
            "verification_required": True,
            "otp_sent": True,
            "retry_after": OTP_COOLDOWN_SECONDS,
            "message": "تم إرسال رمز جديد. استخدم هذا الرمز فقط.",
        }
    except Exception as exc:
        print("SUPABASE RESEND OTP ERROR:", repr(exc))
        data = getattr(exc, "supabase_data", None)
        status = getattr(exc, "supabase_status_code", None)
        retry_after = getattr(exc, "retry_after", 60)

        if status == 429 or is_supabase_rate_limit_error(data):
            raise HTTPException(status_code=429, detail={"message": "تم إرسال رمز مؤخرًا. انتظر قبل طلب رمز آخر.", "retry_after": retry_after})

        raise HTTPException(status_code=502, detail="تعذر إرسال رمز التحقق.")


# =========================================================
# LOGIN
# =========================================================

@app.post("/api/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    username_input = (username or "").strip()

    if not username_input:
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة.")

    user = db.query(UserModel).filter(
        or_(UserModel.username == username_input, UserModel.email == username_input.lower())
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة.")

    if not verify_password(password or "", user.password_hash):
        raise HTTPException(status_code=401, detail="بيانات الدخول غير صحيحة.")

    if not bool(user.email_verified):
        return JSONResponse(
            status_code=403,
            content={
                "status": "verification_required",
                "success": False,
                "verification_required": True,
                "message": "البريد الإلكتروني غير مؤكد. أدخل رمز التحقق.",
                "email": user.email,
                "store_id": user.store_id,
                "user": {"id": user.id, "username": user.username, "email": user.email, "email_verified": False},
            },
        )

    token = create_session(db, user)
    response = JSONResponse(content={
        "status": "success",
        "success": True,
        "message": "تم تسجيل الدخول بنجاح",
        "store_id": user.store_id,
        "user": {"id": user.id, "username": user.username, "email": user.email, "email_verified": True},
        "store": store_to_dict(user.store),
    })
    set_session_cookie(response, token)
    return response


# =========================================================
# LOGOUT
# =========================================================

@app.post("/api/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.query(SessionModel).filter(SessionModel.token_hash == hash_session_token(token)).first()
        if session:
            db.delete(session)
            db.commit()

    response = JSONResponse(content={"status": "success", "success": True, "message": "تم تسجيل الخروج"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# =========================================================
# CURRENT USER
# =========================================================

@app.get("/api/me")
async def me(user: UserModel = Depends(get_current_user)):
    return {
        "status": "success",
        "success": True,
        "user": {"id": user.id, "username": user.username, "email": user.email, "email_verified": bool(user.email_verified)},
        "store": store_to_dict(user.store),
    }


# =========================================================
# UPDATE AGENT
# =========================================================

@app.post("/api/update-agent")
async def update_agent(
    store_id: str = Form(...),
    store_url: str = Form(""),
    whatsapp_number: str = Form(""),
    agent_notes: str = Form(""),
    pdf_file: Optional[UploadFile] = File(None),
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if store_id != user.store_id:
        raise HTTPException(status_code=403, detail="غير مصرح")

    store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")

    store_url = (store_url or "").strip()
    whatsapp_number = (whatsapp_number or "").strip()
    agent_notes = (agent_notes or "").strip()

    if store_url and not (store_url.startswith("http://") or store_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="رابط المتجر يجب أن يبدأ بـ http:// أو https://")

    normalized_phone = normalize_phone(whatsapp_number)
    if not normalized_phone:
        raise HTTPException(status_code=400, detail="رقم واتساب غير صحيح. استخدم المفتاح الدولي مثل 967...")

    store.store_url = store_url
    store.whatsapp_number = normalized_phone
    store.agent_notes = agent_notes

    if pdf_file and pdf_file.filename:
        filename = pdf_file.filename.lower()
        if not filename.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="الملف يجب أن يكون PDF")

        content = await pdf_file.read()
        if content:
            store.catalog_text = extract_pdf_text(content)
            kb = get_knowledge_base(store.id)
            await kb.add_document(
                store.catalog_text,
                {"title": "Product Catalog PDF", "source": "upload", "doc_type": "catalog"},
            )

    db.commit()
    db.refresh(store)

    evolution_result = None
    if EVOLUTION_API_URL and EVOLUTION_GLOBAL_KEY:
        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                ensure_result = await ensure_instance(client, store)
                instance_name = ensure_result["instance_name"]
                webhook_result = await configure_webhook(client, instance_name, store.id)
                evolution_result = {
                    "instance_name": instance_name,
                    "ensure": ensure_result,
                    "webhook": webhook_result,
                }
        except Exception as exc:
            evolution_result = {"error": str(exc)}

    return {
        "status": "success",
        "success": True,
        "message": "تم حفظ إعدادات المساعد بنجاح",
        "store": store_to_dict(store),
        "evolution": evolution_result,
    }


# =========================================================
# WHATSAPP QR
# =========================================================

@app.get("/api/whatsapp/qr/{store_id}")
async def whatsapp_qr(
    store_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_evolution_config()

    if store_id != user.store_id:
        raise HTTPException(status_code=403, detail="غير مصرح")

    store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")

    if not store.whatsapp_number:
        raise HTTPException(status_code=400, detail="رقم الواتساب غير موجود. احفظ رقم واتساب أولاً.")

    async with httpx.AsyncClient(timeout=40.0) as client:
        ensure_result = await ensure_instance(client, store)
        instance_name = ensure_result["instance_name"]
        webhook_result = await configure_webhook(client, instance_name, store.id)
        qr_result = await get_qr_with_retry(
            client, instance_name, attempts=10, delay_seconds=1.5,
            initial_result=ensure_result.get("create"),
        )

    if qr_result.get("qr"):
        return {
            "status": "success",
            "success": True,
            "qr_code": qr_result["qr"],
            "instance_name": instance_name,
            "connection_state": extract_connection_state(qr_result.get("data")),
            "webhook": webhook_result,
        }

    return JSONResponse(
        status_code=502,
        content={
            "status": "error",
            "success": False,
            "message": "Evolution API لم تُرجع QR Code.",
            "instance_name": instance_name,
            "evolution_http_status": qr_result.get("status_code"),
            "connection_state": extract_connection_state(qr_result.get("data")),
            "evolution_response": qr_result.get("data"),
            "ensure_result": ensure_result,
            "webhook_result": webhook_result,
        },
    )


# =========================================================
# WHATSAPP STATUS
# =========================================================

@app.get("/api/whatsapp/status/{store_id}")
async def whatsapp_status(
    store_id: str,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_evolution_config()

    if store_id != user.store_id:
        raise HTTPException(status_code=403, detail="غير مصرح")

    store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")

    instance_name = make_instance_name(store.id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        result = await evolution_status(client, instance_name)

    success = result.get("status_code") in range(200, 300)

    return {
        "status": "success" if success else "error",
        "success": success,
        "instance_name": instance_name,
        "connection_state": result.get("state"),
        "http_status": result.get("status_code"),
        "evolution_response": result.get("data"),
    }


# =========================================================
# CHAT — POWERED BY AI AGENT WITH TOOLS
# =========================================================

class ChatRequest(BaseModel):
    store_id: str
    message: str
    sender_id: Optional[str] = "preview_user"


@app.post("/api/chat")
async def widget_chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    store = db.query(StoreModel).filter(StoreModel.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="الرسالة فارغة")

    # Get conversation history
    previous_logs = (
        db.query(ChatLogModel)
        .filter(ChatLogModel.store_id == store.id, ChatLogModel.sender_id == payload.sender_id)
        .order_by(ChatLogModel.created_at.desc())
        .limit(5)
        .all()
    )
    previous_logs.reverse()

    previous_messages = []
    for log in previous_logs:
        if log.user_message:
            previous_messages.append({"role": "user", "content": log.user_message})
        if log.bot_response:
            previous_messages.append({"role": "assistant", "content": log.bot_response})

    try:
        reply_text = await run_agent(
            store_id=store.id,
            store_name=store.store_name,
            store_url=store.store_url or "",
            agent_notes=store.agent_notes or "",
            catalog_text=store.catalog_text or "",
            sender_id=payload.sender_id or "preview_user",
            message=payload.message,
            previous_messages=previous_messages,
        )

        log = ChatLogModel(
            store_id=store.id,
            sender_id=payload.sender_id or "preview_user",
            user_message=payload.message,
            bot_response=reply_text,
        )
        db.add(log)
        db.commit()

        return {"status": "success", "success": True, "reply": reply_text, "response": reply_text}

    except HTTPException:
        raise
    except Exception as exc:
        print("CHAT ERROR:", repr(exc))
        raise HTTPException(status_code=500, detail="حدث خطأ أثناء الاتصال بالذكاء الاصطناعي")


# =========================================================
# WHATSAPP WEBHOOK — POWERED BY AI AGENT
# =========================================================

def extract_whatsapp_message(payload: dict):
    if not isinstance(payload, dict):
        return None, None

    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None, None

    key = data.get("key", {})
    if not isinstance(key, dict):
        key = {}

    sender = key.get("remoteJid", "")
    message_data = data.get("message", {})
    if not isinstance(message_data, dict):
        return sender, None

    conversation = message_data.get("conversation")
    if conversation:
        return sender, str(conversation)

    extended = message_data.get("extendedTextMessage", {})
    if isinstance(extended, dict):
        value = extended.get("text")
        if value:
            return sender, str(value)

    image_message = message_data.get("imageMessage", {})
    if isinstance(image_message, dict):
        caption = image_message.get("caption")
        if caption:
            return sender, str(caption)

    video_message = message_data.get("videoMessage", {})
    if isinstance(video_message, dict):
        caption = video_message.get("caption")
        if caption:
            return sender, str(caption)

    return sender, None


@app.post("/api/whatsapp/webhook/{store_id}")
async def whatsapp_webhook(
    store_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
    if not store:
        return {"status": "store_not_found"}

    try:
        payload = await request.json()
        sender, incoming_text = extract_whatsapp_message(payload)

        if not sender:
            return {"status": "ignored", "reason": "sender missing"}

        if not incoming_text:
            return {"status": "ignored", "reason": "text missing"}

        if sender.endswith("@g.us"):
            return {"status": "ignored", "reason": "group"}

        if sender.endswith("@broadcast"):
            return {"status": "ignored", "reason": "broadcast"}

        data = payload.get("data", payload)
        key = data.get("key", {}) if isinstance(data, dict) else {}
        if key.get("fromMe", False):
            return {"status": "ignored", "reason": "from_me"}

        incoming_text = incoming_text.strip()

        # Get conversation history
        previous_logs = (
            db.query(ChatLogModel)
            .filter(ChatLogModel.store_id == store.id, ChatLogModel.sender_id == sender)
            .order_by(ChatLogModel.created_at.desc())
            .limit(5)
            .all()
        )
        previous_logs.reverse()

        previous_messages = []
        for log in previous_logs:
            if log.user_message:
                previous_messages.append({"role": "user", "content": log.user_message})
            if log.bot_response:
                previous_messages.append({"role": "assistant", "content": log.bot_response})

        reply_text = await run_agent(
            store_id=store.id,
            store_name=store.store_name,
            store_url=store.store_url or "",
            agent_notes=store.agent_notes or "",
            catalog_text=store.catalog_text or "",
            sender_id=sender,
            message=incoming_text,
            previous_messages=previous_messages,
        )

        log = ChatLogModel(
            store_id=store.id,
            sender_id=sender,
            user_message=incoming_text,
            bot_response=reply_text,
        )
        db.add(log)
        db.commit()

        instance_name = make_instance_name(store.id)
        target_number = sender.split("@")[0]

        async with httpx.AsyncClient(timeout=30.0) as client:
            send_result = await evolution_send_text(client, instance_name, target_number, reply_text)

        return {
            "status": "success",
            "sent": send_result["status_code"] in range(200, 300),
            "evolution_status": send_result["status_code"],
        }

    except Exception as exc:
        print("WHATSAPP WEBHOOK ERROR:", repr(exc))
        return {"status": "error", "error": str(exc)}


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup_event():
    print("=" * 50)
    print("SMART AI STORE ASSISTANT v4.0.0 STARTING")
    print(f"DATABASE: {'configured' if DATABASE_URL else 'missing'}")
    print(f"SUPABASE URL: {SUPABASE_URL or 'missing'}")
    print(f"SUPABASE ANON KEY: {'configured' if SUPABASE_ANON_KEY else 'missing'}")
    print(f"SUPABASE SERVICE ROLE: {'configured' if SUPABASE_SERVICE_ROLE_KEY else 'MISSING'}")
    print(f"SUPABASE ADMIN: {'ready' if supabase_admin_ready() else 'NOT READY'}")
    print(f"OTP FLOW: ADMIN CREATE -> OTP -> VERIFY")
    print(f"EVOLUTION: {'configured' if EVOLUTION_API_URL else 'missing'}")
    print(f"ANTHROPIC: {'configured' if ANTHROPIC_API_KEY else 'missing'}")
    print(f"MODEL: {ANTHROPIC_MODEL}")
    print(f"AGENT: {get_agent_status()}")
    print("=" * 50)


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "10000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
