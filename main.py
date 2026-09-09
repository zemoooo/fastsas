import os
import uuid
from datetime import datetime
from typing import Optional

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

print("=" * 60)
print("AI STORE ASSISTANT STARTING")
print("=" * 60)

print(
    "ANTHROPIC_API_KEY:",
    "LOADED" if ANTHROPIC_API_KEY else "MISSING"
)

print(
    "ANTHROPIC_MODEL:",
    ANTHROPIC_MODEL
)

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

print(
    "DATABASE_URL:",
    DATABASE_URL
)

print("=" * 60)


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
    connect_args=connect_args
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


# ============================================================
# STORE
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
# CHAT LOG
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
# CREATE DATABASE TABLES
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
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ============================================================
# MODELS
# ============================================================

class ChatRequest(BaseModel):
    store_id: str
    message: str
    sender_id: Optional[str] = "preview_user"


# ============================================================
# HELPERS
# ============================================================

def clean_phone_number(phone: str) -> str:
    return (
        phone
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )


def evolution_headers():
    return {
        "apikey": EVOLUTION_GLOBAL_KEY,
        "Content-Type": "application/json"
    }


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
        <title>AI Store Assistant</title>
    </head>
    <body>
        <h1>منصة المساعد الذكي للمتاجر</h1>
        <p>الخدمة تعمل بنجاح.</p>
    </body>
    </html>
    """


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

    # --------------------------------------------------------
    # Validate Evolution
    # --------------------------------------------------------

    if whatsapp_number:

        if not EVOLUTION_API_URL:
            raise HTTPException(
                status_code=500,
                detail="EVOLUTION_API_URL غير مضبوط"
            )

        if not EVOLUTION_GLOBAL_KEY:
            raise HTTPException(
                status_code=500,
                detail="EVOLUTION_GLOBAL_KEY غير مضبوط"
            )

        if not WEBHOOK_BASE_URL:
            raise HTTPException(
                status_code=500,
                detail="WEBHOOK_BASE_URL غير مضبوط"
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
    # Save Store
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

    # ========================================================
    # EVOLUTION
    # ========================================================

    if whatsapp_number:

        clean_phone = clean_phone_number(
            whatsapp_number
        )

        instance_name = (
            "store_" + clean_phone
        )

        headers = evolution_headers()

        async with httpx.AsyncClient(
            follow_redirects=True
        ) as client:

            # ------------------------------------------------
            # CREATE INSTANCE
            # ------------------------------------------------

            create_url = (
                EVOLUTION_API_URL +
                "/instance/create"
            )

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

                response = await client.post(
                    create_url,
                    json=create_payload,
                    headers=headers,
                    timeout=30
                )

                print(
                    "Evolution create status:",
                    response.status_code
                )

                if response.status_code in (200, 201):

                    try:

                        result = response.json()

                        qrcode_data = (
                            result.get("qrcode") or {}
                        )

                        qr_code = (
                            qrcode_data.get("base64")
                        )

                        if not qr_code:
                            qr_code = result.get(
                                "base64"
                            )

                        if qr_code:
                            print(
                                "QR code received"
                            )
                        else:
                            print(
                                "Instance created but QR code missing"
                            )

                    except Exception as e:

                        print(
                            "QR parse error:",
                            str(e)
                        )

                else:

                    print(
                        "Evolution create failed:"
                    )

                    print(
                        response.text[:3000]
                    )

            except Exception as e:

                print(
                    "Evolution connection error:",
                    str(e)
                )

            # ------------------------------------------------
            # WEBHOOK
            # ------------------------------------------------

            webhook_url = (
                WEBHOOK_BASE_URL +
                "/api/whatsapp/webhook/" +
                store.id
            )

            webhook_url_api = (
                EVOLUTION_API_URL +
                "/webhook/set/" +
                instance_name
            )

            webhook_payload = {
                "webhook": {
                    "enabled": True,
                    "url": webhook_url,
                    "byEvents": False,
                    "events": [
                        "MESSAGES_UPSERT"
                    ]
                }
            }

            try:

                print(
                    "Setting webhook:",
                    webhook_url
                )

                webhook_response = await client.post(
                    webhook_url_api,
                    json=webhook_payload,
                    headers=headers,
                    timeout=30
                )

                print(
                    "Webhook status:",
                    webhook_response.status_code
                )

                if webhook_response.status_code >= 300:

                    print(
                        webhook_response.text[:3000]
                    )

                else:

                    print(
                        "Webhook configured successfully"
                    )

            except Exception as e:

                print(
                    "Webhook configuration error:",
                    str(e)
                )

    # ========================================================
    # WIDGET
    # ========================================================

    widget_code = ""

    if WEBHOOK_BASE_URL:

        widget_code = (
            '<script '
            'src="' +
            WEBHOOK_BASE_URL +
            '/widget.js" '
            'data-store-id="' +
            store.id +
            '"></script>'
        )

    # ========================================================
    # RESPONSE
    # ========================================================

    return {
        "status": "success",
        "message": "تم تسجيل المتجر بنجاح",
        "store_id": store.id,
        "instance_name": instance_name,
        "qr_code": qr_code,
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
        .filter(
            StoreModel.id == store_id
        )
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

        msg_data = (
            data.get("data") or {}
        )

        # ----------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------

        message_object = (
            msg_data.get("message")
        )

        if not message_object:
            return {
                "status": "ignored"
            }

        # ----------------------------------------------------
        # KEY
        # ----------------------------------------------------

        key = (
            msg_data.get("key") or {}
        )

        sender_jid = (
            key.get("remoteJid") or ""
        )

        from_me = bool(
            key.get("fromMe", False)
        )

        # Ignore bot messages
        if from_me:
            return {
                "status": "ignored"
            }

        # Ignore groups
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

        message_text = (
            message_object.get(
                "conversation"
            )
            or message_object.get(
                "extendedTextMessage",
                {}
            ).get("text")
            or message_object.get(
                "imageMessage",
                {}
            ).get("caption")
            or ""
        )

        message_text = message_text.strip()

        if not message_text:
            return {
                "status": "ignored"
            }

        # ----------------------------------------------------
        # CLAUDE
        # ----------------------------------------------------

        if not claude_client:

            print(
                "Anthropic is not configured"
            )

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
            .limit(5)
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
        # SYSTEM PROMPT
        # ----------------------------------------------------

        system_prompt = f"""
أنت مساعد مبيعات ذكي لمتجر "{store.store_name}" عبر WhatsApp.

تعليمات المتجر:
{store.agent_notes or "كن ودوداً ومحترفاً وخادماً للعملاء."}

كتالوج المنتجات والأسعار:
{store.catalog_text or "لا يوجد كتالوج متوفر حالياً."}

قواعد مهمة:
- أجب باللغة العربية.
- كن مختصراً وواضحاً.
- كن ودوداً ومحترفاً.
- لا تخترع منتجات أو أسعاراً.
- لا تخترع معلومات غير موجودة في الكتالوج.
- إذا لم تجد الإجابة في المعلومات المتوفرة، أخبر العميل بوضوح.
- اجعل الرد مناسباً للواتساب.
"""

        # ----------------------------------------------------
        # CLAUDE REQUEST
        # ----------------------------------------------------

        print(
            "Sending customer message to Claude..."
        )

        response = claude_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=500,
            system=system_prompt,
            messages=messages
        )

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
        # EVOLUTION CHECK
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

        # ----------------------------------------------------
        # INSTANCE
        # ----------------------------------------------------

        clean_phone = clean_phone_number(
            store.whatsapp_number
        )

        instance_name = (
            "store_" + clean_phone
        )

        # ----------------------------------------------------
        # TARGET NUMBER
        # ----------------------------------------------------

        target_number = (
            sender_jid.split("@")[0]
        )

        # ----------------------------------------------------
        # SEND MESSAGE
        # ----------------------------------------------------

        send_url = (
            EVOLUTION_API_URL +
            "/message/sendText/" +
            instance_name
        )

        payload = {
            "number": target_number,
            "text": reply_text
        }

        try:

            async with httpx.AsyncClient(
                follow_redirects=True
            ) as client:

                send_response = await client.post(
                    send_url,
                    json=payload,
                    headers=evolution_headers(),
                    timeout=30
                )

            print(
                "Evolution send status:",
                send_response.status_code
            )

            if send_response.status_code >= 300:

                print(
                    "Evolution send error:"
                )

                print(
                    send_response.text[:3000]
                )

                return {
                    "status": "send_failed",
                    "reply": reply_text
                }

        except Exception as e:

            print(
                "Evolution send connection error:",
                str(e)
            )

            return {
                "status": "send_failed",
                "reply": reply_text
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
- لا تخترع أسعاراً أو منتجات.
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
                    "content": request.message
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
    # SAVE PREVIEW
    # --------------------------------------------------------

    try:

        db.add(
            ChatLogModel(
                store_id=store.id,
                sender_id=request.sender_id or "preview_user",
                user_message=request.message,
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
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup_event():

    print("=" * 60)
    print("AI STORE ASSISTANT IS READY")
    print("=" * 60)
    print("Health endpoint: /health")
    print("Register endpoint: /api/register-store")
    print("Chat endpoint: /api/chat")
    print("WhatsApp webhook: /api/whatsapp/webhook/{store_id}")
    print("=" * 60)
