/* ── State ───────────────────────────────────────────── */
let es           = null;
let transcript   = [];
let autoScroll   = true;
let analyzeTimer = null;
let countdown    = 60;
let currentVideoId = "";

const $ = id => document.getElementById(id);

/* ── DOM refs ────────────────────────────────────────── */
const videoList       = $("lv-video-list");
const listLoading     = $("lv-list-loading");
const refreshBtn      = $("lv-refresh-btn");
const lv_empty        = $("lv-empty");
const lv_columns      = $("lv-columns");
const iframe          = $("lv-iframe");
const videoTitleLabel = $("lv-video-title-label");
const indicatorDot    = $("lv-indicator-dot");
const indicatorLabel  = $("lv-indicator-label");
const startBtn        = $("lv-start-btn");
const stopBtn         = $("lv-stop-btn");
const iaSpinner       = $("lv-ia-spinner");
const iaEmpty         = $("lv-ia-empty");
const iaContent       = $("lv-ia-content");
const iaFooter        = $("lv-ia-footer");
const iaCountdown     = $("lv-ia-countdown");
const iaNowBtn        = $("lv-ia-now-btn");
const transcriptBody  = $("lv-transcript-body");
const transcriptEmpty = $("lv-transcript-empty");
const linesEl         = $("lv-lines");
const scrollBtn       = $("lv-scroll-btn");
const copyBtn         = $("lv-copy-btn");

/* ── Load video list ─────────────────────────────────── */
async function loadVideos() {
  listLoading.style.display = "flex";
  // Clear existing cards
  Array.from(videoList.querySelectorAll(".lv-video-card")).forEach(c => c.remove());

  try {
    const res  = await fetch("/sesiones/videos");
    const data = await res.json();
    listLoading.style.display = "none";

    if (!data.ok || !data.videos?.length) {
      videoList.innerHTML += `<p style="padding:16px 14px;font-size:12px;color:#aaa">No se encontraron videos.</p>`;
      return;
    }

    for (const v of data.videos) {
      const card = document.createElement("div");
      card.className = "lv-video-card";
      card.dataset.id    = v.id;
      card.dataset.title = v.titulo;
      card.dataset.live  = v.en_vivo ? "1" : "0";

      const liveBadge = v.en_vivo
        ? `<span class="lv-badge-live">🔴 EN VIVO</span>`
        : v.fue_live ? `<span class="lv-badge-past">Finalizado</span>` : "";

      const duration = v.duracion
        ? `<span class="lv-card-duration">${v.duracion}</span>` : "";

      card.innerHTML = `
        <img class="lv-card-thumb" src="${v.thumb}" alt="" loading="lazy">
        <div class="lv-card-meta">${liveBadge}${duration}</div>
        <div class="lv-card-title">${escHtml(v.titulo)}</div>`;

      card.addEventListener("click", () => selectVideo(v.id, v.titulo, v.en_vivo));
      videoList.appendChild(card);
    }
  } catch (err) {
    listLoading.style.display = "none";
    videoList.innerHTML += `<p style="padding:16px 14px;font-size:12px;color:#c53030">Error al cargar: ${escHtml(String(err))}</p>`;
  }
}

/* ── Select a video ──────────────────────────────────── */
function selectVideo(id, title, isLive) {
  // Stop any running transcription
  stopTranscription(false);

  currentVideoId = id;

  // Highlight selected card
  document.querySelectorAll(".lv-video-card").forEach(c => {
    c.classList.toggle("active", c.dataset.id === id);
  });

  // Show 3-column layout
  lv_empty.style.display   = "none";
  lv_columns.style.display = "";

  // Embed video
  iframe.src = `https://www.youtube.com/embed/${id}?autoplay=1`;
  videoTitleLabel.textContent = title;

  // Reset transcript panel
  transcript = [];
  linesEl.innerHTML = "";
  transcriptEmpty.style.display = "";
  copyBtn.style.display = "none";
  autoScroll = true;
  scrollBtn.style.display = "none";

  // Reset IA panel
  iaContent.style.display = "none";
  iaEmpty.style.display   = "";
  iaContent.innerHTML     = "";
  iaFooter.style.display  = "none";

  // Update indicator
  setStatus(isLive ? "🔴 En vivo" : "Sesión grabada", isLive ? "live" : "idle");

  // Show start button
  startBtn.style.display = "";
  stopBtn.style.display  = "none";
}

/* ── Transcription controls ──────────────────────────── */
function startTranscription() {
  if (!currentVideoId) return;

  transcript = [];
  linesEl.innerHTML = "";
  transcriptEmpty.style.display = "";
  copyBtn.style.display = "none";
  iaContent.innerHTML = "";
  iaContent.style.display = "none";
  iaEmpty.style.display = "";
  autoScroll = true;
  scrollBtn.style.display = "none";

  startBtn.style.display = "none";
  stopBtn.style.display  = "";
  setStatus("Conectando...", "live");

  if (es) es.close();
  es = new EventSource(`/live/transcribe?video_id=${encodeURIComponent(currentVideoId)}`);

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
      if (d.status) setStatus(d.status, d.status.toLowerCase().includes("transcrib") ? "transcribing" : "live");
      if (d.error)  setStatus("Error: " + d.error, "idle");
      if (d.text) {
        addLine(d.timestamp || "??:??", d.text);
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

function stopTranscription(resetUI = true) {
  if (es) { es.close(); es = null; }
  stopCountdown();
  if (resetUI) {
    stopBtn.style.display  = "none";
    startBtn.style.display = "";
    setStatus("Detenido", "idle");
  }
}

/* ── Helpers ─────────────────────────────────────────── */
function setStatus(msg, dotClass = "idle") {
  indicatorLabel.textContent = msg;
  indicatorDot.className = "lv-indicator-dot " + dotClass;
}

function addLine(ts, text) {
  if (!text.trim()) return;
  transcript.push({ ts, text });
  if (transcript.length === 1) {
    transcriptEmpty.style.display = "none";
    copyBtn.style.display = "";
  }
  const line = document.createElement("div");
  line.className = "lv-line";
  line.innerHTML = `<span class="lv-line-ts">[${ts}]</span><span class="lv-line-text">${escHtml(text)}</span>`;
  linesEl.appendChild(line);
  if (autoScroll) transcriptBody.scrollTop = transcriptBody.scrollHeight;
}

function escHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

/* ── IA analysis ─────────────────────────────────────── */
async function runAnalysis() {
  if (!transcript.length) return;
  iaEmpty.style.display   = "none";
  iaContent.style.display = "";
  iaSpinner.style.display = "";
  iaContent.innerHTML     = "";

  const body = {
    transcript: transcript.map(l => `[${l.ts}] ${l.text}`).join("\n"),
    titulo: videoTitleLabel.textContent,
  };

  try {
    const res = await fetch("/live/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const reader = res.body.getReader();
    const dec    = new TextDecoder();
    let buf = "", fullText = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n"); buf = parts.pop();
      for (const part of parts) {
        if (!part.startsWith("data: ")) continue;
        const raw = part.slice(6).trim();
        if (raw === "[DONE]") break;
        try {
          const d = JSON.parse(raw);
          if (d.text) { fullText += d.text; iaContent.innerHTML = renderMd(fullText); }
        } catch (_) {}
      }
    }
  } catch (err) {
    iaContent.innerHTML = `<p style="color:#c53030">Error: ${escHtml(String(err))}</p>`;
  } finally {
    iaSpinner.style.display = "none";
  }
}

function renderMd(text) {
  return text.split("\n").map(line => {
    if (/^###?\s/.test(line)) return `<h3>${renderInline(line.replace(/^###?\s/,""))}</h3>`;
    if (/^[-*]\s/.test(line)) return `<li>${renderInline(line.slice(2))}</li>`;
    if (!line.trim()) return "";
    return `<p>${renderInline(line)}</p>`;
  }).join("");
}
function renderInline(s) {
  return escHtml(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

/* ── Countdown ───────────────────────────────────────── */
function startCountdown() {
  countdown = 60; iaFooter.style.display = "";
  clearInterval(analyzeTimer);
  analyzeTimer = setInterval(() => {
    iaCountdown.textContent = --countdown;
    if (countdown <= 0) { runAnalysis(); countdown = 60; iaCountdown.textContent = countdown; }
  }, 1000);
}
function stopCountdown() {
  clearInterval(analyzeTimer); analyzeTimer = null;
  iaFooter.style.display = "none";
}

/* ── Auto-scroll ─────────────────────────────────────── */
transcriptBody.addEventListener("scroll", () => {
  const atBottom = transcriptBody.scrollHeight - transcriptBody.scrollTop <= transcriptBody.clientHeight + 40;
  autoScroll = atBottom;
  scrollBtn.style.display = (!atBottom && transcript.length) ? "" : "none";
});
scrollBtn.addEventListener("click", () => {
  autoScroll = true; scrollBtn.style.display = "none";
  transcriptBody.scrollTop = transcriptBody.scrollHeight;
});

/* ── Copy transcript ─────────────────────────────────── */
copyBtn.addEventListener("click", () => {
  navigator.clipboard.writeText(transcript.map(l => `[${l.ts}] ${l.text}`).join("\n")).then(() => {
    const orig = copyBtn.innerHTML;
    copyBtn.textContent = "¡Copiado!";
    setTimeout(() => { copyBtn.innerHTML = orig; }, 2000);
  });
});

/* ── Events ──────────────────────────────────────────── */
startBtn.addEventListener("click", startTranscription);
stopBtn.addEventListener("click",  () => stopTranscription(true));
iaNowBtn.addEventListener("click", () => { runAnalysis(); countdown = 60; iaCountdown.textContent = 60; });
refreshBtn.addEventListener("click", loadVideos);

/* ── Init ────────────────────────────────────────────── */
loadVideos();
