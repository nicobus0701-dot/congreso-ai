#!/bin/bash
cd "$(dirname "$0")"

# Instala deps Python si faltan
python3 -c "import fastapi, groq, httpx, bs4" 2>/dev/null || {
  echo "Instalando dependencias Python..."
  pip3 install -r requirements.txt --break-system-packages -q
}

# Instala deps Node si faltan
[ -d node_modules ] || {
  echo "Instalando Electron..."
  npm install --silent
}

npm start
