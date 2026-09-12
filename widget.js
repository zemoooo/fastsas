(function () {
    "use strict";

    /* =========================================================
       PREVENT DUPLICATE WIDGET
       يمنع إنشاء الويدجت أكثر من مرة
    ========================================================== */

    if (window.__SMART_AI_STORE_WIDGET_INITIALIZED__) {
        console.warn(
            "AI Chat Widget: الويدجت موجود بالفعل ولن يتم تكراره."
        );
        return;
    }

    window.__SMART_AI_STORE_WIDGET_INITIALIZED__ = true;


    /* =========================================================
       FIND CURRENT SCRIPT
    ========================================================== */

    const currentScript =
        document.currentScript ||
        document.querySelector(
            'script[data-store-id]'
        );


    if (!currentScript) {
        console.error(
            "AI Chat Widget: لم يتم العثور على script[data-store-id]."
        );

        window.__SMART_AI_STORE_WIDGET_INITIALIZED__ = false;

        return;
    }


    /* =========================================================
       STORE ID
    ========================================================== */

    const storeId =
        currentScript.getAttribute(
            "data-store-id"
        );


    if (!storeId) {
        console.error(
            "AI Chat Widget: لم يتم العثور على data-store-id."
        );

        window.__SMART_AI_STORE_WIDGET_INITIALIZED__ = false;

        return;
    }


    /* =========================================================
       SERVER BASE URL
    ========================================================== */

    const scriptSrc =
        currentScript.src;


    if (!scriptSrc) {
        console.error(
            "AI Chat Widget: تعذر تحديد رابط الخادم."
        );

        window.__SMART_AI_STORE_WIDGET_INITIALIZED__ = false;

        return;
    }


    const baseUrl =
        new URL(
            scriptSrc,
            window.location.href
        ).origin;


    /* =========================================================
       SENDER ID
    ========================================================== */

    let senderId =
        localStorage.getItem(
            "ai_widget_sender_id"
        );


    if (!senderId) {

        senderId =
            "user_" +
            Math.random()
                .toString(36)
                .substring(2, 11);

        try {
            localStorage.setItem(
                "ai_widget_sender_id",
                senderId
            );
        } catch (error) {
            console.warn(
                "AI Chat Widget: تعذر حفظ sender_id.",
                error
            );
        }
    }


    /* =========================================================
       REMOVE ANY OLD INSTANCE
       حماية إضافية من التكرار
    ========================================================== */

    const existingContainer =
        document.getElementById(
            "ai-chat-widget-container"
        );


    if (existingContainer) {
        existingContainer.remove();
    }


    const existingStyles =
        document.getElementById(
            "ai-chat-widget-styles"
        );


    if (existingStyles) {
        existingStyles.remove();
    }


    /* =========================================================
       STYLES
    ========================================================== */

    const widgetStyles = `
        #ai-chat-widget-container {
            all: initial;
            direction: rtl;
            font-family:
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                Roboto,
                "Helvetica Neue",
                Arial,
                sans-serif;
        }

        #ai-chat-widget-container *,
        #ai-chat-widget-container *::before,
        #ai-chat-widget-container *::after {
            box-sizing: border-box;
            font-family:
                system-ui,
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                Roboto,
                "Helvetica Neue",
                Arial,
                sans-serif;
        }

        #ai-chat-button {
            position: fixed;
            bottom: 20px;
            left: 20px;

            width: 60px;
            height: 60px;

            margin: 0;
            padding: 0;

            border: none;
            border-radius: 50%;

            background-color: #4f46e5;
            color: #ffffff;

            box-shadow:
                0 4px 14px
                rgba(79, 70, 229, 0.4);

            cursor: pointer;

            z-index: 999999;

            display: flex;
            align-items: center;
            justify-content: center;

            transition:
                transform 0.3s ease,
                background-color 0.3s ease;
        }

        #ai-chat-button:hover {
            transform: scale(1.08);
            background-color: #4338ca;
        }

        #ai-chat-button:focus {
            outline: none;
            box-shadow:
                0 0 0 4px
                rgba(79, 70, 229, 0.2),
                0 4px 14px
                rgba(79, 70, 229, 0.4);
        }

        #ai-chat-button svg {
            width: 28px;
            height: 28px;
            fill: currentColor;
            display: block;
        }

        #ai-chat-box {
            position: fixed;

            bottom: 90px;
            left: 20px;

            width: 360px;
            max-width:
                calc(100vw - 40px);

            height: 520px;
            max-height:
                calc(100vh - 120px);

            margin: 0;
            padding: 0;

            background-color: #ffffff;

            border:
                1px solid #e2e8f0;

            border-radius: 16px;

            box-shadow:
                0 10px 25px
                rgba(0, 0, 0, 0.15);

            z-index: 999999;

            display: none;
            flex-direction: column;

            overflow: hidden;
        }

        #ai-chat-box.active {
            display: flex;
        }

        .ai-chat-header {
            flex-shrink: 0;

            background-color: #4f46e5;
            color: #ffffff;

            padding: 16px;

            display: flex;
            align-items: center;
            justify-content: space-between;

            direction: rtl;
        }

        .ai-chat-header h4 {
            margin: 0;
            padding: 0;

            color: #ffffff;

            font-size: 16px;
            font-weight: 600;

            line-height: 1.5;
        }

        .ai-chat-header .close-btn {
            margin: 0;
            padding: 0;

            background: transparent;
            border: none;

            color: #ffffff;

            font-size: 24px;
            line-height: 1;

            cursor: pointer;
        }

        .ai-chat-header .close-btn:hover {
            opacity: 0.8;
        }

        .ai-chat-header .close-btn:focus {
            outline: none;
        }

        .ai-chat-messages {
            flex: 1;

            min-height: 0;

            padding: 16px;

            overflow-y: auto;

            display: flex;
            flex-direction: column;

            gap: 12px;

            background-color: #f8fafc;
        }

        .ai-message {
            max-width: 80%;

            padding:
                10px 14px;

            margin: 0;

            border-radius: 12px;

            font-size: 14px;
            line-height: 1.6;

            word-wrap: break-word;
            overflow-wrap: anywhere;

            white-space: pre-wrap;

            direction: rtl;
            text-align: right;
        }

        .ai-message.bot {
            align-self: flex-start;

            background-color: #ffffff;
            color: #1e293b;

            border:
                1px solid #e2e8f0;

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

            border:
                1px solid #dbe3ec;
        }

        .ai-chat-input-container {
            flex-shrink: 0;

            padding: 12px;

            background-color: #ffffff;

            border-top:
                1px solid #e2e8f0;

            display: flex;
            align-items: center;

            gap: 8px;

            direction: rtl;
        }

        .ai-chat-input-container input {
            flex: 1;

            min-width: 0;

            margin: 0;
            padding:
                10px 14px;

            border:
                1px solid #cbd5e1;

            border-radius: 8px;

            outline: none;

            background-color: #ffffff;
            color: #1e293b;

            font-size: 14px;

            direction: rtl;
            text-align: right;
        }

        .ai-chat-input-container input::placeholder {
            color: #94a3b8;
        }

        .ai-chat-input-container input:focus {
            border-color: #4f46e5;

            box-shadow:
                0 0 0 2px
                rgba(79, 70, 229, 0.08);
        }

        .ai-chat-input-container input:disabled {
            background-color: #f8fafc;
        }

        .ai-chat-input-container button {
            flex-shrink: 0;

            margin: 0;
            padding:
                10px 16px;

            border: none;
            border-radius: 8px;

            background-color: #4f46e5;
            color: #ffffff;

            cursor: pointer;

            font-size: 14px;
            font-weight: 600;

            white-space: nowrap;

            transition:
                background-color 0.2s ease,
                opacity 0.2s ease;
        }

        .ai-chat-input-container button:hover {
            background-color: #4338ca;
        }

        .ai-chat-input-container button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        @media (max-width: 480px) {

            #ai-chat-box {
                left: 10px;
                bottom: 85px;

                width:
                    calc(100vw - 20px);

                max-width: none;

                height:
                    calc(100vh - 110px);

                max-height: none;

                border-radius: 14px;
            }

            #ai-chat-button {
                left: 15px;
                bottom: 15px;

                width: 58px;
                height: 58px;
            }

            .ai-message {
                max-width: 88%;
            }

        }
    `;


    /* =========================================================
       ADD STYLES
    ========================================================== */

    const styleSheet =
        document.createElement(
            "style"
        );


    styleSheet.id =
        "ai-chat-widget-styles";


    styleSheet.textContent =
        widgetStyles;


    document.head.appendChild(
        styleSheet
    );


    /* =========================================================
       CREATE CONTAINER
    ========================================================== */

    const widgetContainer =
        document.createElement(
            "div"
        );


    widgetContainer.id =
        "ai-chat-widget-container";


    widgetContainer.innerHTML = `
        <button
            id="ai-chat-button"
            type="button"
            aria-label="فتح المحادثة"
            aria-controls="ai-chat-box"
            aria-expanded="false"
        >
            <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
            >
                <path
                    d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"
                />
            </svg>
        </button>

        <div
            id="ai-chat-box"
            role="dialog"
            aria-label="مساعد المتجر الذكي"
            aria-hidden="true"
        >

            <div class="ai-chat-header">

                <h4>
                    مساعد المتجر الذكي 🤖
                </h4>

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
                aria-live="polite"
                aria-atomic="false"
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
                    maxlength="2000"
                    aria-label="رسالتك"
                />

                <button
                    type="submit"
                    id="ai-chat-send"
                >
                    إرسال
                </button>

            </form>

        </div>
    `;


    document.body.appendChild(
        widgetContainer
    );


    /* =========================================================
       ELEMENTS
    ========================================================== */

    const chatBtn =
        document.getElementById(
            "ai-chat-button"
        );


    const chatBox =
        document.getElementById(
            "ai-chat-box"
        );


    const closeBtn =
        document.getElementById(
            "ai-chat-close"
        );


    const chatForm =
        document.getElementById(
            "ai-chat-form"
        );


    const chatInput =
        document.getElementById(
            "ai-chat-input"
        );


    const sendBtn =
        document.getElementById(
            "ai-chat-send"
        );


    const messagesContainer =
        document.getElementById(
            "ai-chat-messages"
        );


    /* =========================================================
       OPEN / CLOSE
    ========================================================== */

    function openChat() {

        chatBox.classList.add(
            "active"
        );

        chatBox.setAttribute(
            "aria-hidden",
            "false"
        );

        chatBtn.setAttribute(
            "aria-expanded",
            "true"
        );

        setTimeout(
            function () {
                chatInput.focus();
            },
            50
        );
    }


    function closeChat() {

        chatBox.classList.remove(
            "active"
        );

        chatBox.setAttribute(
            "aria-hidden",
            "true"
        );

        chatBtn.setAttribute(
            "aria-expanded",
            "false"
        );
    }


    chatBtn.addEventListener(
        "click",
        function () {

            if (
                chatBox.classList.contains(
                    "active"
                )
            ) {

                closeChat();

            } else {

                openChat();

            }

        }
    );


    closeBtn.addEventListener(
        "click",
        function () {

            closeChat();

        }
    );


    /* =========================================================
       ESC TO CLOSE
    ========================================================== */

    document.addEventListener(
        "keydown",
        function (event) {

            if (
                event.key === "Escape" &&
                chatBox.classList.contains(
                    "active"
                )
            ) {

                closeChat();

            }

        }
    );


    /* =========================================================
       SEND MESSAGE
    ========================================================== */

    chatForm.addEventListener(
        "submit",
        async function (event) {

            event.preventDefault();


            const userMsg =
                chatInput.value.trim();


            if (!userMsg) {
                return;
            }


            appendMessage(
                userMsg,
                "user"
            );


            chatInput.value =
                "";


            chatInput.disabled =
                true;


            sendBtn.disabled =
                true;


            const typingIndicator =
                appendMessage(
                    "جاري التفكير...",
                    "typing"
                );


            try {

                const response =
                    await fetch(
                        `${baseUrl}/api/chat`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json",

                                "Accept":
                                    "application/json"
                            },

                            credentials:
                                "include",

                            body:
                                JSON.stringify({
                                    store_id:
                                        storeId,

                                    message:
                                        userMsg,

                                    sender_id:
                                        senderId
                                })
                        }
                    );


                let data =
                    {};


                try {

                    data =
                        await response.json();

                } catch (error) {

                    data =
                        {};

                }


                typingIndicator.remove();


                if (response.ok) {

                    appendMessage(
                        data.reply ||
                        data.response ||
                        "لم يتم استلام رد.",
                        "bot"
                    );

                } else {

                    appendMessage(
                        data.detail ||
                        data.message ||
                        "عذراً، حدث خطأ أثناء الاتصال بالخادم.",
                        "bot"
                    );

                    console.error(
                        "AI Chat Widget Server Error:",
                        response.status,
                        data
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

                chatInput.disabled =
                    false;


                sendBtn.disabled =
                    false;


                setTimeout(
                    function () {
                        chatInput.focus();
                    },
                    50
                );

            }

        }
    );


    /* =========================================================
       APPEND MESSAGE
    ========================================================== */

    function appendMessage(
        text,
        type
    ) {

        const msgDiv =
            document.createElement(
                "div"
            );


        msgDiv.className =
            `ai-message ${type}`;


        msgDiv.textContent =
            String(
                text || ""
            );


        messagesContainer.appendChild(
            msgDiv
        );


        messagesContainer.scrollTop =
            messagesContainer.scrollHeight;


        return msgDiv;

    }


    /* =========================================================
       FINAL READY MESSAGE
    ========================================================== */

    console.log(
        "AI Chat Widget initialized:",
        {
            storeId: storeId,
            baseUrl: baseUrl
        }
    );

})();
