(() => {
  const chatArea  = document.getElementById('chat-area');
  const msgInput  = document.getElementById('msg-input');
  const sendBtn   = document.getElementById('send-btn');
  const clearBtn  = document.getElementById('clear-btn');
  const apiInput  = document.getElementById('api-key-input');
  const cmdBtns   = document.querySelectorAll('.cmd-btn');

  let messages  = [];   // {role, content}
  let streaming = false;

  // ── Persist API key ───────────────────────────────
  const KEY_STORE = 'groq_api_key';
  apiInput.value = localStorage.getItem(KEY_STORE) || '';
  apiInput.addEventListener('input', () => {
    localStorage.setItem(KEY_STORE, apiInput.value.trim());
  });

  // ── Auto-resize textarea ──────────────────────────
  msgInput.addEventListener('input', () => {
    msgInput.style.height = 'auto';
    msgInput.style.height = Math.min(msgInput.scrollHeight, 160) + 'px';
  });

  // ── Send on Enter, newline on Shift+Enter ─────────
  msgInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  sendBtn.addEventListener('click', send);
  clearBtn.addEventListener('click', clearChat);

  // ── Quick command buttons ──────────────────────────
  cmdBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const cmd = btn.dataset.cmd;
      if (!cmd || streaming) return;
      msgInput.value = cmd;
      msgInput.dispatchEvent(new Event('input'));
      send();
    });
  });

  // ── Clear chat ─────────────────────────────────────
  function clearChat() {
    messages = [];
    chatArea.innerHTML = `
      <div class="welcome">
        <div class="welcome-icon">🏛</div>
        <h1>Asistente del Congreso</h1>
        <p>Organizo información parlamentaria en tablas listas para copiar a Word.<br>
        Usa los comandos de la izquierda o escribe directamente.</p>
        <div class="welcome-tips">
          <div class="tip">💡 Puedes <strong>pegar información</strong> del portal del Congreso y te la organizo en tabla</div>
          <div class="tip">💡 Las tablas generadas se pueden <strong>copiar directo a Word</strong></div>
        </div>
      </div>`;
  }

  // ── Main send ──────────────────────────────────────
  async function send() {
    const text = msgInput.value.trim();
    if (!text || streaming) return;

    const apiKey = apiInput.value.trim() || localStorage.getItem(KEY_STORE) || '';
    if (!apiKey) {
      showError('Ingresa tu API key de Groq en el panel izquierdo (gratis en console.groq.com)');
      apiInput.focus();
      return;
    }

    removeWelcome();
    appendUserMsg(text);
    messages.push({ role: 'user', content: text });
    msgInput.value = '';
    msgInput.style.height = 'auto';

    streaming = true;
    sendBtn.disabled = true;

    const assistantEl = appendAssistantTyping();
    let fullText = '';

    try {
      const resp = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages, api_key: apiKey }),
      });

      const reader = resp.body.getReader();
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
            if (obj.error) {
              renderContent(assistantEl, `**Error:** ${obj.error}`);
              break;
            }
            if (obj.text) {
              fullText += obj.text;
              renderContent(assistantEl, fullText);
              scrollBottom();
            }
          } catch { /* ignore parse errors */ }
        }
      }
    } catch (err) {
      renderContent(assistantEl, `**Error de conexión:** ${err.message}`);
    }

    if (fullText) {
      messages.push({ role: 'assistant', content: fullText });
      addCopyButtons(assistantEl);
    }

    streaming = false;
    sendBtn.disabled = false;
    scrollBottom();
  }

  // ── DOM helpers ────────────────────────────────────
  function removeWelcome() {
    const w = chatArea.querySelector('.welcome');
    if (w) w.remove();
  }

  function appendUserMsg(text) {
    const div = document.createElement('div');
    div.className = 'message user';
    div.innerHTML = `
      <div class="msg-avatar">👤</div>
      <div class="msg-content">${escHtml(text)}</div>`;
    chatArea.appendChild(div);
    scrollBottom();
  }

  function appendAssistantTyping() {
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `
      <div class="msg-avatar">🏛</div>
      <div class="msg-content">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>`;
    chatArea.appendChild(div);
    scrollBottom();
    return div.querySelector('.msg-content');
  }

  function renderContent(el, markdown) {
    el.innerHTML = parseMarkdown(markdown);
  }

  function showError(msg) {
    removeWelcome();
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `
      <div class="msg-avatar">⚠️</div>
      <div class="msg-content" style="color:var(--red)">${escHtml(msg)}</div>`;
    chatArea.appendChild(div);
    scrollBottom();
  }

  function scrollBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
  }

  // ── Add copy buttons to tables ─────────────────────
  function addCopyButtons(el) {
    el.querySelectorAll('table').forEach(table => {
      const wrap = document.createElement('div');
      wrap.className = 'table-wrap';
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
      const btn = document.createElement('button');
      btn.className = 'copy-btn';
      btn.textContent = 'Copiar';
      btn.addEventListener('click', () => {
        copyTableAsText(table);
        btn.textContent = '✓ Copiado';
        setTimeout(() => { btn.textContent = 'Copiar'; }, 2000);
      });
      wrap.appendChild(btn);
    });
  }

  function copyTableAsText(table) {
    const rows = Array.from(table.querySelectorAll('tr'));
    const lines = rows.map(row =>
      Array.from(row.querySelectorAll('th,td'))
        .map(c => c.textContent.trim())
        .join('\t')
    );
    navigator.clipboard.writeText(lines.join('\n')).catch(() => {
      const ta = document.createElement('textarea');
      ta.value = lines.join('\n');
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    });
  }

  // ── Minimal Markdown parser ────────────────────────
  function parseMarkdown(md) {
    let html = escHtml(md);

    // Unescape for markdown processing (we'll re-escape inline)
    // Work on raw md instead
    html = md;

    // Tables (must come before other block rules)
    html = html.replace(
      /^\|(.+)\|\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)*)/gm,
      (_, header, body) => {
        const ths = header.split('|').filter(c => c.trim()).map(c => `<th>${escHtml(c.trim())}</th>`).join('');
        const rows = body.trim().split('\n').map(row => {
          if (!row.trim()) return '';
          const tds = row.split('|').filter(c => c.trim() !== '' || row.split('|').length > 2)
            .filter((_, i, a) => i > 0 && i < a.length - 1)
            .map(c => `<td>${escHtml(c.trim())}</td>`).join('');
          return `<tr>${tds}</tr>`;
        }).join('');
        return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
      }
    );

    // Headings
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Horizontal rule
    html = html.replace(/^---$/gm, '<hr>');

    // Bold / italic
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Unordered lists
    html = html.replace(/(^[-*] .+$(\n^[-*] .+$)*)/gm, block => {
      const items = block.split('\n').map(l => `<li>${l.replace(/^[-*] /, '')}</li>`).join('');
      return `<ul>${items}</ul>`;
    });

    // Ordered lists
    html = html.replace(/(^\d+\. .+$(\n^\d+\. .+$)*)/gm, block => {
      const items = block.split('\n').map(l => `<li>${l.replace(/^\d+\. /, '')}</li>`).join('');
      return `<ol>${items}</ol>`;
    });

    // Paragraphs: double newline
    html = html.replace(/\n{2,}/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    html = `<p>${html}</p>`;

    // Clean up empty paragraphs or paragraphs wrapping block elements
    html = html.replace(/<p>(<(?:table|ul|ol|h[1-6]|hr)[^>]*>)/g, '$1');
    html = html.replace(/(<\/(?:table|ul|ol|h[1-6]|hr)>)<\/p>/g, '$1');
    html = html.replace(/<p><\/p>/g, '');
    html = html.replace(/<p><br><\/p>/g, '');

    return html;
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
