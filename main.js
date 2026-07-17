const { app, BrowserWindow, shell, Menu, globalShortcut, ipcMain, dialog, nativeImage } = require('electron');
app.setName('Congreso IA');
if (process.platform === 'linux') app.setDesktopName('congreso-ai.desktop');
const { spawn }  = require('child_process');
const http       = require('http');
const path       = require('path');
const fs         = require('fs');
const os         = require('os');
const { autoUpdater } = require('electron-updater');

const PORT = 8732;   // puerto único para no chocar con adam
let   win  = null;
let   py   = null;

// ── Arranca el servidor FastAPI ─────────────────────────────
function startServer() {
  const isDev = !app.isPackaged;
  const exe     = isDev ? 'python3'                                         : path.join(process.resourcesPath, 'server', 'server');
  const args    = isDev ? [path.join(__dirname, 'server.py')]               : [];
  const cwd     = isDev ? __dirname                                          : path.join(process.resourcesPath, 'server');

  py = spawn(exe, args, {
    env: { ...process.env, PORT: String(PORT) },
    cwd,
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
    icon: path.join(__dirname, 'static', 'app-icon.png'),
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      partition: 'persist:congreso',
      preload: path.join(__dirname, 'preload.js'),
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

  // Links externos se abren en el navegador del sistema
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith('http://localhost')) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith('http://localhost')) {
      e.preventDefault();
      shell.openExternal(url);
    }
  });
}

// ── IPC: abrir enlace externo ────────────────────────────────
ipcMain.handle('open-external', (e, url) => shell.openExternal(url));

// ── IPC: ventana de Sesiones ─────────────────────────────────
let sessionsWin = null;
ipcMain.handle('open-sessions', () => {
  if (sessionsWin && !sessionsWin.isDestroyed()) {
    sessionsWin.focus();
    return;
  }
  sessionsWin = new BrowserWindow({
    width: 1100, height: 750,
    minWidth: 800, minHeight: 550,
    title: 'Sesiones del Congreso',
    icon: path.join(__dirname, 'static', 'app-icon.png'),
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  sessionsWin.loadURL(`http://localhost:${PORT}/sessions`);
  sessionsWin.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith('http://localhost')) shell.openExternal(url);
    return { action: 'deny' };
  });
  sessionsWin.on('closed', () => { sessionsWin = null; });
});

// ── IPC: exportar PDF ────────────────────────────────────────
ipcMain.handle('export-pdf', async (event, html) => {
  const date = new Date().toISOString().slice(0, 10);
  const { filePath } = await dialog.showSaveDialog(win, {
    title: 'Guardar PDF',
    defaultPath: path.join(os.homedir(), `Resumen-Congreso-${date}.pdf`),
    filters: [{ name: 'PDF', extensions: ['pdf'] }],
  });
  if (!filePath) return { ok: false };

  const tmp = path.join(os.tmpdir(), `congreso-export-${Date.now()}.html`);
  fs.writeFileSync(tmp, html, 'utf8');

  const pdfWin = new BrowserWindow({ show: false });
  await pdfWin.loadFile(tmp);
  const data = await pdfWin.webContents.printToPDF({ printBackground: true, pageSize: 'A4' });
  pdfWin.destroy();
  try { fs.unlinkSync(tmp); } catch {}
  fs.writeFileSync(filePath, data);
  return { ok: true };
});

// ── IPC: exportar Word ───────────────────────────────────────
ipcMain.handle('export-word', async (event, content) => {
  const date = new Date().toISOString().slice(0, 10);
  const { filePath } = await dialog.showSaveDialog(win, {
    title: 'Guardar Word',
    defaultPath: path.join(os.homedir(), `Resumen-Congreso-${date}.docx`),
    filters: [{ name: 'Word Document', extensions: ['docx'] }],
  });
  if (!filePath) return { ok: false };

  const res = await fetch(`http://localhost:${PORT}/export/docx`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  const buf = Buffer.from(await res.arrayBuffer());
  fs.writeFileSync(filePath, buf);
  return { ok: true };
});

// ── Auto-update ──────────────────────────────────────────────
function setupAutoUpdater() {
  if (!app.isPackaged) return;

  autoUpdater.checkForUpdates();

  autoUpdater.on('update-downloaded', () => {
    dialog.showMessageBox(win, {
      type: 'info',
      title: 'Actualización lista',
      message: 'Hay una nueva versión de Congreso IA. ¿Instalar ahora?',
      buttons: ['Instalar y reiniciar', 'Después'],
    }).then(({ response }) => {
      if (response === 0) autoUpdater.quitAndInstall();
    });
  });
}

// ── Ciclo de vida ────────────────────────────────────────────
app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  startServer();
  createWindow();
  setupAutoUpdater();
  globalShortcut.register('CmdOrCtrl+Shift+R', () => {
    win?.webContents.reloadIgnoringCache();
  });
});

app.on('window-all-closed', () => {
  if (py) py.kill();
  app.quit();
});

app.on('before-quit', () => {
  if (py) py.kill();
});
