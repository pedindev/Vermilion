#!/usr/bin/env bash
set -euo pipefail

base="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$base"

if [[ ! -f "$base/stockfish/stockfish-linux-x86-64-universal" ]]; then
    echo "Baixe o Stockfish 19 Linux x86-64 Universal antes de preparar:"
    echo "https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-linux-x86-64-universal.tar.gz"
    echo "Extraia a pasta stockfish do arquivo para dentro de Versão Linux e execute novamente."
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Instale Python 3 com suporte a venv antes de preparar o projeto."
    exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Use Python 3.10 ou superior.")'

if [[ ! -x "$base/projeto/.venv/bin/python" ]]; then
    if ! python3 -m venv --copies "$base/projeto/.venv"; then
        echo "No Zorin OS/Ubuntu, instale python3-venv e execute novamente: bash preparar.sh"
        exit 1
    fi
fi

python="$base/projeto/.venv/bin/python"
"$python" -m pip install --no-index --find-links "$base/dependencias" -r "$base/projeto/requirements-dev.txt"
chmod u+x "$base/stockfish/stockfish-linux-x86-64-universal"
cd "$base/projeto"
"$python" -X utf8 - <<'PY'
from chess_challenge.motor import abrir_motor
with abrir_motor() as motor:
    print(f"Motor verificado: {motor.id.get('name', 'Stockfish')}")
print("Preparação concluída. Para cada partida: bash iniciar.sh (na pasta Versão Linux).")
PY
