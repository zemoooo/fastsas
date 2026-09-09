(function() {
    const scriptTag = document.currentScript;
    const storeId = scriptTag.getAttribute('data-store-id');

    if (!storeId) {
        console.error("AI Widget Error: Missing data-store-id");
        return;
    }

    const widgetContainer = document.createElement('div');
    widgetContainer.style.position = 'fixed';
    widgetContainer.style.bottom = '20px';
    widgetContainer.style.right = '20px';
    widgetContainer.style.zIndex = '999999';

    widgetContainer.innerHTML = `
        <div id="ai-chat-window" style="display:none; width: 340px; height: 480px; background: #fff; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.15); flex-direction: column; overflow: hidden; font-family: sans-serif; direction: rtl;">
            <div style="background: #4f46e5; color: white; padding: 14px; font-weight: bold; text-align: center;">مساعد المتجر الذكي</div>
            <div id="ai-messages" style="flex: 1; padding: 12px; overflow-y: auto; background: #f9fafb; display: flex; flex-direction: column; gap: 8px;"></div>
            <div style="display: flex; border-top: 1px solid #eee; padding: 8px; background: #fff;">
                <input type="text" id="ai-input" placeholder="اكتب سؤالك هنا..." style="flex:1; border: 1px solid #ccc; padding: 8px 12px; border-radius: 8px; outline: none; font-size: 14px;">
                <button id="ai-send-btn" style="background: #4f46e5; color: white; border: none; padding: 8px 14px; margin-right: 6px; border-radius: 8px; cursor: pointer; font-weight: bold;">إرسال</button>
            </div>
        </div>
        <button id="ai-toggle-btn" style="width: 56px; height: 56px; border-radius: 50%; background: #4f46e5; color: white; border: none; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.2); font-size: 24px; display: flex; align-items: center; justify-content: center; margin-left: auto;">💬</button>
    `;

    document.body.appendChild(widgetContainer);

    const toggleBtn = document.getElementById('ai-toggle-btn');
    const chatWindow = document.getElementById('ai-chat-window');
    const sendBtn = document.getElementById('ai-send-btn');
    const input = document.getElementById('ai-input');
    const messages = document.getElementById('ai-messages');

    toggleBtn.onclick = () => {
        chatWindow.style.display = chatWindow.style.display === 'none' ? 'flex' : 'none';
    };

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;

        messages.innerHTML += `<div style="background: #e5e7eb; padding: 8px 12px; border-radius: 10px; max-width: 80%; align-self: flex-start;">${text}</div>`;
        input.value = '';
        messages.scrollTop = messages.scrollHeight;

        try {
            const res = await fetch('http://localhost:8000/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ store_id: storeId, message: text })
            });

            const data = await res.json();
            messages.innerHTML += `<div style="background: #e0e7ff; color: #3730a3; padding: 8px 12px; border-radius: 10px; max-width: 80%; align-self: flex-end;">${data.response}</div>`;
            messages.scrollTop = messages.scrollHeight;
        } catch (e) {
            messages.innerHTML += `<div style="background: #fee2e2; color: #991b1b; padding: 8px 12px; border-radius: 10px; max-width: 80%;">حدث خطأ في الاتصال.</div>`;
        }
    }

    sendBtn.onclick = sendMessage;
    input.onkeypress = (e) => { if (e.key === 'Enter') sendMessage(); };
})();
