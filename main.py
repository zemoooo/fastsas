import os
import uuid
import hashlib
import secrets
import re
import io

from datetime import datetime, timedelta, timezone
from typing import Optional

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
from fastapi.responses import FileResponse, JSONResponse, Response

from pydantic import BaseModel

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    create_engine,
    or_,
    text,
    inspect,
)

from sqlalchemy.exc import IntegrityError

from sqlalchemy.orm import (
    declarative_base,
    relationship,
    sessionmaker,
    Session,
)


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="Smart AI Store Assistant",
    version="1.0.0",
)


# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# DATABASE
# =========================================================

DATABASE_URL = os.getenv(
    "DATABASE_CONNECTION_URI",
    ""
).strip()

if not DATABASE_URL:
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        ""
    ).strip()

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./saas_stores.db"


# دعم postgres:// القديم
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = (
        "postgresql://"
        + DATABASE_URL[len("postgres://"):]
    )


# إضافة SSL إلى PostgreSQL / Supabase
if DATABASE_URL.startswith("postgresql"):
    if "sslmode=" not in DATABASE_URL:
        separator = "&" if "?" in DATABASE_URL else "?"
        DATABASE_URL = (
            DATABASE_URL
            + separator
            + "sslmode=require"
        )


# إنشاء محرك قاعدة البيانات
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
# MODELS
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
        String(1000),
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
        DateTime,
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
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    # nullable=True مهم للتوافق مع قواعد البيانات القديمة
    email = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )

    password_hash = Column(
        String(255),
        nullable=False,
    )

    created_at = Column(
        DateTime,
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
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    expires_at = Column(
        DateTime,
        nullable=False,
    )

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )


class ChatLogModel(Base):

    __tablename__ = "chat_logs"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
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
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    store = relationship(
        "StoreModel",
        back_populates="logs",
    )


# =========================================================
# CREATE TABLES
# =========================================================

try:

    Base.metadata.create_all(
        bind=engine
    )

except Exception as error:

    print(
        "Database create_all warning:",
        str(error)
    )


# =========================================================
# DATABASE MIGRATION
# =========================================================

def ensure_database_schema():

    """
    يقوم هذا الجزء بفحص قاعدة البيانات القديمة
    وإضافة الأعمدة الضرورية إذا كانت غير موجودة.

    مهم جداً لأن SQLAlchemy create_all()
    لا يقوم بتعديل الجداول الموجودة مسبقاً.
    """

    try:

        inspector = inspect(engine)

        tables = inspector.get_table_names()

        # -------------------------------------------------
        # USERS
        # -------------------------------------------------

        if "users" in tables:

            columns = {
                column["name"]
                for column in inspector.get_columns(
                    "users"
                )
            }

            # إضافة email إذا لم يكن موجوداً
            if "email" not in columns:

                print(
                    "Adding missing users.email column..."
                )

                with engine.begin() as connection:

                    connection.execute(
                        text(
                            """
                            ALTER TABLE users
                            ADD COLUMN email VARCHAR(255)
                            """
                        )
                    )

            # -------------------------------------------------
            # UNIQUE INDEX FOR EMAIL
            # -------------------------------------------------

            try:

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

            except Exception as error:

                print(
                    "Email unique index warning:",
                    str(error)
                )

        print(
            "Database schema check completed."
        )

    except Exception as error:

        print(
            "Database schema migration warning:",
            str(error)
        )


# تشغيل الترحيل
ensure_database_schema()


# =========================================================
# DATABASE DEPENDENCY
# =========================================================

def get_db():

    db = SessionLocal()

    try:

        yield db

    finally:

        db.close()


# =========================================================
# PASSWORD HASHING
# =========================================================

PBKDF2_ROUNDS = 240000


def hash_password(
    password: str
) -> str:

    salt = secrets.token_bytes(16)

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ROUNDS,
    )

    return (
        f"pbkdf2_sha256$"
        f"{PBKDF2_ROUNDS}$"
        f"{salt.hex()}$"
        f"{derived.hex()}"
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
        rounds = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])

        if algorithm != "pbkdf2_sha256":
            return False

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            rounds,
        )

        return secrets.compare_digest(
            actual,
            expected,
        )

    except Exception:

        return False


# =========================================================
# SESSION
# =========================================================

SESSION_COOKIE = "ai_store_session"

SESSION_DAYS = 30

COOKIE_SECURE = (
    os.getenv(
        "COOKIE_SECURE",
        "true",
    ).lower()
    in ("1", "true", "yes")
)


def hash_session_token(
    token: str
) -> str:

    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def create_session(
    db: Session,
    user: UserModel,
):

    raw_token = secrets.token_urlsafe(48)

    token_hash = hash_session_token(
        raw_token
    )

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(days=SESSION_DAYS)
    )

    session = SessionModel(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    db.add(session)
    db.commit()

    return raw_token


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
):

    token = request.cookies.get(
        SESSION_COOKIE
    )

    if not token:
        return None

    token_hash = hash_session_token(
        token
    )

    session = (
        db.query(SessionModel)
        .filter(
            SessionModel.token_hash
            == token_hash
        )
        .first()
    )

    if not session:
        return None

    now = datetime.now(timezone.utc)

    expires_at = session.expires_at

    if expires_at.tzinfo is None:

        expires_at = expires_at.replace(
            tzinfo=timezone.utc
        )

    if expires_at < now:

        db.delete(session)
        db.commit()

        return None

    user = (
        db.query(UserModel)
        .filter(
            UserModel.id
            == session.user_id
        )
        .first()
    )

    if not user:
        return None

    return user


def require_current_user(
    request: Request,
    db: Session = Depends(get_db),
):

    user = get_current_user(
        request,
        db,
    )

    if not user:

        raise HTTPException(
            status_code=401,
            detail="يجب تسجيل الدخول أولاً.",
        )

    return user


# =========================================================
# EVOLUTION API
# =========================================================

EVOLUTION_API_URL = os.getenv(
    "EVOLUTION_API_URL",
    "",
).strip().rstrip("/")


EVOLUTION_API_KEY = (
    os.getenv(
        "EVOLUTION_GLOBAL_KEY",
        "",
    ).strip()
    or os.getenv(
        "EVOLUTION_API_KEY",
        "",
    ).strip()
    or os.getenv(
        "AUTHENTICATION_API_KEY",
        "",
    ).strip()
)


WEBHOOK_BASE_URL = os.getenv(
    "WEBHOOK_BASE_URL",
    "",
).strip().rstrip("/")


def require_evolution_config():

    if not EVOLUTION_API_URL:

        raise HTTPException(
            status_code=500,
            detail=(
                "EVOLUTION_API_URL غير موجود "
                "في متغيرات البيئة على Render."
            ),
        )

    if not EVOLUTION_API_KEY:

        raise HTTPException(
            status_code=500,
            detail=(
                "EVOLUTION_GLOBAL_KEY أو "
                "EVOLUTION_API_KEY غير موجود "
                "في متغيرات البيئة على Render."
            ),
        )


def evolution_headers():

    return {
        "Content-Type": "application/json",
        "apikey": EVOLUTION_API_KEY,
    }


# =========================================================
# PHONE NORMALIZATION
# =========================================================

def normalize_phone(
    phone: str
) -> str:

    if not phone:
        return ""

    value = phone.strip()

    value = (
        value.replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if value.startswith("00"):
        value = value[2:]

    if not value.isdigit():

        raise HTTPException(
            status_code=400,
            detail=(
                "رقم الواتساب غير صحيح. "
                "اكتب الرقم مع مفتاح الدولة بدون + أو مسافات."
            ),
        )

    if len(value) < 8:

        raise HTTPException(
            status_code=400,
            detail="رقم الواتساب قصير جداً.",
        )

    return value


# =========================================================
# PDF EXTRACTION
# =========================================================

async def extract_pdf_text(
    pdf_file: Optional[UploadFile],
) -> Optional[str]:

    if not pdf_file:
        return None

    if not pdf_file.filename:
        return None

    filename = pdf_file.filename.lower()

    if not filename.endswith(".pdf"):

        raise HTTPException(
            status_code=400,
            detail="الملف يجب أن يكون PDF.",
        )

    try:

        content = await pdf_file.read()

        if not content:
            return None

        reader = PdfReader(
            io.BytesIO(content)
        )

        pages = []

        for page in reader.pages:

            page_text = (
                page.extract_text()
                or ""
            )

            if page_text.strip():

                pages.append(
                    page_text.strip()
                )

        result = "\n\n".join(pages)

        return result[:500000]

    except Exception as error:

        raise HTTPException(
            status_code=400,
            detail=(
                "تعذر قراءة ملف PDF: "
                + str(error)
            ),
        )


# =========================================================
# STORE SERIALIZER
# =========================================================

def store_to_dict(
    store: StoreModel,
    user: Optional[UserModel] = None,
):

    return {

        "id":
            store.id,

        "store_name":
            store.store_name,

        "store_url":
            store.store_url
            or "",

        "whatsapp_number":
            store.whatsapp_number
            or "",

        "agent_notes":
            store.agent_notes
            or "",

        "has_catalog":
            bool(store.catalog_text),

        "email":
            (
                user.email
                if user and user.email
                else ""
            ),

        "username":
            (
                user.username
                if user
                else ""
            ),
    }


# =========================================================
# HOME
# =========================================================

@app.get("/")
async def home():

    if os.path.exists("index.html"):

        return FileResponse(
            "index.html"
        )

    return {
        "message":
            "Smart AI Store Assistant is running"
    }


# =========================================================
# HEAD HOME
# =========================================================

@app.head("/")
async def head_home():

    return Response(
        status_code=200
    )


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health():

    return {

        "status":
            "ok",

        "database":
            (
                "configured"
                if DATABASE_URL
                else "missing"
            ),

        "evolution":
            (
                "configured"
                if EVOLUTION_API_URL
                and EVOLUTION_API_KEY
                else "not_configured"
            ),

        "anthropic":
            (
                "configured"
                if os.getenv(
                    "ANTHROPIC_API_KEY",
                    "",
                ).strip()
                else "not_configured"
            ),
    }


# =========================================================
# DATABASE HEALTH
# =========================================================

@app.get("/health/db")
def health_db(
    db: Session = Depends(get_db),
):

    try:

        db.execute(
            text("SELECT 1")
        )

        return {

            "status":
                "ok",

            "database":
                "connected",
        }

    except Exception as error:

        return JSONResponse(

            status_code=500,

            content={

                "status":
                    "error",

                "database":
                    "not_connected",

                "detail":
                    str(error),
            },
        )


# =========================================================
# WIDGET
# =========================================================

@app.get("/widget.js")
async def widget():

    if os.path.exists("widget.js"):

        return FileResponse(
            "widget.js",
            media_type="application/javascript",
        )

    return Response(
        "// widget not found",
        media_type="application/javascript",
    )


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


    # =====================================================
    # VALIDATION
    # =====================================================

    if not store_name:

        raise HTTPException(
            status_code=400,
            detail="اسم المتجر مطلوب.",
        )


    if not username:

        raise HTTPException(
            status_code=400,
            detail="اسم المستخدم مطلوب.",
        )


    if len(username) < 3:

        raise HTTPException(
            status_code=400,
            detail=(
                "اسم المستخدم يجب أن يكون "
                "3 أحرف على الأقل."
            ),
        )


    if len(username) > 50:

        raise HTTPException(
            status_code=400,
            detail=(
                "اسم المستخدم يجب ألا يتجاوز "
                "50 حرفاً."
            ),
        )


    # =====================================================
    # USERNAME VALIDATION
    # عربي + إنجليزي + أرقام + _ - .
    # =====================================================

    USERNAME_PATTERN = (
        r"^[A-Za-z0-9\u0600-\u06FF_.-]+$"
    )


    if not re.fullmatch(
        USERNAME_PATTERN,
        username,
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "اسم المستخدم يجب أن يحتوي على "
                "أحرف عربية أو إنجليزية أو أرقام "
                "أو _ أو - أو . فقط."
            ),
        )


    # =====================================================
    # EMAIL
    # =====================================================

    if not email:

        raise HTTPException(
            status_code=400,
            detail="الإيميل مطلوب.",
        )


    email_pattern = (
        r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )


    if not re.fullmatch(
        email_pattern,
        email,
    ):

        raise HTTPException(
            status_code=400,
            detail="الإيميل غير صحيح.",
        )


    # =====================================================
    # PASSWORD
    # =====================================================

    if len(password) < 6:

        raise HTTPException(
            status_code=400,
            detail=(
                "كلمة المرور يجب أن تكون "
                "6 أحرف على الأقل."
            ),
        )


    # =====================================================
    # CHECK USERNAME
    # =====================================================

    try:

        existing_username = (
            db.query(UserModel)
            .filter(
                UserModel.username
                == username
            )
            .first()
        )

    except Exception as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "حدث خطأ في قاعدة البيانات "
                "أثناء فحص اسم المستخدم: "
                + str(error)
            ),
        )


    if existing_username:

        raise HTTPException(
            status_code=409,
            detail="اسم المستخدم مستخدم بالفعل.",
        )


    # =====================================================
    # CHECK EMAIL
    # =====================================================

    try:

        existing_email = (
            db.query(UserModel)
            .filter(
                UserModel.email
                == email
            )
            .first()
        )

    except Exception as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "حدث خطأ في قاعدة البيانات "
                "أثناء فحص الإيميل: "
                + str(error)
            ),
        )


    if existing_email:

        raise HTTPException(
            status_code=409,
            detail="الإيميل مستخدم بالفعل.",
        )


    # =====================================================
    # CREATE STORE
    # =====================================================

    store = StoreModel(

        id=str(uuid.uuid4()),

        store_name=store_name,
    )


    # =====================================================
    # CREATE USER
    # =====================================================

    user = UserModel(

        id=str(uuid.uuid4()),

        store_id=store.id,

        username=username,

        email=email,

        password_hash=hash_password(
            password
        ),
    )


    # =====================================================
    # SAVE
    # =====================================================

    try:

        db.add(store)

        db.add(user)

        db.commit()

        db.refresh(store)

        db.refresh(user)

    except IntegrityError as error:

        db.rollback()

        print(
            "Registration IntegrityError:",
            str(error)
        )

        raise HTTPException(
            status_code=409,
            detail=(
                "اسم المستخدم أو الإيميل "
                "موجود بالفعل."
            ),
        )

    except Exception as error:

        db.rollback()

        print(
            "Registration database error:",
            str(error)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "تعذر إنشاء الحساب: "
                + str(error)
            ),
        )


    # =====================================================
    # CREATE SESSION
    # =====================================================

    try:

        token = create_session(
            db,
            user,
        )

    except Exception as error:

        db.rollback()

        print(
            "Session creation error:",
            str(error)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "تم إنشاء الحساب ولكن تعذر "
                "إنشاء جلسة الدخول: "
                + str(error)
            ),
        )


    # =====================================================
    # RESPONSE
    # =====================================================

    response = JSONResponse(

        content={

            "success":
                True,

            "message":
                "تم إنشاء الحساب بنجاح.",

            "store_id":
                store.id,

            "id":
                store.id,

            "username":
                user.username,

            "email":
                user.email,

            "store":
                store_to_dict(
                    store,
                    user,
                ),
        }
    )


    response.set_cookie(

        key=SESSION_COOKIE,

        value=token,

        max_age=SESSION_DAYS * 86400,

        httponly=True,

        secure=COOKIE_SECURE,

        samesite="lax",

        path="/",
    )


    return response


# =========================================================
# LOGIN
# =========================================================

@app.post("/api/login")
async def login(

    username: str = Form(...),

    password: str = Form(...),

    db: Session = Depends(get_db),
):

    login_value = username.strip()


    if not login_value:

        raise HTTPException(
            status_code=400,
            detail="اسم المستخدم أو الإيميل مطلوب.",
        )


    # =====================================================
    # SEARCH USER
    # =====================================================

    try:

        user = (

            db.query(UserModel)

            .filter(

                or_(

                    UserModel.username
                    == login_value,

                    UserModel.email
                    == login_value.lower(),

                )

            )

            .first()
        )

    except Exception as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "حدث خطأ في قاعدة البيانات "
                "أثناء تسجيل الدخول: "
                + str(error)
            ),
        )


    if not user:

        raise HTTPException(
            status_code=401,
            detail=(
                "اسم المستخدم أو الإيميل "
                "أو كلمة المرور غير صحيحة."
            ),
        )


    if not verify_password(
        password,
        user.password_hash,
    ):

        raise HTTPException(
            status_code=401,
            detail=(
                "اسم المستخدم أو الإيميل "
                "أو كلمة المرور غير صحيحة."
            ),
        )


    # =====================================================
    # STORE
    # =====================================================

    store = (

        db.query(StoreModel)

        .filter(

            StoreModel.id
            == user.store_id

        )

        .first()
    )


    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود.",
        )


    # =====================================================
    # SESSION
    # =====================================================

    try:

        token = create_session(
            db,
            user,
        )

    except Exception as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "تعذر إنشاء جلسة الدخول: "
                + str(error)
            ),
        )


    # =====================================================
    # RESPONSE
    # =====================================================

    response = JSONResponse(

        content={

            "success":
                True,

            "username":
                user.username,

            "email":
                user.email
                or "",

            "store":
                store_to_dict(
                    store,
                    user,
                ),
        }
    )


    response.set_cookie(

        key=SESSION_COOKIE,

        value=token,

        max_age=SESSION_DAYS * 86400,

        httponly=True,

        secure=COOKIE_SECURE,

        samesite="lax",

        path="/",
    )


    return response


# =========================================================
# LOGOUT
# =========================================================

@app.post("/api/logout")
async def logout(

    request: Request,

    db: Session = Depends(get_db),
):

    token = request.cookies.get(
        SESSION_COOKIE
    )


    if token:

        token_hash = hash_session_token(
            token
        )


        session = (

            db.query(SessionModel)

            .filter(

                SessionModel.token_hash
                == token_hash

            )

            .first()
        )


        if session:

            db.delete(session)

            db.commit()


    response = JSONResponse(

        content={
            "success": True
        }
    )


    response.delete_cookie(

        key=SESSION_COOKIE,

        path="/",
    )


    return response


# =========================================================
# CURRENT USER
# =========================================================

@app.get("/api/me")
async def me(

    user: UserModel = Depends(
        require_current_user
    ),

    db: Session = Depends(get_db),
):

    store = (

        db.query(StoreModel)

        .filter(

            StoreModel.id
            == user.store_id

        )

        .first()
    )


    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود.",
        )


    return {

        "success":
            True,

        "username":
            user.username,

        "email":
            user.email
            or "",

        "store":
            store_to_dict(
                store,
                user,
            ),
    }


# =========================================================
# UPDATE AGENT
# =========================================================

@app.post("/api/update-agent")
async def update_agent(

    store_id: str = Form(...),

    store_url: str = Form(...),

    whatsapp_number: str = Form(...),

    agent_notes: str = Form(...),

    pdf_file: Optional[UploadFile] = File(None),

    user: UserModel = Depends(
        require_current_user
    ),

    db: Session = Depends(get_db),
):

    store_id = store_id.strip()

    store_url = store_url.strip()

    agent_notes = agent_notes.strip()


    # =====================================================
    # SECURITY
    # =====================================================

    if store_id != user.store_id:

        raise HTTPException(
            status_code=403,
            detail="لا يمكنك تعديل هذا المتجر.",
        )


    # =====================================================
    # STORE URL
    # =====================================================

    if not store_url:

        raise HTTPException(
            status_code=400,
            detail="رابط المتجر مطلوب.",
        )


    if not (

        store_url.startswith("http://")

        or store_url.startswith("https://")

    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "رابط المتجر يجب أن يبدأ "
                "بـ https:// أو http://"
            ),
        )


    # =====================================================
    # AGENT NOTES
    # =====================================================

    if not agent_notes:

        raise HTTPException(
            status_code=400,
            detail="تعليمات المساعد مطلوبة.",
        )


    # =====================================================
    # WHATSAPP
    # =====================================================

    phone = normalize_phone(
        whatsapp_number
    )


    # =====================================================
    # FIND STORE
    # =====================================================

    store = (

        db.query(StoreModel)

        .filter(

            StoreModel.id
            == user.store_id

        )

        .first()
    )


    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود.",
        )


    # =====================================================
    # PDF
    # =====================================================

    catalog_text = None


    if pdf_file:

        catalog_text = (

            await extract_pdf_text(
                pdf_file
            )

        )


    # =====================================================
    # UPDATE
    # =====================================================

    store.store_url = store_url

    store.whatsapp_number = phone

    store.agent_notes = agent_notes


    if catalog_text is not None:

        store.catalog_text = catalog_text


    try:

        db.commit()

        db.refresh(store)

    except Exception as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                "تعذر حفظ بيانات المتجر: "
                + str(error)
            ),
        )


    return {

        "success":
            True,

        "message":
            "تم حفظ بيانات المتجر والمساعد بنجاح.",

        "store":
            store_to_dict(
                store,
                user,
            ),
    }


# =========================================================
# EVOLUTION CREATE INSTANCE
# =========================================================

async def evolution_create_instance(
    instance_name: str,
):

    require_evolution_config()


    payload = {

        "instanceName":
            instance_name,

        "qrcode":
            True,

        "integration":
            "WHATSAPP-BAILEYS",
    }


    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.post(

            f"{EVOLUTION_API_URL}/instance/create",

            headers=evolution_headers(),

            json=payload,
        )


    return response


# =========================================================
# EVOLUTION CONNECT
# =========================================================

async def evolution_connect(
    instance_name: str,
):

    require_evolution_config()


    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.get(

            f"{EVOLUTION_API_URL}/instance/connect/{instance_name}",

            headers=evolution_headers(),
        )


    return response


# =========================================================
# EVOLUTION STATUS
# =========================================================

async def evolution_status(
    instance_name: str,
):

    require_evolution_config()


    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.get(

            f"{EVOLUTION_API_URL}/instance/connectionState/{instance_name}",

            headers=evolution_headers(),
        )


    return response


# =========================================================
# EVOLUTION WEBHOOK
# =========================================================

async def evolution_set_webhook(

    instance_name: str,

    store_id: str,

):

    if not WEBHOOK_BASE_URL:
        return None


    require_evolution_config()


    webhook_url = (

        f"{WEBHOOK_BASE_URL}/api/whatsapp/webhook/"
        f"{store_id}"

    )


    payload = {

        "enabled":
            True,

        "url":
            webhook_url,

        "webhookByEvents":
            False,

        "webhookBase64":
            False,

        "events":
            [
                "MESSAGES_UPSERT"
            ],
    }


    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.post(

            f"{EVOLUTION_API_URL}/webhook/set/{instance_name}",

            headers=evolution_headers(),

            json=payload,
        )


    return response


# =========================================================
# ENSURE EVOLUTION INSTANCE
# =========================================================

async def ensure_evolution_instance(
    store: StoreModel,
):

    require_evolution_config()


    instance_name = (

        "store_"

        + re.sub(

            r"[^a-zA-Z0-9_]",

            "_",

            store.id,

        )

    )


    # =====================================================
    # CREATE
    # =====================================================

    try:

        create_response = (

            await evolution_create_instance(
                instance_name
            )

        )


        if create_response.status_code not in (

            200,
            201,
            409,

        ):

            try:

                error_data = (
                    create_response.json()
                )

                error_text = str(
                    error_data
                ).lower()

            except Exception:

                error_text = (

                    create_response.text
                    or ""

                ).lower()


            already_exists = (

                "already" in error_text

                or "exists" in error_text

                or "exist" in error_text

                or (
                    "instance" in error_text
                    and "found" in error_text
                )

            )


            if not already_exists:

                raise HTTPException(

                    status_code=502,

                    detail=(

                        "تعذر إنشاء اتصال Evolution API: "

                        + (

                            create_response.text
                            or "خطأ غير معروف"

                        )

                    ),
                )


    except HTTPException:

        raise


    except Exception:

        pass


    # =====================================================
    # WEBHOOK
    # =====================================================

    try:

        await evolution_set_webhook(

            instance_name,

            store.id,

        )

    except Exception as error:

        print(

            "Webhook setup warning:",

            str(error),

        )


    return instance_name


# =========================================================
# EXTRACT QR CODE
# =========================================================

def extract_qr_code(data):

    if not isinstance(data, dict):
        return None


    possible_keys = [

        "base64",

        "qrCode",

        "qrcode",

        "qr",

        "code",

    ]


    # المستوى الرئيسي
    for key in possible_keys:

        value = data.get(key)


        if (

            isinstance(value, str)

            and value.strip()

        ):

            if value.startswith(
                "data:image"
            ):

                return value


            return (

                "data:image/png;base64,"

                + value

            )


    # داخل instance
    instance = data.get(
        "instance"
    )


    if isinstance(
        instance,
        dict,
    ):

        for key in possible_keys:

            value = instance.get(key)


            if (

                isinstance(value, str)

                and value.strip()

            ):

                if value.startswith(
                    "data:image"
                ):

                    return value


                return (

                    "data:image/png;base64,"

                    + value

                )


    # داخل data
    nested_data = data.get(
        "data"
    )


    if isinstance(
        nested_data,
        dict,
    ):

        for key in possible_keys:

            value = nested_data.get(key)


            if (

                isinstance(value, str)

                and value.strip()

            ):

                if value.startswith(
                    "data:image"
                ):

                    return value


                return (

                    "data:image/png;base64,"

                    + value

                )


    return None


# =========================================================
# WHATSAPP QR
# =========================================================

@app.get("/api/whatsapp/qr/{store_id}")
async def whatsapp_qr(

    store_id: str,

    user: UserModel = Depends(
        require_current_user
    ),

    db: Session = Depends(get_db),

):

    # =====================================================
    # SECURITY
    # =====================================================

    if store_id != user.store_id:

        raise HTTPException(
            status_code=403,
            detail="لا يمكنك الوصول إلى هذا المتجر.",
        )


    # =====================================================
    # STORE
    # =====================================================

    store = (

        db.query(StoreModel)

        .filter(

            StoreModel.id
            == store_id

        )

        .first()
    )


    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود.",
        )


    # =====================================================
    # PHONE
    # =====================================================

    if not store.whatsapp_number:

        raise HTTPException(
            status_code=400,
            detail=(
                "رقم الواتساب غير موجود لهذا المتجر. "
                "أدخل رقم المتجر أولاً ثم احفظ البيانات."
            ),
        )


    # =====================================================
    # EVOLUTION
    # =====================================================

    instance_name = (

        await ensure_evolution_instance(
            store
        )

    )


    # =====================================================
    # CONNECT
    # =====================================================

    try:

        connect_response = (

            await evolution_connect(
                instance_name
            )

        )

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "تعذر الاتصال بـ Evolution API: "
                + str(error)
            ),
        )


    # =====================================================
    # PARSE
    # =====================================================

    try:

        connect_data = (
            connect_response.json()
        )

    except Exception:

        connect_data = {}


    qr_code = extract_qr_code(
        connect_data
    )


    if qr_code:

        return {

            "success":
                True,

            "qr_code":
                qr_code,

            "instance":
                instance_name,

        }


    # =====================================================
    # RETRY
    # =====================================================

    try:

        import asyncio

        await asyncio.sleep(2)


        second_response = (

            await evolution_connect(
                instance_name
            )

        )


        try:

            second_data = (
                second_response.json()
            )

        except Exception:

            second_data = {}


        qr_code = extract_qr_code(
            second_data
        )


        if qr_code:

            return {

                "success":
                    True,

                "qr_code":
                    qr_code,

                "instance":
                    instance_name,

            }


    except Exception:

        pass


    # =====================================================
    # ERROR
    # =====================================================

    detail = (

        "تم حفظ بيانات المتجر، "
        "لكن Evolution API لم يرجع رمز QR."

    )


    if connect_response.status_code >= 400:

        detail += (

            f" حالة Evolution API: "

            f"{connect_response.status_code}. "

            f"{connect_response.text[:500]}"

        )


    raise HTTPException(

        status_code=502,

        detail=detail,

    )


# =========================================================
# WHATSAPP STATUS
# =========================================================

@app.get("/api/whatsapp/status/{store_id}")
async def whatsapp_status(

    store_id: str,

    user: UserModel = Depends(
        require_current_user
    ),

    db: Session = Depends(get_db),

):

    if store_id != user.store_id:

        raise HTTPException(
            status_code=403,
            detail="غير مسموح.",
        )


    store = (

        db.query(StoreModel)

        .filter(

            StoreModel.id
            == store_id

        )

        .first()
    )


    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود.",
        )


    instance_name = (

        "store_"

        + re.sub(

            r"[^a-zA-Z0-9_]",

            "_",

            store.id,

        )

    )


    try:

        response = await evolution_status(
            instance_name
        )

    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "تعذر الاتصال بـ Evolution API: "
                + str(error)
            ),
        )


    try:

        data = response.json()

    except Exception:

        data = {
            "raw": response.text
        }


    return {

        "success":
            response.status_code < 400,

        "instance":
            instance_name,

        "status":
            data,

    }


# =========================================================
# CLAUDE
# =========================================================

ANTHROPIC_API_KEY = os.getenv(
    "ANTHROPIC_API_KEY",
    "",
).strip()


CLAUDE_MODEL = os.getenv(
    "CLAUDE_MODEL",
    "claude-3-5-sonnet-latest",
).strip()


def get_anthropic_client():

    if not ANTHROPIC_API_KEY:

        raise HTTPException(
            status_code=500,
            detail=(
                "ANTHROPIC_API_KEY غير موجود "
                "في متغيرات البيئة."
            ),
        )


    return anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY
    )


# =========================================================
# CHAT REQUEST
# =========================================================

class ChatRequest(BaseModel):

    store_id: str

    message: str

    sender_id: Optional[str] = None


# =========================================================
# CHAT
# =========================================================

@app.post("/api/chat")
async def chat(

    payload: ChatRequest,

    user: UserModel = Depends(
        require_current_user
    ),

    db: Session = Depends(get_db),

):

    if payload.store_id != user.store_id:

        raise HTTPException(
            status_code=403,
            detail="غير مسموح.",
        )


    if not payload.message.strip():

        raise HTTPException(
            status_code=400,
            detail="الرسالة فارغة.",
        )


    store = (

        db.query(StoreModel)

        .filter(

            StoreModel.id
            == payload.store_id

        )

        .first()
    )


    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود.",
        )


    client = get_anthropic_client()


    system_prompt = f"""

أنت المساعد الذكي الخاص بالمتجر التالي:

اسم المتجر:
{store.store_name}

رابط المتجر:
{store.store_url or "غير محدد"}

تعليمات صاحب المتجر:
{store.agent_notes or "لا توجد تعليمات إضافية."}

بيانات كتالوج المنتجات:
{store.catalog_text or "لا يوجد كتالوج PDF."}

التزم بتعليمات صاحب المتجر.

لا تخترع أسعاراً أو منتجات أو معلومات غير موجودة.

إذا لم تعرف معلومة،
أخبر العميل بوضوح أنك لا تملك المعلومة.

كن مهذباً ومختصراً ومفيداً.

"""


    try:

        message = client.messages.create(

            model=CLAUDE_MODEL,

            max_tokens=1000,

            system=system_prompt,

            messages=[

                {

                    "role":
                        "user",

                    "content":
                        payload.message,

                }

            ],

        )


        bot_response = ""


        for block in message.content:

            if hasattr(
                block,
                "text",
            ):

                bot_response += (
                    block.text
                )


    except Exception as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "تعذر الاتصال بالذكاء الاصطناعي: "
                + str(error)
            ),
        )


    log = ChatLogModel(

        store_id:
            store.id,

        sender_id:
            payload.sender_id,

        user_message:
            payload.message,

        bot_response:
            bot_response,

    )


    try:

        db.add(log)

        db.commit()

    except Exception:

        db.rollback()


    return {

        "success":
            True,

        "response":
            bot_response,

    }


# =========================================================
# EVOLUTION SEND TEXT
# =========================================================

async def evolution_send_text(

    instance_name: str,

    number: str,

    text_message: str,

):

    require_evolution_config()


    payload = {

        "number":
            number,

        "text":
            text_message,

    }


    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.post(

            f"{EVOLUTION_API_URL}/message/sendText/{instance_name}",

            headers=evolution_headers(),

            json=payload,

        )


    return response


# =========================================================
# WEBHOOK MESSAGE EXTRACTION
# =========================================================

def extract_webhook_message(
    payload: dict,
):

    data = payload.get(
        "data",
        payload,
    )


    if not isinstance(
        data,
        dict,
    ):

        return None, None


    key = data.get(
        "key",
        {},
    )


    if not isinstance(
        key,
        dict,
    ):

        key = {}


    sender = key.get(
        "remoteJid"
    )


    message_data = data.get(
        "message",
        {},
    )


    if not isinstance(
        message_data,
        dict,
    ):

        message_data = {}


    incoming_text = ""


    # =====================================================
    # TEXT MESSAGE
    # =====================================================

    conversation = (
        message_data.get(
            "conversation"
        )
    )


    if conversation:

        incoming_text = str(
            conversation
        )


    # =====================================================
    # EXTENDED TEXT
    # =====================================================

    extended = (
        message_data.get(
            "extendedTextMessage"
        )
    )


    if (

        not incoming_text

        and isinstance(
            extended,
            dict,
        )

    ):

        incoming_text = str(

            extended.get(
                "text",
                ""
            )

        )


    # =====================================================
    # IMAGE CAPTION
    # =====================================================

    if not incoming_text:

        image_message = (

            message_data.get(
                "imageMessage"
            )

        )


        if isinstance(
            image_message,
            dict,
        ):

            caption = image_message.get(
                "caption"
            )


            if caption:

                incoming_text = str(
                    caption
                )


    return sender, incoming_text


# =========================================================
# WHATSAPP WEBHOOK
# =========================================================

@app.post("/api/whatsapp/webhook/{store_id}")
async def whatsapp_webhook(

    store_id: str,

    request: Request,

    db: Session = Depends(get_db),

):

    store = (

        db.query(StoreModel)

        .filter(

            StoreModel.id
            == store_id

        )

        .first()
    )


    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود.",
        )


    try:

        payload = await request.json()

    except Exception:

        payload = {}


    sender, incoming_text = (

        extract_webhook_message(
            payload
        )

    )


    if not incoming_text:

        return {

            "success":
                True,

            "message":
                "Webhook received but no text message found.",

        }


    if not sender:

        return {

            "success":
                True,

            "message":
                "Sender not found.",

        }


    # =====================================================
    # IGNORE GROUPS
    # =====================================================

    if "@g.us" in str(sender):

        return {

            "success":
                True,

            "message":
                "Group message ignored.",

        }


    # =====================================================
    # AI
    # =====================================================

    try:

        client = get_anthropic_client()


        system_prompt = f"""

أنت المساعد الذكي لمتجر:

{store.store_name}

رابط المتجر:
{store.store_url or "غير محدد"}

تعليمات صاحب المتجر:
{store.agent_notes or "لا توجد تعليمات."}

كتالوج المنتجات:
{store.catalog_text or "لا يوجد كتالوج."}

التزم بالتعليمات.

لا تخترع معلومات.

إذا لم توجد المعلومة في البيانات المتوفرة،
أخبر العميل بذلك.

كن مهذباً ومختصراً ومفيداً.

"""


        ai_message = client.messages.create(

            model=CLAUDE_MODEL,

            max_tokens=1000,

            system=system_prompt,

            messages=[

                {

                    "role":
                        "user",

                    "content":
                        incoming_text,

                }

            ],

        )


        answer = ""


        for block in ai_message.content:

            if hasattr(
                block,
                "text",
            ):

                answer += block.text


    except Exception as error:

        return {

            "success":
                False,

            "error":
                str(error),

        }


    if not answer.strip():

        return {

            "success":
                False,

            "error":
                "الذكاء الاصطناعي لم يرجع إجابة.",

        }


    # =====================================================
    # INSTANCE
    # =====================================================

    instance_name = (

        "store_"

        + re.sub(

            r"[^a-zA-Z0-9_]",

            "_",

            store.id,

        )

    )


    # =====================================================
    # SEND
    # =====================================================

    try:

        send_response = (

            await evolution_send_text(

                instance_name,

                sender,

                answer,

            )

        )

    except Exception as error:

        return {

            "success":
                False,

            "error":
                str(error),

        }


    # =====================================================
    # LOG
    # =====================================================

    try:

        log = ChatLogModel(

            store_id:
                store.id,

            sender_id:
                sender,

            user_message:
                incoming_text,

            bot_response:
                answer,

        )


        db.add(log)

        db.commit()

    except Exception:

        db.rollback()


    return {

        "success":
            True,

        "response":
            answer,

        "evolution_status":
            send_response.status_code,

    }


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup_event():

    print("=" * 60)

    print(
        "Smart AI Store Assistant"
    )

    print("=" * 60)


    print(

        "Database:",

        (

            "configured"

            if DATABASE_URL

            else "missing"

        )

    )


    print(

        "Evolution API:",

        (

            "configured"

            if EVOLUTION_API_URL
            and EVOLUTION_API_KEY

            else "not configured"

        )

    )


    print(

        "Anthropic:",

        (

            "configured"

            if ANTHROPIC_API_KEY

            else "not configured"

        )

    )


    print("=" * 60)


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    import uvicorn


    port = int(

        os.getenv(

            "PORT",

            "10000",

        )

    )


    uvicorn.run(

        app,

        host="0.0.0.0",

        port=port,

    )
