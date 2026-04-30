#!/usr/bin/env bash
# Start the full Veille Terminaux stack (backend + frontend)
# Usage: ./start.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "▶ Démarrage du backend FastAPI sur http://localhost:8000 …"
cd "$SCRIPT_DIR/backend"
"$SCRIPT_DIR/.venv/bin/uvicorn" main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

echo "▶ Démarrage du frontend React sur http://localhost:5173 …"
cd "$SCRIPT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✅  Stack démarrée :"
echo "   Frontend  → http://localhost:5173"
echo "   Backend   → http://localhost:8000"
echo "   API Docs  → http://localhost:8000/docs"
echo ""
echo "Ctrl+C pour tout arrêter."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stack arrêtée.'" INT TERM
wait
