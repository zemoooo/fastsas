import os
import io
import re
import uuid
import hashlib
import secrets
import asyncio

from datetime import datetime, timedelta, timezone
from typing import Optional, Any

import anthropic
import httpx
from pypdf import PdfReader
from bs4 import BeautifulSoup

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

ANTHROPIC_API_KEY = (
    os.getenv("ANTHROPIC_API_KEY", "").strip()
)

ANTHROPIC_MODEL = (
    os.getenv(
        "ANTHROPIC_MODEL",
        os.getenv(
            "CLAUDE_MODEL",
            "claude-3-5-sonnet-latest",
        ),
    ).strip()
)


# =========================================================
# SUPABASE
# =========================================================

SUPABASE_URL = (
    os.getenv("SUPABASE_URL", "")
    .strip()
    .rstrip("/")
)

SUPABASE_ANON_KEY = (
    os.getenv("SUPABASE_ANON_KEY", "")
    .strip()
    or os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    .strip()
)

# مهم جدًا:
# هذا المفتاح يبقى على Backend فقط.
SUPABASE_SERVICE_ROLE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    .strip()
)

SUPABASE_AUTH_TIMEOUT = 30.0

OTP_MIN_DIGITS = 6
OTP_MAX_DIGITS = 8

OTP_COOLDOWN_SECONDS = 60


# =========================================================
# EVOLUTION API
# =========================================================

EVOLUTION_API_URL = (
    os.getenv("EVOLUTION_API_URL", "")
    .strip()
    .rstrip("/")
)

EVOLUTION_GLOBAL_KEY = (
    os.getenv("EVOLUTION_GLOBAL_KEY", "")
    .strip()
)

if not EVOLUTION_GLOBAL_KEY:
    EVOLUTION_GLOBAL_KEY = (
        os.getenv("EVOLUTION_API_KEY", "")
        .strip()
    )

if not EVOLUTION_GLOBAL_KEY:
    EVOLUTION_GLOBAL_KEY = (
        os.getenv("AUTHENTICATION_API_KEY", "")
        .strip()
    )


# =========================================================
# WEBHOOK
# =========================================================

WEBHOOK_BASE_URL = (
    os.getenv(
        "WEBHOOK_BASE_URL",
        os.getenv("RENDER_EXTERNAL_URL", ""),
    )
    .strip()
    .rstrip("/")
)


# =========================================================
# FRONTEND
# =========================================================

FRONTEND_URL = (
    os.getenv("FRONTEND_URL", "")
    .strip()
    .rstrip("/")
)

CORS_ORIGINS = (
    [FRONTEND_URL]
    if FRONTEND_URL
    else ["*"]
)


# =========================================================
# DATABASE
# =========================================================

if DATABASE_URL.startswith("sqlite"):

    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "check_same_thread": False,
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
    version="3.0.0",
)

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

    email_verified = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    password_hash = Column(
        String(500),
        nullable=False,
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
# DATABASE CREATE
# =========================================================

try:
    Base.metadata.create_all(bind=engine)
except Exception as exc:
    print(f"DATABASE CREATE ERROR: {exc}")


# =========================================================
# WEB SCRAPING TOOL FOR ANTHROPIC CLAUDE
# =========================================================

async def execute_web_scraping(url: str) -> str:
    """
    يقوم بجلب المحتوى النصي لأي رابط موقع وتنظيفه بالكامل من وسوم البرمجة
    لتقديمه بشكل مبسط ومفهوم إلى نموذج Claude.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                return f"خطأ: تعذر كشط الموقع بنجاح. رمز الاستجابة: {response.status_code}"
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # تنظيف عناصر الصفحة غير الضرورية
            for element in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                element.extract()
                
            # تجميع النصوص وتصفية الفراغات والأسطر التكرارية
            text_content = soup.get_text(separator="\n")
            lines = [line.strip() for line in text_content.splitlines() if line.strip()]
            clean_text = "\n".join(lines)
            
            # اقتطاع المحتوى لحماية نافذة سياق المحادثة (الحد الأقصى 6000 حرف)
            return clean_text[:6000]
            
    except Exception as e:
        return f"فشل كشط الموقع بسبب حدوث خطأ تقني: {str(e)}"

# هيكل الأداة الخاص بنظام الأنثروبيك الرسمي
CLAUDE_SCRAPE_TOOL = {
    "name": "scrape_website_content",
