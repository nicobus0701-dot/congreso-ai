const { app, BrowserWindow, shell, Menu } = require('electron');
const { spawn }  = require('child_process');
const http       = require('http');
const path       = require('path');

const PORT = 8732;   // puerto único para no chocar con adam
let   win  = null;
let   py   = null;

// ── Arranca el servidor FastAPI ─────────────────────────────
function startServer() {
  py = spawn('python3', [path.join(__dirname, 'server.py')], {
    env: { ...process.env, PORT: String(PORT) },
    cwd: __dirname,
  });
  py.stdout.on('data', d => process.stdout.write('[py] ' + d));
  py.stderr.on('data', d => process.stderr.write('[py] ' + d));
  py.on('exit', code => {
    if (code && code !== 0) console.error('[py] salió con código', code);
  });
}

// ── Espera a que el servidor esté listo ─────────────────────
function waitReady(retries, cb) {
  http.get(`http://localhost:${PORT}/`, () => cb(true))
    .on('error', () => {
      if (retries > 0) setTimeout(() => waitReady(retries - 1, cb), 400);
      else             cb(false);
    });
}

// ── Ventana principal ────────────────────────────────────────
function createWindow() {
  win = new BrowserWindow({
    width:  1300,
    height: 840,
    minWidth:  900,
    minHeight: 600,
    title: 'Asistente Congreso Perú',
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
    },
  });

  // Pantalla de carga mientras Python arranca
  win.loadURL(`data:text/html,
    <html><head><style>
      body{margin:0;height:100vh;display:flex;flex-direction:column;
           align-items:center;justify-content:center;
           font-family:system-ui;background:#fff;color:#111;font-weight:700}
      .icon{font-size:52px;margin-bottom:16px}
      .msg{font-size:16px;color:#666}
      .dot{display:inline-block;animation:b 1.2s ease-in-out infinite}
      .dot:nth-child(2){animation-delay:.2s}
      .dot:nth-child(3){animation-delay:.4s}
      @keyframes b{0%,100%{opacity:.2}50%{opacity:1}}
    </style></head><body>
      <div class="icon">🏛</div>
      <div>Iniciando asistente</div>
      <div class="msg">
        <span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>
      </div>
    </body></html>`);

  waitReady(40, ok => {
    if (ok) {
      win.loadURL(`http://localhost:${PORT}`);
    } else {
      win.loadURL(`data:text/html,
        <html><body style="font-family:system-ui;padding:40px;font-weight:700">
          <h2>Error iniciando el servidor</h2>
          <p>Asegúrate de tener Python 3 y las dependencias instaladas:</p>
          <pre>pip3 install -r requirements.txt --break-system-packages</pre>
        </body></html>`);
    }
  });

  // Links externos se abren en el navegador
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

// ── Ciclo de vida ────────────────────────────────────────────
app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  startServer();
  createWindow();
});

app.on('window-all-closed', () => {
  if (py) py.kill();
  app.quit();
});

app.on('before-quit', () => {
  if (py) py.kill();
});
