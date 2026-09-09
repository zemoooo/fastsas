import os
import uuid
import base64
from datetime import datetime
from typing import Optional, Any

import anthropic
import httpx
import pypdf

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./saas_stores.db"
).strip()

ANTHROPIC_API_KEY = os.getenv(
    "ANTHROPIC_API_KEY",
    ""
).strip()

ANTHROPIC_MODEL = os.getenv(
    "ANTHROPIC_MODEL",
    "claude-sonnet-4-5"
).strip()

EVOLUTION_API_URL = os.getenv(
    "EVOLUTION_API_URL",
    ""
).strip().rstrip("/")

EVOLUTION_GLOBAL_KEY = os.getenv(
    "EVOLUTION_GLOBAL_KEY",
    ""
).strip()

WEBHOOK_BASE_URL = os.getenv(
    "WEBHOOK_BASE_URL",
    ""
).strip().rstrip("/")


# ============================================================
# STARTUP LOG
# ============================================================

print("=" * 70)
print("AI STORE ASSISTANT STARTING")
print("=" * 70)

print(
    "ANTHROPIC_API_KEY:",
    "LOADED" if ANTHROPIC_API_KEY else "MISSING"
)

print("ANTHROPIC_MODEL:", ANTHROPIC_MODEL)

print(
    "EVOLUTION_API_URL:",
    EVOLUTION_API_URL or "MISSING"
)

print(
    "EVOLUTION_GLOBAL_KEY:",
    "LOADED" if EVOLUTION_GLOBAL_KEY else "MISSING"
)

print(
    "WEBHOOK_BASE_URL:",
    WEBHOOK_BASE_URL or "MISSING"
)

print("DATABASE_URL:", DATABASE_URL)

print("=" * 70)


# ============================================================
# DATABASE
# ============================================================

connect_args = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args = {
        "check_same_thread": False
    }

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


# ============================================================
# STORE MODEL
# ============================================================

class StoreModel(Base):
    __tablename__ = "stores"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    store_name = Column(
        String,
        nullable=False
    )

    store_url = Column(
        String,
        nullable=True
    )

    whatsapp_number = Column(
        String,
        nullable=True
    )

    agent_notes = Column(
        Text,
        nullable=True
    )

    catalog_text = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    logs = relationship(
        "ChatLogModel",
        back_populates="store",
        cascade="all, delete-orphan"
    )


# ============================================================
# CHAT LOG MODEL
# ============================================================

class ChatLogModel(Base):
    __tablename__ = "chat_logs"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    store_id = Column(
        String,
        ForeignKey("stores.id"),
        nullable=False
    )

    sender_id = Column(
        String,
        default="default_user"
    )

    user_message = Column(
        Text
    )

    bot_response = Column(
        Text
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    store = relationship(
        "StoreModel",
        back_populates="logs"
    )


# ============================================================
# CREATE DATABASE
# ============================================================

try:
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully")
except Exception as e:
    print("Database initialization error:", str(e))


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# ============================================================
# ANTHROPIC
# ============================================================

claude_client = None

if ANTHROPIC_API_KEY:

    try:
        claude_client = anthropic.Anthropic(
            api_key=ANTHROPIC_API_KEY
        )

        print("Anthropic client initialized")

    except Exception as e:

        print(
            "Anthropic initialization error:",
            str(e)
        )


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="AI Store Assistant SaaS Platform",
    version="2.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ============================================================
# CHAT REQUEST
# ============================================================

class ChatRequest(BaseModel):

    store_id: str

    message: str

    sender_id: Optional[str] = "preview_user"


# ============================================================
# HELPERS
# ============================================================

def clean_phone_number(phone: str) -> str:

    if not phone:
        return ""

    return (
        phone
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace(".", "")
        .strip()
    )


def make_instance_name(phone: str) -> str:

    clean_phone = clean_phone_number(phone)

    return f"store_{clean_phone}"


def evolution_headers():

    return {
        "apikey": EVOLUTION_GLOBAL_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }


def safe_json(response: httpx.Response) -> dict:

    try:

        data = response.json()

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


def normalize_qr(value: Any) -> Optional[str]:

    if value is None:
        return None

    if isinstance(value, str):

        value = value.strip()

        if not value:
            return None

        # Already a data URL
        if value.startswith("data:image"):
            return value

        # Base64 PNG/JPG without prefix
        return "data:image/png;base64," + value

    return None


def extract_qr_code(data: Any) -> Optional[str]:

    """
    Supports multiple Evolution API QR response formats.
    """

    if not data:
        return None

    if isinstance(data, dict):

        # ----------------------------------------------------
        # qrcode object
        # ----------------------------------------------------

        qrcode = data.get("qrcode")

        if isinstance(qrcode, dict):

            for key in (
                "base64",
                "code",
                "qrcode"
            ):

                value = qrcode.get(key)

                result = normalize_qr(value)

                if result:
                    return result

        else:

            result = normalize_qr(qrcode)

            if result:
                return result

        # ----------------------------------------------------
        # direct base64
        # ----------------------------------------------------

        for key in (
            "base64",
            "qr",
            "qrCode",
            "code"
        ):

            value = data.get(key)

            result = normalize_qr(value)

            if result:
                return result

        # ----------------------------------------------------
        # nested data
        # ----------------------------------------------------

        nested = data.get("data")

        if nested:

            result = extract_qr_code(nested)

            if result:
                return result

        # ----------------------------------------------------
        # nested response
        # ----------------------------------------------------

        nested = data.get("response")

        if nested:

            result = extract_qr_code(nested)

            if result:
                return result

    return None


def extract_instance_status(data: Any) -> str:

    if not isinstance(data, dict):
        return "unknown"

    instance = data.get("instance")

    if isinstance(instance, dict):

        status = (
            instance.get("status")
            or instance.get("state")
            or instance.get("connectionStatus")
        )

        if status:
            return str(status)

    return str(
        data.get("status")
        or data.get("state")
        or "unknown"
    )


# ============================================================
# PDF
# ============================================================

def extract_pdf_text(file_object) -> str:

    try:

        reader = pypdf.PdfReader(file_object)

        parts = []

        for page in reader.pages:

            text = page.extract_text()

            if text:
                parts.append(text)

        return "\n".join(parts).strip()

    except Exception as e:

        print(
            "PDF extraction error:",
            str(e)
        )

        return ""


# ============================================================
# EVOLUTION REQUEST
# ============================================================

async def evolution_request(
    method: str,
    path: str,
    json_data: Optional[dict] = None,
    timeout: int = 30
):

    if not EVOLUTION_API_URL:
        raise RuntimeError(
            "EVOLUTION_API_URL غير مضبوط"
        )

    if not EVOLUTION_GLOBAL_KEY:
        raise RuntimeError(
            "EVOLUTION_GLOBAL_KEY غير مضبوط"
        )

    url = (
        EVOLUTION_API_URL.rstrip("/")
        + "/"
        + path.lstrip("/")
    )

    print("Evolution request:", method, url)

    async with httpx.AsyncClient(
        follow_redirects=True
    ) as client:

        response = await client.request(
            method=method.upper(),
            url=url,
            json=json_data,
            headers=evolution_headers(),
            timeout=timeout
        )

    print(
        "Evolution status:",
        response.status_code
    )

    if response.text:
        print(
            "Evolution response:",
            response.text[:4000]
        )

    return response


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "service": "AI Store Assistant",
        "database_configured": bool(DATABASE_URL),
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "evolution_configured": bool(EVOLUTION_API_URL),
        "evolution_key_configured": bool(EVOLUTION_GLOBAL_KEY),
        "webhook_configured": bool(WEBHOOK_BASE_URL)
    }


# ============================================================
# HOME
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home():

    if os.path.exists("index.html"):

        try:

            with open(
                "index.html",
                "r",
                encoding="utf-8"
            ) as file:

                return file.read()

        except Exception as e:

            print(
                "index.html error:",
                str(e)
            )

    return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>AI Store Assistant</title>
    </head>
    <body>
        <h1>منصة المساعد الذكي للمتاجر</h1>
        <p>الخدمة تعمل بنجاح.</p>
    </body>
    </html>
    """


# ============================================================
# GET STORED INSTANCE INFORMATION
# ============================================================

@app.get("/api/whatsapp/status/{store_id}")
async def whatsapp_status(
    store_id: str,
    db: Session = Depends(get_db)
):

    store = (
        db.query(StoreModel)
        .filter(StoreModel.id == store_id)
        .first()
    )

    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود"
        )

    if not store.whatsapp_number:

        return {
            "status": "no_whatsapp"
        }

    instance_name = make_instance_name(
        store.whatsapp_number
    )

    try:

        response = await evolution_request(
            "GET",
            f"/instance/connectionState/{instance_name}"
        )

        data = safe_json(response)

        return {
            "status": "success"
            if response.status_code < 300
            else "failed",
            "instance_name": instance_name,
            "connection_status": extract_instance_status(data),
            "response": data
        }

    except Exception as e:

        return {
            "status": "failed",
            "instance_name": instance_name,
            "error": str(e)
        }


# ============================================================
# GET QR
# ============================================================

@app.get("/api/whatsapp/qr/{store_id}")
async def whatsapp_qr(
    store_id: str,
    db: Session = Depends(get_db)
):

    store = (
        db.query(StoreModel)
        .filter(StoreModel.id == store_id)
        .first()
    )

    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود"
        )

    if not store.whatsapp_number:

        raise HTTPException(
            status_code=400,
            detail="لا يوجد رقم WhatsApp للمتجر"
        )

    instance_name = make_instance_name(
        store.whatsapp_number
    )

    # --------------------------------------------------------
    # Try current Evolution QR endpoint
    # --------------------------------------------------------

    try:

        response = await evolution_request(
            "GET",
            f"/instance/qr/{instance_name}"
        )

        data = safe_json(response)

        qr_code = extract_qr_code(data)

        if qr_code:

            return {
                "status": "success",
                "instance_name": instance_name,
                "qr_code": qr_code,
                "response": data
            }

    except Exception as e:

        print(
            "QR endpoint attempt 1 failed:",
            str(e)
        )

    # --------------------------------------------------------
    # Try alternate endpoint used by some Evolution builds
    # --------------------------------------------------------

    try:

        response = await evolution_request(
            "GET",
            f"/instance/qr?instanceName={instance_name}"
        )

        data = safe_json(response)

        qr_code = extract_qr_code(data)

        if qr_code:

            return {
                "status": "success",
                "instance_name": instance_name,
                "qr_code": qr_code,
                "response": data
            }

    except Exception as e:

        print(
            "QR endpoint attempt 2 failed:",
            str(e)
        )

    return {
        "status": "qr_not_available",
        "instance_name": instance_name,
        "message": (
            "لم يتم الحصول على QR Code من Evolution API. "
            "تحقق من اتصال Evolution وRedis."
        )
    }


# ============================================================
# RECONNECT / NEW QR
# ============================================================

@app.post("/api/whatsapp/connect/{store_id}")
async def whatsapp_connect(
    store_id: str,
    db: Session = Depends(get_db)
):

    store = (
        db.query(StoreModel)
        .filter(StoreModel.id == store_id)
        .first()
    )

    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود"
        )

    if not store.whatsapp_number:

        raise HTTPException(
            status_code=400,
            detail="رقم WhatsApp غير موجود"
        )

    instance_name = make_instance_name(
        store.whatsapp_number
    )

    # --------------------------------------------------------
    # First check existing connection
    # --------------------------------------------------------

    try:

        state_response = await evolution_request(
            "GET",
            f"/instance/connectionState/{instance_name}"
        )

        state_data = safe_json(state_response)

        state = extract_instance_status(
            state_data
        ).lower()

        if state in (
            "open",
            "connected"
        ):

            return {
                "status": "connected",
                "instance_name": instance_name,
                "connection_status": state
            }

    except Exception as e:

        print(
            "Connection state check error:",
            str(e)
        )

    # --------------------------------------------------------
    # Try connect endpoint
    # --------------------------------------------------------

    connect_attempts = [
        (
            f"/instance/connect/{instance_name}",
            {}
        ),
        (
            f"/instance/connect",
            {
                "instanceName": instance_name
            }
        )
    ]

    for path, payload in connect_attempts:

        try:

            response = await evolution_request(
                "GET" if not payload else "POST",
                path,
                payload if payload else None
            )

            data = safe_json(response)

            qr_code = extract_qr_code(data)

            if qr_code:

                return {
                    "status": "success",
                    "instance_name": instance_name,
                    "qr_code": qr_code,
                    "response": data
                }

        except Exception as e:

            print(
                "Connect attempt failed:",
                path,
                str(e)
            )

    # --------------------------------------------------------
    # If no QR yet, ask QR endpoint
    # --------------------------------------------------------

    try:

        qr_response = await evolution_request(
            "GET",
            f"/instance/qr/{instance_name}"
        )

        qr_data = safe_json(qr_response)

        qr_code = extract_qr_code(qr_data)

        if qr_code:

            return {
                "status": "success",
                "instance_name": instance_name,
                "qr_code": qr_code,
                "response": qr_data
            }

    except Exception as e:

        print(
            "Final QR request failed:",
            str(e)
        )

    return {
        "status": "qr_not_available",
        "instance_name": instance_name,
        "message": (
            "Evolution API لم ترجع QR Code. "
            "راجع سجلات Evolution API وRedis."
        )
    }


# ============================================================
# REGISTER STORE
# ============================================================

@app.post("/api/register-store")
async def register_store(
    store_name: str = Form(...),
    store_url: Optional[str] = Form(None),
    whatsapp_number: Optional[str] = Form(None),
    agent_notes: Optional[str] = Form(None),
    pdf_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):

    store_name = store_name.strip()

    if not store_name:

        raise HTTPException(
            status_code=400,
            detail="اسم المتجر مطلوب"
        )

    whatsapp_number = (
        whatsapp_number.strip()
        if whatsapp_number
        else None
    )

    # --------------------------------------------------------
    # Validate Evolution
    # --------------------------------------------------------

    if whatsapp_number:

        if not EVOLUTION_API_URL:

            raise HTTPException(
                status_code=500,
                detail="EVOLUTION_API_URL غير مضبوط في Render"
            )

        if not EVOLUTION_GLOBAL_KEY:

            raise HTTPException(
                status_code=500,
                detail="EVOLUTION_GLOBAL_KEY غير مضبوط في Render"
            )

        if not WEBHOOK_BASE_URL:

            raise HTTPException(
                status_code=500,
                detail="WEBHOOK_BASE_URL غير مضبوط في Render"
            )

    # --------------------------------------------------------
    # PDF
    # --------------------------------------------------------

    catalog_text = ""

    if pdf_file:

        filename = pdf_file.filename or ""

        if filename.lower().endswith(".pdf"):

            catalog_text = extract_pdf_text(
                pdf_file.file
            )

    # --------------------------------------------------------
    # Create store
    # --------------------------------------------------------

    store = StoreModel(
        store_name=store_name,
        store_url=store_url,
        whatsapp_number=whatsapp_number,
        agent_notes=agent_notes,
        catalog_text=catalog_text
    )

    try:

        db.add(store)

        db.commit()

        db.refresh(store)

    except Exception as e:

        db.rollback()

        print(
            "Store database error:",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="فشل حفظ بيانات المتجر"
        )

    qr_code = None
    instance_name = None
    evolution_response = None

    # ========================================================
    # EVOLUTION
    # ========================================================

    if whatsapp_number:

        instance_name = make_instance_name(
            whatsapp_number
        )

        webhook_url = (
            WEBHOOK_BASE_URL
            + "/api/whatsapp/webhook/"
            + store.id
        )

        # ----------------------------------------------------
        # CREATE INSTANCE
        # ----------------------------------------------------

        create_payload = {
            "instanceName": instance_name,
            "qrcode": True,
            "integration": "WHATSAPP-BAILEYS"
        }

        try:

            print(
                "Creating Evolution instance:",
                instance_name
            )

            response = await evolution_request(
                "POST",
                "/instance/create",
                create_payload
            )

            evolution_response = safe_json(
                response
            )

            # ------------------------------------------------
            # Existing instance
            # ------------------------------------------------

            if response.status_code >= 300:

                print(
                    "Evolution create failed:",
                    response.text[:4000]
                )

                # Try getting QR from existing instance
                try:

                    qr_response = await evolution_request(
                        "GET",
                        f"/instance/qr/{instance_name}"
                    )

                    qr_data = safe_json(
                        qr_response
                    )

                    qr_code = extract_qr_code(
                        qr_data
                    )

                except Exception as qr_error:

                    print(
                        "Existing QR lookup failed:",
                        str(qr_error)
                    )

            else:

                qr_code = extract_qr_code(
                    evolution_response
                )

                print(
                    "QR after create:",
                    "RECEIVED"
                    if qr_code
                    else "NOT RECEIVED"
                )

        except Exception as e:

            print(
                "Evolution create exception:",
                str(e)
            )

        # ----------------------------------------------------
        # WEBHOOK
        # ----------------------------------------------------

        webhook_payload = {
            "webhook": {
                "enabled": True,
                "url": webhook_url,
                "byEvents": False,
                "base64": False,
                "events": [
                    "MESSAGES_UPSERT",
                    "CONNECTION_UPDATE"
                ]
            }
        }

        webhook_paths = [
            f"/webhook/set/{instance_name}",
            f"/webhook/set/{instance_name}"
        ]

        webhook_configured = False

        for webhook_path in webhook_paths:

            try:

                print(
                    "Setting Evolution webhook:",
                    webhook_url
                )

                webhook_response = await evolution_request(
                    "POST",
                    webhook_path,
                    webhook_payload
                )

                if webhook_response.status_code < 300:

                    webhook_configured = True

                    print(
                        "Webhook configured successfully"
                    )

                    break

                print(
                    "Webhook configuration failed:",
                    webhook_response.text[:3000]
                )

            except Exception as e:

                print(
                    "Webhook configuration exception:",
                    str(e)
                )

        if not webhook_configured:

            print(
                "WARNING: Evolution webhook was not configured"
            )

        # ----------------------------------------------------
        # If QR missing, try QR endpoint
        # ----------------------------------------------------

        if not qr_code:

            try:

                qr_response = await evolution_request(
                    "GET",
                    f"/instance/qr/{instance_name}"
                )

                qr_data = safe_json(
                    qr_response
                )

                qr_code = extract_qr_code(
                    qr_data
                )

            except Exception as e:

                print(
                    "QR fallback error:",
                    str(e)
                )

        # ----------------------------------------------------
        # Second QR format
        # ----------------------------------------------------

        if not qr_code:

            try:

                qr_response = await evolution_request(
                    "GET",
                    f"/instance/qr?instanceName={instance_name}"
                )

                qr_data = safe_json(
                    qr_response
                )

                qr_code = extract_qr_code(
                    qr_data
                )

            except Exception as e:

                print(
                    "QR alternate fallback error:",
                    str(e)
                )

    # ========================================================
    # WIDGET
    # ========================================================

    widget_code = ""

    if WEBHOOK_BASE_URL:

        widget_code = (
            '<script '
            'src="'
            + WEBHOOK_BASE_URL
            + '/widget.js" '
            'data-store-id="'
            + store.id
            + '"></script>'
        )

    # ========================================================
    # RESPONSE
    # ========================================================

    return {
        "status": "success",
        "message": (
            "تم تسجيل المتجر بنجاح"
            if not whatsapp_number
            else (
                "تم تسجيل المتجر وإنشاء اتصال WhatsApp"
                if qr_code
                else
                "تم تسجيل المتجر، لكن QR Code لم يصل من Evolution API"
            )
        ),
        "store_id": store.id,
        "instance_name": instance_name,
        "qr_code": qr_code,
        "qr_available": bool(qr_code),
        "widget_code": widget_code
    }


# ============================================================
# WHATSAPP WEBHOOK
# ============================================================

@app.post("/api/whatsapp/webhook/{store_id}")
async def whatsapp_webhook(
    store_id: str,
    request: Request,
    db: Session = Depends(get_db)
):

    store = (
        db.query(StoreModel)
        .filter(StoreModel.id == store_id)
        .first()
    )

    if not store:

        return {
            "status": "store_not_found"
        }

    try:

        data = await request.json()

        print(
            "WhatsApp webhook received:",
            store_id
        )

        print(
            "Webhook event:",
            data.get("event")
        )

        # ----------------------------------------------------
        # Evolution normally puts payload in data
        # ----------------------------------------------------

        msg_data = (
            data.get("data")
            or {}
        )

        if not isinstance(msg_data, dict):

            return {
                "status": "ignored"
            }

        # ----------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------

        message_object = (
            msg_data.get("message")
            or {}
        )

        if not message_object:

            return {
                "status": "ignored"
            }

        # ----------------------------------------------------
        # KEY
        # ----------------------------------------------------

        key = (
            msg_data.get("key")
            or {}
        )

        sender_jid = (
            key.get("remoteJid")
            or key.get("senderPn")
            or ""
        )

        from_me = bool(
            key.get("fromMe", False)
        )

        if from_me:

            return {
                "status": "ignored"
            }

        if "g.us" in sender_jid:

            return {
                "status": "ignored"
            }

        if not sender_jid:

            return {
                "status": "ignored"
            }

        # ----------------------------------------------------
        # TEXT
        # ----------------------------------------------------

        extended_text = (
            message_object.get(
                "extendedTextMessage"
            )
            or {}
        )

        image_message = (
            message_object.get(
                "imageMessage"
            )
            or {}
        )

        message_text = (
            message_object.get("conversation")
            or extended_text.get("text")
            or image_message.get("caption")
            or ""
        )

        message_text = str(
            message_text
        ).strip()

        if not message_text:

            return {
                "status": "ignored"
            }

        # ----------------------------------------------------
        # CLAUDE
        # ----------------------------------------------------

        if not claude_client:

            return {
                "status": "ai_not_configured"
            }

        # ----------------------------------------------------
        # HISTORY
        # ----------------------------------------------------

        previous_logs = (
            db.query(ChatLogModel)
            .filter(
                ChatLogModel.store_id == store.id,
                ChatLogModel.sender_id == sender_jid
            )
            .order_by(
                ChatLogModel.created_at.desc()
            )
            .limit(10)
            .all()
        )

        previous_logs.reverse()

        messages = []

        for log in previous_logs:

            if log.user_message:

                messages.append({
                    "role": "user",
                    "content": log.user_message
                })

            if log.bot_response:

                messages.append({
                    "role": "assistant",
                    "content": log.bot_response
                })

        messages.append({
            "role": "user",
            "content": message_text
        })

        # ----------------------------------------------------
        # SYSTEM
        # ----------------------------------------------------

        system_prompt = f"""
أنت مساعد مبيعات ذكي لمتجر "{store.store_name}" عبر WhatsApp.

تعليمات المتجر:
{store.agent_notes or "كن ودوداً ومحترفاً وخادماً للعملاء."}

كتالوج المنتجات والأسعار:
{store.catalog_text or "لا يوجد كتالوج متوفر حالياً."}

القواعد:
- أجب باللغة العربية.
- كن مختصراً وواضحاً.
- كن ودوداً ومحترفاً.
- لا تخترع منتجات.
- لا تخترع أسعاراً.
- لا تخترع معلومات غير موجودة.
- إذا لم تجد الإجابة في المعلومات المتوفرة، أخبر العميل بذلك.
- اجعل الرد مناسباً للواتساب.
"""

        # ----------------------------------------------------
        # CLAUDE
        # ----------------------------------------------------

        try:

            response = claude_client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=500,
                system=system_prompt,
                messages=messages
            )

        except Exception as e:

            print(
                "Claude webhook error:",
                str(e)
            )

            return {
                "status": "ai_error",
                "error": str(e)
            }

        reply_text = ""

        if response.content:

            for item in response.content:

                if hasattr(item, "text"):

                    reply_text += item.text

        reply_text = reply_text.strip()

        if not reply_text:

            reply_text = (
                "عذراً، لم أتمكن من إنشاء الرد حالياً."
            )

        # ----------------------------------------------------
        # SAVE LOG
        # ----------------------------------------------------

        try:

            db.add(
                ChatLogModel(
                    store_id=store.id,
                    sender_id=sender_jid,
                    user_message=message_text,
                    bot_response=reply_text
                )
            )

            db.commit()

        except Exception as e:

            db.rollback()

            print(
                "Chat log error:",
                str(e)
            )

        # ----------------------------------------------------
        # EVOLUTION
        # ----------------------------------------------------

        if not store.whatsapp_number:

            return {
                "status": "no_whatsapp_number",
                "reply": reply_text
            }

        if not EVOLUTION_API_URL:

            return {
                "status": "evolution_not_configured",
                "reply": reply_text
            }

        if not EVOLUTION_GLOBAL_KEY:

            return {
                "status": "evolution_key_missing",
                "reply": reply_text
            }

        instance_name = make_instance_name(
            store.whatsapp_number
        )

        target_number = (
            sender_jid
            .split("@")[0]
            .split(":")[0]
        )

        # ----------------------------------------------------
        # SEND TEXT
        # ----------------------------------------------------

        send_url = (
            "/message/sendText/"
            + instance_name
        )

        payload = {
            "number": target_number,
            "text": reply_text
        }

        try:

            send_response = await evolution_request(
                "POST",
                send_url,
                payload
            )

            if send_response.status_code >= 300:

                return {
                    "status": "send_failed",
                    "reply": reply_text,
                    "evolution_status": send_response.status_code,
                    "evolution_response": send_response.text[:2000]
                }

        except Exception as e:

            print(
                "Evolution send error:",
                str(e)
            )

            return {
                "status": "send_failed",
                "reply": reply_text,
                "error": str(e)
            }

        print(
            "WhatsApp reply sent successfully"
        )

        return {
            "status": "success",
            "reply": reply_text
        }

    except Exception as e:

        print(
            "Webhook processing error:",
            str(e)
        )

        return {
            "status": "error",
            "error": str(e)
        }


# ============================================================
# PREVIEW CHAT
# ============================================================

@app.post("/api/chat")
async def chat_preview(
    request: ChatRequest,
    db: Session = Depends(get_db)
):

    message = request.message.strip()

    if not message:

        raise HTTPException(
            status_code=400,
            detail="الرسالة فارغة"
        )

    store = (
        db.query(StoreModel)
        .filter(
            StoreModel.id == request.store_id
        )
        .first()
    )

    if not store:

        raise HTTPException(
            status_code=404,
            detail="المتجر غير موجود"
        )

    if not claude_client:

        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY غير مضبوط"
        )

    system_prompt = f"""
أنت مساعد مبيعات ذكي لمتجر "{store.store_name}".

تعليمات المتجر:
{store.agent_notes or "كن ودوداً ومحترفاً."}

الكتالوج:
{store.catalog_text or "لا يوجد كتالوج."}

القواعد:
- أجب باللغة العربية.
- كن مختصراً وواضحاً.
- لا تخترع أسعاراً.
- لا تخترع منتجات.
- استخدم المعلومات الموجودة في الكتالوج.
- إذا لم تجد الإجابة أخبر العميل بذلك.
"""

    try:

        response = claude_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=500,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": message
                }
            ]
        )

    except Exception as e:

        print(
            "Claude preview error:",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="حدث خطأ أثناء الاتصال بـ Claude"
        )

    reply_text = ""

    if response.content:

        for item in response.content:

            if hasattr(item, "text"):

                reply_text += item.text

    reply_text = reply_text.strip()

    if not reply_text:

        reply_text = (
            "لم أتمكن من إنشاء الرد."
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    try:

        db.add(
            ChatLogModel(
                store_id=store.id,
                sender_id=request.sender_id or "preview_user",
                user_message=message,
                bot_response=reply_text
            )
        )

        db.commit()

    except Exception as e:

        db.rollback()

        print(
            "Preview log error:",
            str(e)
        )

    return {
        "status": "success",
        "reply": reply_text
    }


# ============================================================
# WIDGET
# ============================================================

@app.get("/widget.js")
async def widget():

    return HTMLResponse(
        content="""
(function () {

    const script =
        document.currentScript;

    if (!script) return;

    const storeId =
        script.getAttribute("data-store-id");

    if (!storeId) {
        console.error(
            "AI Store Widget: data-store-id missing"
        );
        return;
    }

    if (
        document.getElementById(
            "ai-store-chat-widget"
        )
    ) {
        return;
    }

    const API_BASE =
        new URL(
            script.src
        ).origin;

    const root =
        document.createElement("div");

    root.id =
        "ai-store-chat-widget";

    root.innerHTML = `
        <div id="ai-chat-button"
             style="
             position:fixed;
             bottom:20px;
             right:20px;
             width:58px;
             height:58px;
             border-radius:50%;
             background:#111827;
             color:white;
             display:flex;
             align-items:center;
             justify-content:center;
             cursor:pointer;
             z-index:999999;
             font-size:25px;
             box-shadow:0 5px 20px rgba(0,0,0,.25);
             ">
            💬
        </div>

        <div id="ai-chat-box"
             style="
             display:none;
             position:fixed;
             bottom:90px;
             right:20px;
             width:340px;
             max-width:calc(100vw - 40px);
             height:480px;
             background:white;
             border-radius:16px;
             overflow:hidden;
             box-shadow:0 10px 40px rgba(0,0,0,.25);
             z-index:999999;
             font-family:Arial,sans-serif;
             direction:rtl;
             ">

            <div style="
                background:#111827;
                color:white;
                padding:16px;
                font-weight:bold;
                ">
                المساعد الذكي
            </div>

            <div id="ai-chat-messages"
                 style="
                 height:370px;
                 overflow-y:auto;
                 padding:12px;
                 background:#f3f4f6;
                 "></div>

            <div style="
                 display:flex;
                 gap:6px;
                 padding:10px;
                 border-top:1px solid #ddd;
                 ">

                <input
                    id="ai-chat-input"
                    type="text"
                    placeholder="اكتب رسالتك..."
                    style="
                    flex:1;
                    border:1px solid #ddd;
                    border-radius:10px;
                    padding:10px;
                    outline:none;
                    "
                />

                <button
                    id="ai-chat-send"
                    style="
                    border:0;
                    border-radius:10px;
                    padding:10px 14px;
                    background:#111827;
                    color:white;
                    cursor:pointer;
                    ">
                    إرسال
                </button>

            </div>
        </div>
    `;

    document.body.appendChild(root);

    const button =
        document.getElementById(
            "ai-chat-button"
        );

    const box =
        document.getElementById(
            "ai-chat-box"
        );

    const input =
        document.getElementById(
            "ai-chat-input"
        );

    const send =
        document.getElementById(
            "ai-chat-send"
        );

    const messages =
        document.getElementById(
            "ai-chat-messages"
        );

    button.onclick = function () {

        box.style.display =
            box.style.display === "none"
                ? "block"
                : "none";

    };

    function addMessage(
        text,
        type
    ) {

        const div =
            document.createElement("div");

        div.textContent =
            text;

        div.style.margin =
            "8px 0";

        div.style.padding =
            "9px 11px";

        div.style.borderRadius =
            "10px";

        div.style.maxWidth =
            "85%";

        div.style.whiteSpace =
            "pre-wrap";

        if (type === "user") {

            div.style.marginRight =
                "auto";

            div.style.background =
                "#dbeafe";

        } else {

            div.style.marginLeft =
                "auto";

            div.style.background =
                "#ffffff";
        }

        messages.appendChild(div);

        messages.scrollTop =
            messages.scrollHeight;
    }

    async function sendMessage() {

        const text =
            input.value.trim();

        if (!text) return;

        addMessage(
            text,
            "user"
        );

        input.value = "";

        send.disabled = true;

        try {

            const response =
                await fetch(
                    API_BASE +
                    "/api/chat",
                    {
                        method:"POST",
                        headers:{
                            "Content-Type":
                                "application/json"
                        },
                        body:JSON.stringify({
                            store_id:
                                String(storeId),
                            message:
                                text,
                            sender_id:
                                "widget_user"
                        })
                    }
                );

            const data =
                await response.json();

            if (!response.ok) {

                throw new Error(
                    data.detail ||
                    "حدث خطأ"
                );
            }

            addMessage(
                data.reply ||
                data.response ||
                "لم يصل رد.",
                "bot"
            );

        } catch (error) {

            addMessage(
                "تعذر الاتصال بالمساعد حالياً.",
                "bot"
            );

            console.error(
                "AI Store Widget:",
                error
            );

        } finally {

            send.disabled = false;
            input.focus();
        }
    }

    send.onclick =
        sendMessage;

    input.addEventListener(
        "keydown",
        function (event) {

            if (
                event.key === "Enter"
            ) {
                sendMessage();
            }

        }
    );

})();
        """,
        media_type="application/javascript"
    )


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup_event():

    print("=" * 70)
    print("AI STORE ASSISTANT IS READY")
    print("=" * 70)
    print("Health: /health")
    print("Register: /api/register-store")
    print("Chat: /api/chat")
    print("QR: /api/whatsapp/qr/{store_id}")
    print("Connect: /api/whatsapp/connect/{store_id}")
    print("Status: /api/whatsapp/status/{store_id}")
    print("Webhook: /api/whatsapp/webhook/{store_id}")
    print("Widget: /widget.js")
    print("=" * 70)
