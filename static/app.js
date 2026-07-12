(() => {
  // ── Canvas — constelación magnética ──────────────
  const canvas = document.getElementById('bg-canvas');
  const ctx    = canvas.getContext('2d');

  const GRID  = 52;   // separación entre puntos
  const R0    = 1.6;  // radio base del punto
  const RMAX  = 4.5;  // radio máximo cerca del cursor
  const CR    = 230;  // radio de influencia del cursor
  const PULL  = 20;   // fuerza magnética (px)
  const LMAX  = GRID * 1.55; // largo máximo de línea
  const LERP  = 0.10; // suavidad de movimiento

  let COLS = 0, ROWS = 0;
  let dots   = [];
  let mouseX = -9999, mouseY = -9999;
  let bursts = [];

  function buildDots() {
    COLS = Math.ceil(canvas.width  / GRID) + 2;
    ROWS = Math.ceil(canvas.height / GRID) + 2;
    dots = [];
    for (let row = 0; row < ROWS; row++) {
      for (let col = 0; col < COLS; col++) {
        const ox = col * GRID;
        const oy = row * GRID;
        dots.push({ ox, oy, cx: ox, cy: oy, row, col });
      }
    }
  }

  function resizeCanvas() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    buildDots();
  }

  function getDot(row, col) {
    if (row < 0 || row >= ROWS || col < 0 || col >= COLS) return null;
    return dots[row * COLS + col];
  }

  function frame() {
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    const now = performance.now();
    bursts = bursts.filter(b => now - b.t < 900);

    // 1. Mover puntos (imán + repulsión de click)
    for (const d of dots) {
      const dx = mouseX - d.ox, dy = mouseY - d.oy;
      const md = Math.hypot(dx, dy);
      let tx = d.ox, ty = d.oy;

      // Atracción hacia el cursor
      if (md < CR && md > 1) {
        const f = (1 - md / CR) * PULL;
        tx += (dx / md) * f;
        ty += (dy / md) * f;
      }

      // Onda de repulsión al hacer click
      for (const b of bursts) {
        const bd  = Math.hypot(d.ox - b.x, d.oy - b.y);
        const pr  = (now - b.t) / 900;
        const rng = pr * 320;
        const df  = Math.abs(bd - rng);
        if (df < 45) {
          const f   = (1 - df / 45) * (1 - pr) * 28;
          const ang = Math.atan2(d.oy - b.y, d.ox - b.x);
          tx += Math.cos(ang) * f;
          ty += Math.sin(ang) * f;
        }
      }

      d.cx += (tx - d.cx) * LERP;
      d.cy += (ty - d.cy) * LERP;
    }

    // 2. Dibujar líneas entre vecinos del grid (solo cerca del cursor)
    ctx.lineWidth = 0.9;
    for (const d of dots) {
      const dDist = Math.hypot(d.cx - mouseX, d.cy - mouseY);
      if (dDist > CR * 1.5) continue;

      // 4 vecinos: derecha, abajo, diagonal-derecha, diagonal-izquierda
      const neighbors = [
        getDot(d.row,     d.col + 1),
        getDot(d.row + 1, d.col),
        getDot(d.row + 1, d.col + 1),
        getDot(d.row + 1, d.col - 1),
      ];

      for (const n of neighbors) {
        if (!n) continue;
        const nDist   = Math.hypot(n.cx - mouseX, n.cy - mouseY);
        const closest = Math.min(dDist, nDist);
        if (closest > CR * 1.5) continue;
        const ld = Math.hypot(d.cx - n.cx, d.cy - n.cy);
        if (ld > LMAX) continue;

        const a = (1 - closest / (CR * 1.5)) * (1 - ld / LMAX) * 0.32;
        ctx.globalAlpha = a;
        ctx.strokeStyle = '#000';
        ctx.beginPath();
        ctx.moveTo(d.cx, d.cy);
        ctx.lineTo(n.cx, n.cy);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;

    // 3. Dibujar puntos
    for (const d of dots) {
      const dist = Math.hypot(d.cx - mouseX, d.cy - mouseY);
      const prox = Math.max(0, 1 - dist / CR);

      let extra = 0;
      for (const b of bursts) {
        const bd  = Math.hypot(d.ox - b.x, d.oy - b.y);
        const pr  = (now - b.t) / 900;
        const rng = pr * 320;
        const df  = Math.abs(bd - rng);
        if (df < 45) extra = Math.max(extra, (1 - df/45) * (1 - pr) * 5);
      }

      ctx.beginPath();
      ctx.arc(d.cx, d.cy, R0 + prox * RMAX + extra, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0,0,0,${(0.07 + prox * 0.38 + extra * 0.08).toFixed(3)})`;
      ctx.fill();
    }

    requestAnimationFrame(frame);
  }

  window.addEventListener('resize',    resizeCanvas);
  window.addEventListener('mousemove', e => { mouseX = e.clientX; mouseY = e.clientY; });
  window.addEventListener('click',     e => bursts.push({ x: e.clientX, y: e.clientY, t: performance.now() }));
  resizeCanvas();
  requestAnimationFrame(frame);

  // ── DOM refs ─────────────────────────────────────
  const chatArea    = document.getElementById('chat-area');
  const msgInput    = document.getElementById('msg-input');
  const sendBtn     = document.getElementById('send-btn');
  const chatList    = document.getElementById('chat-list');
  const newChatBtn  = document.getElementById('new-chat-btn');
  const cmdChips    = document.getElementById('cmd-chips');
  const statusEl    = document.getElementById('server-status');

  // ── Server status ping ────────────────────────────
  async function pingStatus() {
    try {
      const r = await fetch('/status');
      const d = await r.json();
      if (d.ready) {
        statusEl.className = 'server-status ok';
        statusEl.querySelector('.status-text').textContent = 'IA lista';
      } else {
        statusEl.className = 'server-status err';
        statusEl.querySelector('.status-text').textContent = 'Falta API key — configura el .env';
      }
    } catch {
      statusEl.className = 'server-status err';
      statusEl.querySelector('.status-text').textContent = 'Servidor desconectado';
    }
  }
  pingStatus();

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
    chatArea.innerHTML = `
      <div class="welcome">
        <svg class="welcome-icon" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="8" y="54" width="48" height="6" rx="1.5"/>
          <rect x="13" y="24" width="7" height="30" rx="1.5"/>
          <rect x="28.5" y="24" width="7" height="30" rx="1.5"/>
          <rect x="44" y="24" width="7" height="30" rx="1.5"/>
          <path d="M4 24h56M32 6L4 24h56L32 6z"/>
        </svg>
        <h1>¿En qué te puedo ayudar?</h1>
        <p>Organizo información parlamentaria en tablas listas para copiar a Word.</p>
      </div>`;
    cmdChips.style.display = 'flex';
  }

  function renderMessages() {
    const conv = getActive();
    if (!conv || !conv.messages.length) { showWelcome(); return; }
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

  apiInput.value = localStorage.getItem('groq_api_key') || '';
  apiInput.addEventListener('input', () => {
    localStorage.setItem('groq_api_key', apiInput.value.trim());
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
