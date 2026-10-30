"""Stockfish original via UCI; o próprio motor administra o relógio recebido."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from math import isfinite
import logging
from pathlib import Path
import shutil
from time import monotonic

import chess
import chess.engine


MOTOR_PADRAO = Path(__file__).resolve().parents[2] / "stockfish" / "stockfish-windows-x86-64-universal.exe"
THREADS_PADRAO = 4
HASH_PADRAO = 512


class _ConfiguracaoUci(logging.Filter):
    def filter(self, registro):
        # SF19 informa as threads durante setoption; python-chess 1.11.2 avisa
        # como saída inesperada. Suprime somente esse aviso conhecido.
        return "Unexpected engine output: 'info string Using " not in registro.getMessage()


logging.getLogger("chess.engine").addFilter(_ConfiguracaoUci())


@dataclass(frozen=True)
class LanceCalculado:
    lance: chess.Move
    tempo: float
    info: dict
    previsao: chess.Move | None = None
    detalhes: dict = field(default_factory=dict)


@contextmanager
def abrir_motor(caminho=None, threads=THREADS_PADRAO, hash_mb=HASH_PADRAO):
    if threads < 1 or hash_mb < 1:
        raise ValueError("Threads e memória hash devem ser positivos.")
    if caminho is None:
        caminho = MOTOR_PADRAO if MOTOR_PADRAO.is_file() else shutil.which("stockfish")
    if caminho is None or not Path(caminho).is_file():
        raise FileNotFoundError("Stockfish não encontrado. Use --motor com o caminho do executável.")
    with chess.engine.SimpleEngine.popen_uci(str(Path(caminho).resolve()), timeout=30) as motor:
        motor.configure({"Threads": threads, "Hash": hash_mb,
                         "SyzygyPath": "", "SyzygyProbeLimit": 5})
        motor.ping()
        motor.timeout = 5
        yield motor


def calcular_lance(motor, tabuleiro, restante, incremento=10, agora=monotonic, adversario=None):
    if not isfinite(restante) or restante <= 0 or not isfinite(incremento) or incremento < 0:
        raise ValueError("Informe um saldo positivo e um incremento não negativo.")
    # Não envia movetime, profundidade-alvo, sondagem ou regras próprias de parada.
    # Envia os saldos por cor; o próprio Stockfish escolhe a duração da busca.
    if tabuleiro.turn == chess.WHITE:
        limite = chess.engine.Limit(white_clock=restante, white_inc=incremento)
    else:
        limite = chess.engine.Limit(black_clock=restante, black_inc=incremento)
    if adversario is not None:
        if not isfinite(adversario) or adversario < 0:
            raise ValueError("Saldo adversário inválido.")
        if tabuleiro.turn:
            limite.black_clock, limite.black_inc = adversario, incremento
        else:
            limite.white_clock, limite.white_inc = adversario, incremento
    inicio = agora()
    resposta = motor.play(tabuleiro.copy(stack=True), limite, ponder=False,
                          info=chess.engine.INFO_ALL)
    tempo = agora() - inicio
    if resposta.move is None or resposta.move not in tabuleiro.legal_moves:
        raise chess.engine.EngineError("Stockfish não retornou um lance legal.")
    return LanceCalculado(resposta.move, tempo, resposta.info, resposta.ponder)
