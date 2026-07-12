(() => {
  // ── Canvas — constellation + magnetic dots ────────
  const canvas = document.getElementById('bg-canvas');
  const ctx    = canvas.getContext('2d');

  const GRID      = 46;   // dot spacing
  const DOT_R     = 1.4;  // base radius
  const PULL_R    = 200;  // cursor magnetic radius
  const PULL_STR  = 14;   // max pixel pull
  const LINE_R    = 90;   // max line length between dots
  const LERP      = 0.07; // smoothing speed
  const BURST_DUR = 800;  // click burst ms

  let dots = [];
  let mouseX = -9999, mouseY = -9999;
  let bursts = [];

  function buildDots() {
    dots = [];
    const cols = Math.ceil(canvas.width  / GRID) + 2;
    const rows = Math.ceil(canvas.height / GRID) + 2;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const ox = c * GRID;
        const oy = r * GRID;
        dots.push({ ox, oy, cx: ox, cy: oy, r: c, c: r });
      }
    }
  }

  function resizeCanvas() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    buildDots();
  }

  function frame() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const now = performance.now();
    bursts = bursts.filter(b => now - b.t < BURST_DUR);

    // ── Update dot positions (magnetic pull toward cursor) ──
    for (const d of dots) {
      const dx   = mouseX - d.ox;
      const dy   = mouseY - d.oy;
      const dist = Math.hypot(dx, dy);
      let tx = d.ox, ty = d.oy;
      if (dist < PULL_R && dist > 0) {
        const pull = (1 - dist / PULL_R) * PULL_STR;
        tx = d.ox + (dx / dist) * pull;
        ty = d.oy + (dy / dist) * pull;
      }
      // Burst repulsion
      for (const b of bursts) {
        const bd   = Math.hypot(d.ox - b.x, d.oy - b.y);
        const prog = (now - b.t) / BURST_DUR;
        const ring = prog * 280;
        if (Math.abs(bd - ring) < 40) {
          const force = (1 - Math.abs(bd - ring) / 40) * (1 - prog) * 22;
          const ang   = Math.atan2(d.oy - b.y, d.ox - b.x);
          tx += Math.cos(ang) * force;
          ty += Math.sin(ang) * force;
        }
      }
      d.cx += (tx - d.cx) * LERP;
      d.cy += (ty - d.cy) * LERP;
    }

    // ── Draw lines between nearby dots near cursor ──────────
    ctx.save();
    for (let i = 0; i < dots.length; i++) {
      const a = dots[i];
      const aDist = Math.hypot(a.cx - mouseX, a.cy - mouseY);
      if (aDist > PULL_R * 1.4) continue;

      // Only check grid neighbors (up to 2 steps away) for performance
      const nc = a.c, nr = a.r;
      const cols = Math.ceil(canvas.width / GRID) + 2;

      const neighbors = [
        [nc+1, nr], [nc, nr+1], [nc+1, nr+1], [nc-1, nr+1]
      ];
      for (const [nc2, nr2] of neighbors) {
        const idx = nr2 * cols + nc2;
        if (idx < 0 || idx >= dots.length) continue;
        const b = dots[idx];
        const lineDist = Math.hypot(a.cx - b.cx, a.cy - b.cy);
        if (lineDist > LINE_R) continue;
        const bDist   = Math.hypot(b.cx - mouseX, b.cy - mouseY);
        const closest = Math.min(aDist, bDist);
        if (closest > PULL_R * 1.4) continue;
        const lineAlpha = (1 - lineDist / LINE_R) * (1 - closest / (PULL_R * 1.4)) * 0.28;
        ctx.globalAlpha = lineAlpha;
        ctx.strokeStyle = '#000';
        ctx.lineWidth   = 0.8;
        ctx.beginPath();
        ctx.moveTo(a.cx, a.cy);
        ctx.lineTo(b.cx, b.cy);
        ctx.stroke();
      }
    }
    ctx.restore();

    // ── Draw dots ───────────────────────────────────────────
    for (const d of dots) {
      const dist  = Math.hypot(d.cx - mouseX, d.cy - mouseY);
      const prox  = Math.max(0, 1 - dist / PULL_R);
      const r     = DOT_R + prox * 2.8;
      const alpha = 0.08 + prox * 0.28;

      // Burst glow
      let burst = 0;
      for (const b of bursts) {
        const bd   = Math.hypot(d.ox - b.x, d.oy - b.y);
        const prog = (now - b.t) / BURST_DUR;
        const ring = prog * 280;
        const diff = Math.abs(bd - ring);
        if (diff < 36) burst = Math.max(burst, Math.pow(1 - diff/36, 2) * (1 - prog));
      }

      ctx.beginPath();
      ctx.arc(d.cx, d.cy, r + burst * 4, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0,0,0,${Math.min(1, alpha + burst * 0.5).toFixed(3)})`;
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
  const chatArea  = document.getElementById('chat-area');
  const msgInput  = document.getElementById('msg-input');
  const sendBtn   = document.getElementById('send-btn');
  const chatList  = document.getElementById('chat-list');
  const newChatBtn= document.getElementById('new-chat-btn');
  const apiInput  = document.getElementById('api-key-input');
  const cmdChips  = document.getElementById('cmd-chips');

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

    const apiKey = apiInput.value.trim() || localStorage.getItem('groq_api_key') || '';
    if (!apiKey) {
      alert('Ingresa tu API key de Groq en el panel izquierdo.');
      apiInput.focus();
      return;
    }

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
        body: JSON.stringify({ messages: conv.messages, api_key: apiKey }),
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
