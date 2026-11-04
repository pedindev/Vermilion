"""Stockfish via UCI; distribui o orçamento dos relógios e da janela total."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from math import isfinite
import logging
from pathlib import Path
import shutil
import sys
from time import monotonic

import chess
import chess.engine


NOME_MOTOR = {"win32": "stockfish-windows-x86-64-universal.exe",
              "linux": "stockfish-linux-x86-64-universal"}.get(sys.platform, "stockfish")
MOTOR_PADRAO = Path(__file__).resolve().parents[2] / "stockfish" / NOME_MOTOR
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


def calcular_lance(motor, tabuleiro, restante, incremento=10, agora=monotonic, adversario=None,
                   janela_restante=None):
    if not isfinite(restante) or restante <= 0 or not isfinite(incremento) or incremento < 0:
        raise ValueError("Informe um saldo positivo e um incremento não negativo.")
    if adversario is not None and (not isfinite(adversario) or adversario < 0):
        raise ValueError("Saldo adversário inválido.")
    detalhes = {}
    nosso_calculo, outro_calculo, incremento_calculo = restante, adversario, incremento
    if janela_restante is not None:
        if not isfinite(janela_restante) or janela_restante < 0:
            raise ValueError("A previsão restante deve ser não negativa e finita.")
        # A previsão orienta o orçamento, mas não é um prazo de encerramento.
        # Depois de atingida, o planejamento volta aos relógios oficiais.
        if janela_restante > 0:
            disponivel = janela_restante - min(1.0, janela_restante * .05)
            outro_saldo = restante if adversario is None else adversario
            fracao = restante / (restante + outro_saldo)
            nosso_calculo = min(restante, disponivel * fracao)
            outro_calculo = min(outro_saldo, disponivel * (1 - fracao)) if adversario is not None else None
            restringe = nosso_calculo < restante or (outro_calculo is not None and outro_calculo < adversario)
            incremento_calculo = 0 if restringe else incremento
        detalhes["planejamento_tempo"] = dict(janela_restante_s=janela_restante,
            relogio_nosso_s=restante, relogio_adversario_s=adversario,
            orcamento_nosso_s=nosso_calculo, orcamento_adversario_s=outro_calculo,
            incremento_planejamento_s=incremento_calculo,
            previsao_atingida=janela_restante == 0,
            metodo="Previsão de duração e saldos reais; sem encerramento por previsão")
    # Sem movetime, profundidade ou nós fixos: o Stockfish distribui o orçamento.
    if tabuleiro.turn == chess.WHITE:
        limite = chess.engine.Limit(white_clock=nosso_calculo, white_inc=incremento_calculo)
    else:
        limite = chess.engine.Limit(black_clock=nosso_calculo, black_inc=incremento_calculo)
    if adversario is not None:
        if tabuleiro.turn:
            limite.black_clock, limite.black_inc = outro_calculo, incremento_calculo
        else:
            limite.white_clock, limite.white_inc = outro_calculo, incremento_calculo
    inicio = agora()
    resposta = motor.play(tabuleiro.copy(stack=True), limite, ponder=False,
                          info=chess.engine.INFO_ALL)
    tempo = agora() - inicio
    if resposta.move is None or resposta.move not in tabuleiro.legal_moves:
        raise chess.engine.EngineError("Stockfish não retornou um lance legal.")
    return LanceCalculado(resposta.move, tempo, resposta.info, resposta.ponder, detalhes)
