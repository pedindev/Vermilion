"""Base local para operar o Stockfish no III Chess Challenge."""

import argparse
from dataclasses import replace
from time import monotonic
from functools import partial
from math import isfinite
from pathlib import Path
import sys

import chess
import chess.engine

from .motor import abrir_motor, THREADS_PADRAO, HASH_PADRAO
from .inteligencia import Jogador, MODOS
from .aberturas import Repertorio
from .relatorios import PASTA_RELATORIOS, registrar_lance, salvar_relatorio
from .relogio import (RelogioPartida, TempoEsgotado, JanelaPartida, DuracaoEsgotada,
                      entrada_com_prazo, formatar_relogios, formatar_tempo, ler_tempo)


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
    partes = texto.strip().lower().split()
    if len(partes) != 1:
        raise ValueError("Digite apenas o lance UCI, por exemplo: e7e5.")
    try:
        lance = chess.Move.from_uci(partes[0])
    except ValueError as erro:
        raise ValueError("Formato de lance inválido. Exemplo: e7e5.") from erro
    if lance not in tabuleiro.legal_moves:
        raise ValueError("Lance ilegal. A posição foi mantida.")
    return lance


def oferecer_relatorio(registros, resultado, cor, incremento, nome_motor, restante,
                       entrada, saida, pasta, configuracao="", relogios=None):
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
                                       nome_motor, pasta, restante, configuracao, relogios=relogios)
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
             tempo_adversario=None, agora=monotonic, repertorio=None,
             compacto=False, exportar_relatorio=True, duracao_total_minutos=None):
    if not isfinite(tempo) or tempo <= 0 or not isfinite(incremento) or incremento < 0:
        raise ValueError("Tempo deve ser positivo e incremento não negativo.")
    if cor_inicial is not None and type(cor_inicial) is not bool:
        raise ValueError("Cor inicial inválida.")
    tabuleiro, registros = chess.Board(), []
    janela = JanelaPartida(duracao_total_minutos, agora)
    cor, nome_motor, relogio = cor_inicial, "Stockfish", None
    resultado, sem_entrada, falha = "Partida interrompida.", False, None
    saldos = {True: tempo, False: tempo}
    try:
        while cor is None:
            escolha = entrada("Sua equipe joga com [1] Brancas ou [2] Pretas? ").strip().lower()
            if escolha in ("1", "brancas"):
                cor = chess.WHITE
            elif escolha in ("2", "pretas"):
                cor = chess.BLACK
            else:
                saida("Escolha 1 ou 2.")
        inicial_outro = tempo if tempo_adversario is None else tempo_adversario
        saida(f"Nossa equipe: {'Brancas' if cor else 'Pretas'}.\n")
        if compacto and tempo != inicial_outro:
            saida(f"Relógios: brancas {(tempo if cor else inicial_outro) / 60:g} min | "
                  f"pretas {(inicial_outro if cor else tempo) / 60:g} min | +{incremento:g}s.\n")
        else:
            saida(f"Ritmo: {tempo / 60:g} minutos + {incremento:g} segundos por lance.\n")
        if janela.total is not None:
            saida(f"Duração total informada: {duracao_total_minutos:g} minutos.\n")
        if contexto is not None and not compacto:
            saida(f"Campanha: {contexto.objetivo} — {contexto.motivo}\n")
        with conectar() as motor, Jogador(motor, modo, contexto=contexto, repertorio=repertorio) as jogador:
            nome_motor = motor.id.get("name", "Stockfish")
            saida(f"{nome_motor} conectado.\n" if compacto else f"Motor conectado: {nome_motor}. Modo: {modo}.\n")
            if repertorio is not None and repertorio.erro and modo == "completo":
                saida("Repertório indisponível; usando a análise normal do Stockfish.\n")
            if configuracao and not compacto:
                saida(configuracao + "\n")
            saldos = {cor: tempo, not cor: inicial_outro}
            relogio = RelogioPartida(saldos[True], saldos[False], incremento, agora)
            if not compacto:
                saida("Relógios automáticos iniciados. Digite apenas o lance adversário.\n")
            relogio.iniciar(chess.WHITE)
            janela.iniciar()
            fim = None
            try:
                while fim is None:
                    janela.verificar()
                    turno = tabuleiro.turn
                    if relogio.saldos()[turno] <= 0:
                        raise TempoEsgotado(turno)
                    calculado = None
                    fim_futuro = None
                    if turno == cor:
                        saida("IA pensando...\n")
                        atuais = relogio.saldos()
                        calculado = jogador.calcular(tabuleiro, atuais[cor], incremento,
                                                      adversario=atuais[not cor], agora=agora,
                                                      janela_restante=janela.restante())
                        janela.verificar()
                        if janela.total is not None:
                            calculado = replace(calculado, detalhes={**calculado.detalhes,
                                "duracao_partida": dict(total_s=janela.total, restante_s=janela.restante())})
                        lance = calculado.lance
                        futura = tabuleiro.copy(stack=True)
                        futura.push(lance)
                        fim_futuro = motivo_encerramento(futura)
                        if not fim_futuro:
                            jogador.preparar(futura, calculado)
                    else:
                        try:
                            texto = entrada_com_prazo(entrada, "Adversário — digite o lance UCI: ",
                                                       min(relogio.saldos()[turno],
                                                           janela.restante() if janela.total is not None else float("inf")))
                        except TimeoutError:
                            janela.verificar()
                            raise TempoEsgotado(turno) from None
                        janela.verificar()
                        try:
                            partes = texto.strip().lower().split()
                            if compacto and partes == ["fim"]:
                                resultado = "Partida encerrada pelo operador; resultado oficial pendente."
                                break
                            if partes and partes[0] == "relogios":
                                if len(partes) != 3:
                                    raise ValueError("Use: relogios TEMPO_BRANCAS TEMPO_PRETAS, por exemplo relogios 14:30.250 14:05.125.")
                                relogio.ajustar(ler_tempo(partes[1]), ler_tempo(partes[2]))
                                saldos = relogio.saldos()
                                saida("Ajuste pelo relógio físico registrado. " + formatar_relogios(saldos) + "\n")
                                if acompanhamento:
                                    acompanhamento("relogio_fisico", tabuleiro, registros, saldos, resultado)
                                continue
                            lance = ler_entrada(texto, tabuleiro)
                        except ValueError as erro:
                            saida(f"{erro}\n")
                            continue  # Mesmo turno e mesmo relógio, sem reiniciar o prazo.
                    janela.verificar()
                    gasto = relogio.confirmar_lance(turno)
                    registro = registrar_lance(tabuleiro, lance, cor, calculado)
                    tabuleiro.push(lance)
                    fim = fim_futuro if calculado is not None else motivo_encerramento(tabuleiro)
                    saldos = relogio.parar() if fim else relogio.saldos()
                    registro = replace(registro, tempo=gasto, saldo_brancas=saldos[True],
                                       saldo_pretas=saldos[False], fonte_tempo=relogio.fonte)
                    registros.append(registro)
                    if calculado is not None and not compacto:
                        saida(f"Análise: {calculado.tempo:.2f}s | "
                              f"{calculado.detalhes.get('criterio', 'Stockfish')}.\n")
                    analise = f" | {calculado.tempo:.2f}s" if compacto and calculado is not None else ""
                    saida(f"{registro.numero}. {registro.autor} | {registro.cor} | {registro.uci}{analise}\n")
                    saida(mostrar_tabuleiro(tabuleiro) + "\n")
                    prazo = f" | Partida: {formatar_tempo(janela.restante())}" if janela.total is not None else ""
                    saida(formatar_relogios(saldos) + prazo + "\n")
                    if acompanhamento:
                        acompanhamento("lance", tabuleiro, registros, saldos, resultado)
                else:
                    resultado = fim
            except DuracaoEsgotada as erro:
                resultado = str(erro)
            except TempoEsgotado as erro:
                empate = tabuleiro.has_insufficient_material(not erro.cor)
                resultado = (f"{erro} Empate: adversário sem material para mate." if empate
                             else f"{erro} Vitória das {'pretas' if erro.cor else 'brancas'}.")
            finally:
                saldos = relogio.parar()  # Parar antes de fechar o motor ou perguntar sobre TXT.
            saida(resultado)
    except EOFError:
        sem_entrada = True
        resultado = "Entrada encerrada. Partida interrompida."
        saida("\n" + resultado)
    except KeyboardInterrupt:
        resultado = "Partida interrompida pelo operador."
        saida("\n" + resultado)
    except (OSError, chess.engine.EngineError, TimeoutError) as erro:
        falha = erro
        resultado = f"Partida interrompida por falha: {erro or type(erro).__name__}"
        saida(resultado)
    if relogio is not None:
        saldos = relogio.parar()
    if acompanhamento:
        acompanhamento("fim", tabuleiro, registros, saldos, resultado)
    if exportar_relatorio and registros and not sem_entrada:
        oferecer_relatorio(registros, resultado, cor, incremento, nome_motor, saldos[cor],
                           entrada, saida, pasta_relatorios, f"Modo: {modo}. {configuracao}",
                           relogios=saldos)
    if falha is not None:
        raise falha
    return tabuleiro


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "campeonato":
        from .torneio import main as main_campanha
        return main_campanha(["iniciar", *argv[1:]])
    if argv and argv[0] == "campanha":
        from .torneio import main as main_campanha
        return main_campanha(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motor", type=Path, help="Caminho do executável Stockfish")
    parser.add_argument("--modo", choices=MODOS, default="completo")
    parser.add_argument("--sem-abertura", action="store_true", help="Desativar o repertório preparado")
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
                 repertorio=Repertorio.carregar() if args.modo == "completo" and not args.sem_abertura else None,
                 configuracao=f"Recursos: {args.threads} threads, {args.hash_mb} MB de hash.")
    except (OSError, chess.engine.EngineError, TimeoutError) as erro:
        print(f"Falha: {erro or type(erro).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
