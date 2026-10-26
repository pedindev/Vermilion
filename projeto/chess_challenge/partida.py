"""Base local para operar o Stockfish no III Chess Challenge."""

import argparse
from functools import partial
from math import isfinite
from pathlib import Path
import re
import sys

import chess
import chess.engine

from .motor import abrir_motor, THREADS_PADRAO, HASH_PADRAO
from .inteligencia import Jogador, MODOS
from .relatorios import PASTA_RELATORIOS, registrar_lance, salvar_relatorio


def motivo_encerramento(tabuleiro):
    if tabuleiro.is_checkmate():
        vencedor = "pretas" if tabuleiro.turn else "brancas"
        return f"Xeque-mate. Vitória das {vencedor}."
    if tabuleiro.is_stalemate():
        return "Empate por afogamento."
    if tabuleiro.is_insufficient_material():
        return "Empate por material insuficiente."
    if tabuleiro.is_repetition(3):
        return "Empate por tripla repetição."
    if tabuleiro.is_fifty_moves():
        return "Empate pela regra dos 50 lances."
    return None


def mostrar_tabuleiro(tabuleiro):
    return "\n".join([f"{8-i}  {linha}" for i, linha in enumerate(str(tabuleiro).splitlines())]
                     + ["   a b c d e f g h"])


def ler_entrada(texto, tabuleiro):
    partes = texto.lower().split()
    if len(partes) != 2 or not re.fullmatch(r"[0-9]{1,3}:[0-5][0-9]", partes[1]):
        raise ValueError("Use lance UCI e nosso tempo: e7e5 14:50.")
    try:
        lance = chess.Move.from_uci(partes[0])
    except ValueError as erro:
        raise ValueError("Formato de lance inválido. Exemplo: e7e5.") from erro
    if lance not in tabuleiro.legal_moves:
        raise ValueError("Lance ilegal. A posição foi mantida.")
    minutos, segundos = map(int, partes[1].split(":"))
    return lance, minutos * 60 + segundos


def oferecer_relatorio(registros, resultado, cor, incremento, nome_motor, restante,
                       entrada, saida, pasta, configuracao=""):
    while True:
        try:
            resposta = entrada("\nDeseja salvar o relatório? [s/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if resposta in ("n", "não", "nao", ""):
            saida("Relatório não salvo.")
            return
        if resposta in ("s", "sim"):
            break
        saida("Responda s ou n.")
    while True:
        try:
            nome = entrada("Nome da partida: ")
            caminho = salvar_relatorio(nome, registros, resultado, cor, incremento,
                                       nome_motor, pasta, restante, configuracao)
        except (EOFError, KeyboardInterrupt):
            return
        except (ValueError, OSError) as erro:
            saida(f"Não foi possível salvar: {erro}")
        else:
            saida(f"Relatório salvo: {caminho}")
            return


def executar(entrada=input, saida=partial(print, flush=True), conectar=abrir_motor,
             pasta_relatorios=PASTA_RELATORIOS, tempo=900, incremento=10, modo="completo",
             configuracao="", cor_inicial=None, contexto=None, acompanhamento=None,
             tempo_adversario=None):
    if not isfinite(tempo) or tempo <= 0 or not isfinite(incremento) or incremento < 0:
        raise ValueError("Tempo deve ser positivo e incremento não negativo.")
    tabuleiro, registros = chess.Board(), []
    cor, restante, nome_motor = cor_inicial, tempo, "Stockfish"
    saldo_adversario = tempo_adversario
    resultado, sem_entrada, falha = "Partida interrompida.", False, None
    try:
        while cor is None:
            escolha = entrada("Sua equipe joga com [1] Brancas ou [2] Pretas? ").strip().lower()
            if escolha in ("1", "brancas"):
                cor = chess.WHITE
            elif escolha in ("2", "pretas"):
                cor = chess.BLACK
            else:
                saida("Escolha 1 ou 2.")
        saida(f"Nossa equipe: {'Brancas' if cor else 'Pretas'}.\n")
        saida(f"Ritmo: {tempo / 60:g} minutos + {incremento:g} segundos por lance.\n")
        if contexto is not None:
            saida(f"Campanha: {contexto.objetivo} — {contexto.motivo}\n")
        with conectar() as motor, Jogador(motor, modo, contexto=contexto) as jogador:
            nome_motor = motor.id.get("name", "Stockfish")
            saida(f"Motor conectado: {nome_motor}. Modo: {modo}.\n")
            if configuracao:
                saida(configuracao + "\n")
            while not (fim := motivo_encerramento(tabuleiro)):
                calculado = None
                if tabuleiro.turn == cor:
                    if restante <= 0:
                        resultado = "Saldo informado esgotado. Confira o resultado com o árbitro."
                        break
                    saida("IA pensando...\n")
                    calculado = jogador.calcular(tabuleiro, restante, incremento, adversario=saldo_adversario)
                    if calculado.tempo >= restante:
                        resultado = "Motor retornou após o saldo informado; lance não aplicado. Confira o árbitro."
                        break
                    lance = calculado.lance
                    restante = restante - calculado.tempo + incremento
                    saida(f"Análise: {calculado.tempo:.2f}s | antecipação {calculado.detalhes['antecipacao']} | "
                          f"{calculado.detalhes['criterio']}.\n")
                else:
                    texto = entrada("Adversário — UCI e nosso tempo" +
                        (", opcionalmente tempo adversário (e7e5 14:50 14:40): " if acompanhamento else " (e7e5 14:50): "))
                    try:
                        partes = texto.split()
                        if acompanhamento and len(partes) == 3:
                            lance, novo_saldo = ler_entrada(" ".join(partes[:2]), tabuleiro)
                            if not re.fullmatch(r"[0-9]{1,3}:[0-5][0-9]", partes[2]):
                                raise ValueError("Tempo adversário inválido. Use mm:ss.")
                            m, s = map(int, partes[2].split(":"))
                            saldo_adversario = m * 60 + s
                        else:
                            lance, novo_saldo = ler_entrada(texto, tabuleiro)
                            saldo_adversario = None
                    except ValueError as erro:
                        saida(f"{erro}\n")
                        continue
                    restante = novo_saldo
                registro = registrar_lance(tabuleiro, lance, cor, calculado)
                tabuleiro.push(lance)
                registros.append(registro)
                if acompanhamento:
                    acompanhamento("lance", tabuleiro, registros, restante, resultado)
                saida(f"{registro.numero}. {registro.autor} | {registro.cor} | {registro.uci}\n")
                saida(mostrar_tabuleiro(tabuleiro) + "\n")
                if calculado is not None and not motivo_encerramento(tabuleiro):
                    jogador.preparar(tabuleiro, calculado)
            else:
                resultado = fim
            saida(resultado)
    except EOFError:
        sem_entrada = True
        saida("\nEntrada encerrada. Partida interrompida.")
    except KeyboardInterrupt:
        saida("\nPartida interrompida pelo operador.")
    except (OSError, chess.engine.EngineError, TimeoutError) as erro:
        falha = erro
        resultado = f"Partida interrompida por falha: {erro or type(erro).__name__}"
        saida(resultado)
    if acompanhamento:
        acompanhamento("fim", tabuleiro, registros, restante, resultado)
    if registros and not sem_entrada:
        oferecer_relatorio(registros, resultado, cor, incremento, nome_motor, restante,
                           entrada, saida, pasta_relatorios, f"Modo: {modo}. {configuracao}")
    if falha is not None:
        raise falha
    return tabuleiro


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "campanha":
        from .torneio import main as main_campanha
        return main_campanha(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motor", type=Path, help="Caminho do executável Stockfish")
    parser.add_argument("--modo", choices=MODOS, default="completo")
    parser.add_argument("--threads", type=int, default=THREADS_PADRAO)
    parser.add_argument("--hash", dest="hash_mb", type=int, default=HASH_PADRAO)
    parser.add_argument("--tempo", type=float, default=900, help="Segundos iniciais; campeonato: 900")
    parser.add_argument("--incremento", type=float, default=10, help="Segundos por lance; campeonato: 10")
    args = parser.parse_args(argv)
    if args.threads < 1 or args.hash_mb < 1:
        parser.error("Threads e hash devem ser positivos.")
    if not isfinite(args.tempo) or args.tempo <= 0 or not isfinite(args.incremento) or args.incremento < 0:
        parser.error("Tempo deve ser positivo e incremento não negativo; ambos finitos.")
    try:
        executar(conectar=partial(abrir_motor, args.motor, args.threads, args.hash_mb),
                 tempo=args.tempo, incremento=args.incremento, modo=args.modo,
                 configuracao=f"Recursos: {args.threads} threads, {args.hash_mb} MB de hash.")
    except (OSError, chess.engine.EngineError, TimeoutError) as erro:
        print(f"Falha: {erro or type(erro).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
