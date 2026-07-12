(() => {
  // ── Canvas — grid gris que se ilumina con el cursor ──
  const canvas = document.getElementById('bg-canvas');
  const ctx    = canvas.getContext('2d');

  const GRID = 48;
  let W = 0, H = 0;
  let mx = -9999, my = -9999;
  let tx = -9999, ty = -9999;
  let sidebarW = 260; // se actualiza dinámicamente

  function resizeCanvas() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function drawGrid(sw) {
    ctx.beginPath();
    for (let x = sw; x <= W + GRID; x += GRID) {
      ctx.moveTo(x, 0);
      ctx.lineTo(x, H);
    }
    for (let y = 0; y <= H + GRID; y += GRID) {
      ctx.moveTo(sw, y);
      ctx.lineTo(W, y);
    }
    ctx.stroke();
  }

  function frame() {
    // Leer ancho real del sidebar en cada frame
    const sidebarEl = document.querySelector('.sidebar');
    sidebarW = sidebarEl ? sidebarEl.getBoundingClientRect().width : 260;

    mx += (tx - mx) * 0.14;
    my += (ty - my) * 0.14;

    ctx.clearRect(0, 0, W, H);

    ctx.save();
    ctx.beginPath();
    ctx.rect(sidebarW, 0, W - sidebarW, H);
    ctx.clip();
    ctx.lineWidth = 1;

    ctx.strokeStyle = 'rgba(0,0,0,0.07)';
    drawGrid(sidebarW);

    if (mx > sidebarW) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(mx, my, 28, 0, Math.PI * 2);
      ctx.clip();
      ctx.strokeStyle = 'rgba(0,0,0,0.30)';
      drawGrid(sidebarW);
      ctx.restore();

      ctx.save();
      ctx.beginPath();
      ctx.arc(mx, my, 14, 0, Math.PI * 2);
      ctx.clip();
      ctx.strokeStyle = 'rgba(0,0,0,0.60)';
      drawGrid(sidebarW);
      ctx.restore();

      ctx.save();
      ctx.beginPath();
      ctx.arc(mx, my, 6, 0, Math.PI * 2);
      ctx.clip();
      ctx.strokeStyle = 'rgba(0,0,0,0.90)';
      drawGrid(sidebarW);
      ctx.restore();
    }

    ctx.restore();
    requestAnimationFrame(frame);
  }

  window.addEventListener('resize',    resizeCanvas);
  window.addEventListener('mousemove', e => { tx = e.clientX; ty = e.clientY; });
  resizeCanvas();
  requestAnimationFrame(frame);

  // ── DOM refs ─────────────────────────────────────
  const chatArea      = document.getElementById('chat-area');
  const msgInput      = document.getElementById('msg-input');
  const sendBtn       = document.getElementById('send-btn');
  const chatList      = document.getElementById('chat-list');
  const newChatBtn    = document.getElementById('new-chat-btn');
  const cmdChips      = document.getElementById('cmd-chips');
  const mainEl        = document.querySelector('.main');
  const sidebar       = document.querySelector('.sidebar');
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const sidebarOpen   = document.getElementById('sidebar-open');

  // ── Sidebar toggle ────────────────────────────────
  function toggleSidebar(open) {
    const isOpen = open !== undefined ? open : sidebar.classList.contains('collapsed');
    sidebar.classList.toggle('collapsed', !isOpen);
    sidebarOpen.style.display = isOpen ? 'none' : 'flex';
  }

  sidebarToggle.addEventListener('click', () => toggleSidebar());
  sidebarOpen.addEventListener('click',   () => toggleSidebar(true));

  // ── Conversations (localStorage) ─────────────────
  const STORE = 'congreso_convs';
  let convs    = [];
  let activeId = null;
  let streaming= false;

  function loadConvs() {
    try { convs = JSON.parse(localStorage.getItem(STORE)) || []; }
    catch { convs = []; }
  }

  function saveConvs() {
    localStorage.setItem(STORE, JSON.stringify(convs));
  }

  function getActive() {
    return convs.find(c => c.id === activeId) || null;
  }

  function newChat() {
    const id = Date.now().toString();
    convs.unshift({ id, title: 'Nueva conversación', messages: [], ts: Date.now() });
    activeId = id;
    saveConvs();
    renderSidebar();
    showWelcome();
  }

  function switchConv(id) {
    if (id === activeId) return;
    chatArea.classList.add('fading');
    setTimeout(() => {
      activeId = id;
      renderSidebar();
      renderMessages();
      chatArea.classList.remove('fading');
    }, 160);
  }

  function deleteConv(id, e) {
    e.stopPropagation();
    convs = convs.filter(c => c.id !== id);
    if (activeId === id) {
      activeId = convs[0]?.id || null;
    }
    saveConvs();
    renderSidebar();
    if (activeId) renderMessages(); else showWelcome();
  }

  function autoTitle(text) {
    return text.slice(0, 38) + (text.length > 38 ? '…' : '');
  }

  // ── Sidebar render ────────────────────────────────
  function renderSidebar() {
    chatList.innerHTML = '';

    if (!convs.length) {
      chatList.innerHTML = '<div style="padding:16px 10px;font-size:12px;color:var(--text-dim)">Sin conversaciones</div>';
      return;
    }

    const groups = groupByDate(convs);

    for (const [label, items] of groups) {
      if (!items.length) continue;
      const gl = document.createElement('div');
      gl.className = 'chat-group-label';
      gl.textContent = label;
      chatList.appendChild(gl);

      for (const c of items) {
        const el = document.createElement('div');
        el.className = 'chat-item' + (c.id === activeId ? ' active' : '');
        el.dataset.id = c.id;
        el.innerHTML = `
          <span class="chat-item-icon">
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 4h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H7l-4 2V5a1 1 0 0 1 1-1z"/>
            </svg>
          </span>
          <span class="chat-item-title">${escHtml(c.title)}</span>
          <button class="chat-item-del" title="Eliminar">✕</button>`;
        el.addEventListener('click', () => {
          el.classList.add('clicking');
          el.addEventListener('animationend', () => el.classList.remove('clicking'), { once: true });
          switchConv(c.id);
        });
        el.querySelector('.chat-item-del').addEventListener('click', ev => deleteConv(c.id, ev));
        chatList.appendChild(el);
      }
    }
  }

  function groupByDate(list) {
    const now   = Date.now();
    const DAY   = 86400000;
    const today = []; const yesterday = []; const week = []; const older = [];
    for (const c of list) {
      const age = now - c.ts;
      if (age < DAY)         today.push(c);
      else if (age < 2*DAY)  yesterday.push(c);
      else if (age < 7*DAY)  week.push(c);
      else                   older.push(c);
    }
    return [['Hoy', today], ['Ayer', yesterday], ['Últimos 7 días', week], ['Anteriores', older]];
  }

  // ── Message rendering ─────────────────────────────
  function showWelcome() {
    mainEl.classList.remove('chat-mode');
    chatArea.innerHTML = `
      <div class="welcome">
        <div class="tw-main">
          <span id="tw-text"></span><span class="tw-cursor"></span>
        </div>
      </div>`;
    startTypewriter();
    cmdChips.style.display = 'flex';
  }

  function renderMessages() {
    const conv = getActive();
    if (!conv || !conv.messages.length) { showWelcome(); return; }
    mainEl.classList.add('chat-mode');
    chatArea.innerHTML = '';
    cmdChips.style.display = 'none';
    for (const m of conv.messages) {
      if (m.role === 'user')      appendUserBubble(m.content);
      else if (m.role === 'assistant') appendAssistantBubble(m.content);
    }
    scrollBottom();
  }

  // ── Chat send ─────────────────────────────────────
  async function send(textOverride) {
    const text = (textOverride || msgInput.value).trim();
    if (!text || streaming) return;

    // Create conversation if none active
    if (!activeId || !getActive()) newChat();
    const conv = getActive();

    // First message → auto-title
    if (!conv.messages.length) {
      conv.title = autoTitle(text);
    }

    mainEl.classList.add('chat-mode');
    chatArea.querySelector('.welcome')?.remove();
    cmdChips.style.display = 'none';

    conv.messages.push({ role: 'user', content: text });
    saveConvs();
    renderSidebar();
    appendUserBubble(text);

    msgInput.value = '';
    msgInput.style.height = 'auto';
    sendBtn.disabled = true;
    streaming = true;

    const assistantEl = appendAssistantTyping();
    let fullText = '';

    try {
      const resp = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: conv.messages }),
      });

      const reader  = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (raw === '[DONE]') continue;
          try {
            const obj = JSON.parse(raw);
            if (obj.error)  { renderContent(assistantEl, `**Error:** ${obj.error}`); break; }
            if (obj.status) { assistantEl.innerHTML = `<span class="fetch-status">${escHtml(obj.status)}</span>`; scrollBottom(); }
            if (obj.text)   {
              fullText += obj.text;
              renderContent(assistantEl, fullText);
              scrollBottom();
            }
          } catch { /* ignore */ }
        }
      }
    } catch (err) {
      renderContent(assistantEl, `**Error de conexión:** ${err.message}`);
    }

    if (fullText) {
      conv.messages.push({ role: 'assistant', content: fullText });
      saveConvs();
      addCopyBtns(assistantEl);
    }

    streaming = false;
    sendBtn.disabled = !msgInput.value.trim();
    scrollBottom();
  }

  // ── DOM helpers ───────────────────────────────────
  const SVG_USER = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>`;
  const SVG_BOT  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="20" width="18" height="2" rx=".5"/><rect x="5" y="9" width="3" height="11" rx=".5"/><rect x="10.5" y="9" width="3" height="11" rx=".5"/><rect x="16" y="9" width="3" height="11" rx=".5"/><path d="M1 9h22M12 2L1 9h22L12 2z"/></svg>`;

  function appendUserBubble(text) {
    const d = document.createElement('div');
    d.className = 'message user';
    d.innerHTML = `<div class="msg-avatar">${SVG_USER}</div><div class="msg-content">${escHtml(text)}</div>`;
    chatArea.appendChild(d);
    scrollBottom();
  }

  function appendAssistantTyping() {
    const d = document.createElement('div');
    d.className = 'message assistant';
    d.innerHTML = `
      <div class="msg-avatar">${SVG_BOT}</div>
      <div class="msg-content">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>`;
    chatArea.appendChild(d);
    scrollBottom();
    return d.querySelector('.msg-content');
  }

  function appendAssistantBubble(md) {
    const d = document.createElement('div');
    d.className = 'message assistant';
    d.innerHTML = `<div class="msg-avatar">${SVG_BOT}</div><div class="msg-content"></div>`;
    chatArea.appendChild(d);
    const el = d.querySelector('.msg-content');
    renderContent(el, md);
    addCopyBtns(el);
    return el;
  }

  function renderContent(el, md) {
    el.innerHTML = parseMarkdown(md);
  }

  function scrollBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
  }

  function addCopyBtns(el) {
    el.querySelectorAll('table').forEach(table => {
      const wrap = document.createElement('div');
      wrap.className = 'table-wrap';
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
      const btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.textContent = 'Copiar';
      btn.addEventListener('click', () => {
        const rows = Array.from(table.querySelectorAll('tr'));
        const tsv  = rows.map(r =>
          Array.from(r.querySelectorAll('th,td')).map(c => c.textContent.trim()).join('\t')
        ).join('\n');
        navigator.clipboard.writeText(tsv).catch(() => {
          const ta = document.createElement('textarea');
          ta.value = tsv;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          ta.remove();
        });
        btn.textContent = '✓ Copiado';
        setTimeout(() => { btn.textContent = 'Copiar'; }, 2000);
      });
      wrap.appendChild(btn);
    });
  }

  // ── Typewriter decoration ─────────────────────────
  const TW_PHRASES = [
    "¿Cuáles son los proyectos de ley de esta semana?",
    "Busca proyectos sobre educación superior",
    "¿Qué sesiones hay programadas hoy?",
    "Muéstrame la agenda parlamentaria",
    "Proyectos presentados por el congresista García",
    "¿Qué comisiones sesionan esta semana?",
    "Organiza los destacados en tabla",
    "¿Cuáles son los últimos dictámenes aprobados?",
    "Resumen de sesiones de la comisión de salud",
  ];

  let _twTimer = null;

  function startTypewriter() {
    clearTimeout(_twTimer);
    const el = document.getElementById('tw-text');
    if (!el) return;
    let pi = 0, ci = 0, deleting = false;

    function tick() {
      const live = document.getElementById('tw-text');
      if (!live) return; // welcome screen gone
      const phrase = TW_PHRASES[pi];
      if (!deleting) {
        ci++;
        live.textContent = phrase.slice(0, ci);
        if (ci === phrase.length) {
          _twTimer = setTimeout(() => { deleting = true; tick(); }, 2200);
          return;
        }
        _twTimer = setTimeout(tick, 42 + Math.random() * 28);
      } else {
        ci--;
        live.textContent = phrase.slice(0, ci);
        if (ci === 0) {
          deleting = false;
          pi = (pi + 1) % TW_PHRASES.length;
          _twTimer = setTimeout(tick, 380);
          return;
        }
        _twTimer = setTimeout(tick, 22);
      }
    }
    _twTimer = setTimeout(tick, 900);
  }

  // ── Events ────────────────────────────────────────
  newChatBtn.addEventListener('click', newChat);

  sendBtn.addEventListener('click', () => send());

  msgInput.addEventListener('input', () => {
    msgInput.style.height = 'auto';
    msgInput.style.height = Math.min(msgInput.scrollHeight, 160) + 'px';
    sendBtn.disabled = !msgInput.value.trim();
  });

  msgInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });

  document.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => { if (!streaming) send(btn.dataset.cmd); });
  });

  // ── Markdown parser ───────────────────────────────
  function parseMarkdown(md) {
    let h = md;

    // Tables
    h = h.replace(
      /^\|(.+)\|\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)*)/gm,
      (_, header, body) => {
        const ths = header.split('|').filter(s => s.trim())
          .map(s => `<th>${escHtml(s.trim())}</th>`).join('');
        const rows = body.trim().split('\n').filter(Boolean).map(row => {
          const cells = row.split('|').slice(1, -1)
            .map(s => `<td>${escHtml(s.trim())}</td>`).join('');
          return `<tr>${cells}</tr>`;
        }).join('');
        return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
      }
    );

    // Headings
    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm,  '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm,   '<h1>$1</h1>');

    // Bold / italic
    h = h.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    h = h.replace(/\*\*(.+?)\*\*/g,     '<strong>$1</strong>');
    h = h.replace(/\*(.+?)\*/g,         '<em>$1</em>');

    // Inline code
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Lists
    h = h.replace(/(^[-*] .+$(\n^[-*] .+$)*)/gm, block => {
      const items = block.split('\n').map(l => `<li>${l.replace(/^[-*] /, '')}</li>`).join('');
      return `<ul>${items}</ul>`;
    });
    h = h.replace(/(^\d+\. .+$(\n^\d+\. .+$)*)/gm, block => {
      const items = block.split('\n').map(l => `<li>${l.replace(/^\d+\. /, '')}</li>`).join('');
      return `<ol>${items}</ol>`;
    });

    // Paragraphs
    h = h.replace(/\n{2,}/g, '</p><p>');
    h = h.replace(/\n/g, '<br>');
    h = `<p>${h}</p>`;

    // Clean up blocks wrapped in <p>
    h = h.replace(/<p>(<(?:table|ul|ol|h[1-6])[^>]*>)/g, '$1');
    h = h.replace(/(<\/(?:table|ul|ol|h[1-6])>)<\/p>/g, '$1');
    h = h.replace(/<p><\/p>/g, '').replace(/<p><br><\/p>/g, '');

    return h;
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Init ──────────────────────────────────────────
  loadConvs();
  renderSidebar();
  if (convs.length) {
    activeId = convs[0].id;
    renderSidebar();
    renderMessages();
  } else {
    showWelcome();
  }
})();
