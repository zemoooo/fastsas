(function () {
    "use strict";

    const scriptTag = document.currentScript;
    const storeId = scriptTag
        ? scriptTag.getAttribute("data-store-id")
        : null;

    if (!storeId) {
        console.error("AI Store Widget: data-store-id is missing.");
        return;
    }

    // منع تحميل الودجت أكثر من مرة
    if (document.getElementById("ai-store-chat-widget")) {
        return;
    }

    // =========================
    // إنشاء الواجهة
    // =========================

    const chatWidget = document.createElement("div");

    chatWidget.innerHTML = `
        <div id="ai-store-chat-widget"
             dir="rtl"
             style="
                position:fixed;
                bottom:20px;
                right:20px;
                z-index:999999;
                font-family:Arial,Tahoma,sans-serif;
             ">

            <div id="ai-chat-window"
                 style="
                    display:none;
                    width:350px;
                    height:450px;
                    max-width:calc(100vw - 30px);
                    max-height:calc(100vh - 100px);
                    background:#fff;
                    border-radius:14px;
                    box-shadow:0 8px 35px rgba(0,0,0,.22);
                    flex-direction:column;
                    overflow:hidden;
                    margin-bottom:12px;
                    border:1px solid #e5e5e5;
                 ">

                <!-- Header -->
                <div style="
                    background:#007bff;
                    color:#fff;
                    padding:14px 16px;
                    font-weight:bold;
                    display:flex;
                    justify-content:space-between;
                    align-items:center;
                ">
                    <span>🤖 مساعد المتجر الذكي</span>

                    <button id="ai-chat-close"
                            type="button"
                            aria-label="إغلاق"
                            style="
                                background:none;
                                border:none;
                                color:white;
                                cursor:pointer;
                                font-size:24px;
                                line-height:1;
                            ">
                        &times;
                    </button>
                </div>

                <!-- Messages -->
                <div id="ai-chat-messages"
                     style="
                        flex:1;
                        padding:15px;
                        overflow-y:auto;
                        background:#f7f8fa;
                        display:flex;
                        flex-direction:column;
                        gap:10px;
                     ">

                    <div style="
                        background:#e9ecef;
                        color:#333;
                        padding:10px 12px;
                        border-radius:10px;
                        max-width:82%;
                        align-self:flex-start;
                        font-size:14px;
                        line-height:1.6;
                    ">
                        أهلاً بك 👋<br>
                        كيف يمكنني مساعدتك في منتجاتنا اليوم؟
                    </div>

                </div>

                <!-- Input -->
                <div style="
                    padding:10px;
                    background:#fff;
                    border-top:1px solid #ddd;
                    display:flex;
                    gap:7px;
                    align-items:center;
                ">

                    <input
                        type="text"
                        id="ai-chat-input"
                        placeholder="اكتب رسالتك هنا..."
                        autocomplete="off"
                        style="
                            flex:1;
                            min-width:0;
                            padding:11px;
                            border:1px solid #ccc;
                            border-radius:8px;
                            outline:none;
                            font-size:14px;
                            direction:rtl;
                        "
                    >

                    <button
                        id="ai-chat-send"
                        type="button"
                        style="
                            background:#007bff;
                            color:#fff;
                            border:none;
                            padding:11px 15px;
                            border-radius:8px;
                            cursor:pointer;
                            font-weight:bold;
                            white-space:nowrap;
                        ">
                        إرسال
                    </button>

                </div>
            </div>

            <!-- Floating Button -->
            <button
                id="ai-chat-toggle"
                type="button"
                aria-label="فتح المساعد"
                style="
                    background:#007bff;
                    color:#fff;
                    border:none;
                    width:60px;
                    height:60px;
                    border-radius:50%;
                    cursor:pointer;
                    box-shadow:0 5px 15px rgba(0,0,0,.3);
                    font-size:25px;
                    display:flex;
                    align-items:center;
                    justify-content:center;
                    transition:.2s;
                ">
                💬
            </button>

        </div>
    `;

    document.body.appendChild(chatWidget);

    // =========================
    // العناصر
    // =========================

    const widget = document.getElementById("ai-store-chat-widget");
    const chatWindow = document.getElementById("ai-chat-window");
    const toggleBtn = document.getElementById("ai-chat-toggle");
    const closeBtn = document.getElementById("ai-chat-close");
    const sendBtn = document.getElementById("ai-chat-send");
    const inputField = document.getElementById("ai-chat-input");
    const messagesArea = document.getElementById("ai-chat-messages");

    let isOpen = false;
    let isSending = false;

    // =========================
    // معرف المستخدم
    // =========================

    function getSenderId() {
        const storageKey = "ai_store_sender_id_" + storeId;

        let senderId = localStorage.getItem(storageKey);

        if (!senderId) {
            senderId =
                "user_" +
                Date.now().toString(36) +
                "_" +
                Math.random().toString(36).substring(2, 10);

            localStorage.setItem(storageKey, senderId);
        }

        return senderId;
    }

    // =========================
    // إضافة رسالة بأمان
    // =========================

    function addMessage(text, type) {
        const message = document.createElement("div");

        message.textContent = text;

        if (type === "user") {
            message.style.cssText = `
                background:#007bff;
                color:white;
                padding:10px 12px;
                border-radius:10px;
                max-width:82%;
                align-self:flex-end;
                font-size:14px;
                line-height:1.6;
                word-break:break-word;
            `;
        } else if (type === "error") {
            message.style.cssText = `
                background:#f8d7da;
                color:#721c24;
                padding:10px 12px;
                border-radius:10px;
                max-width:82%;
                align-self:flex-start;
                font-size:14px;
                line-height:1.6;
            `;
        } else {
            message.style.cssText = `
                background:#e9ecef;
                color:#333;
                padding:10px 12px;
                border-radius:10px;
                max-width:82%;
                align-self:flex-start;
                font-size:14px;
                line-height:1.6;
                word-break:break-word;
            `;
        }

        messagesArea.appendChild(message);
        messagesArea.scrollTop = messagesArea.scrollHeight;

        return message;
    }

    // =========================
    // مؤشر الكتابة
    // =========================

    function showTyping() {
        const typing = document.createElement("div");

        typing.id = "ai-chat-typing";

        typing.textContent = "المساعد يكتب...";

        typing.style.cssText = `
            background:#e9ecef;
            color:#666;
            padding:9px 12px;
            border-radius:10px;
            max-width:82%;
            align-self:flex-start;
            font-size:13px;
            font-style:italic;
        `;

        messagesArea.appendChild(typing);
        messagesArea.scrollTop = messagesArea.scrollHeight;
    }

    function hideTyping() {
        const typing = document.getElementById("ai-chat-typing");

        if (typing) {
            typing.remove();
        }
    }

    // =========================
    // فتح / إغلاق
    // =========================

    function openChat() {
        isOpen = true;

        chatWindow.style.display = "flex";

        setTimeout(() => {
            inputField.focus();
        }, 100);
    }

    function closeChat() {
        isOpen = false;
        chatWindow.style.display = "none";
    }

    toggleBtn.addEventListener("click", function () {
        if (isOpen) {
            closeChat();
        } else {
            openChat();
        }
    });

    closeBtn.addEventListener("click", closeChat);

    // =========================
    // إرسال الرسالة
    // =========================

    async function sendMessage() {
        if (isSending) return;

        const text = inputField.value.trim();

        if (!text) return;

        isSending = true;

        sendBtn.disabled = true;
        sendBtn.style.opacity = "0.6";
        sendBtn.style.cursor = "not-allowed";

        // رسالة المستخدم
        addMessage(text, "user");

        inputField.value = "";

        showTyping();

        try {
            const senderId = getSenderId();

            const response = await fetch("/api/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                body: JSON.stringify({
                    store_id: Number(storeId),
                    message: text,
                    sender_id: senderId
                })
            });

            let data = {};

            try {
                data = await response.json();
            } catch (jsonError) {
                throw new Error("الخادم أعاد استجابة غير صحيحة.");
            }

            hideTyping();

            if (!response.ok) {
                throw new Error(
                    data.detail ||
                    data.message ||
                    "حدث خطأ في الخادم."
                );
            }

            // Backend الحالي يرجع:
            // { status: "success", reply: "..." }

            const reply =
                data.reply ||
                data.response ||
                data.message ||
                "عذراً، لم يتم الحصول على رد من المساعد.";

            addMessage(String(reply), "assistant");

        } catch (error) {
            console.error("AI Store Chat Error:", error);

            hideTyping();

            addMessage(
                "عذراً، حدث خطأ في الاتصال بالمساعد. حاول مرة أخرى.",
                "error"
            );
        } finally {
            isSending = false;

            sendBtn.disabled = false;
            sendBtn.style.opacity = "1";
            sendBtn.style.cursor = "pointer";

            inputField.focus();
        }
    }

    sendBtn.addEventListener("click", sendMessage);

    inputField.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
            event.preventDefault();
            sendMessage();
        }
    });

    // =========================
    // تحسين الهاتف
    // =========================

    function adjustForMobile() {
        if (window.innerWidth <= 480) {
            widget.style.right = "10px";
            widget.style.bottom = "10px";

            chatWindow.style.width = "calc(100vw - 20px)";
            chatWindow.style.height = "min(500px, calc(100vh - 90px))";
        } else {
            widget.style.right = "20px";
            widget.style.bottom = "20px";

            chatWindow.style.width = "350px";
            chatWindow.style.height = "450px";
        }
    }

    window.addEventListener("resize", adjustForMobile);

    adjustForMobile();

})();
