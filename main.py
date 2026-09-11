import os
import re
import io
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List

import httpx
import anthropic
import pypdf
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, DateTime, ForeignKey, or_
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from supabase import create_client, Client

# =========================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# =========================================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fastsas.db")
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
SESSION_COOKIE = os.getenv("SESSION_COOKIE_NAME", "fastsas_session")
EMAIL_VERIFICATION_REQUIRED = os.getenv("EMAIL_VERIFICATION_REQUIRED", "true").lower() == "true"

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://localhost:8080")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "your-evolution-api-key")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

# إعدادات Supabase (بديل SMTP)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-supabase-project.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_ANON_KEY", ""))

supabase_client: Optional[Client] = (
    create_client(SUPABASE_URL, SUPABASE_KEY)
    if SUPABASE_URL and SUPABASE_KEY
    else None
)

# =========================================================
# DATABASE SETUP
# =========================================================

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class StoreModel(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    store_name = Column(String(255), nullable=False)
    store_url = Column(String(500), nullable=True)
    whatsapp_number = Column(String(50), nullable=True)
    agent_notes = Column(Text, nullable=True)
    catalog_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("UserModel", back_populates="store")
    chat_logs = relationship("ChatLogModel", back_populates="store")


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email_verified = Column(Boolean, default=False)
    verification_code_hash = Column(String(255), nullable=True)
    verification_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("StoreModel", back_populates="users")
    sessions = relationship("SessionModel", back_populates="user")


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(255), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("UserModel", back_populates="sessions")


class ChatLogModel(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    sender_id = Column(String(100), nullable=False)
    user_message = Column(Text, nullable=False)
    bot_response = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("StoreModel", back_populates="chat_logs")


Base.metadata.create_all(bind=engine)

# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title="FastSAS - Smart AI Store Assistant",
    description="نظام إدارة المتاجر المساعد بالذكاء الاصطناعي وربط الواتساب عبر Evolution API و Supabase",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency للحصول على جلسة قاعدة البيانات
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# HELPER FUNCTIONS & SECURITY
# =========================================================

def hash_password(password: str) -> str:
    return hashlib.sha256((password + SECRET_KEY).encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return secrets.compare_digest(hash_password(password), hashed)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_verification_code(user_id: int, code: str) -> str:
    raw = f"{user_id}:{code}:{SECRET_KEY}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return digits.lstrip("0")


def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        extracted = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                extracted.append(text)
        return "\n".join(extracted).strip()
    except Exception as exc:
        print("PDF EXTRACTION ERROR:", repr(exc))
        return ""


def store_to_dict(store: StoreModel) -> dict:
    return {
        "id": store.id,
        "store_name": store.store_name,
        "store_url": store.store_url,
        "whatsapp_number": store.whatsapp_number,
        "agent_notes": store.agent_notes,
        "catalog_text": store.catalog_text,
        "created_at": store.created_at.isoformat() if store.created_at else None,
    }


# =========================================================
# SUPABASE EMAIL SERVICE
# =========================================================

def send_verification_email(email: str, code: str) -> bool:
    """
    إرسال رمز التحقق أو رسالة التفعيل باستخدام Supabase Auth / RPC
    """
    if not supabase_client:
        print("SUPABASE ERROR: لم يتم إعداد Supabase Client بشكل صحيح.")
        return False

    try:
        # المحاولة 1: إعادة إرسال بريد التأكيد عبر Supabase Auth
        supabase_client.auth.resend({
            "type": "signup",
            "email": email,
        })
        return True
    except Exception as exc:
        print("SUPABASE AUTH RESEND NOTICE:", repr(exc))

        # المحاولة 2: إرسال الرمز المخصص عبر دالة RPC في حال استخدام جدول خاص
        try:
            supabase_client.rpc(
                "send_verification_code",
                {"recipient_email": email, "code": code}
            ).execute()
            return True
        except Exception as rpc_exc:
            print("SUPABASE RPC ERROR:", repr(rpc_exc))
            return False


def prepare_verification_code(user: UserModel) -> str:
    code = f"{secrets.randbelow(900000) + 100000}"
    user.verification_code_hash = hash_verification_code(user.id, code)
    user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
    return code


def verification_expired(user: UserModel) -> bool:
    if not user.verification_expires_at:
        return True
    return datetime.utcnow() > user.verification_expires_at


def email_verification_response(email: str, message: str, status_code: int = 200):
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "requires_verification": True,
            "email": email,
            "message": message,
        }
    )


# =========================================================
# SESSION & CURRENT USER DEPENDENCY
# =========================================================

def create_session(db: Session, user: UserModel) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(token)
    expires_at = datetime.utcnow() + timedelta(days=7)

    session_entry = SessionModel(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(session_entry)
    return token


def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        max_age=7 * 24 * 3600,
        samesite="lax",
        secure=False,
    )


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> UserModel:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="غير مصرح: جلسة العمل مفقودة")

    token_hash = hash_session_token(token)
    session_entry = db.query(SessionModel).filter(
        SessionModel.token_hash == token_hash,
        SessionModel.expires_at > datetime.utcnow()
    ).first()

    if not session_entry:
        raise HTTPException(status_code=401, detail="غير مصرح: جلسة العمل غير صالحة أو منتهية")

    user = db.query(UserModel).filter(UserModel.id == session_entry.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")

    return user


# =========================================================
# EVOLUTION API UTILITIES
# =========================================================

def require_evolution_config():
    if not EVOLUTION_API_URL or not EVOLUTION_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="لم يتم ضبط إعدادات Evolution API بنجاح"
        )


def evolution_headers():
    return {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }


def make_instance_name(store_id: int) -> str:
    return f"store_{store_id}"


def safe_json(response: httpx.Response):
    try:
        return response.json()
    except Exception:
        return {"raw_text": response.text}


async def evolution_status(client: httpx.AsyncClient, instance_name: str):
    url = f"{EVOLUTION_API_URL}/instance/connectionState/{instance_name}"
    try:
        res = await client.get(url, headers=evolution_headers(), timeout=10.0)
        data = safe_json(res)
        state = data.get("instance", {}).get("state") or data.get("state") or "unknown"
        return {"status_code": res.status_code, "state": state, "data": data}
    except Exception as exc:
        return {"status_code": 0, "state": "error", "error": str(exc)}


async def evolution_create_instance(client: httpx.AsyncClient, instance_name: str):
    url = f"{EVOLUTION_API_URL}/instance/create"
    payload = {
        "instanceName": instance_name,
        "token": secrets.token_hex(16),
        "qrcode": True,
    }
    try:
        res = await client.post(url, headers=evolution_headers(), json=payload, timeout=15.0)
        return {"status_code": res.status_code, "data": safe_json(res)}
    except Exception as exc:
        return {"status_code": 0, "data": {"error": str(exc)}}


async def evolution_connect(client: httpx.AsyncClient, instance_name: str):
    url = f"{EVOLUTION_API_URL}/instance/connect/{instance_name}"
    try:
        res = await client.get(url, headers=evolution_headers(), timeout=15.0)
        data = safe_json(res)
        qr = data.get("base64") or data.get("code")
        return {"status_code": res.status_code, "qr": qr, "data": data}
    except Exception as exc:
        return {"status_code": 0, "qr": None, "error": str(exc)}


async def evolution_delete_instance(client: httpx.AsyncClient, instance_name: str):
    url = f"{EVOLUTION_API_URL}/instance/delete/{instance_name}"
    try:
        res = await client.delete(url, headers=evolution_headers(), timeout=15.0)
        return {"status_code": res.status_code, "data": safe_json(res)}
    except Exception as exc:
        return {"status_code": 0, "data": {"error": str(exc)}}


async def ensure_instance(client: httpx.AsyncClient, store: StoreModel):
    instance_name = make_instance_name(store.id)
    status_info = await evolution_status(client, instance_name)
    state = (status_info.get("state") or "").lower()

    if state in {"open", "connected", "online"}:
        return {
            "instance_name": instance_name,
            "created": False,
            "create": None,
            "status": status_info,
        }

    create_result = await evolution_create_instance(client, instance_name)
    if create_result["status_code"] in (200, 201):
        status_info = await evolution_status(client, instance_name)

    return {
        "instance_name": instance_name,
        "created": create_result["status_code"] in (200, 201),
        "create": create_result,
        "status": status_info,
    }


async def evolution_send_message(
    client: httpx.AsyncClient,
    instance_name: str,
    recipient_number: str,
    text_content: str,
):
    url = f"{EVOLUTION_API_URL}/message/sendText/{instance_name}"
    payload = {
        "number": recipient_number,
        "options": {
            "delay": 1200,
            "presence": "composing",
            "linkPreview": True,
        },
        "textMessage": {"text": text_content},
    }
    try:
        res = await client.post(url, headers=evolution_headers(), json=payload, timeout=15.0)
        return {"status_code": res.status_code, "data": safe_json(res)}
    except Exception as exc:
        return {"status_code": 0, "data": {"error": str(exc)}}


# =========================================================
# ANTHROPIC CLAUDE AI INTEGRATION
# =========================================================

async def generate_ai_response(
    store: StoreModel,
    user_message: str,
    chat_history: list = None,
) -> str:
    if not ANTHROPIC_API_KEY:
        return "عذراً، الخدمة غير متاحة حالياً بسبب عدم ضبط مفتاح Anthropic API."

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    system_prompt = f"""
أنت مساعد الذكاء الاصطناعي الخاص بمتجر: {store.store_name}.
مهمتك هي الإجابة بأسلوب ودود، احترافي ومباشر على استفسارات العملاء على واتساب.

معلومات المتجر الأساسية:
- اسم المتجر: {store.store_name}
- رابط المتجر: {store.store_url or 'غير متوفر'}
- رقم الواتساب: {store.whatsapp_number or 'غير متوفر'}

تعليمات المساعد وملاحظات الإدارة:
{store.agent_notes or 'تجاوب بأسلوب لبق وساعد العملاء بتقديم المعلومات الصحيحة.'}

كتالوج المنتجات والخدمات:
{store.catalog_text or 'لا يوجد كتالوج تفصيلي مرفق حالياً.'}

قواعد الإجابة:
1. استخدم اللغة العربية الواضحة والبسيطة.
2. اعتمد فقط على البيانات المتاحة في الكتالوج وملاحظات المتجر.
3. إذا سُئلت عن شيء غير موجود بالكتالوج، أبلغ العميل بلطف أن المعلومة غير متوفرة حالياً ووجهه للتواصل مع الإدارة.
4. لا تخترع أسعاراً أو تفاصيل غير موجودة.
"""

    messages = []
    if chat_history:
        for log in chat_history:
            messages.append({"role": "user", "content": log.user_message})
            messages.append({"role": "assistant", "content": log.bot_response})

    messages.append({"role": "user", "content": user_message})

    try:
        response = await client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=800,
            temperature=0.3,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text.strip()
    except Exception as exc:
        print("ANTHROPIC API ERROR:", repr(exc))
        return "عذراً، حدث خطأ أثناء معالجة طلبك. يرجى المحاولة لاحقاً."


# =========================================================
# PYDANTIC SCHEMAS
# =========================================================

class RegisterSchema(BaseModel):
    username: str
    email: str
    password: str
    store_name: str


class VerifyEmailSchema(BaseModel):
    email: str
    code: str


class LoginSchema(BaseModel):
    username_or_email: str
    password: str


class StoreUpdateSchema(BaseModel):
    store_name: Optional[str] = None
    store_url: Optional[str] = None
    whatsapp_number: Optional[str] = None
    agent_notes: Optional[str] = None
    catalog_text: Optional[str] = None


# =========================================================
# AUTHENTICATION ENDPOINTS
# =========================================================

@app.post("/api/auth/register")
async def register(
    data: RegisterSchema,
    db: Session = Depends(get_db),
):
    existing_user = db.query(UserModel).filter(
        or_(UserModel.username == data.username, UserModel.email == data.email)
    ).first()

    if existing_user:
        raise HTTPException(status_code=400, detail="اسم المستخدم أو البريد الإلكتروني مستخدم بالفعل")

    new_store = StoreModel(store_name=data.store_name)
    db.add(new_store)
    db.flush()

    new_user = UserModel(
        store_id=new_store.id,
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        email_verified=not EMAIL_VERIFICATION_REQUIRED,
    )

    verification_code = None
    if EMAIL_VERIFICATION_REQUIRED:
        verification_code = prepare_verification_code(new_user)

    db.add(new_user)
    db.commit()

    if EMAIL_VERIFICATION_REQUIRED and verification_code:
        send_verification_email(data.email, verification_code)
        return email_verification_response(
            email=data.email,
            message="تم إنشاء الحساب بنجاح. تم إرسال رسالة التفعيل عبر Supabase.",
            status_code=201,
        )

    return {"success": True, "message": "تم إنشاء الحساب بنجاح"}


@app.post("/api/auth/verify-email")
async def verify_email(
    data: VerifyEmailSchema,
    db: Session = Depends(get_db),
):
    user = db.query(UserModel).filter(UserModel.email == data.email).first()

    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")

    if user.email_verified:
        return {"success": True, "message": "البريد الإلكتروني مؤكد بالفعل"}

    if verification_expired(user):
        raise HTTPException(status_code=400, detail="انتهت صلاحية رمز التأكيد")

    expected_hash = hash_verification_code(user.id, data.code.strip())
    if not user.verification_code_hash or not secrets.compare_digest(user.verification_code_hash, expected_hash):
        raise HTTPException(status_code=400, detail="رمز التأكيد غير صحيح")

    user.email_verified = True
    user.verification_code_hash = None
    user.verification_expires_at = None

    token = create_session(db, user)
    db.commit()

    response = JSONResponse(content={"success": True, "message": "تم تأكيد البريد الإلكتروني بنجاح"})
    set_session_cookie(response, token)
    return response


@app.post("/api/auth/login")
async def login(
    data: LoginSchema,
    db: Session = Depends(get_db),
):
    identifier = data.username_or_email.strip()
    user = db.query(UserModel).filter(
        or_(UserModel.username == identifier, UserModel.email == identifier)
    ).first()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="اسم المستخدم أو كلمة المرور غير صحيحة")

    if EMAIL_VERIFICATION_REQUIRED and not user.email_verified:
        return email_verification_response(
            email=user.email,
            message="يرجى تأكيد البريد الإلكتروني قبل تسجيل الدخول",
            status_code=403,
        )

    token = create_session(db, user)
    db.commit()

    response = JSONResponse(content={"success": True, "message": "تم تسجيل الدخول بنجاح"})
    set_session_cookie(response, token)
    return response


@app.post("/api/auth/logout")
async def logout(
    request: Request,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session_entry = db.query(SessionModel).filter(
            SessionModel.token_hash == hash_session_token(token)
        ).first()
        if session_entry:
            db.delete(session_entry)
            db.commit()

    response = JSONResponse(content={"success": True, "message": "تم تسجيل الخروج"})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/api/auth/me")
async def get_me(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    store = db.query(StoreModel).filter(StoreModel.id == current_user.store_id).first()
    return {
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "email": current_user.email,
            "email_verified": current_user.email_verified,
        },
        "store": store_to_dict(store) if store else None,
    }


# =========================================================
# STORE MANAGEMENT ENDPOINTS
# =========================================================

@app.get("/api/store")
async def get_store_details(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    store = db.query(StoreModel).filter(StoreModel.id == current_user.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")
    return store_to_dict(store)


@app.put("/api/store")
async def update_store(
    data: StoreUpdateSchema,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    store = db.query(StoreModel).filter(StoreModel.id == current_user.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")

    if data.store_name is not None:
        store.store_name = data.store_name
    if data.store_url is not None:
        store.store_url = data.store_url
    if data.whatsapp_number is not None:
        store.whatsapp_number = normalize_phone(data.whatsapp_number)
    if data.agent_notes is not None:
        store.agent_notes = data.agent_notes
    if data.catalog_text is not None:
        store.catalog_text = data.catalog_text

    db.commit()
    return store_to_dict(store)


@app.post("/api/store/catalog/pdf")
async def upload_pdf_catalog(
    file: UploadFile = File(...),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="يجب رفع ملف بصيغة PDF فقط")

    content = await file.read()
    extracted_text = extract_pdf_text(content)

    if not extracted_text:
        raise HTTPException(status_code=400, detail="عذراً، تعذر استخراج النص من ملف PDF")

    store = db.query(StoreModel).filter(StoreModel.id == current_user.store_id).first()
    store.catalog_text = extracted_text
    db.commit()

    return {
        "success": True,
        "message": "تم استخراج الكتالوج وحفظه بنجاح",
        "length": len(extracted_text),
    }


# =========================================================
# WHATSAPP INTEGRATION ENDPOINTS
# =========================================================

@app.get("/api/whatsapp/connect")
async def whatsapp_connect(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_evolution_config()
    store = db.query(StoreModel).filter(StoreModel.id == current_user.store_id).first()

    async with httpx.AsyncClient() as client:
        ensured = await ensure_instance(client, store)
        instance_name = ensured["instance_name"]
        connect_res = await evolution_connect(client, instance_name)

        return {
            "instance_name": instance_name,
            "status": ensured.get("status"),
            "qr": connect_res.get("qr") or (ensured.get("create") or {}).get("qr"),
        }


@app.get("/api/whatsapp/status")
async def whatsapp_status(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_evolution_config()
    store = db.query(StoreModel).filter(StoreModel.id == current_user.store_id).first()
    instance_name = make_instance_name(store.id)

    async with httpx.AsyncClient() as client:
        return await evolution_status(client, instance_name)


@app.delete("/api/whatsapp/disconnect")
async def whatsapp_disconnect(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_evolution_config()
    store = db.query(StoreModel).filter(StoreModel.id == current_user.store_id).first()
    instance_name = make_instance_name(store.id)

    async with httpx.AsyncClient() as client:
        return await evolution_delete_instance(client, instance_name)


# =========================================================
# EVOLUTION WEBHOOK (INCOMING MESSAGES)
# =========================================================

@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        body = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "invalid_json"}

    instance_name = body.get("instance")
    event_type = body.get("event")

    if event_type != "messages.upsert":
        return {"status": "ignored", "event": event_type}

    data = body.get("data", {})
    key = data.get("key", {})

    if key.get("fromMe", False):
        return {"status": "ignored", "reason": "sent_by_bot"}

    remote_jid = key.get("remoteJid", "")
    if "@g.us" in remote_jid:
        return {"status": "ignored", "reason": "group_message"}

    sender_number = normalize_phone(remote_jid)

    message_content = (
        data.get("message", {}).get("conversation")
        or data.get("message", {}).get("extendedTextMessage", {}).get("text")
    )

    if not message_content or not instance_name:
        return {"status": "ignored", "reason": "no_text_content"}

    stores = db.query(StoreModel).all()
    matched_store = None
    for store in stores:
        if make_instance_name(store.id) == instance_name:
            matched_store = store
            break

    if not matched_store:
        return {"status": "error", "reason": "store_not_found"}

    recent_logs = (
        db.query(ChatLogModel)
        .filter(ChatLogModel.store_id == matched_store.id, ChatLogModel.sender_id == sender_number)
        .order_by(ChatLogModel.created_at.desc())
        .limit(3)
        .all()
    )
    recent_logs.reverse()

    ai_reply = await generate_ai_response(
        store=matched_store,
        user_message=message_content,
        chat_history=recent_logs,
    )

    async with httpx.AsyncClient() as client:
        await evolution_send_message(
            client=client,
            instance_name=instance_name,
            recipient_number=sender_number,
            text_content=ai_reply,
        )

    log_entry = ChatLogModel(
        store_id=matched_store.id,
        sender_id=sender_number,
        user_message=message_content,
        bot_response=ai_reply,
    )
    db.add(log_entry)
    db.commit()

    return {"status": "success", "reply": ai_reply}


# =========================================================
# ROOT & HEALTH CHECK
# =========================================================

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "Smart AI Store Assistant API",
        "version": "2.1.0",
        "supabase_connected": supabase_client is not None,
    }
