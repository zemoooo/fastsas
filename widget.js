(function () {
    "use strict";

    const currentScript =
        document.currentScript ||
        document.querySelector("script[data-store-id]");

    const storeId = currentScript
        ? currentScript.getAttribute("data-store-id")
        : null;

    if (!storeId) {
        console.error(
            "AI Chat Widget: لم يتم العثور على data-store-id."
        );
        return;
    }

    const scriptSrc = currentScript.src;

    if (!scriptSrc) {
        console.error(
            "AI Chat Widget: تعذر تحديد رابط الخادم."
        );
        return;
    }

    const baseUrl = new URL(scriptSrc).origin;

    let senderId = localStorage.getItem(
        "ai_widget_sender_id"
    );

    if (!senderId) {
        senderId =
            "user_" +
            Math.random()
                .toString(36)
                .substring(2, 11);

        localStorage.setItem(
            "ai_widget_sender_id",
            senderId
        );
    }

    const widgetStyles = `
        #ai-chat-widget-container * {
            box-sizing: border-box;
            font-family: system-ui, -apple-system, "Segoe UI",
                Roboto, "Helvetica Neue", Arial, sans-serif;
            direction: rtl;
        }

        #ai-chat-button {
            position: fixed;
            bottom: 20px;
            left: 20px;
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background-color: #4f46e5;
            color: #ffffff;
            border: none;
            box-shadow: 0 4px 14px rgba(79, 70, 229, 0.4);
            cursor: pointer;
            z-index: 999999;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: transform 0.3s ease,
                background-color 0.3s ease;
        }

        #ai-chat-button:hover {
            transform: scale(1.08);
            background-color: #4338ca;
        }

        #ai-chat-button svg {
            width: 28px;
            height: 28px;
            fill: currentColor;
        }

        #ai-chat-box {
            position: fixed;
            bottom: 90px;
            left: 20px;
            width: 360px;
            max-width: calc(100vw - 40px);
            height: 520px;
            max-height: calc(100vh - 120px);
            background-color: #ffffff;
            border-radius: 16px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15);
            border: 1px solid #e2e8f0;
            z-index: 999999;
            display: none;
            flex-direction: column;
            overflow: hidden;
        }

        #ai-chat-box.active {
            display: flex;
        }

        .ai-chat-header {
            background-color: #4f46e5;
            color: #ffffff;
            padding: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .ai-chat-header h4 {
            margin: 0;
            font-size: 16px;
            font-weight: 600;
        }

        .ai-chat-header .close-btn {
            background: none;
            border: none;
            color: #ffffff;
            font-size: 20px;
            cursor: pointer;
            line-height: 1;
            padding: 0;
        }

        .ai-chat-messages {
            flex: 1;
            padding: 16px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background-color: #f8fafc;
        }

        .ai-message {
            max-width: 80%;
            padding: 10px 14px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.5;
            word-wrap: break-word;
            white-space: pre-wrap;
        }

        .ai-message.bot {
            align-self: flex-start;
            background-color: #ffffff;
            color: #1e293b;
            border: 1px solid #e2e8f0;
            border-bottom-right-radius: 2px;
        }

        .ai-message.user {
            align-self: flex-end;
            background-color: #4f46e5;
            color: #ffffff;
            border-bottom-left-radius: 2px;
        }

        .ai-message.typing {
            align-self: flex-start;
            background-color: #e2e8f0;
            color: #64748b;
            font-style: italic;
            font-size: 12px;
        }

        .ai-chat-input-container {
            padding: 12px;
            background-color: #ffffff;
            border-top: 1px solid #e2e8f0;
            display: flex;
            gap: 8px;
        }

        .ai-chat-input-container input {
            flex: 1;
            min-width: 0;
            padding: 10px 14px;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            outline: none;
            font-size: 14px;
        }

        .ai-chat-input-container input:focus {
            border-color: #4f46e5;
        }

        .ai-chat-input-container button {
            background-color: #4f46e5;
            color: #ffffff;
            border: none;
            padding: 10px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
        }

        .ai-chat-input-container button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        @media (max-width: 480px) {
            #ai-chat-box {
                left: 10px;
                bottom: 85px;
                width: calc(100vw - 20px);
                max-width: none;
                height: calc(100vh - 110px);
            }

            #ai-chat-button {
                left: 15px;
                bottom: 15px;
            }
        }
    `;

    const styleSheet = document.createElement("style");
    styleSheet.textContent = widgetStyles;
    document.head.appendChild(styleSheet);

    const widgetContainer = document.createElement("div");
    widgetContainer.id = "ai-chat-widget-container";

    widgetContainer.innerHTML = `
        <button id="ai-chat-button" aria-label="فتح المحادثة">
            <svg viewBox="0 0 24 24">
                <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"/>
            </svg>
        </button>

        <div id="ai-chat-box">
            <div class="ai-chat-header">
                <h4>مساعد المتجر الذكي 🤖</h4>
                <button
                    class="close-btn"
                    id="ai-chat-close"
                    type="button"
                    aria-label="إغلاق"
                >
                    &times;
                </button>
            </div>

            <div
                class="ai-chat-messages"
                id="ai-chat-messages"
            >
                <div class="ai-message bot">
                    مرحباً بك! كيف يمكنني مساعدتك اليوم؟
                </div>
            </div>

            <form
                class="ai-chat-input-container"
                id="ai-chat-form"
            >
                <input
                    type="text"
                    id="ai-chat-input"
                    placeholder="اكتب استفسارك هنا..."
                    required
                    autocomplete="off"
                />

                <button type="submit" id="ai-chat-send">
                    إرسال
                </button>
            </form>
        </div>
    `;

    document.body.appendChild(widgetContainer);

    const chatBtn =
        document.getElementById("ai-chat-button");

    const chatBox =
        document.getElementById("ai-chat-box");

    const closeBtn =
        document.getElementById("ai-chat-close");

    const chatForm =
        document.getElementById("ai-chat-form");

    const chatInput =
        document.getElementById("ai-chat-input");

    const sendBtn =
        document.getElementById("ai-chat-send");

    const messagesContainer =
        document.getElementById("ai-chat-messages");

    chatBtn.addEventListener("click", function () {
        chatBox.classList.toggle("active");

        if (chatBox.classList.contains("active")) {
            chatInput.focus();
        }
    });

    closeBtn.addEventListener("click", function () {
        chatBox.classList.remove("active");
    });

    chatForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const userMsg = chatInput.value.trim();

        if (!userMsg) {
            return;
        }

        appendMessage(userMsg, "user");

        chatInput.value = "";
        chatInput.disabled = true;
        sendBtn.disabled = true;

        const typingIndicator =
            appendMessage(
                "جاري التفكير...",
                "typing"
            );

        try {
            const response = await fetch(
                `${baseUrl}/api/chat`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        store_id: storeId,
                        message: userMsg,
                        sender_id: senderId
                    })
                }
            );

            let data = {};

            try {
                data = await response.json();
            } catch (_) {
                data = {};
            }

            typingIndicator.remove();

            if (response.ok) {
                appendMessage(
                    data.reply ||
                    "لم يتم استلام رد.",
                    "bot"
                );
            } else {
                appendMessage(
                    data.detail ||
                    "عذراً، حدث خطأ أثناء الاتصال بالخادم.",
                    "bot"
                );
            }
        } catch (error) {
            console.error(
                "AI Chat Widget Error:",
                error
            );

            typingIndicator.remove();

            appendMessage(
                "تعذر الاتصال بالخادم. يرجى المحاولة مرة أخرى.",
                "bot"
            );
        } finally {
            chatInput.disabled = false;
            sendBtn.disabled = false;
            chatInput.focus();
        }
    });

    function appendMessage(text, type) {
        const msgDiv =
            document.createElement("div");

        msgDiv.className =
            `ai-message ${type}`;

        msgDiv.textContent = text;

        messagesContainer.appendChild(msgDiv);

        messagesContainer.scrollTop =
            messagesContainer.scrollHeight;

        return msgDiv;
    }
})();
