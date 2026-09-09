```python
import os
import uuid
from datetime import datetime
from typing import Optional

import httpx
import anthropic
import pypdf

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    Session,
    relationship,
    sessionmaker,
    declarative_base,
)


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./saas_stores.db")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

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
# VALIDATION
# ============================================================

print("=" * 60)
print("AI STORE ASSISTANT - STARTING")
print("=" * 60)

print(
    f"ANTHROPIC_API_KEY: "
    f"{'LOADED' if ANTHROPIC_API_KEY else 'MISSING'}"
)

print(
    f"EVOLUTION_API_URL: "
    f"{EVOLUTION_API_URL if EVOLUTION_API_URL else 'MISSING'}"
)

print(
    f"EVOLUTION_GLOBAL_KEY: "
    f"{'LOADED' if EVOLUTION_GLOBAL_KEY else 'MISSING'}"
)

print(
    f"WEBHOOK_BASE_URL: "
    f"{WEBHOOK_BASE_URL if WEBHOOK_BASE_URL else 'MISSING'}"
)

print(f"ANTHROPIC_MODEL: {ANTHROPIC_MODEL}")
print(f"DATABASE_URL: {DATABASE_URL}")
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
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


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
        cascade="all, delete-orphan",
    )


class ChatLogModel(Base):
    __tablename__ = "chat_logs"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    store_id = Column(
        String,
        ForeignKey("stores.id")
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


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# ============================================================
# ANTHROPIC CLIENT
# ============================================================

claude_client = None

if ANTHROPIC_API_KEY:
    claude_client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY
    )


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="AI Store Assistant SaaS Platform",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# MODELS
# ============================================================

class ChatRequest(BaseModel):
    store_id: str
    message: str
    sender_id: Optional[str] = "preview_user"


# ============================================================
# PDF
# ============================================================

def extract_pdf_text(file_bytes) -> str:

    try:
        reader = pypdf.PdfReader(file_bytes)

        text = ""

        for page in reader.pages:

            extracted = page.extract_text()

            if extracted:
                text += extracted + "\n"

        return text.strip()

    except Exception as e:

        print(
            f"❌ Error reading PDF: {e}"
        )

        return ""


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "evolution_configured": bool(
            EVOLUTION_API_URL
        ),
        "evolution_key_configured": bool(
            EVOLUTION_GLOBAL_KEY
        ),
        "anthropic_configured": bool(
            ANTHROPIC_API_KEY
        ),
        "webhook_configured": bool(
            WEBHOOK_BASE_URL
        ),
    }


# ============================================================
# HOME
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def read_index():

    if os.path.exists("index.html"):

        with open(
            "index.html",
            "r",
            encoding="utf-8"
        ) as f:

            return f.read()

    return """
    <html>
        <head>
            <meta charset="UTF-8">
            <title>AI Store Assistant</title>
        </head>

        <body>
            <h1>مرحباً بك في منصة المساعد الذكي للمتاجر</h1>
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

    db: Session = Depends(get_db),

):

    # --------------------------------------------------------
    # Validate Evolution configuration
    # --------------------------------------------------------

    if whatsapp_number:

        if not EVOLUTION_API_URL:

            raise HTTPException(
                status_code=500,
                detail="EVOLUTION_API_URL غير مضبوط في Environment Variables"
            )

        if not EVOLUTION_GLOBAL_KEY:

            raise HTTPException(
                status_code=500,
                detail="EVOLUTION_GLOBAL_KEY غير مضبوط في Environment Variables"
            )

        if not WEBHOOK_BASE_URL:

            raise HTTPException(
                status_code=500,
                detail="WEBHOOK_BASE_URL غير مضبوط في Environment Variables"
            )


    # --------------------------------------------------------
    # PDF
    # --------------------------------------------------------

    catalog_content = ""

    if pdf_file:

        filename = pdf_file.filename or ""

        if filename.lower().endswith(".pdf"):

            catalog_content = extract_pdf_text(
                pdf_file.file
            )


    # --------------------------------------------------------
    # Create Store
    # --------------------------------------------------------

    new_store = StoreModel(

        store_name=store_name,

        store_url=store_url,

        whatsapp_number=whatsapp_number,

        agent_notes=agent_notes,

        catalog_text=catalog_content,

    )

    db.add(new_store)

    db.commit()

    db.refresh(new_store)


    qr_code_data = None


    # ========================================================
    # EVOLUTION API
    # ========================================================

    if whatsapp_number:

        clean_phone = (
            whatsapp_number
            .replace("+", "")
            .replace(" ", "")
            .replace("-", "")
            .strip()
        )

        instance_name = f"store_{clean_phone}"

        headers = {

            "apikey": EVOLUTION_GLOBAL_KEY,

            "Content-Type":
                "application/json",

        }


        async with httpx.AsyncClient(
            follow_redirects=True
        ) as client:

            # ------------------------------------------------
            # CREATE INSTANCE
            # ------------------------------------------------

            try:

                create_payload = {

                    "instanceName":
                        instance_name,

                    "qrcode":
                        True,

                    "integration":
                        "WHATSAPP-BAILEYS",

                }


                create_url = (
                    f"{EVOLUTION_API_URL}"
                    f"/instance/create"
                )


                print(
                    f"📱 Creating Evolution instance: "
                    f"{instance_name}"
                )


                res = await client.post(

                    create_url,

                    json=create_payload,

                    headers=headers,

                    timeout=30.0,

                )


                print(
                    f"Evolution create status: "
                    f"{res.status_code}"
                )


                if res.status_code in [200, 201]:

                    try:

                        response_data = res.json()

                        qrcode_object = (
                            response_data.get(
                                "qrcode"
                            )
                            or {}
                        )

                        qr_code_data = (
                            qrcode_object.get(
                                "base64"
                            )
                        )

                        # Some Evolution versions
                        # may return QR differently.

                        if not qr_code_data:

                            qr_code_data = (
                                response_data.get(
                                    "base64"
                                )
                            )

                    except Exception as e:

                        print(
                            f"⚠️ QR response parse error: "
                            f"{e}"
                        )

                else:

                    print(
                        "❌ Evolution instance "
                        "creation failed:"
                    )

                    print(
                        res.text[:2000]
                    )


            except Exception as e:

                print(
                    f"❌ Evolution API "
                    f"Connection Error: {e}"
                )


            # ------------------------------------------------
            # WEBHOOK
            # ------------------------------------------------

            try:

                webhook_url = (
                    f"{WEBHOOK_BASE_URL}"
                    f"/api/whatsapp/webhook/"
                    f"{new_store.id}"
                )


                webhook_payload = {

                    "webhook": {

                        "enabled":
                            True,

                        "url":
                            webhook_url,

                        "byEvents":
                            False,

                        "events": [

                            "MESSAGES_UPSERT"

                        ],

                    }

                }


                webhook_endpoint = (

                    f"{EVOLUTION_API_URL}"
                    f"/webhook/set/"
                    f"{instance_name}"

                )


                print(
                    f"🔗 Setting webhook: "
                    f"{webhook_url}"
                )


                webhook_res = await client.post(

                    webhook_endpoint,

                    json=webhook_payload,

                    headers=headers,

                    timeout=30.0,

                )


                print(
                    f"Evolution webhook status: "
                    f"{webhook_res.status_code}"
                )


                if webhook_res.status_code >= 300:

                    print(
                        webhook_res.text[:2000]
                    )


            except Exception as e:

                print(
                    f"❌ Webhook configuration "
                    f"error: {e}"
                )


    # ========================================================
    # RESPONSE
    # ========================================================

    widget_code = ""

    if WEBHOOK_BASE_URL:

        widget_code = (
            f'<script '
            f'src="{WEBHOOK_BASE_URL}/widget.js" '
            f'data-store-id="{new_store.id}">'
            f'</script>'
        )


    return {

        "status":
            "success",

        "message":
            "تم تسجيل المتجر بنجاح",

        "store_id":
            new_store.id,

        "qr_code":
            qr_code_data,

        "widget_code":
            widget_code,

    }


# ============================================================
# WHATSAPP WEBHOOK
# ============================================================

@app.post(
    "/api/whatsapp/webhook/{store_id}"
)
async def whatsapp_evolution_webhook(

    store_id: str,

    request: Request,

    db: Session = Depends(get_db),

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
            "status":
                "store_not_found"
        }


    try:

        data = await request.json()

        msg_data = (
            data.get("data")
            or {}
        )


        # ----------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------

        if "message" not in msg_data:

            return {
                "status":
                    "ignored"
            }


        key = (
            msg_data.get("key")
            or {}
        )


        sender_remote_jid = (
            key.get("remoteJid")
            or ""
        )


        is_from_me = (
            key.get("fromMe")
            or False
        )


        # Ignore own messages
        # and WhatsApp groups.

        if (
            is_from_me
            or "g.us" in sender_remote_jid
        ):

            return {
                "status":
                    "ignored"
            }


        # ----------------------------------------------------
        # MESSAGE CONTENT
        # ----------------------------------------------------

        msg_body = (
            msg_data.get("message")
            or {}
        )


        message_content = (

            msg_body.get(
                "conversation"
            )

            or msg_body.get(
                "extendedTextMessage",
                {}
            ).get("text")

            or ""

        )


        if (
            not message_content
            or not sender_remote_jid
        ):

            return {
                "status":
                    "ignored"
            }


        # ----------------------------------------------------
        # ANTHROPIC CHECK
        # ----------------------------------------------------

        if not claude_client:

            print(
                "❌ ANTHROPIC_API_KEY "
                "is not configured"
            )

            return {
                "status":
                    "ai_not_configured"
            }


        # ----------------------------------------------------
        # CHAT HISTORY
        # ----------------------------------------------------

        previous_logs = (

            db.query(ChatLogModel)

            .filter(

                ChatLogModel.store_id
                == store.id,

                ChatLogModel.sender_id
                == sender_remote_jid,

            )

            .order_by(
                ChatLogModel.created_at.desc()
            )

            .limit(5)

            .all()

        )


        previous_logs.reverse()


        chat_history = []


        for log in previous_logs:

            if log.user_message:

                chat_history.append({

                    "role":
                        "user",

                    "content":
                        log.user_message,

                })


            if log.bot_response:

                chat_history.append({

                    "role":
                        "assistant",

                    "content":
                        log.bot_response,

                })


        chat_history.append({

            "role":
                "user",

            "content":
                message_content,

        })


        # ----------------------------------------------------
        # SYSTEM PROMPT
        # ----------------------------------------------------

        system_prompt = f"""

أنت مساعد مبيعات ذكي يعمل لصالح متجر
'{store.store_name}'
عبر الواتساب.

تعليمات المتجر:

{store.agent_notes or 'كن ودوداً وخادماً للعملاء.'}

كتالوج المنتجات والأسعار:

{store.catalog_text or 'لا يوجد كتالوج مرفق.'}

قواعد الإجابة:

- جاوب باللغة العربية.
- كن مختصراً وواضحاً.
- لا تخترع أسعاراً أو منتجات غير موجودة في الكتالوج.
- إذا لم تجد الإجابة في الكتالوج، أخبر العميل بذلك بوضوح.
- اجعل الرد مناسباً لمحادثات WhatsApp.
"""


        # ----------------------------------------------------
        # CLAUDE
        # ----------------------------------------------------

        print(
            f"🤖 Sending message to Claude "
            f"for store: {store.id}"
        )


        response = claude_client.messages.create(

            model=ANTHROPIC_MODEL,

            max_tokens=500,

            system=system_prompt,

            messages=chat_history,

        )


        reply_text = (
            response.content[0].text
            if response.content
            else "عذراً، لم أتمكن من إنشاء الرد."
        )


        # ----------------------------------------------------
        # SAVE LOG
        # ----------------------------------------------------

        db.add(

            ChatLogModel(

                store_id:
                    store.id,

                sender_id:
                    sender_remote_jid,

                user_message:
                    message_content,

                bot_response:
                    reply_text,

            )

        )


        db.commit()


        # ----------------------------------------------------
        # SEND REPLY THROUGH EVOLUTION
        # ----------------------------------------------------

        if not store.whatsapp_number:

            print(
                "❌ Store has no WhatsApp number"
            )

            return {
                "status":
                    "no_whatsapp_number"
            }


        if not EVOLUTION_API_URL:

            print(
                "❌ EVOLUTION_API_URL missing"
            )

            return {
                "status":
                    "evolution_not_configured"
            }


        if not EVOLUTION_GLOBAL_KEY:

            print(
                "❌ EVOLUTION_GLOBAL_KEY missing"
            )

            return {
                "status":
                    "evolution_key_missing"
            }


        clean_phone = (

            store.whatsapp_number

            .replace("+", "")

            .replace(" ", "")

            .replace("-", "")

            .strip()

        )


        instance_name = (
            f"store_{clean_phone}"
        )


        send_url = (

            f"{EVOLUTION_API_URL}"
            f"/message/sendText/"
            f"{instance_name}"

        )


        headers = {

            "apikey":
                EVOLUTION_GLOBAL_KEY,

            "Content-Type":
                "application/json",

        }


        target_number = (
            sender_remote_jid
            .split("@")[0]
        )


        payload = {

            "number":
                target_number,

            "text":
                reply_text,

        }


        async with httpx.AsyncClient(
            follow_redirects=True
        ) as client:

            send_res = await client.post(

                send_url,

                json=payload,

                headers=headers,

                timeout=30.0,

            )


            print(
                f"Evolution send message status: "
                f"{send_res.status_code}"
            )


            if send_res.status_code >= 300:

                print(
                    "❌ Evolution send error:"
                )

                print(
                    send_res.text[:2000]
                )


    except Exception as e:

        print(
            f"❌ Webhook Processing Error: "
            f"{e}"
        )


    return {
        "status":
            "success"
    }


# ============================================================
# OPTIONAL PREVIEW CHAT
# ============================================================

@app.post("/api/chat")
async def chat_preview(

    request: ChatRequest,

    db: Session = Depends(get_db),

):

    store = (

        db.query(StoreModel)

        .filter(
            StoreModel.id
            == request.store_id
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

أنت مساعد مبيعات ذكي لمتجر
'{store.store_name}'.

تعليمات المتجر:

{store.agent_notes or 'كن ودوداً وخادماً للعملاء.'}

الكتالوج:

{store.catalog_text or 'لا يوجد كتالوج.'}

أجب باختصار ووضوح باللغة العربية.
"""


    response = claude_client.messages.create(

        model=ANTHROPIC_MODEL,

        max_tokens=500,

        system=system_prompt,

        messages=[

            {

                "role":
                    "user",

                "content":
                    request.message,

            }

        ],

    )


    reply_text = (

        response.content[0].text

        if response.content

        else "لم أتمكن من إنشاء الرد."

    )


    db.add(

        ChatLogModel(

            store_id:
                store.id,

            sender_id:
                request.sender_id
                or "preview_user",

            user_message:
                request.message,

            bot_response:
                reply_text,

        )

    )


    db.commit()


    return {

        "status":
            "success",

        "reply":
            reply_text,

    }
```
