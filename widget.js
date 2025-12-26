(function() {
    // --- CONFIGURATION ---
    const API_URL = "https://bot-rdv.onrender.com/chat";
    
    // On récupère ou on crée un ID utilisateur unique
    let userId = localStorage.getItem("bot_user_id");
    if (!userId) {
        userId = "user_" + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("bot_user_id", userId);
    }

    // Récupération de l'ID du garage Michel
    const scriptTag = document.currentScript;
    const clientId = scriptTag.getAttribute("data-client-id") || "garage_michel_v6";

    // Tableau pour mémoriser la discussion
    let chatHistory = [];

    // --- 1. CRÉATION DU DESIGN ---
    const bubble = document.createElement('div');
    bubble.innerText = "💬";
    Object.assign(bubble.style, {
        position: 'fixed', bottom: '20px', right: '20px', width: '60px', height: '60px',
        backgroundColor: '#2563EB', color: 'white', borderRadius: '50%', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '30px', zIndex: '9999'
    });
    document.body.appendChild(bubble);

    const chatBox = document.createElement('div');
    Object.assign(chatBox.style, {
        position: 'fixed', bottom: '90px', right: '20px', width: '350px', height: '500px',
        backgroundColor: 'white', borderRadius: '12px', boxShadow: '0 5px 20px rgba(0,0,0,0.2)',
        display: 'none', flexDirection: 'column', overflow: 'hidden', zIndex: '9999', fontFamily: 'Arial, sans-serif'
    });
    document.body.appendChild(chatBox);

    const header = document.createElement('div');
    header.innerHTML = "Garage Michel 🤖";
    Object.assign(header.style, { backgroundColor: '#2563EB', color: 'white', padding: '15px', fontWeight: 'bold' });
    chatBox.appendChild(header);

    const messagesArea = document.createElement('div');
    Object.assign(messagesArea.style, { flex: '1', padding: '15px', overflowY: 'auto', backgroundColor: '#f9f9f9', display: 'flex', flexDirection: 'column', gap: '10px' });
    chatBox.appendChild(messagesArea);

    const inputArea = document.createElement('div');
    Object.assign(inputArea.style, { display: 'flex', borderTop: '1px solid #eee' });
    chatBox.appendChild(inputArea);

    const inputField = document.createElement('input');
    inputField.placeholder = "Écrivez ici...";
    Object.assign(inputField.style, { flex: '1', padding: '15px', border: 'none', outline: 'none' });
    inputArea.appendChild(inputField);

    const sendBtn = document.createElement('button');
    sendBtn.innerText = "➤";
    Object.assign(sendBtn.style, { padding: '0 20px', backgroundColor: 'transparent', border: 'none', cursor: 'pointer', color: '#2563EB', fontSize: '18px' });
    inputArea.appendChild(sendBtn);

    // --- 2. LOGIQUE DE COMMUNICATION ---

    function addMessage(text, sender) {
        const msgDiv = document.createElement('div');
        msgDiv.innerText = text;
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

        // On construit l'URL avec les paramètres attendus par Python (clientID et requestID)
        const targetUrl = `${API_URL}?clientID=${clientId}&requestID=${userId}`;

        try {
            const response = await fetch(targetUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    history: chatHistory // Envoie l'historique pour l'intelligence
                })
            });
            const data = await response.json();
            
            addMessage(data.reply, 'bot');
            
            // Mise à jour de l'historique pour le prochain message
            chatHistory.push({ role: "user", content: text });
            chatHistory.push({ role: "assistant", content: data.reply });

        } catch (error) {
            addMessage("❌ Erreur de connexion.", 'bot');
        }
    }

    bubble.onclick = () => {
        const isClosed = chatBox.style.display === 'none';
        chatBox.style.display = isClosed ? 'flex' : 'none';
        bubble.innerText = isClosed ? "❌" : "💬";
    };

    sendBtn.onclick = sendMessage;
    inputField.onkeypress = (e) => { if (e.key === 'Enter') sendMessage(); };
})();