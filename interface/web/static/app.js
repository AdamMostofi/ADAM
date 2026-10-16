document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupChat();
    setupMemory();
    setupGraph();
    setupSkills();
    setupSettings();
});

function setupTabs() {
    document.querySelectorAll('.tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
            if (btn.dataset.tab === 'graph') loadGraph();
            if (btn.dataset.tab === 'memory') loadMemory();
            if (btn.dataset.tab === 'skills') loadSkills();
            if (btn.dataset.tab === 'settings') loadStats();
        });
    });
}

function setupChat() {
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const messages = document.getElementById('chat-messages');
    const loading = document.getElementById('loading');
    const modeToggle = document.getElementById('mode-toggle');

    sendBtn.addEventListener('click', sendMessage);
    input.addEventListener('keypress', e => { if (e.key === 'Enter') sendMessage(); });

    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        appendMessage('user', text);
        loading.classList.remove('hidden');
        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, mode: modeToggle.value })
            });
            const data = await res.json();
            const meta = `tone: ${data.state.emotional_tone} | warmth: ${data.params.warmth} | depth: ${data.params.depth}`;
            appendMessage('adam', data.response, meta);
        } catch (e) {
            appendMessage('adam', 'Error: ' + e.message, 'error');
        }
        loading.classList.add('hidden');
    }

    function appendMessage(role, text, meta) {
        const div = document.createElement('div');
        div.className = `chat-msg ${role}`;
        div.innerHTML = `<div>${escapeHtml(text)}</div>${meta ? `<div class="meta">${escapeHtml(meta)}</div>` : ''}`;
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }
}

function setupMemory() {
    document.getElementById('memory-refresh').addEventListener('click', loadMemory);
    document.getElementById('memory-search').addEventListener('keypress', e => { if (e.key === 'Enter') loadMemory(); });
}

async function loadMemory() {
    const q = document.getElementById('memory-search').value;
    const list = document.getElementById('memory-list');
    const url = q ? `/api/facts?q=${encodeURIComponent(q)}` : '/api/facts';
    try {
        const res = await fetch(url);
        const data = await res.json();
        list.innerHTML = data.map(f => `
            <div class="memory-item">
                <div class="fact-text">${escapeHtml(f.subject)} ${escapeHtml(f.predicate)} ${escapeHtml(f.object)}</div>
                <div class="fact-meta">confidence: ${(f.confidence * 100).toFixed(0)}%${f.similarity ? ` | similarity: ${(f.similarity * 100).toFixed(0)}%` : ''}</div>
            </div>
        `).join('') || '<div class="memory-item">No memories found.</div>';
    } catch (e) { list.innerHTML = `<div class="memory-item">Error: ${escapeHtml(e.message)}</div>`; }
}

function setupGraph() {}

async function loadGraph() {
    const container = document.getElementById('graph-container');
    try {
        const res = await fetch('/api/graph');
        const data = await res.json();
        const nodes = new vis.DataSet(data.nodes.map(n => ({ ...n, color: '#58a6ff' })));
        const edges = new vis.DataSet(data.edges.map(e => ({ ...e, color: '#30363d', arrows: 'to' })));
        new vis.Network(container, { nodes, edges }, {
            physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -50 } },
            nodes: { shape: 'dot', size: 12, font: { color: '#c9d1d9' } },
            interaction: { hover: true }
        });
    } catch (e) { container.innerHTML = `<p style="padding:20px">Error: ${escapeHtml(e.message)}</p>`; }
}

function setupSkills() {}

async function loadSkills() {
    const list = document.getElementById('skills-list');
    try {
        const res = await fetch('/api/skills');
        const data = await res.json();
        list.innerHTML = data.map(s => `
            <div class="skill-item">
                <div class="skill-name">${escapeHtml(s.name)}</div>
                <div class="skill-domain">${escapeHtml(s.domain)}</div>
                <div class="skill-confidence">confidence: ${(s.confidence * 100).toFixed(0)}%</div>
            </div>
        `).join('') || '<div class="skill-item">No skills compiled yet.</div>';
    } catch (e) { list.innerHTML = `<div class="skill-item">Error: ${escapeHtml(e.message)}</div>`; }
}

function setupSettings() {
    document.getElementById('save-btn').addEventListener('click', async () => {
        await fetch('/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        alert('State saved.');
    });
    document.getElementById('add-fact-btn').addEventListener('click', () => {
        document.getElementById('add-fact-form').classList.toggle('hidden');
    });
    document.getElementById('fact-submit').addEventListener('click', async () => {
        const s = document.getElementById('fact-subject').value.trim();
        const p = document.getElementById('fact-predicate').value.trim();
        const o = document.getElementById('fact-object').value.trim();
        if (!s || !p || !o) return alert('All fields required');
        await fetch('/api/facts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ subject: s, predicate: p, object: o }) });
        document.getElementById('fact-subject').value = '';
        document.getElementById('fact-predicate').value = '';
        document.getElementById('fact-object').value = '';
        document.getElementById('add-fact-form').classList.add('hidden');
        alert('Fact added.');
    });
}

async function loadStats() {
    const panel = document.getElementById('stats-panel');
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        panel.innerHTML = `
            <div class="stat-row"><span class="stat-label">Facts</span><span class="stat-value">${data.facts}</span></div>
            <div class="stat-row"><span class="stat-label">Skills</span><span class="stat-value">${data.skills}</span></div>
            <div class="stat-row"><span class="stat-label">Graph Nodes</span><span class="stat-value">${data.nodes}</span></div>
            <div class="stat-row"><span class="stat-label">Graph Edges</span><span class="stat-value">${data.edges}</span></div>
            <div class="stat-row"><span class="stat-label">EQ Baseline</span><span class="stat-value">${data.baseline.toFixed(2)}</span></div>
            <div class="stat-row"><span class="stat-label">Mood Shift</span><span class="stat-value">${data.mood_shift}</span></div>
        `;
    } catch (e) { panel.innerHTML = `<p>Error: ${escapeHtml(e.message)}</p>`; }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
