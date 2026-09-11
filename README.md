# FastSAS Smart AI Store Assistant — 5.0

نسخة مدمجة ومحسنة من المشروع مع إدارة متجر، مساعد Claude، وWhatsApp عبر Evolution API.

## أهم التحسينات
- إنشاء Instance تلقائياً لكل متجر.
- دعم Evolution API QR بعدة صيغ واستجابات.
- منع اعتبار pairing code مثل `2@...` صورة QR.
- إعادة محاولة الحصول على QR تلقائياً.
- كشف حالة الاتصال قبل إنشاء Instance جديدة.
- إعداد Webhook تلقائياً مع توافق مع الصيغ القديمة.
- واجهة QR مع فحص اتصال تلقائي كل 5 ثوانٍ.
- فصل جلسة واتساب وإعادة الربط.
- endpoint تشخيص: `/api/whatsapp/diagnostics/{store_id}`.
- health check: `/api/health`.
- حماية مفاتيح Evolution وClaude في متغيرات البيئة فقط.
- PostgreSQL/Render جاهز.

## Render
اضبط:
- `DATABASE_CONNECTION_URI`
- `EVOLUTION_API_URL`
- `EVOLUTION_GLOBAL_KEY`
- `WEBHOOK_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`

يجب أن يكون `WEBHOOK_BASE_URL` عنوان HTTPS عام يمكن لخادم Evolution الوصول إليه.

## التشغيل
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

ثم افتح `/`.

## ملاحظة
لا يمكن ضمان اتصال فعلي بـ Evolution API من داخل حزمة المشروع وحدها؛ يجب أن تكون خدمة Evolution API متاحة، والمفتاح صحيحاً، وWebhook URL عاماً وقابلاً للوصول.
