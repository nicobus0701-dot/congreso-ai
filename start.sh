#!/bin/bash
cd "$(dirname "$0")"

# Matar backend previo en el puerto si existe (evita conflicto)
fuser -k 8732/tcp 2>/dev/null || true

# Instala deps Python si faltan (silencioso, no bloquea el inicio)
python3 -c "import fastapi, groq, httpx, bs4, Crypto" 2>/dev/null || \
  pip3 install -r requirements.txt --break-system-packages -q 2>/dev/null || true

# Instala deps Node si faltan
[ -d node_modules ] || npm install --silent 2>/dev/null

npm start
