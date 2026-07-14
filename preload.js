const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  exportPDF:     (html)    => ipcRenderer.invoke('export-pdf',    html),
  exportWord:    (content) => ipcRenderer.invoke('export-word',   content),
  openSessions:  ()        => ipcRenderer.invoke('open-sessions'),
});
