(function() {
    const scriptTag = document.currentScript;
    const storeId = scriptTag ? scriptTag.getAttribute('data-store-id') : null;

    if (!storeId) return;

    // Create floating chat button and window
    const chatWidget = document.createElement('div');
    chatWidget.innerHTML = `
        <div id="ai-store-chat-widget" style="position: fixed; bottom: 20px; right: 20px; z-index: 999999; font-family: sans-serif;">
            <div id="ai-chat-window" style="display: none; width: 350px; height: 450px; background: white; border-radius: 12px; box-shadow: 0 5px 25px rgba(0,0,0,0.2); flex-direction: column; overflow: hidden; margin-bottom: 10px; border: 1px solid #ddd;">
                <div style="background: #007bff; color: white; padding: 15px; font-weight: bold; display: flex; justify-content: space-between; align-items: center;">
                    <span>مساعد المتجر الذكي</span>
                    <span id="ai-chat-close" style="cursor: pointer; font-size: 18px;">&times;</span>
                </div>
                <div id="ai-chat-messages" style="flex: 1; padding: 15px; overflow-y: auto; background: #f9f9f9; display: flex; flex-direction: column; gap: 10px;">
                    <div style="background: #e9ecef; padding: 10px; border-radius: 8px; max-width: 80%; align-self: flex-start; font-size: 14px;">أهلاً بك! كيف يمكنني مساعدتك في منتجاتنا اليوم؟</div>
                </div>
                <div style="padding: 10px; background: white; border-top: 1px solid #ddd; display: flex; gap: 5px;">
                    <input type="text" id="ai-chat-input" placeholder="اكتب رسالتك هنا..." style="flex: 1; padding: 10px; border: 1px solid #ccc; border-radius: 6px; outline: none; font-size: 14px;">
                    <button id="ai-chat-send" style="background: #007bff; color: white; border: none; padding: 10px 15px; border-radius: 6px; cursor: pointer; font-weight: bold;">إرسال</button>
                </div>
            </div>
            <button id="ai-chat-toggle" style="background: #007bff; color: white; border: none; width: 60px; height: 60px; border-radius: 50%; cursor: pointer; box-shadow: 0 4px 10px rgba(0,0,0,0.3); font-size: 24px; display: flex; align-items: center; justify-content: center;">💬</button>
        </div>
    `;
    document.body.appendChild(chatWidget);

    const chatWindow = document.getElementById('ai-chat-window');
    const toggleBtn = document.getElementById('ai-chat-toggle');
    const closeBtn = document.getElementById('ai-chat-close');
    const sendBtn = document.getElementById('ai-chat-send');
    const inputField = document.getElementById('ai-chat-input');
    const messagesArea = document.getElementById('ai-chat-messages');

    let isOpen = false;

    toggleBtn.onclick = () => {
        isOpen = !isOpen;
        chatWindow.style.display = isOpen ? 'flex' : 'none';
    };

    closeBtn.onclick = () => {
        isOpen = false;
        chatWindow.style.display = 'none';
    };

    async function sendMessage() {
        const text = inputField.value.trim();
        if (!text) return;

        messagesArea.innerHTML += `<div style="background: #007bff; color: white; padding: 10px; border-radius: 8px; max-width: 80%; align-self: flex-end; font-size: 14px;">${text}</div>`;
        inputField.value = '';
        messagesArea.scrollTop = messagesArea.scrollHeight;

        try {
            let senderId = localStorage.getItem('ai_store_sender_id');
            if (!senderId) {
                senderId = 'user_' + Math.random().toString(36).substring(2, 9);
                localStorage.setItem('ai_store_sender_id', senderId);
            }

            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    store_id: storeId,
                    message: text,
                    sender_id: senderId
                })
            });

            const data = await response.json();
            messagesArea.innerHTML += `<div style="background: #e9ecef; color: #333; padding: 10px; border-radius: 8px; max-width: 80%; align-self: flex-start; font-size: 14px;">${data.response}</div>`;
            messagesArea.scrollTop = messagesArea.scrollHeight;
        } catch (error) {
            messagesArea.innerHTML += `<div style="background: #f8d7da; color: #721c24; padding: 10px; border-radius: 8px; max-width: 80%; align-self: flex-start; font-size: 14px;">عذراً، حدث خطأ في الاتصال.</div>`;
        }
    }

    sendBtn.onclick = sendMessage;
    inputField.onkeypress = (e) => {
        if (e.key === 'Enter') sendMessage();
    };
})();
