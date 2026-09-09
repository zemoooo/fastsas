import os
import uuid
from datetime import datetime
from typing import Optional, Any

import anthropic
import httpx
import pypdf
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker


# =========================================================
# Environment Variables
# =========================================================

DATABASE_URL = os.getenv("DATABASE_CONNECTION_URI", "").strip()
if not DATABASE_URL:
    DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./saas_stores.db"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine_kwargs = {}
if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5").strip()

EVOLUTION_API_URL = os.getenv(
    "EVOLUTION_API_URL",
    "https://evolution-api-render-1-nsvq.onrender.com",
).strip().rstrip("/")

EVOLUTION_GLOBAL_KEY = os.getenv("EVOLUTION_GLOBAL_KEY", "").strip()

WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")

if ANTHROPIC_API_KEY:
    claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
else:
    claude_client = None


# =========================================================
# Database Models
# =========================================================

class StoreModel(Base):
    __tablename__ = "stores"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    store_name = Column(String, nullable=False)
    store_url = Column(String, nullable=True)
    whatsapp_number = Column(String, nullable=True)
    agent_notes = Column(Text, nullable=True)
    catalog_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    logs = relationship(
        "ChatLogModel",
        back_populates="store",
        cascade="all, delete-orphan",
    )


class ChatLogModel(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String, ForeignKey("stores.id"))
    sender_id = Column(String, default="default_user")
    user_message = Column(Text)
    bot_response = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("StoreModel", back_populates="logs")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# FastAPI
# =========================================================

app = FastAPI(title="AI Store Assistant SaaS Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    store_id: str
    message: str
    sender_id: Optional[str] = "preview_user"


# =========================================================
# Helpers
# =========================================================

def normalize_phone(value: str) -> str:
    if not value:
        return ""
    return (
        value.replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .strip()
    )


def make_instance_name(phone: str) -> str:
    clean = normalize_phone(phone)
    return f"store_{clean}"


def extract_pdf_text(file_obj) -> str:
    try:
        reader = pypdf.PdfReader(file_obj)
        parts = []

        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                parts.append(extracted)

        return "\n".join(parts).strip()

    except Exception as exc:
        print(f"PDF extraction error: {exc}")
        return ""


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


def normalize_qr(value: Any) -> Optional[str]:
    if not value:
        return None

    if isinstance(value, dict):
        value = first_value(
            value.get("base64"),
            value.get("base64Image"),
            value.get("qrcode"),
            value.get("code"),
        )

    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    if value.startswith("data:image"):
        return value

    # Evolution normally returns the QR as base64.
    if value.startswith("http://") or value.startswith("https://"):
        return value

    # Remove possible surrounding whitespace only.
    return f"data:image/png;base64,{value}"


def extract_qr_code(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None

    candidates = [
        data.get("qrcode"),
        data.get("qrCode"),
        data.get("base64"),
        data.get("base64Image"),
        data.get("code"),
        data.get("instance", {}).get("qrcode") if isinstance(data.get("instance"), dict) else None,
        data.get("instance", {}).get("qrCode") if isinstance(data.get("instance"), dict) else None,
    ]

    for candidate in candidates:
        qr = normalize_qr(candidate)
        if qr:
            return qr

    return None


def extract_instance_status(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None

    values = [
        data.get("state"),
        data.get("status"),
        data.get("connectionStatus"),
    ]

    instance = data.get("instance")
    if isinstance(instance, dict):
        values.extend([
            instance.get("state"),
            instance.get("status"),
            instance.get("connectionStatus"),
        ])

    for value in values:
        if value:
            return str(value)

    return None


def require_evolution_config():
    if not EVOLUTION_API_URL:
        raise HTTPException(
            status_code=500,
            detail="EVOLUTION_API_URL غير مضبوط في Render.",
        )

    if not EVOLUTION_GLOBAL_KEY:
        raise HTTPException(
            status_code=500,
            detail="EVOLUTION_GLOBAL_KEY غير مضبوط في Render.",
        )


def require_claude():
    if not claude_client:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY غير مضبوط في Render.",
        )


async def evolution_connect(
    client: httpx.AsyncClient,
    instance_name: str,
    headers: dict,
):
    """
    Ask Evolution API to connect the instance and return the QR if available.
    """
    url = f"{EVOLUTION_API_URL}/instance/connect/{instance_name}"

    try:
        response = await client.get(url, headers=headers)
        data = safe_json(response)

        print(
            f"Evolution connect: status={response.status_code}, "
            f"response={data}"
        )

        qr = extract_qr_code(data)

        return {
            "status_code": response.status_code,
            "data": data,
            "qr": qr,
        }

    except Exception as exc:
        print(f"Evolution connect exception: {exc}")
        return {
            "status_code": 0,
            "data": {"error": str(exc)},
            "qr": None,
        }


async def evolution_create(
    client: httpx.AsyncClient,
    instance_name: str,
    headers: dict,
):
    payload = {
        "instanceName": instance_name,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }

    url = f"{EVOLUTION_API_URL}/instance/create"

    try:
        response = await client.post(
            url,
            json=payload,
            headers=headers,
        )

        data = safe_json(response)

        print(
            f"Evolution create: status={response.status_code}, "
            f"response={data}"
        )

        return {
            "status_code": response.status_code,
            "data": data,
            "qr": extract_qr_code(data),
        }

    except Exception as exc:
        print(f"Evolution create exception: {exc}")
        return {
            "status_code": 0,
            "data": {"error": str(exc)},
            "qr": None,
        }


async def configure_webhook(
    client: httpx.AsyncClient,
    instance_name: str,
    store_id: str,
    headers: dict,
):
    if not WEBHOOK_BASE_URL:
        return {
            "status_code": 0,
            "data": {
                "warning": "WEBHOOK_BASE_URL غير مضبوط، تم تخطي Webhook."
            },
        }

    webhook_url = (
        f"{WEBHOOK_BASE_URL}/api/whatsapp/webhook/{store_id}"
    )

    payload = {
        "webhook": {
            "enabled": True,
            "url": webhook_url,
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
        response = await client.post(
            url,
            json=payload,
            headers=headers,
        )

        data = safe_json(response)

        print(
            f"Evolution webhook: status={response.status_code}, "
            f"response={data}"
        )

        return {
            "status_code": response.status_code,
            "data": data,
        }

    except Exception as exc:
        print(f"Webhook configuration exception: {exc}")
        return {
            "status_code": 0,
            "data": {"error": str(exc)},
        }


async def get_qr_with_retry(
    client: httpx.AsyncClient,
    instance_name: str,
    headers: dict,
    attempts: int = 8,
    delay_seconds: float = 1.5,
):
    """
    QR may not be present immediately after instance creation.
    Retry the connect endpoint a few times.
    """
    import asyncio

    last_result = None

    for attempt in range(1, attempts + 1):
        result = await evolution_connect(
            client,
            instance_name,
            headers,
        )

        last_result = result

        if result.get("qr"):
            print(f"QR received on attempt {attempt}")
            return result

        status = extract_instance_status(result.get("data"))

        if status and status.lower() in {
            "open",
            "connected",
            "online",
        }:
            return result

        if attempt < attempts:
            await asyncio.sleep(delay_seconds)

    return last_result or {
        "status_code": 0,
        "data": {"error": "لم تتم إعادة نتيجة Evolution API."},
        "qr": None,
    }


# =========================================================
# Basic Routes
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as file:
            return file.read()

    return "<h1>مرحباً بك في منصة المساعد الذكي للمتاجر</h1>"


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "evolution_api_url": EVOLUTION_API_URL,
        "evolution_key_configured": bool(EVOLUTION_GLOBAL_KEY),
        "claude_key_configured": bool(ANTHROPIC_API_KEY),
        "webhook_base_url_configured": bool(WEBHOOK_BASE_URL),
    }


@app.get("/widget.js", response_class=FileResponse)
async def get_widget_script():
    if os.path.exists("widget.js"):
        return FileResponse(
            "widget.js",
            media_type="application/javascript",
        )

    raise HTTPException(
        status_code=404,
        detail="widget.js not found",
    )


# =========================================================
# Store Registration + WhatsApp QR
# =========================================================

@app.post("/api/register-store")
async def register_store(
    store_name: str = Form(...),
    store_url: Optional[str] = Form(None),
    whatsapp_number: Optional[str] = Form(None),
    agent_notes: Optional[str] = Form(None),
    pdf_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    catalog_content = ""

    if pdf_file and pdf_file.filename:
        if pdf_file.filename.lower().endswith(".pdf"):
            catalog_content = extract_pdf_text(pdf_file.file)

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
    evolution_error = None
    evolution_create_response = None
    evolution_connect_response = None
    instance_name = None

    if whatsapp_number:
        require_evolution_config()

        clean_phone = normalize_phone(whatsapp_number)

        if not clean_phone.isdigit():
            return {
                "status": "success",
                "message": "تم تسجيل المتجر، لكن رقم الواتساب غير صالح.",
                "store_id": new_store.id,
                "qr_code": None,
                "evolution_error": "رقم الواتساب يجب أن يحتوي على أرقام فقط مع المفتاح الدولي.",
                "widget_code": (
                    f'<script src="{WEBHOOK_BASE_URL}/widget.js" '
                    f'data-store-id="{new_store.id}"></script>'
                ),
            }

        instance_name = make_instance_name(clean_phone)

        headers = {
            "apikey": EVOLUTION_GLOBAL_KEY,
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(
            connect=15.0,
            read=30.0,
            write=30.0,
            pool=30.0,
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                # 1) Create the instance.
                create_result = await evolution_create(
                    client,
                    instance_name,
                    headers,
                )

                evolution_create_response = create_result["data"]

                if create_result.get("qr"):
                    qr_code_data = create_result["qr"]

                # 2) If create did not return a QR, call connect and retry.
                if not qr_code_data:
                    connect_result = await get_qr_with_retry(
                        client,
                        instance_name,
                        headers,
                    )

                    evolution_connect_response = connect_result["data"]

                    if connect_result.get("qr"):
                        qr_code_data = connect_result["qr"]

                    if not qr_code_data:
                        evolution_error = (
                            "Evolution API لم يُرجع QR Code. "
                            "تحقق من اتصال Redis/Valkey وحالة Instance وAPI Key."
                        )

                # 3) Configure webhook regardless of whether QR was immediate.
                await configure_webhook(
                    client,
                    instance_name,
                    new_store.id,
                    headers,
                )

            except Exception as exc:
                evolution_error = str(exc)
                print(f"Evolution registration error: {exc}")

    return {
        "status": "success",
        "message": (
            "تم تسجيل المتجر بنجاح وتم توليد QR Code."
            if qr_code_data
            else "تم تسجيل المتجر، لكن لم يتم استلام QR Code من Evolution API."
        ),
        "store_id": new_store.id,
        "instance_name": instance_name,
        "qr_code": qr_code_data,
        "evolution_error": evolution_error,
        "evolution_create_response": evolution_create_response,
        "evolution_connect_response": evolution_connect_response,
        "widget_code": (
            f'<script src="{WEBHOOK_BASE_URL}/widget.js" '
            f'data-store-id="{new_store.id}"></script>'
        ),
    }


@app.get("/api/whatsapp/qr/{store_id}")
async def whatsapp_qr(
    store_id: str,
    db: Session = Depends(get_db),
):
    require_evolution_config()

    store = (
        db.query(StoreModel)
        .filter(StoreModel.id == store_id)
        .first()
    )

    if not store:
        raise HTTPException(
            status_code=404,
            detail="Store not found",
        )

    if not store.whatsapp_number:
        raise HTTPException(
            status_code=400,
            detail="رقم الواتساب غير موجود لهذا المتجر.",
        )

    instance_name = make_instance_name(store.whatsapp_number)

    headers = {
        "apikey": EVOLUTION_GLOBAL_KEY,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        result = await get_qr_with_retry(
            client,
            instance_name,
            headers,
            attempts=5,
            delay_seconds=1.5,
        )

    if result.get("qr"):
        return {
            "status": "success",
            "qr_code": result["qr"],
            "instance_name": instance_name,
            "evolution_response": result["data"],
        }

    return {
        "status": "error",
        "qr_code": None,
        "instance_name": instance_name,
        "message": "Evolution API لم يُرجع QR Code.",
        "evolution_response": result.get("data"),
    }


@app.get("/api/whatsapp/status/{store_id}")
async def whatsapp_status(
    store_id: str,
    db: Session = Depends(get_db),
):
    require_evolution_config()

    store = (
        db.query(StoreModel)
        .filter(StoreModel.id == store_id)
        .first()
    )

    if not store:
        raise HTTPException(
            status_code=404,
            detail="Store not found",
        )

    if not store.whatsapp_number:
        raise HTTPException(
            status_code=400,
            detail="رقم الواتساب غير موجود.",
        )

    instance_name = make_instance_name(store.whatsapp_number)

    headers = {
        "apikey": EVOLUTION_GLOBAL_KEY,
        "Content-Type": "application/json",
    }

    url = (
        f"{EVOLUTION_API_URL}/instance/connectionState/"
        f"{instance_name}"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                url,
                headers=headers,
            )

            data = safe_json(response)

            return {
                "status": "success" if response.is_success else "error",
                "http_status": response.status_code,
                "instance_name": instance_name,
                "connection_state": extract_instance_status(data),
                "evolution_response": data,
            }

        except Exception as exc:
            return {
                "status": "error",
                "instance_name": instance_name,
                "error": str(exc),
            }


# =========================================================
# Claude Chat
# =========================================================

async def generate_ai_reply(
    store: StoreModel,
    sender_id: str,
    message: str,
    db: Session,
) -> str:
    require_claude()

    previous_logs = (
        db.query(ChatLogModel)
        .filter(
            ChatLogModel.store_id == store.id,
            ChatLogModel.sender_id == sender_id,
        )
        .order_by(ChatLogModel.created_at.desc())
        .limit(5)
        .all()
    )

    previous_logs.reverse()

    chat_history = []

    for log in previous_logs:
        if log.user_message:
            chat_history.append({
                "role": "user",
                "content": log.user_message,
            })

        if log.bot_response:
            chat_history.append({
                "role": "assistant",
                "content": log.bot_response,
            })

    chat_history.append({
        "role": "user",
        "content": message,
    })

    system_prompt = f"""
أنت مساعد مبيعات ذكي يعمل لصالح متجر "{store.store_name}".

تعليمات المساعد:
{store.agent_notes if store.agent_notes else "كن ودوداً ومفيداً وخادماً للعملاء."}

كتالوج المنتجات والأسعار:
{store.catalog_text if store.catalog_text else "لا يوجد كتالوج مرفق."}

أجب باللغة العربية بشكل واضح ومختصر.
لا تخترع أسعاراً أو منتجات غير موجودة في الكتالوج.
إذا لم تعرف الإجابة، أخبر العميل بذلك واطلب منه التواصل مع المتجر.
"""

    response = claude_client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=500,
        system=system_prompt,
        messages=chat_history,
    )

    if not response.content:
        return "عذراً، لم أتمكن من إنشاء رد."

    first_block = response.content[0]

    if hasattr(first_block, "text"):
        return first_block.text

    return str(first_block)


@app.post("/api/chat")
async def widget_chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    store = (
        db.query(StoreModel)
        .filter(StoreModel.id == payload.store_id)
        .first()
    )

    if not store:
        raise HTTPException(
            status_code=404,
            detail="Store not found",
        )

    try:
        reply_text = await generate_ai_reply(
            store,
            payload.sender_id or "preview_user",
            payload.message,
            db,
        )

        db.add(
            ChatLogModel(
                store_id=store.id,
                sender_id=payload.sender_id or "preview_user",
                user_message=payload.message,
                bot_response=reply_text,
            )
        )

        db.commit()

        return {
            "status": "success",
            "reply": reply_text,
        }

    except HTTPException:
        raise

    except Exception as exc:
        print(f"Widget Chat Error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Internal Server Error",
        )


# =========================================================
# Evolution WhatsApp Webhook
# =========================================================

@app.post("/api/whatsapp/webhook/{store_id}")
async def whatsapp_evolution_webhook(
    store_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    store = (
        db.query(StoreModel)
        .filter(StoreModel.id == store_id)
        .first()
    )

    if not store:
        return {"status": "store_not_found"}

    try:
        data = await request.json()

        print(
            f"WhatsApp webhook received for store={store_id}: "
            f"{data}"
        )

        msg_data = data.get("data", data)

        if not isinstance(msg_data, dict):
            return {"status": "ignored"}

        # Ignore non-message webhook events.
        message_obj = msg_data.get("message")

        if not message_obj:
            return {"status": "event_received"}

        key = msg_data.get("key", {})

        if not isinstance(key, dict):
            return {"status": "ignored"}

        sender_remote_jid = key.get("remoteJid", "")
        is_from_me = bool(key.get("fromMe", False))

        if is_from_me:
            return {"status": "ignored"}

        if "g.us" in sender_remote_jid:
            return {"status": "ignored"}

        msg_body = message_obj if isinstance(message_obj, dict) else {}

        message_content = (
            msg_body.get("conversation")
            or msg_body.get("extendedTextMessage", {}).get("text")
            or msg_body.get("imageMessage", {}).get("caption")
            or msg_body.get("videoMessage", {}).get("caption")
            or ""
        )

        message_content = str(message_content).strip()

        if not message_content or not sender_remote_jid:
            return {"status": "ignored"}

        # Generate Claude reply.
        reply_text = await generate_ai_reply(
            store,
            sender_remote_jid,
            message_content,
            db,
        )

        # Save conversation.
        db.add(
            ChatLogModel(
                store_id=store.id,
                sender_id=sender_remote_jid,
                user_message=message_content,
                bot_response=reply_text,
            )
        )

        db.commit()

        # Send response through Evolution API.
        if not store.whatsapp_number:
            return {
                "status": "success",
                "warning": "store whatsapp number is missing",
            }

        clean_phone = normalize_phone(store.whatsapp_number)
        instance_name = make_instance_name(clean_phone)

        target_number = sender_remote_jid.split("@")[0]

        send_url = (
            f"{EVOLUTION_API_URL}/message/sendText/"
            f"{instance_name}"
        )

        headers = {
            "apikey": EVOLUTION_GLOBAL_KEY,
            "Content-Type": "application/json",
        }

        send_payload = {
            "number": target_number,
            "text": reply_text,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                send_url,
                json=send_payload,
                headers=headers,
            )

            print(
                f"Evolution sendText: status={response.status_code}, "
                f"response={response.text}"
            )

            if not response.is_success:
                return {
                    "status": "success",
                    "warning": "تم إنشاء الرد لكن Evolution API لم يرسل الرسالة.",
                    "evolution_status": response.status_code,
                    "evolution_response": safe_json(response),
                }

        return {"status": "success"}

    except Exception as exc:
        print(f"Webhook Processing Error: {exc}")
        return {
            "status": "error",
            "error": str(exc),
        }


# =========================================================
# Run with:
# uvicorn main:app --host 0.0.0.0 --port $PORT
# =========================================================
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import pypdf
import httpx
import anthropic
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_CONNECTION_URI")
if not DATABASE_URL or DATABASE_URL.strip() == "":
    DATABASE_URL = "sqlite:///./saas_stores.db"

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "")
EVOLUTION_GLOBAL_KEY = os.getenv("EVOLUTION_GLOBAL_KEY", "")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://twelve-garlics-mix.loca.lt")


class StoreModel(Base):
    __tablename__ = "stores"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    store_name = Column(String, nullable=False)
    store_url = Column(String, nullable=True)
    whatsapp_number = Column(String, nullable=True)
    agent_notes = Column(Text, nullable=True)
    catalog_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    logs = relationship("ChatLogModel", back_populates="store", cascade="all, delete-orphan")


class ChatLogModel(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String, ForeignKey("stores.id"))
    sender_id = Column(String, default="default_user")
    user_message = Column(Text)
    bot_response = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("StoreModel", back_populates="logs")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI(title="AI Store Assistant SaaS Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    store_id: str
    message: str
    sender_id: Optional[str] = "preview_user"


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
        print(f"Error reading PDF: {e}")
        return ""


@app.get("/", response_class=HTMLResponse)
async def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>مرحباً بك في منصة المساعد الذكي للمتاجر</h1>"


@app.get("/widget.js", response_class=FileResponse)
async def get_widget_script():
    if os.path.exists("widget.js"):
        return FileResponse("widget.js", media_type="application/javascript")
    raise HTTPException(status_code=404, detail="widget.js not found")


@app.post("/api/register-store")
async def register_store(
    store_name: str = Form(...),
    store_url: Optional[str] = Form(None),
    whatsapp_number: Optional[str] = Form(None),
    agent_notes: Optional[str] = Form(None),
    pdf_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    catalog_content = ""
    if pdf_file and pdf_file.filename.endswith(".pdf"):
        catalog_content = extract_pdf_text(pdf_file.file)

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

    if whatsapp_number:
        clean_phone = whatsapp_number.replace("+", "").replace(" ", "").replace("-", "").strip()
        instance_name = f"store_{clean_phone}"
        headers = {
            "apikey": EVOLUTION_GLOBAL_KEY,
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # 1. محاولة إنشاء Instance جديدة
                create_payload = {
                    "instanceName": instance_name,
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS"
                }
                res = await client.post(
                    f"{EVOLUTION_API_URL}/instance/create",
                    json=create_payload,
                    headers=headers
                )
                
                if res.status_code in [200, 201]:
                    res_data = res.json()
                    qr_raw = (
                        res_data.get("qrcode", {}).get("base64") or 
                        res_data.get("base64") or 
                        res_data.get("code")
                    )
                    if qr_raw:
                        qr_code_data = qr_raw if str(qr_raw).startswith("data:image") else f"data:image/png;base64,{qr_raw}"

                # 2. إذا لم نحصل على الكود (مثلاً الجلسة موجودة مسبقاً)، نطلب كود الاتصال مباشرة
                if not qr_code_data:
                    connect_res = await client.get(
                        f"{EVOLUTION_API_URL}/instance/connect/{instance_name}",
                        headers=headers
                    )
                    if connect_res.status_code in [200, 201]:
                        c_data = connect_res.json()
                        qr_raw = (
                            c_data.get("base64") or 
                            c_data.get("qrcode", {}).get("base64") or 
                            c_data.get("code")
                        )
                        if qr_raw:
                            qr_code_data = qr_raw if str(qr_raw).startswith("data:image") else f"data:image/png;base64,{qr_raw}"

                # 3. ضبط الـ Webhook تلقائياً
                webhook_payload = {
                    "webhook": {
                        "enabled": True,
                        "url": f"{WEBHOOK_BASE_URL}/api/whatsapp/webhook/{new_store.id}",
                        "byEvents": False,
                        "events": ["MESSAGES-UPSERT"]
                    }
                }
                await client.post(
                    f"{EVOLUTION_API_URL}/webhook/set/{instance_name}",
                    json=webhook_payload,
                    headers=headers
                )

            except Exception as e:
                print(f"❌ Evolution API Exception: {e}")

    return {
        "status": "success",
        "message": "تم تسجيل المتجر بنجاح",
        "store_id": new_store.id,
        "qr_code": qr_code_data,
        "widget_code": f'<script src="{WEBHOOK_BASE_URL}/widget.js" data-store-id="{new_store.id}"></script>',
    }


@app.post("/api/chat")
async def widget_chat(payload: ChatRequest, db: Session = Depends(get_db)):
    store = db.query(StoreModel).filter(StoreModel.id == payload.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    try:
        previous_logs = db.query(ChatLogModel).filter(
            ChatLogModel.store_id == store.id,
            ChatLogModel.sender_id == payload.sender_id
        ).order_by(ChatLogModel.created_at.desc()).limit(5).all()

        previous_logs.reverse()

        chat_history = []
        for log in previous_logs:
            chat_history.append({"role": "user", "content": log.user_message})
            chat_history.append({"role": "assistant", "content": log.bot_response})

        chat_history.append({"role": "user", "content": payload.message})

        system_prompt = f"""
        أنت مساعد مبيعات ذكي يعمل لصالح متجر '{store.store_name}' عبر الودجت.
        التعليمات والمهام: {store.agent_notes if store.agent_notes else 'كن ودوداً وخادماً للعملاء.'}
        كتالوج المنتجات والأسعار: {store.catalog_text if store.catalog_text else 'لا يوجد كتالوج مرفق.'}
        جاوب باختصار وبشكل واضح.
        """

        response = claude_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=500,
            system=system_prompt,
            messages=chat_history
        )
        reply_text = response.content[0].text

        db.add(ChatLogModel(
            store_id=store.id,
            sender_id=payload.sender_id,
            user_message=payload.message,
            bot_response=reply_text
        ))
        db.commit()

        return {"reply": reply_text}
    except Exception as e:
        print(f"❌ Widget Chat Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.post("/api/whatsapp/webhook/{store_id}")
async def whatsapp_evolution_webhook(store_id: str, request: Request, db: Session = Depends(get_db)):
    store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
    if not store:
        return {"status": "store_not_found"}

    try:
        data = await request.json()
        msg_data = data.get("data", {})
        
        if "message" in msg_data:
            key = msg_data.get("key", {})
            sender_remote_jid = key.get("remoteJid", "")
            is_from_me = key.get("fromMe", False)

            if is_from_me or "g.us" in sender_remote_jid:
                return {"status": "ignored"}

            msg_body = msg_data.get("message", {})
            message_content = (
                msg_body.get("conversation") or 
                msg_body.get("extendedTextMessage", {}).get("text") or ""
            )

            if message_content and sender_remote_jid:
                previous_logs = db.query(ChatLogModel).filter(
                    ChatLogModel.store_id == store.id,
                    ChatLogModel.sender_id == sender_remote_jid
                ).order_by(ChatLogModel.created_at.desc()).limit(5).all()

                previous_logs.reverse()

                chat_history = []
                for log in previous_logs:
                    chat_history.append({"role": "user", "content": log.user_message})
                    chat_history.append({"role": "assistant", "content": log.bot_response})

                chat_history.append({"role": "user", "content": message_content})

                system_prompt = f"""
                أنت مساعد مبيعات ذكي يعمل لصالح متجر '{store.store_name}' عبر الواتساب.
                التعليمات والمهام: {store.agent_notes if store.agent_notes else 'كن ودوداً وخادماً للعملاء.'}
                كتالوج المنتجات والأسعار: {store.catalog_text if store.catalog_text else 'لا يوجد كتالوج مرفق.'}
                جاوب باختصار وبشكل واضح ومناسب للمحادثات عبر الواتساب.
                """

                response = claude_client.messages.create(
                    model="claude-sonnet-4-5",
                    max_tokens=500,
                    system=system_prompt,
                    messages=chat_history
                )
                reply_text = response.content[0].text

                db.add(ChatLogModel(
                    store_id=store.id,
                    sender_id=sender_remote_jid,
                    user_message=message_content,
                    bot_response=reply_text
                ))
                db.commit()

                clean_phone = store.whatsapp_number.replace('+', '').replace(' ', '').replace('-', '').strip()
                send_url = f"{EVOLUTION_API_URL}/message/sendText/store_{clean_phone}"
                headers = {
                    "apikey": EVOLUTION_GLOBAL_KEY,
                    "Content-Type": "application/json"
                }
                
                target_number = sender_remote_jid.split("@")[0]
                payload = {
                    "number": target_number,
                    "text": reply_text
                }

                async with httpx.AsyncClient() as client:
                    await client.post(send_url, json=payload, headers=headers, timeout=10.0)

    except Exception as e:
        print(f"❌ Webhook Processing Error: {e}")

    return {"status": "success"}
