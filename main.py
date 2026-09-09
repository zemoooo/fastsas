import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
import pypdf
import httpx
import anthropic
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

# التحقق من متغير قاعدة البيانات أو استخدام SQLite كقيمة افتراضية آمنة
DATABASE_URL = os.getenv("DATABASE_CONNECTION_URI")
if not DATABASE_URL or DATABASE_URL.strip() == "":
    DATABASE_URL = "sqlite:///./saas_stores.db"

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "https://evolution-api-render-1-nsvq.onrender.com")
EVOLUTION_GLOBAL_KEY = os.getenv("EVOLUTION_GLOBAL_KEY", "")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://twelve-garlics-mix.loca.lt")

print(f"🔑 Evolution Global Key Loaded: {'Yes' if EVOLUTION_GLOBAL_KEY else 'No'}")
print(f"🔑 Anthropic API Key Loaded: {'Yes' if ANTHROPIC_API_KEY else 'No'}")


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


app = FastAPI(title="AI Store Assistant SaaS Platform with WhatsApp Integration")

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
        clean_phone = whatsapp_number.replace("+", "").strip()
        instance_name = f"store_{clean_phone}"
        headers = {
            "apikey": EVOLUTION_GLOBAL_KEY,
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient() as client:
            try:
                create_payload = {
                    "instanceName": instance_name,
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS"
                }
                res = await client.post(f"{EVOLUTION_API_URL}/instance/create", json=create_payload, headers=headers, timeout=15.0)
                
                if res.status_code in [200, 201]:
                    qr_code_data = res.json().get("qrcode", {}).get("base64")

                webhook_payload = {
                    "webhook": {
                        "enabled": True,
                        "url": f"{WEBHOOK_BASE_URL}/api/whatsapp/webhook/{new_store.id}",
                        "byEvents": False,
                        "events": ["MESSAGES-UPSERT"]
                    }
                }
                await client.post(f"{EVOLUTION_API_URL}/webhook/set/{instance_name}", json=webhook_payload, headers=headers, timeout=15.0)

            except Exception as e:
                print(f"❌ Evolution API Connection Error: {e}")

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

                clean_phone = store.whatsapp_number.replace('+', '').strip()
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
