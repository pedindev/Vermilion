#!/usr/bin/env bash
set -euo pipefail

base="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="$base/projeto/.venv/bin/python"
if [[ ! -x "$python" ]]; then
    echo "Prepare o ambiente primeiro: bash preparar.sh"
    exit 1
fi
chmod u+x "$base/stockfish/stockfish-linux-x86-64-universal"
cd "$base/projeto"
exec "$python" -X utf8 jogar.py campeonato "$@"
