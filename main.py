import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
import pypdf
import requests
import anthropic
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

DATABASE_URL = "sqlite:///./saas_stores.db"
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "sk-ant-api03-YOUR_CLAUDE_KEY_HERE")
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# تم التحديث ليرتبط بسيرفرك الجديد على Render ومفتاح الحماية الخاص بك
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "https://evolution-api-render-1-nsvq.onrender.com")
EVOLUTION_GLOBAL_KEY = os.getenv("EVOLUTION_GLOBAL_KEY", "114477azaz@@")
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

    logs = relationship(
        "ChatLogModel", back_populates="store", cascade="all, delete-orphan"
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
    return "<h1>خطأ: ملف index.html غير موجود في مجلد المشروع</h1>"


@app.get("/widget.js")
async def get_widget_js():
    if os.path.exists("widget.js"):
        return FileResponse("widget.js", media_type="application/javascript")
    raise HTTPException(status_code=404, detail="ملف widget.js غير موجود")


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

    if whatsapp_number:
        try:
            clean_phone = whatsapp_number.replace("+", "")
            instance_name = f"store_{clean_phone}"
            headers = {
                "apikey": EVOLUTION_GLOBAL_KEY,
                "Content-Type": "application/json"
            }
            payload = {
                "instanceName": instance_name,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS"
            }
            requests.post(f"{EVOLUTION_API_URL}/instance/create", json=payload, headers=headers, timeout=10)
            
            webhook_payload = {
                "webhook": {
                    "enabled": True,
                    "url": f"{WEBHOOK_BASE_URL}/api/whatsapp/webhook/{new_store.id}",
                    "byEvents": False,
                    "events": ["MESSAGES-UPSERT"]
                }
            }
            webhook_headers = {
                "apikey": EVOLUTION_GLOBAL_KEY,
                "Content-Type": "application/json",
                "Bypass-Tunnel-Reminder": "true"
            }
            requests.post(f"{EVOLUTION_API_URL}/webhook/set/{instance_name}", json=webhook_payload, headers=webhook_headers, timeout=10)
        except Exception as e:
            print(f"Evolution API Connection Error: {e}")

    return {
        "status": "success",
        "message": "تم تسجيل المتجر بنجاح",
        "store_id": new_store.id,
        "widget_code": f'<script src="{WEBHOOK_BASE_URL}/widget.js" data-store-id="{new_store.id}"></script>',
    }


@app.get("/api/whatsapp/connect/{store_id}")
async def connect_whatsapp(store_id: str, db: Session = Depends(get_db)):
    store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
    if not store or not store.whatsapp_number:
        raise HTTPException(status_code=404, detail="المتجر أو رقم الواتساب غير موجود")

    clean_phone = store.whatsapp_number.replace("+", "")
    instance_name = f"store_{clean_phone}"
    headers = {
        "apikey": EVOLUTION_GLOBAL_KEY,
        "Content-Type": "application/json",
        "Bypass-Tunnel-Reminder": "true"
    }

    try:
        connect_res = requests.get(f"{EVOLUTION_API_URL}/instance/connect/{instance_name}", headers=headers, timeout=10)
        res_data = connect_res.json()
        return {"status": "success", "evolution_data": res_data}
    except Exception as e:
        try:
            qr_res = requests.get(f"{EVOLUTION_API_URL}/qrcode/{instance_name}", headers=headers, timeout=10)
            return {"status": "success", "evolution_data": qr_res.json()}
        except Exception as inner_e:
            raise HTTPException(status_code=500, detail=f"خطأ في الاتصال بـ Evolution API: {str(e)}")


@app.get("/api/store/{store_id}")
async def get_store_info(store_id: str, db: Session = Depends(get_db)):
    store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")
    return store


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db)):
    store = db.query(StoreModel).filter(StoreModel.id == req.store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="معرف المتجر غير صالح")

    previous_logs = db.query(ChatLogModel).filter(
        ChatLogModel.store_id == store.id,
        ChatLogModel.sender_id == req.sender_id
    ).order_by(ChatLogModel.created_at.asc()).all()

    chat_history = []
    for log in previous_logs:
        chat_history.append({"role": "user", "content": log.user_message})
        chat_history.append({"role": "assistant", "content": log.bot_response})

    chat_history.append({"role": "user", "content": req.message})

    system_prompt = f"""
    أنت مساعد مبيعات ذكي يعمل لصالح متجر '{store.store_name}'.
    رابط الموقع: {store.store_url if store.store_url else 'غير متوفر'}
    التعليمات: {store.agent_notes if store.agent_notes else 'كن ودوداً، ساعد العملاء واعرض الخدمات بدقة.'}
    {f"معلومات الكتالوج والأسعار:\n{store.catalog_text}" if store.catalog_text else "لا يوجد كتالوج مرفق."}
    """

    ai_reply = "أهلاً بك! تم استلام رسالتك."
    try:
        response = claude_client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=500,
            system=system_prompt,
            messages=chat_history[-10:]
        )
        ai_reply = response.content[0].text
    except Exception as e:
        print(f"Claude API Error: {e}")

    chat_log = ChatLogModel(
        store_id=store.id,
        sender_id=req.sender_id,
        user_message=req.message,
        bot_response=ai_reply
    )
    db.add(chat_log)
    db.commit()

    return {"response": ai_reply, "store_id": store.id}


@app.post("/api/whatsapp/webhook/{store_id}")
async def whatsapp_evolution_webhook(store_id: str, request: Request, db: Session = Depends(get_db)):
    store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
    if not store:
        return {"status": "store_not_found"}

    try:
        data = await request.json()

        msg_data = data.get("data", {})
        if "message" in msg_data:
            sender_remote_jid = msg_data.get("key", {}).get("remoteJid", "")
            is_from_me = msg_data.get("key", {}).get("fromMe", False)
            
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
                ).order_by(ChatLogModel.created_at.asc()).all()

                chat_history = []
                for log in previous_logs:
                    chat_history.append({"role": "user", "content": log.user_message})
                    chat_history.append({"role": "assistant", "content": log.bot_response})

                chat_history.append({"role": "user", "content": message_content})

                system_prompt = f"""
                أنت مساعد مبيعات ذكي يعمل لصالح متجر '{store.store_name}' عبر الواتساب.
                التعليمات: {store.agent_notes if store.agent_notes else 'كن ودوداً وخادماً للعملاء.'}
                الكتالوج: {store.catalog_text if store.catalog_text else 'لا يوجد كتالوج.'}
                """

                response = claude_client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=500,
                    system=system_prompt,
                    messages=chat_history[-10:]
                )
                reply_text = response.content[0].text

                db.add(ChatLogModel(
                    store_id=store.id,
                    sender_id=sender_remote_jid,
                    user_message=message_content,
                    bot_response=reply_text
                ))
                db.commit()

                clean_phone = store.whatsapp_number.replace('+', '')
                send_url = f"{EVOLUTION_API_URL}/message/sendText/store_{clean_phone}"
                headers = {
                    "apikey": EVOLUTION_GLOBAL_KEY,
                    "Content-Type": "application/json",
                    "Bypass-Tunnel-Reminder": "true"
                }
                payload = {
                    "number": sender_remote_jid.split("@")[0],
                    "text": reply_text
                }
                requests.post(send_url, json=payload, headers=headers, timeout=10)

    except Exception as e:
        print(f"Webhook Processing Error: {e}")

    return {"status": "success"}
