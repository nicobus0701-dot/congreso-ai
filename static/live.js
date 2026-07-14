/* ── State ───────────────────────────────────────────── */
let es          = null;   // EventSource
let videoId     = "";
let transcript  = [];     // [{ts, text}]
let autoScroll  = true;
let analyzeTimer = null;
let countdown    = 60;

const $ = id => document.getElementById(id);

/* ── DOM refs ────────────────────────────────────────── */
const urlInput      = $("lv-url-input");
const startBtn      = $("lv-start-btn");
const stopBtn       = $("lv-stop-btn");
const statusEl      = $("lv-status");
const iframe        = $("lv-iframe");
const placeholder   = $("lv-video-placeholder");
const dot           = $("lv-dot");
const indicatorLabel= $("lv-indicator-label");
const linesEl       = $("lv-lines");
const transcriptBody= $("lv-transcript-body");
const transcriptEmpty = $("lv-transcript-empty");
const scrollBtn     = $("lv-scroll-btn");
const copyBtn       = $("lv-copy-btn");
const iaEmpty       = $("lv-ia-empty");
const iaContent     = $("lv-ia-content");
const iaSpinner     = $("lv-ia-spinner");
const iaFooter      = $("lv-ia-footer");
const iaCountdown   = $("lv-ia-countdown");
const iaNowBtn      = $("lv-ia-now-btn");

/* ── Parse YouTube ID ────────────────────────────────── */
function parseYouTubeId(input) {
  input = input.trim();
  // Already a bare ID (11 chars)
  if (/^[A-Za-z0-9_-]{11}$/.test(input)) return input;
  try {
    const u = new URL(input);
    if (u.hostname.includes("youtu.be"))      return u.pathname.slice(1).split("?")[0];
    if (u.searchParams.get("v"))               return u.searchParams.get("v");
    // live chat URLs have /live_chat?v=...
    if (u.searchParams.get("video_id"))        return u.searchParams.get("video_id");
  } catch (_) {}
  // youtube.com/live/ID
  const m = input.match(/youtube\.com\/live\/([A-Za-z0-9_-]{11})/);
  if (m) return m[1];
  return null;
}

/* ── Status helper ───────────────────────────────────── */
function setStatus(msg, dotClass = "idle") {
  statusEl.textContent = msg;
  indicatorLabel.textContent = msg;
  dot.className = "lv-dot " + dotClass;
}

/* ── Embed video ─────────────────────────────────────── */
function embedVideo(vid) {
  iframe.src = `https://www.youtube.com/embed/${vid}?autoplay=1`;
  placeholder.style.display = "none";
  iframe.style.display = "block";
}

/* ── Add a transcript line ───────────────────────────── */
function addLine(ts, text) {
  if (!text.trim()) return;
  transcript.push({ ts, text });

  // Show area if first line
  if (transcript.length === 1) {
    transcriptEmpty.style.display = "none";
    copyBtn.style.display = "";
  }

  const line = document.createElement("div");
  line.className = "lv-line";
  line.innerHTML = `
    <span class="lv-line-ts">[${ts}]</span>
    <span class="lv-line-text">${escapeHtml(text)}</span>`;
  linesEl.appendChild(line);

  if (autoScroll) scrollToBottom();
}

function scrollToBottom() {
  transcriptBody.scrollTop = transcriptBody.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

/* ── Render markdown-ish IA text ─────────────────────── */
function renderMd(text) {
  return text
    .split("\n")
    .map(line => {
      // ### heading
      if (/^###\s/.test(line)) return `<h3>${escapeHtml(line.slice(4))}</h3>`;
      // ## heading
      if (/^##\s/.test(line))  return `<h3>${escapeHtml(line.slice(3))}</h3>`;
      // bullet
      if (/^[-*]\s/.test(line)) return `<li>${renderInline(line.slice(2))}</li>`;
      // empty
      if (!line.trim()) return "";
      return `<p>${renderInline(line)}</p>`;
    })
    .join("");
}

function renderInline(s) {
  return escapeHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

/* ── IA analysis ─────────────────────────────────────── */
async function runAnalysis() {
  if (transcript.length === 0) return;

  iaEmpty.style.display = "none";
  iaContent.style.display = "";
  iaSpinner.style.display = "";
  iaContent.innerHTML = "";

  const body = {
    transcript: transcript.map(l => `[${l.ts}] ${l.text}`).join("\n"),
    titulo: `Live — ${videoId}`,
  };

  try {
    const res = await fetch("/live/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const reader = res.body.getReader();
    const dec    = new TextDecoder();
    let buf      = "";
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        const raw = part.slice(6).trim();
        if (raw === "[DONE]") break;
        try {
          const d = JSON.parse(raw);
          if (d.text) {
            fullText += d.text;
            iaContent.innerHTML = renderMd(fullText);
          }
        } catch (_) {}
      }
    }
  } catch (err) {
    iaContent.innerHTML = `<p style="color:#c53030">Error al analizar: ${escapeHtml(String(err))}</p>`;
  } finally {
    iaSpinner.style.display = "none";
  }
}

/* ── Countdown timer for auto-analysis ──────────────── */
function startCountdown() {
  countdown = 60;
  iaFooter.style.display = "";
  clearInterval(analyzeTimer);
  analyzeTimer = setInterval(() => {
    countdown--;
    iaCountdown.textContent = countdown;
    if (countdown <= 0) {
      runAnalysis();
      countdown = 60;
      iaCountdown.textContent = countdown;
    }
  }, 1000);
}

function stopCountdown() {
  clearInterval(analyzeTimer);
  analyzeTimer = null;
  iaFooter.style.display = "none";
}

/* ── Start transcription ─────────────────────────────── */
function startTranscription() {
  const input = urlInput.value.trim();
  if (!input) { urlInput.focus(); return; }

  const vid = parseYouTubeId(input);
  if (!vid) {
    setStatus("URL no reconocida. Pega una URL de YouTube válida.", "idle");
    return;
  }

  videoId = vid;
  embedVideo(vid);

  // Reset transcript
  transcript = [];
  linesEl.innerHTML = "";
  transcriptEmpty.style.display = "";
  copyBtn.style.display = "none";
  iaContent.style.display = "none";
  iaEmpty.style.display = "";
  iaContent.innerHTML = "";
  autoScroll = true;
  scrollBtn.style.display = "none";

  startBtn.style.display  = "none";
  stopBtn.style.display   = "";

  setStatus("Conectando...", "live");

  if (es) es.close();
  es = new EventSource(`/live/transcribe?video_id=${encodeURIComponent(vid)}`);

  es.onmessage = (e) => {
    if (e.data === "[DONE]") {
      setStatus("Transmisión terminada.", "idle");
      stopBtn.style.display  = "none";
      startBtn.style.display = "";
      stopCountdown();
      return;
    }
    try {
      const d = JSON.parse(e.data);
      if (d.status)    { setStatus(d.status, d.status.includes("Transcrib") ? "transcribing" : "live"); }
      if (d.error)     { setStatus("Error: " + d.error, "idle"); }
      if (d.text)      {
        addLine(d.timestamp || "??:??", d.text);
        // Start auto-analysis on first real transcription line
        if (transcript.length === 1) startCountdown();
      }
    } catch (_) {}
  };

  es.onerror = () => {
    setStatus("Conexión interrumpida.", "idle");
    stopBtn.style.display  = "none";
    startBtn.style.display = "";
    stopCountdown();
    if (es) { es.close(); es = null; }
  };
}

/* ── Stop ────────────────────────────────────────────── */
function stopTranscription() {
  if (es) { es.close(); es = null; }
  stopCountdown();
  stopBtn.style.display  = "none";
  startBtn.style.display = "";
  dot.className = "lv-dot idle";
  indicatorLabel.textContent = "Detenido";
  statusEl.textContent = "Detenido";
}

/* ── Auto-scroll pause on manual scroll ─────────────── */
transcriptBody.addEventListener("scroll", () => {
  const atBottom = transcriptBody.scrollHeight - transcriptBody.scrollTop
                   <= transcriptBody.clientHeight + 40;
  if (atBottom) {
    autoScroll = true;
    scrollBtn.style.display = "none";
  } else {
    autoScroll = false;
    scrollBtn.style.display = transcript.length > 0 ? "" : "none";
  }
});

scrollBtn.addEventListener("click", () => {
  autoScroll = true;
  scrollBtn.style.display = "none";
  scrollToBottom();
});

/* ── Copy transcript ─────────────────────────────────── */
copyBtn.addEventListener("click", () => {
  const text = transcript.map(l => `[${l.ts}] ${l.text}`).join("\n");
  navigator.clipboard.writeText(text).then(() => {
    copyBtn.textContent = "¡Copiado!";
    setTimeout(() => {
      copyBtn.innerHTML = `
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
          <rect x="5" y="5" width="9" height="9" rx="1.5"/>
          <path d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2h-6A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5"/>
        </svg>Copiar`;
    }, 2000);
  });
});

/* ── Manual analysis ─────────────────────────────────── */
iaNowBtn.addEventListener("click", () => {
  runAnalysis();
  countdown = 60;
  iaCountdown.textContent = countdown;
});

/* ── Events ──────────────────────────────────────────── */
startBtn.addEventListener("click", startTranscription);
stopBtn.addEventListener("click", stopTranscription);
urlInput.addEventListener("keydown", e => {
  if (e.key === "Enter") startTranscription();
});

/* ── Mobile tabs ─────────────────────────────────────── */
document.querySelectorAll(".lv-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".lv-tab").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    document.querySelector(".lv-col-ia").classList.remove("mobile-active");
    document.querySelector(".lv-col-transcript").classList.remove("mobile-active");
    if (tab === "ia") document.querySelector(".lv-col-ia").classList.add("mobile-active");
    if (tab === "transcript") document.querySelector(".lv-col-transcript").classList.add("mobile-active");
  });
});
// Default mobile: show IA tab
if (window.innerWidth <= 768) {
  document.querySelector(".lv-col-ia").classList.add("mobile-active");
}

/* ── Pre-fill URL from query string ─────────────────── */
const params = new URLSearchParams(location.search);
if (params.get("v")) {
  urlInput.value = params.get("v");
  startTranscription();
}
