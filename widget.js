(function() {
    const API_URL = "https://bot-rdv.onrender.com/chat";
    let userId = localStorage.getItem("bot_user_id") || "user_" + Math.random().toString(36).substr(2, 9);
    localStorage.setItem("bot_user_id", userId);

    const scriptTag = document.currentScript;
    const clientId = scriptTag.getAttribute("data-client-id") || "garage_michel_v6";
    let chatHistory = [];

    // --- DESIGN ---
    const bubble = document.createElement('div');
    Object.assign(bubble.style, {
        position: 'fixed', bottom: '20px', right: '20px', width: '60px', height: '60px',
        borderRadius: '50%', boxShadow: '0 4px 12px rgba(0,0,0,0.3)', cursor: 'pointer', zIndex: '9999',
        backgroundImage: 'url("https://bot-rdv.onrender.com/logo.png")', backgroundSize: 'cover', backgroundColor: 'white'
    });
    document.body.appendChild(bubble);

    const chatBox = document.createElement('div');
    Object.assign(chatBox.style, {
        position: 'fixed', bottom: '90px', right: '20px', width: '350px', height: '500px',
        backgroundColor: 'white', borderRadius: '12px', boxShadow: '0 5px 20px rgba(0,0,0,0.2)',
        display: 'none', flexDirection: 'column', overflow: 'hidden', zIndex: '9999', fontFamily: 'Arial, sans-serif'
    });
    document.body.appendChild(chatBox);

    const messagesArea = document.createElement('div');
    Object.assign(messagesArea.style, { flex: '1', padding: '15px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '10px', backgroundColor: '#f9f9f9' });
    chatBox.appendChild(messagesArea);

    const inputArea = document.createElement('div');
    inputArea.style.display = 'flex';
    chatBox.appendChild(inputArea);

    const inputField = document.createElement('input');
    Object.assign(inputField.style, { flex: '1', padding: '15px', border: 'none', outline: 'none', borderTop: '1px solid #eee' });
    inputArea.appendChild(inputField);

    // --- LOGIQUE RENDU HTML (POUR LIENS) ---
    function addMessage(text, sender) {
        const msgDiv = document.createElement('div');
        
        // Transforme [Texte](Lien) en lien cliquable
        let html = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:inherit; font-weight:bold; text-decoration:underline;">$1</a>');
        html = html.replace(/\n/g, '<br>'); // Gère les sauts de ligne
        
        msgDiv.innerHTML = html;
        Object.assign(msgDiv.style, {
            maxWidth: '80%', padding: '10px', borderRadius: '10px', fontSize: '14px',
            alignSelf: sender === 'user' ? 'flex-end' : 'flex-start',
            backgroundColor: sender === 'user' ? '#2563EB' : '#E5E7EB',
            color: sender === 'user' ? 'white' : 'black'
        });
        messagesArea.appendChild(msgDiv);
        messagesArea.scrollTop = messagesArea.scrollHeight;
    }

    async function sendMessage() {
        const text = inputField.value.trim();
        if (!text) return;
        addMessage(text, 'user');
        inputField.value = "";
        try {
            const res = await fetch(`${API_URL}?clientID=${clientId}&requestID=${userId}`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text, history: chatHistory })
            });
            const data = await res.json();
            addMessage(data.reply, 'bot');
            chatHistory.push({ role: "user", content: text }, { role: "assistant", content: data.reply });
        } catch { addMessage("❌ Erreur.", 'bot'); }
    }

    bubble.onclick = () => {
        const isClosed = chatBox.style.display === 'none';
        chatBox.style.display = isClosed ? 'flex' : 'none';
        bubble.innerText = isClosed ? "❌" : "";
    };
    inputField.onkeypress = (e) => { if (e.key === 'Enter') sendMessage(); };
})();