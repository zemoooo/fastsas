(function () {
    const scriptTag = document.currentScript;
    if (!scriptTag) return;
    const storeId = scriptTag.getAttribute('data-store-id');
    if (!storeId) return;

    // استخراج الدومين الأساسي للسيرفر من رابط السكريبت
    const scriptSrc = scriptTag.src;
    const baseUrl = new URL(scriptSrc).origin;

    // إنشاء وتصميم عناصر الـ Widget
    const container = document.createElement('div');
    container.innerHTML = `
        <div id="ai-chat-widget-root" style="position: fixed; bottom: 20px; right: 20px; z-index: 999999; font-family: 'Cairo', sans-serif; direction: rtl;">
            <!-- زر فتح الدردشة -->
            <button id="ai-chat-toggle-btn" style="background-color: #4f46e5; color: white; border: none; border-radius: 50px; width: 60px; height: 60px; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.15); display: flex; align-items: center; justify-content: center; transition: transform 0.2s;">
                <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
            </button>

            <!-- نافذة المحادثة -->
            <div id="ai-chat-box" style="display: none; position: absolute; bottom: 75px; right: 0; width: 340px; height: 480px; background: white; border-radius: 16px; box-shadow: 0 5px 25px rgba(0,0,0,0.15); border: 1px solid #e2e8f0; flex-direction: column; overflow: hidden;">
                <!-- رأس النافذة -->
                <div style="background: #4f46e5; color: white; padding: 14px 16px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-weight: 700; font-size: 15px;">المساعد الذكي للمتجر</span>
                    <button id="ai-chat-close-btn" style="background: none; border: none; color: white; font-size: 18px; cursor: pointer;">&times;</button>
                </div>

                <!-- صندوق الرسائل -->
                <div id="ai-chat-messages" style="flex: 1; padding: 16px; overflow-y: auto; background: #f8fafc; display: flex; flex-direction: column; gap: 10px; font-size: 13px;">
                    <div style="background: white; padding: 10px 14px; border-radius: 12px; border: 1px solid #e2e8f0; align-self: flex-start; max-width: 80%; color: #334155;">
                        مرحباً بك! كيف يمكنني مساعدتك في منتجات المتجر اليوم؟
                    </div>
                </div>

                <!-- شريط الإدخال -->
                <div style="padding: 12px; background: white; border-top: 1px solid #e2e8f0; display: flex; gap: 8px;">
                    <input type="text" id="ai-chat-input" placeholder="اكتب رسالتك هنا..." style="flex: 1; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 8px; outline: none; font-size: 13px;">
                    <button id="ai-chat-send-btn" style="background: #4f46e5; color: white; border: none; padding: 0 16px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 13px;">إرسال</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(container);

    const toggleBtn = document.getElementById('ai-chat-toggle-btn');
    const closeBtn = document.getElementById('ai-chat-close-btn');
    const chatBox = document.getElementById('ai-chat-box');
    const sendBtn = document.getElementById('ai-chat-send-btn');
    const inputField = document.getElementById('ai-chat-input');
    const messagesContainer = document.getElementById('ai-chat-messages');

    // توليد معرف فريد للمتصفح الحالي لجلسة المحادثة
    let senderId = localStorage.getItem('ai_chat_sender_id');
    if (!senderId) {
        senderId = 'web_user_' + Math.random().toString(36).substring(2, 9);
        localStorage.setItem('ai_chat_sender_id', senderId);
    }

    toggleBtn.addEventListener('click', () => {
        chatBox.style.display = chatBox.style.display === 'flex' ? 'none' : 'flex';
    });

    closeBtn.addEventListener('click', () => {
        chatBox.style.display = 'none';
    });

    async function sendMessage() {
        const text = inputField.value.trim();
        if (!text) return;

        // إضافة رسالة المستخدم للواجهة
        appendMessage(text, 'user');
        inputField.value = '';

        // رسالة انتظار الرد
        const loadingId = 'loading_' + Date.now();
        appendMessage('جاري الرد...', 'bot', loadingId);

        try {
            const response = await fetch(`${baseUrl}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    store_id: storeId,
                    message: text,
                    sender_id: senderId
                })
            });
            const data = await response.json();

            // إزالة رسالة الانتظار
            document.getElementById(loadingId)?.remove();

            if (data.reply) {
                appendMessage(data.reply, 'bot');
            } else {
                appendMessage('عذراً، حدث خطأ في الرد.', 'bot');
            }
        } catch (err) {
            document.getElementById(loadingId)?.remove();
            appendMessage('فشل الاتصال بالخادم.', 'bot');
        }
    }

    function appendMessage(text, sender, customId = null) {
        const msgDiv = document.createElement('div');
        if (customId) msgDiv.id = customId;

        if (sender === 'user') {
            msgDiv.style.cssText = "background: #4f46e5; color: white; padding: 10px 14px; border-radius: 12px; align-self: flex-end; max-width: 80%; word-break: break-word;";
        } else {
            msgDiv.style.cssText = "background: white; color: #334155; padding: 10px 14px; border-radius: 12px; border: 1px solid #e2e8f0; align-self: flex-start; max-width: 80%; word-break: break-word;";
        }
        msgDiv.textContent = text;
        messagesContainer.appendChild(msgDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    sendBtn.addEventListener('click', sendMessage);
    inputField.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });
})();
