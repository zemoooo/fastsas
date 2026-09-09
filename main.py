import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import pypdf
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

# --- 1. إعداد قاعدة البيانات (SQLite) ---
DATABASE_URL = "sqlite:///./saas_stores.db"
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class StoreModel(Base):
  __tablename__ = "stores"

  id = Column(
      String, primary_key=True, default=lambda: str(uuid.uuid4())
  )  # store_id
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


# --- 2. إعداد تطبيق FastAPI ---
app = FastAPI(title="AI Store Assistant SaaS Platform")

# السماح بالطلبات من أي مصدر (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 3. نماذج البيانات (Pydantic Models) ---
class ChatRequest(BaseModel):
  store_id: str
  message: str


# --- 4. وظائف مساعدة ---
def extract_pdf_text(file_bytes) -> str:
  """استخراج النص من ملف PDF مرفوع"""
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


# --- 5. مسارات تقديم الملفات (تأمين الواجهة والرابط الرئيسية) ---


@app.get("/", response_class=HTMLResponse)
async def read_index():
  """تقديم صفحة index.html على الصفحة الرئيسية للمشروع"""
  if os.path.exists("index.html"):
    with open("index.html", "r", encoding="utf-8") as f:
      return f.read()
  return "<h1>خطأ: ملف index.html غير موجود في مجلد المشروع</h1>"


@app.get("/widget.js")
async def get_widget_js():
  """تقديم ملف widget.js لتضمنه المتاجر"""
  if os.path.exists("widget.js"):
    return FileResponse("widget.js", media_type="application/javascript")
  raise HTTPException(status_code=404, detail="ملف widget.js غير موجود")


# --- 6. مسارات الـ API ---


@app.post("/api/register-store")
async def register_store(
    store_name: str = Form(...),
    store_url: Optional[str] = Form(None),
    whatsapp_number: Optional[str] = Form(None),
    agent_notes: Optional[str] = Form(None),
    pdf_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
  """تسجيل متجر جديد وإنشاء store_id وكود الويدجت"""
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

  return {
      "status": "success",
      "message": "تم تسجيل المتجر بنجاح",
      "store_id": new_store.id,
      "widget_code": (
          f'<script src="http://localhost:8000/widget.js"'
          f' data-store-id="{new_store.id}"></script>'
      ),
  }


@app.get("/api/store/{store_id}")
async def get_store_info(store_id: str, db: Session = Depends(get_db)):
  """جلب معلومات المتجر"""
  store = db.query(StoreModel).filter(StoreModel.id == store_id).first()
  if not store:
    raise HTTPException(status_code=404, detail="المتجر غير موجود")
  return store


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, db: Session = Depends(get_db)):
  """مسار المحادثة المخصص حسب store_id"""
  store = db.query(StoreModel).filter(StoreModel.id == req.store_id).first()

  if not store:
    raise HTTPException(status_code=404, detail="معرف المتجر غير صالح")

  # إجابة تجريبية مخصصة للمتجر (يمكن ربطها مستقبلاً بـ Gemini API)
  ai_reply = (
      f"أهلاً بك في {store.store_name}! "
      f"بناءً على استفسارك: '{req.message}'، يسعدنا تواصلك معنا عبر الواتساب"
      f" {store.whatsapp_number or ''} لمزيد من التفاصيل."
  )

  chat_log = ChatLogModel(
      store_id=store.id, user_message=req.message, bot_response=ai_reply
  )
  db.add(chat_log)
  db.commit()

  return {"response": ai_reply, "store_id": store.id}