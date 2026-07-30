(() => {
  // ── Modo oscuro ───────────────────────────────────
  const DARK_KEY = 'congreso_dark';
  const html     = document.documentElement;

  function applyTheme(dark) {
    html.dataset.theme = dark ? 'dark' : 'light';
    document.getElementById('dark-icon-moon').style.display = dark ? 'none' : '';
    document.getElementById('dark-icon-sun').style.display  = dark ? ''     : 'none';
    localStorage.setItem(DARK_KEY, dark ? '1' : '0');
  }

  applyTheme(localStorage.getItem(DARK_KEY) === '1');

  document.getElementById('dark-toggle').addEventListener('click', () => {
    applyTheme(html.dataset.theme !== 'dark');
  });

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

  // ── Conversations (archivo JSON via IPC, localStorage como fallback) ──
  const STORE = 'congreso_convs';
  let convs    = [];
  let activeId = null;
  let streaming= false;

  function loadConvs() {
    try { convs = JSON.parse(localStorage.getItem(STORE)) || []; }
    catch { convs = []; }
  }

  function saveConvs() {
    // localStorage tiene ~5 MB: unas pocas respuestas de expediente completo
    // lo llenan y setItem tira QuotaExceededError. Si eso escala, congela el
    // chat entero, así que acá se descartan las conversaciones más viejas.
    try {
      localStorage.setItem(STORE, JSON.stringify(convs));
    } catch (e) {
      console.warn('localStorage lleno, recortando historial:', e.name);
      try {
        convs = convs.slice(0, 10);
        localStorage.setItem(STORE, JSON.stringify(convs));
      } catch {
        localStorage.removeItem(STORE);
      }
    }
    if (window.electronAPI?.saveHistory) {
      window.electronAPI.saveHistory(convs).catch(() => {});
    }
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

  function deleteConv(id) {
    convs = convs.filter(c => c.id !== id);
    if (activeId === id) activeId = convs[0]?.id || null;
    saveConvs();
    renderSidebar();
    if (activeId) renderMessages(); else showWelcome();
  }

  function renameConvInline(id, span) {
    const conv = convs.find(c => c.id === id);
    if (!conv) return;

    const input = document.createElement('input');
    input.className = 'chat-item-rename';
    input.value     = conv.title;
    span.replaceWith(input);
    input.focus();
    input.select();

    function commit() {
      const val = input.value.trim();
      if (val) conv.title = val;
      saveConvs();
      renderSidebar();
    }
    input.addEventListener('blur',   commit);
    input.addEventListener('keydown', ev => {
      if (ev.key === 'Enter')  { ev.preventDefault(); input.blur(); }
      if (ev.key === 'Escape') { input.value = conv.title; input.blur(); }
    });
    input.addEventListener('click', ev => ev.stopPropagation());
  }

  function autoTitle(text) {
    return text.slice(0, 38) + (text.length > 38 ? '…' : '');
  }

  // Delegación de eventos en el sidebar — un solo listener para delete y rename
  chatList.addEventListener('click', e => {
    const delBtn = e.target.closest('.chat-item-del');
    if (delBtn) {
      e.stopPropagation();
      const id = delBtn.closest('.chat-item')?.dataset.id;
      if (id) deleteConv(id);
      return;
    }
  });
  chatList.addEventListener('dblclick', e => {
    const title = e.target.closest('.chat-item-title');
    if (title) {
      const id = title.closest('.chat-item')?.dataset.id;
      if (!id) return;
      // Si no es la activa, activarla primero y luego renombrar después del re-render
      if (id !== activeId) {
        activeId = id;
        renderSidebar();
        renderMessages();
        const newTitle = chatList.querySelector(`.chat-item[data-id="${id}"] .chat-item-title`);
        if (newTitle) renameConvInline(id, newTitle);
      } else {
        renameConvInline(id, title);
      }
    }
  });

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
          <span class="chat-item-title" title="Doble clic para renombrar">${escHtml(c.title)}</span>
          <button class="chat-item-del" title="Eliminar conversación" data-del-id="${c.id}">
            <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="pointer-events:none">
              <path d="M2 2l10 10M12 2L2 12"/>
            </svg>
          </button>`;
        el.querySelector('.chat-item-del').addEventListener('click', (e) => {
          e.stopPropagation();
          deleteConv(c.id);
        });
        el.addEventListener('click', (e) => {
          if (e.target.closest('.chat-item-del')) return;
          el.classList.add('clicking');
          el.addEventListener('animationend', () => el.classList.remove('clicking'), { once: true });
          switchConv(c.id);
        });
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
  async function send(textOverride, sectorOverride) {
    let text = (textOverride || msgInput.value).trim();
    if (!text || streaming) return;

    const isResumen = text === '__RESUMEN_SEMANAL__';
    const sector    = sectorOverride || null;

    // Create conversation if none active
    if (!activeId || !getActive()) newChat();
    const conv = getActive();

    // First message → auto-title. El resumen manda un centinela como texto, así
    // que sin este caso el título del chat quedaba como "__RESUMEN_SEMANAL__".
    if (!conv.messages.length) {
      conv.title = isResumen
        ? 'Resumen Semanal' + (sector && sector !== 'general' ? ' — ' + sector : '')
        : autoTitle(text);
    }

    mainEl.classList.add('chat-mode');
    chatArea.querySelector('.welcome')?.remove();
    cmdChips.style.display = 'none';

    const userContent = isResumen
      ? `__RESUMEN_SEMANAL__${sector ? ':' + sector : ''}`
      : text;
    conv.messages.push({ role: 'user', content: userContent });
    saveConvs();
    renderSidebar();
    appendUserBubble(isResumen
      ? `📄 Resumen ejecutivo${sector && sector !== 'general' ? ' — ' + sector : ''}`
      : text);

    msgInput.value = '';
    msgInput.style.height = 'auto';
    sendBtn.disabled = true;
    streaming = true;
    const assistantEl = appendAssistantTyping();
    let fullText   = '';
    let toolCalled = false;  // true si el modelo consultó una herramienta

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
            if (obj.status) {
              toolCalled = true;
              assistantEl.innerHTML = `<span class="fetch-status">${escHtml(obj.status)}</span>`;
              scrollBottom();
            }
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
    } finally {
      // Ojo: esto va sí o sí en el finally. Si `streaming` se queda en true
      // (por ej. si saveConvs revienta con el localStorage lleno), los chips
      // y el botón de enviar dejan de responder para siempre, sin ningún error
      // visible, hasta recargar la ventana.
      try {
        if (fullText) {
          conv.messages.push({ role: 'assistant', content: fullText });
          saveConvs();
          addCopyBtns(assistantEl);
          addMessageCopyBtns(assistantEl.closest('.message'), fullText);
          if (toolCalled && hasExportableContent(fullText)) {
            addExportBtns(assistantEl.closest('.message'), fullText);
          }
        }
      } catch (e) {
        console.error('Error al guardar/renderizar la respuesta:', e);
      }

      streaming = false;
      sendBtn.disabled = !msgInput.value.trim();
      scrollBottom();
    }
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
    addMessageCopyBtns(d, md);
    addExportBtns(d, md);
    return el;
  }

  function renderContent(el, md) {
    el.innerHTML = parseMarkdown(md);
  }

  // ── Modal de resumen ─────────────────────────────
  const resumenModal = document.getElementById('resumen-modal');

  function openResumenModal() {
    resumenModal.style.display = 'flex';
  }
  function closeResumenModal() {
    resumenModal.style.display = 'none';
  }

  document.getElementById('resumen-cancel').addEventListener('click', closeResumenModal);
  resumenModal.addEventListener('click', e => {
    if (e.target === resumenModal) closeResumenModal();
  });

  // Cada botón de sector dispara la generación del resumen con ese contexto
  resumenModal.querySelectorAll('.sector-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const sector = btn.dataset.sector;
      closeResumenModal();
      send('__RESUMEN_SEMANAL__', sector);
    });
  });


  // Devuelve true si el texto tiene contenido exportable (tablas, listas de datos)
  function hasExportableContent(md) {
    return md.includes('|') && md.includes('---');  // markdown table
  }

  // Botones de descarga que aparecen DESPUÉS de que termina el resumen
  function addExportBtns(msgDiv, md) {
    const wrap = document.createElement('div');
    wrap.className = 'export-btns';
    wrap.innerHTML = `
      <button class="export-btn" data-type="pdf">PDF</button>
      <button class="export-btn" data-type="word">Word</button>`;
    const pdfBtn  = wrap.querySelector('[data-type="pdf"]');
    const wordBtn = wrap.querySelector('[data-type="word"]');
    pdfBtn._orig  = pdfBtn.innerHTML;
    wordBtn._orig = wordBtn.innerHTML;
    pdfBtn.addEventListener('click',  () => exportPdf(md,  pdfBtn));
    wordBtn.addEventListener('click', () => exportWord(md, wordBtn));
    const content = msgDiv.querySelector('.msg-content') || msgDiv;
    content.appendChild(wrap);
  }

  function _buildPrintHtml(md) {
    const html = parseMarkdown(md);
    const date = new Date().toLocaleDateString('es-PE', { day:'numeric', month:'long', year:'numeric' });
    return `<!DOCTYPE html><html lang="es"><head>
<meta charset="UTF-8"><title>Resumen Ejecutivo — Congreso del Perú</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Georgia',serif;font-size:12pt;color:#111;padding:40px 60px;line-height:1.7;max-width:900px;margin:0 auto}
  h1{font-size:18pt;font-weight:bold;margin-bottom:4px}
  h2{font-size:13pt;font-weight:bold;margin:24px 0 8px;border-bottom:1.5px solid #111;padding-bottom:4px}
  h3{font-size:12pt;font-weight:bold;margin:16px 0 6px}
  p{margin-bottom:10px} ul,ol{padding-left:20px;margin-bottom:10px} li{margin-bottom:4px}
  table{border-collapse:collapse;width:100%;margin:12px 0;font-size:10pt}
  th{background:#111;color:#fff;padding:6px 10px;text-align:left;font-weight:bold}
  td{border:1px solid #ccc;padding:6px 10px}
  tr:nth-child(even) td{background:#f7f7f7}
  a{color:#111} hr{border:none;border-top:1px solid #ccc;margin:20px 0}
  .hdr{border-bottom:3px solid #111;padding-bottom:12px;margin-bottom:24px;font-size:9pt;color:#666}
  .ftr{margin-top:40px;border-top:1px solid #ccc;padding-top:12px;font-size:9pt;color:#666}
  strong{font-weight:bold} em{font-style:italic}
  @media print{body{padding:20px 30px} a{text-decoration:none}}
</style></head><body>
<div class="hdr">DOCUMENTO CONFIDENCIAL — GESTIÓN DE ASUNTOS PÚBLICOS</div>
${html}
<div class="ftr">Generado por Lex — Sistema de Monitoreo Parlamentario · ${date}</div>
</body></html>`;
  }

  function exportPdf(md, btn) {
    const html = _buildPrintHtml(md);
    if (window.electronAPI) {
      if (btn) { btn.disabled = true; btn.textContent = 'Generando…'; }
      window.electronAPI.exportPDF(html)
        .then(r => { if (btn) { btn.disabled = false; btn.innerHTML = btn._orig; } })
        .catch(e => { alert('Error al generar PDF: ' + e.message); if (btn) { btn.disabled = false; btn.innerHTML = btn._orig; } });
    } else {
      const w = window.open('', '_blank');
      w.document.write(html);
      w.document.close();
      setTimeout(() => w.print(), 400);
    }
  }

  function exportWord(md, btn) {
    if (window.electronAPI) {
      if (btn) { btn.disabled = true; btn.textContent = 'Generando…'; }
      window.electronAPI.exportWord(md)
        .then(r => { if (btn) { btn.disabled = false; btn.innerHTML = btn._orig; } })
        .catch(e => { alert('Error al generar Word: ' + e.message); if (btn) { btn.disabled = false; btn.innerHTML = btn._orig; } });
    } else {
      fetch('/export/docx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: md }),
      })
      .then(r => r.blob())
      .then(blob => {
        const url = URL.createObjectURL(blob);
        const a   = document.createElement('a');
        a.href     = url;
        a.download = `Resumen-Congreso-${new Date().toISOString().slice(0,10)}.docx`;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch(() => alert('Error generando el Word.'));
    }
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
      btn.textContent = 'Copiar tabla';
      btn.addEventListener('click', () => {
        // HTML rico: Word lo pega como tabla con formato completo
        const htmlTable = `
<html><body>
<style>
  table{border-collapse:collapse;font-family:Calibri,sans-serif;font-size:11pt}
  th{background:#1a1a1a;color:#fff;padding:6px 12px;font-weight:bold;border:1px solid #333}
  td{padding:5px 12px;border:1px solid #ccc}
  tr:nth-child(even) td{background:#f5f5f5}
</style>
${table.outerHTML}
</body></html>`;

        // Texto plano como fallback (TSV pega como tabla en Word también)
        const rows = Array.from(table.querySelectorAll('tr'));
        const tsv  = rows.map(r =>
          Array.from(r.querySelectorAll('th,td')).map(c => c.textContent.trim()).join('\t')
        ).join('\n');

        if (window.ClipboardItem) {
          const item = new ClipboardItem({
            'text/html':  new Blob([htmlTable], { type: 'text/html' }),
            'text/plain': new Blob([tsv],       { type: 'text/plain' }),
          });
          navigator.clipboard.write([item]).catch(() => fallbackCopy(tsv));
        } else {
          fallbackCopy(tsv);
        }

        btn.textContent = '✓ Copiado';
        setTimeout(() => { btn.textContent = 'Copiar tabla'; }, 2000);
      });
      wrap.appendChild(btn);
    });
  }

  function addMessageCopyBtns(msgDiv, fullText) {
    // Separar contenido principal de fuentes
    const sepIdx = fullText.search(/\n---\n\*\*Fuentes:/);
    const mainText    = sepIdx >= 0 ? fullText.slice(0, sepIdx).trim() : fullText.trim();
    const sourcesText = sepIdx >= 0 ? fullText.slice(sepIdx).trim() : null;

    const toolbar = document.createElement('div');
    toolbar.className = 'msg-toolbar';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'msg-action-btn';
    copyBtn.textContent = 'Copiar mensaje';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(mainText).catch(() => fallbackCopy(mainText));
      copyBtn.textContent = '✓ Copiado';
      setTimeout(() => { copyBtn.textContent = 'Copiar mensaje'; }, 2000);
    });
    toolbar.appendChild(copyBtn);

    if (sourcesText) {
      const srcBtn = document.createElement('button');
      srcBtn.className = 'msg-action-btn';
      srcBtn.textContent = 'Copiar fuentes';
      srcBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(sourcesText).catch(() => fallbackCopy(sourcesText));
        srcBtn.textContent = '✓ Copiado';
        setTimeout(() => { srcBtn.textContent = 'Copiar fuentes'; }, 2000);
      });
      toolbar.appendChild(srcBtn);
    }

    // Insertar el toolbar dentro del msg-content, al final
    const content = msgDiv.querySelector('.msg-content');
    if (content) content.appendChild(toolbar);
  }

  function fallbackCopy(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }

  // ── Typewriter decoration ─────────────────────────
  const TW_PHRASES = [
    "Novedades de agendas de comisiones de Diputados",
    "Novedades de agendas de comisiones del Senado",
    "Proyectos de ley recientes en Diputados",
    "¿Cuál es el estatus del proyecto de ley N° [número]?",
    "Resumen de noticias de Senado, Diputados y Congreso",
    "Destacados y citaciones de Diputados, Senado y Congreso",
    "Proyectos de ley de los últimos 15 días por tema",
    "Comisiones y miembros de la Comisión Permanente",
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
  // ── Drag & drop PDF ───────────────────────────────
  const dropZone = document.querySelector('.main');
  dropZone.addEventListener('dragover', e => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });
  dropZone.addEventListener('dragleave', e => {
    if (!dropZone.contains(e.relatedTarget)) dropZone.classList.remove('drag-over');
  });
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = Array.from(e.dataTransfer.files).find(f => f.name.endsWith('.pdf'));
    if (file) uploadPdfFile(file);
  });

  // ── Panel PDFs del Congreso ───────────────────────
  const congresoPanel  = document.getElementById('congreso-pdf-panel');
  const cpdfList       = document.getElementById('cpdf-list');
  let cpdfLoaded = false;

  document.getElementById('congreso-pdf-btn').addEventListener('click', async () => {
    const visible = congresoPanel.style.display !== 'none';
    congresoPanel.style.display = visible ? 'none' : 'block';
    if (!visible && !cpdfLoaded) {
      cpdfLoaded = true;
      cpdfList.innerHTML = '<div class="cpdf-loading">Cargando PDFs del Congreso...</div>';
      try {
        const res  = await fetch('/congreso-pdfs');
        const data = await res.json();
        if (!data.pdfs.length) {
          cpdfList.innerHTML = '<div class="cpdf-loading">No hay PDFs disponibles ahora.</div>';
          return;
        }
        cpdfList.innerHTML = '';
        for (const pdf of data.pdfs) {
          const el = document.createElement('div');
          el.className = 'cpdf-item';
          el.innerHTML = `<span class="cpdf-tipo">${pdf.tipo}</span><span class="cpdf-title">${escHtml(pdf.titulo)}</span>`;
          el.addEventListener('click', async () => {
            congresoPanel.style.display = 'none';
            await loadPdfFromUrl(pdf.enlace, pdf.titulo);
          });
          cpdfList.appendChild(el);
        }
      } catch {
        cpdfList.innerHTML = '<div class="cpdf-loading">Error al cargar los PDFs.</div>';
      }
    }
  });

  document.getElementById('cpdf-close').addEventListener('click', () => {
    congresoPanel.style.display = 'none';
  });

  async function loadPdfFromUrl(url, titulo) {
    if (!activeId || !getActive()) newChat();
    const conv = getActive();
    if (!conv.messages.length) conv.title = '📄 ' + titulo.slice(0, 40);

    mainEl.classList.add('chat-mode');
    chatArea.querySelector('.welcome')?.remove();
    cmdChips.style.display = 'none';
    appendUserBubble(`📄 ${titulo}`);
    const assistantEl = appendAssistantTyping();
    streaming = true; sendBtn.disabled = true;

    try {
      const res  = await fetch('/load-pdf-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error);
      const ctx = `He cargado el documento "${titulo}" (${data.pages} páginas).\n\nContenido:\n${data.text}\n\n¿Qué quieres analizar?`;
      conv.messages.push({ role: 'user', content: ctx });
      saveConvs(); renderSidebar();
      const msg = `PDF cargado — **${titulo.slice(0, 60)}** (${data.pages} págs.). ¿Qué quieres analizar?`;
      renderContent(assistantEl, msg);
      addMessageCopyBtns(assistantEl.closest('.message'), msg);
    } catch (err) {
      renderContent(assistantEl, `**Error al cargar el PDF:** ${err.message}`);
    }
    streaming = false; sendBtn.disabled = !msgInput.value.trim(); scrollBottom();
  }

  // ── PDF upload (archivo local) ────────────────────
  async function uploadPdfFile(file) {
    if (!activeId || !getActive()) newChat();
    const conv = getActive();
    if (!conv.messages.length) conv.title = '📄 ' + file.name;
    mainEl.classList.add('chat-mode');
    chatArea.querySelector('.welcome')?.remove();
    cmdChips.style.display = 'none';
    appendUserBubble(`📄 ${file.name}`);
    const assistantEl = appendAssistantTyping();
    streaming = true; sendBtn.disabled = true;
    try {
      const form = new FormData();
      form.append('file', file);
      const res  = await fetch('/upload-pdf', { method: 'POST', body: form });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Error al leer el PDF');
      const ctx = `He cargado el documento "${file.name}" (${data.pages} páginas).\n\nContenido:\n${data.text}\n\n¿Qué quieres analizar?`;
      conv.messages.push({ role: 'user', content: ctx });
      saveConvs(); renderSidebar();
      const msg = `PDF cargado — **${file.name}** (${data.pages} págs.). ¿Qué quieres analizar?`;
      renderContent(assistantEl, msg);
      addMessageCopyBtns(assistantEl.closest('.message'), msg);
    } catch (err) {
      renderContent(assistantEl, `**Error al cargar el PDF:** ${err.message}`);
    }
    streaming = false; sendBtn.disabled = !msgInput.value.trim(); scrollBottom();
  }

  document.getElementById('pdf-input').addEventListener('change', e => {
    const file = e.target.files[0];
    e.target.value = '';
    if (file) uploadPdfFile(file);
  });

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
    if (btn.id === 'resumen-btn') return;
    btn.addEventListener('click', () => { if (!streaming) send(btn.dataset.cmd); });
  });

  document.getElementById('resumen-btn').addEventListener('click', () => {
    if (!streaming) openResumenModal();
  });



  // ── Markdown parser ───────────────────────────────
  // marked + DOMPurify: más robusto que el parser manual y XSS-safe.
  // El guard importa: si alguna de las dos librerías no cargó, una excepción
  // acá aborta el resto del script y deja sin cablear los listeners de más
  // abajo (navegación), con la app aparentemente viva pero sin botones.
  const MD_OK = typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined';
  if (MD_OK) {
    marked.setOptions({ breaks: true, gfm: true });
  } else {
    console.error('marked/DOMPurify no cargaron — se muestra el texto sin formato.');
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function parseMarkdown(md) {
    // Degradar a texto plano escapado antes que romper el chat.
    if (!MD_OK) return `<p>${escapeHtml(md).replace(/\n/g, '<br>')}</p>`;
    const raw = marked.parse(md);
    return DOMPurify.sanitize(raw, {
      ADD_ATTR: ['target', 'rel'],
      ALLOWED_TAGS: ['p','br','h1','h2','h3','h4','h5','h6',
        'strong','em','code','pre','blockquote',
        'table','thead','tbody','tr','th','td',
        'ul','ol','li','a','hr','span'],
    });
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Navegación Chat / Live / PDFs ────────────────
  const navChat    = document.getElementById('nav-chat');
  const navLive    = document.getElementById('nav-live');
  const navPdfs    = document.getElementById('nav-pdfs');
  const viewLive   = document.getElementById('view-live');
  const viewPdfs   = document.getElementById('view-pdfs');
  const liveIframe = document.getElementById('live-iframe');
  const pdfsIframe = document.getElementById('pdfs-iframe');
  const chatArea2  = document.getElementById('chat-area');
  const inputArea  = document.querySelector('.input-area');

  function setNavActive(btn) {
    [navChat, navLive, navPdfs].forEach(b => b && b.classList.remove('active'));
    if (btn) btn.classList.add('active');
  }

  function switchToChat() {
    setNavActive(navChat);
    if (viewLive) viewLive.style.display = 'none';
    if (viewPdfs) viewPdfs.style.display = 'none';
    chatArea2.style.display = '';
    inputArea.style.display = '';
  }

  function switchToLive() {
    setNavActive(navLive);
    chatArea2.style.display = 'none';
    inputArea.style.display = 'none';
    if (viewPdfs) viewPdfs.style.display = 'none';
    viewLive.style.display = '';
    if (!liveIframe.src || liveIframe.src === window.location.href) {
      liveIframe.src = '/live';
    }
  }

  function switchToPdfs() {
    setNavActive(navPdfs);
    chatArea2.style.display = 'none';
    inputArea.style.display = 'none';
    if (viewLive) viewLive.style.display = 'none';
    viewPdfs.style.display = '';
    if (!pdfsIframe.src || pdfsIframe.src === window.location.href) {
      pdfsIframe.src = '/pdfs';
    }
  }

  navChat.addEventListener('click', switchToChat);
  if (navLive) navLive.addEventListener('click', switchToLive);
  if (navPdfs) navPdfs.addEventListener('click', switchToPdfs);

  window.addEventListener('message', (e) => {
    if (e.data === 'close-live') { switchToChat(); return; }
    if (e.data && e.data.type === 'load-pdf') {
      switchToChat();
      loadPdfFromUrl(e.data.url, e.data.titulo);
    }
    if (e.data && e.data.type === 'query-proyecto') {
      switchToChat();
      const query = `Dame información sobre el proyecto de ley ${e.data.numero}: estado actual, autores, y de qué trata.`;
      send(query);
    }
    if (e.data && e.data.type === 'open-external') {
      window.electronAPI?.openExternal(e.data.url);
    }
  });

  // ── Init ──────────────────────────────────────────
  async function init() {
    // Intentar cargar desde archivo en disco (más confiable que localStorage)
    if (window.electronAPI?.loadHistory) {
      try {
        const fromFile = await window.electronAPI.loadHistory();
        const valid = Array.isArray(fromFile) && fromFile.length > 0
          && fromFile.every(c => c && typeof c.id === 'string' && Array.isArray(c.messages));
        if (valid) {
          convs = fromFile;
          // Sincronizar también a localStorage
          localStorage.setItem(STORE, JSON.stringify(convs));
        } else {
          loadConvs(); // fallback a localStorage
        }
      } catch {
        loadConvs();
      }
    } else {
      loadConvs();
    }

    // Arrancar siempre en la pantalla principal: no reabrir la última
    // conversación automáticamente. El historial sigue en el sidebar, un
    // clic la reabre.
    renderSidebar();
    showWelcome();
  }

  init();
})();
