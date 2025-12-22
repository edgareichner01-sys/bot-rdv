(function() {
    // --- CONFIGURATION ---
const API_URL = "https://bot-rdv.onrender.com/chat";// Adresse du render
    // On récupère ou on crée un ID utilisateur unique pour ce visiteur
    let userId = localStorage.getItem("bot_user_id");
    if (!userId) {
        userId = "user_" + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("bot_user_id", userId);
    }
    // On récupère le client_id depuis le script HTML (data-client-id)
    const scriptTag = document.currentScript;
    const clientId = scriptTag.getAttribute("data-client-id") || "demo";

    // --- 1. CRÉATION DU DESIGN (VISUEL) ---
    
    // La Bulle
    const bubble = document.createElement('div');
    bubble.innerText = "💬";
    Object.assign(bubble.style, {
        position: 'fixed', bottom: '20px', right: '20px', width: '60px', height: '60px',
        backgroundColor: '#2563EB', color: 'white', borderRadius: '50%', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '30px', zIndex: '9999', transition: 'transform 0.3s'
    });
    document.body.appendChild(bubble);

    // La Fenêtre de Chat
    const chatBox = document.createElement('div');
    Object.assign(chatBox.style, {
        position: 'fixed', bottom: '90px', right: '20px', width: '350px', height: '500px',
        backgroundColor: 'white', borderRadius: '12px', boxShadow: '0 5px 20px rgba(0,0,0,0.2)',
        display: 'none', flexDirection: 'column', overflow: 'hidden', zIndex: '9999', fontFamily: 'Arial, sans-serif'
    });
    document.body.appendChild(chatBox);

    // Header
    const header = document.createElement('div');
    header.innerHTML = "Assistant RDV 🤖";
    Object.assign(header.style, { backgroundColor: '#2563EB', color: 'white', padding: '15px', fontWeight: 'bold' });
    chatBox.appendChild(header);

    // Zone des messages
    const messagesArea = document.createElement('div');
    Object.assign(messagesArea.style, { flex: '1', padding: '15px', overflowY: 'auto', backgroundColor: '#f9f9f9', display: 'flex', flexDirection: 'column', gap: '10px' });
    chatBox.appendChild(messagesArea);

    // Zone de saisie (Input)
    const inputArea = document.createElement('div');
    Object.assign(inputArea.style, { display: 'flex', borderTop: '1px solid #eee' });
    chatBox.appendChild(inputArea);

    const inputField = document.createElement('input');
    inputField.placeholder = "Écrivez votre message...";
    Object.assign(inputField.style, { flex: '1', padding: '15px', border: 'none', outline: 'none' });
    inputArea.appendChild(inputField);

    const sendBtn = document.createElement('button');
    sendBtn.innerText = "➤";
    Object.assign(sendBtn.style, { padding: '0 20px', backgroundColor: 'transparent', border: 'none', cursor: 'pointer', color: '#2563EB', fontSize: '18px' });
    inputArea.appendChild(sendBtn);

    // --- 2. FONCTIONS UTILES ---

    function addMessage(text, sender) {
        const msgDiv = document.createElement('div');
        msgDiv.innerText = text;
        Object.assign(msgDiv.style, {
            maxWidth: '80%', padding: '10px', borderRadius: '10px', fontSize: '14px', lineHeight: '1.4',
            alignSelf: sender === 'user' ? 'flex-end' : 'flex-start',
            backgroundColor: sender === 'user' ? '#2563EB' : '#E5E7EB',
            color: sender === 'user' ? 'white' : 'black'
        });
        messagesArea.appendChild(msgDiv);
        messagesArea.scrollTop = messagesArea.scrollHeight; // Auto-scroll vers le bas
    }

    async function sendMessage() {
        const text = inputField.value.trim();
        if (!text) return;

        // 1. Affiche le message de l'utilisateur
        addMessage(text, 'user');
        inputField.value = "";

        // 2. Envoie au serveur (Python)
        try {
            const response = await fetch(API_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    client_id: clientId,
                    user_id: userId,
                    message: text
                })
            });
            const data = await response.json();
            
            // 3. Affiche la réponse du bot
            addMessage(data.reply, 'bot');

        } catch (error) {
            console.error(error);
            addMessage("❌ Erreur de connexion au serveur.", 'bot');
        }
    }

    // --- 3. ÉVÉNEMENTS (CLICS) ---

    // Ouvrir / Fermer
    bubble.onclick = () => {
        const isClosed = chatBox.style.display === 'none';
        chatBox.style.display = isClosed ? 'flex' : 'none';
        bubble.innerText = isClosed ? "❌" : "💬";
        if (isClosed) inputField.focus();
    };

    // Envoyer avec le bouton ou "Entrée"
    sendBtn.onclick = sendMessage;
    inputField.onkeypress = (e) => { if (e.key === 'Enter') sendMessage(); };

})();