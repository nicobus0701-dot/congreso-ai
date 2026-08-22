#!/bin/bash
cd "$(dirname "$0")"

# Matar cualquier instancia previa del app.
# macOS no trae `fuser` (es de psmisc, paquete de Linux): el equivalente que sí
# viene de fábrica es lsof.
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8732/tcp 2>/dev/null || true
else
  lsof -ti tcp:8732 2>/dev/null | xargs -r kill -9 2>/dev/null || true
fi
pkill -f "[Ee]lectron.*congreso-ai" 2>/dev/null || true
sleep 0.5

# Deps de Python en un venv del proyecto. Antes esto hacía
# `pip3 install --break-system-packages` contra el Python del sistema: esa
# bandera es de las distros Linux con PEP 668 (Debian/Ubuntu), en macOS no
# aplica y ensucia el Python global. El venv sirve en los dos sistemas.
if [ ! -d .venv ]; then
  echo "Creando entorno virtual (.venv)..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
else
  .venv/bin/python -c "import fastapi, groq, httpx, bs4, Crypto" 2>/dev/null || \
    .venv/bin/pip install -q -r requirements.txt
fi

# Instala deps Node si faltan
[ -d node_modules ] || npm install --silent 2>/dev/null

npm start
