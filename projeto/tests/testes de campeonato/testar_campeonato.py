"""Partidas automáticas com relógio real, antecipação e cores invertidas."""

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from functools import partial
from math import isfinite
import hashlib
import json
import random
import sqlite3
from pathlib import Path
import sys
from time import monotonic, sleep
from uuid import uuid4

import chess
import chess.engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from chess_challenge.inteligencia import Jogador, MODOS, VERSAO, Parametros
from chess_challenge.motor import abrir_motor, THREADS_PADRAO, HASH_PADRAO
from chess_challenge.aberturas import Repertorio
from chess_challenge.partida import motivo_encerramento
from chess_challenge.relatorios import registrar_lance, salvar_texto
from chess_challenge.campanha import Campanha, Regras, Repositorio, agora as data_utc


PASTA_LOGS = Path(__file__).resolve().parent / "relatórios"
ABERTURAS = [
    ("Siciliana", "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6"),
    ("Gambito da dama", "d2d4 d7d5 c2c4 e7e6 b1c3 g8f6"),
    ("Jogo aberto", "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6"),
    ("Francesa", "e2e4 e7e6 d2d4 d7d5 b1c3 g8f6"),
    ("Inglesa", "c2c4 e7e5 b1c3 g8f6 g1f3 b8c6"),
    ("Inicial", ""),
]


def grupos_cpu():
    """Separa núcleos físicos no Windows, incluindo irmãos SMT no mesmo grupo."""
    if sys.platform != "win32":
        return None
    import ctypes as ct
    from ctypes import wintypes as wt

    class Cpu(ct.Structure):
        _fields_ = [("mask", ct.c_size_t), ("relationship", wt.DWORD), ("reserved", ct.c_ulonglong * 2)]

    kernel = ct.WinDLL("kernel32", use_last_error=True)
    funcao = kernel.GetLogicalProcessorInformation
    funcao.argtypes = [ct.c_void_p, ct.POINTER(wt.DWORD)]
    funcao.restype = wt.BOOL
    tamanho = wt.DWORD()
    funcao(None, ct.byref(tamanho))
    if not tamanho.value:
        raise OSError("Não foi possível consultar a topologia da CPU.")
    dados = (Cpu * (tamanho.value // ct.sizeof(Cpu)))()
    if not funcao(dados, ct.byref(tamanho)):
        raise ct.WinError(ct.get_last_error())
    nucleos = [c.mask for c in dados if c.relationship == 0]
    if len(nucleos) < 2:
        return None
    grupos = [0, 0]
    for i, mask in enumerate(nucleos):
        grupos[i % 2] |= mask
    return tuple(grupos)


def fixar_cpu(motor, mascara):
    if mascara is None:
        return
    import ctypes as ct
    from ctypes import wintypes as wt
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.OpenProcess.restype = wt.HANDLE
    kernel.SetProcessAffinityMask.argtypes = [wt.HANDLE, ct.c_size_t]
    kernel.SetProcessAffinityMask.restype = wt.BOOL
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.OpenProcess(0x0200 | 0x0400, False, motor.transport.get_pid())
    if not handle:
        raise ct.WinError(ct.get_last_error())
    try:
        if not kernel.SetProcessAffinityMask(handle, mascara):
            raise ct.WinError(ct.get_last_error())
    finally:
        kernel.CloseHandle(handle)


@dataclass
class Resultado:
    cor_nossa: bool
    placar: str
    motivo: str
    meios_lances: int
    relogios: dict
    trocas: int = 0
    acertos: int = 0
    previsoes: int = 0
    historico: tuple = ()


def disputar(nosso, adversario, cor_nossa, tempo=900, incremento=10, max_lances=150,
             inicial=None, saida=partial(print, flush=True), registrar=lambda _: None,
             agora=monotonic, latencia=0, dormir=sleep, tempos_iniciais=None,
             falha_derrota=False, ao_lance=None):
    if (not isfinite(tempo) or tempo <= 0 or not isfinite(incremento) or incremento < 0
            or not isfinite(latencia) or latencia < 0 or max_lances < 1):
        raise ValueError("Relógios, latência ou limite de teste inválidos.")
    board = inicial.copy(stack=True) if inicial is not None else chess.Board()
    relogios = dict(tempos_iniciais) if tempos_iniciais is not None else {True: tempo, False: tempo}
    if set(relogios) != {True, False} or any(not isfinite(x) or x <= 0 for x in relogios.values()):
        raise ValueError("Informe os dois relógios iniciais positivos.")
    trocas = acertos = previsoes = 0

    def resultado(placar, motivo):
        return Resultado(cor_nossa, placar, motivo, len(board.move_stack), dict(relogios),
                         trocas, acertos, previsoes, tuple(m.uci() for m in board.move_stack))

    if fim := motivo_encerramento(board):
        return resultado(board.result() if board.is_checkmate() else "1/2-1/2", fim)

    for _ in range(max_lances * 2):
        cor = board.turn
        jogador = nosso if cor == cor_nossa else adversario
        autor = "Nosso programa" if cor == cor_nossa else "Adversário"
        inicio = agora()
        try:
            d = jogador.calcular(board.copy(stack=True), relogios[cor], incremento,
                                  adversario=relogios[not cor])
            if d.lance not in board.legal_moves:
                raise chess.engine.EngineError("Lance inválido")
            futura = board.copy(stack=True)
            futura.push(d.lance)
            if not motivo_encerramento(futura):
                jogador.preparar(futura, d)
        except (chess.engine.EngineError, OSError, TimeoutError, ValueError) as erro:
            relogios[cor] -= agora() - inicio
            if relogios[cor] > 0:
                if falha_derrota:
                    return resultado("0-1" if cor else "1-0", f"Falha de {autor}; derrota conforme edital: {erro}")
                return resultado("*", f"Falha de {autor}: {erro}")
            if board.has_insufficient_material(not cor):
                return resultado("1/2-1/2", "Tempo esgotado; adversário sem material para mate")
            return resultado("0-1" if cor else "1-0", f"{autor}: perda por tempo")
        if latencia:
            dormir(latencia)  # Tempo físico simulado: ainda no relógio de quem joga.
        gasto = agora() - inicio
        relogios[cor] -= gasto
        if relogios[cor] <= 0:
            if board.has_insufficient_material(not cor):
                return resultado("1/2-1/2", "Tempo esgotado; adversário sem material para mate")
            return resultado("0-1" if cor else "1-0", f"{autor}: perda por tempo; lance não aplicado")
        r = registrar_lance(board, d.lance, cor_nossa, replace(d, tempo=gasto))
        fen = board.fen()
        board.push(d.lance)
        relogios[cor] += incremento
        if ao_lance:
            ao_lance(board, r, relogios)
        info = d.detalhes
        if cor == cor_nossa:
            trocas += bool(info.get("troca_autoral"))
            previsoes += info.get("previsao") is not None
            acertos += info.get("antecipacao") == "acertou"
        saida(f"{r.numero}. {autor} | {r.cor} | {r.uci} | usou {gasto:.2f}s | "
              f"restam {relogios[cor]:.2f}s | {info.get('criterio', 'Stockfish original')}")
        registrar(f"  FEN antes: {fen}")
        registrar(f"  Técnica: profundidade {r.profundidade} | nós {r.nos} | avaliação {r.avaliacao} | PV {r.pv}")
        registrar(f"  Decisão: {r.detalhes}")
        fim = motivo_encerramento(board)
        if fim:
            return resultado(board.result() if board.is_checkmate() else "1/2-1/2", fim)
    return resultado("*", "Limite do teste atingido; inconclusiva, não é empate")


def oferecer_log(linhas, entrada, saida, pasta):
    while True:
        try:
            resposta = entrada("\nDeseja salvar o log deste teste? [s/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if resposta in ("n", "não", "nao", ""):
            saida("Log não salvo.")
            return
        if resposta in ("s", "sim"):
            break
        saida("Responda s ou n.")
    while True:
        try:
            nome = entrada("Nome do teste: ")
            caminho = salvar_texto(nome, "\n".join(linhas) + "\n", pasta)
        except (EOFError, KeyboardInterrupt):
            return
        except (ValueError, OSError) as erro:
            saida(f"Não foi possível salvar: {erro}")
        else:
            saida(f"Log salvo: {caminho}")
            return


def main(argv=None, entrada=input, emitir=partial(print, flush=True), conectar=abrir_motor,
         pasta_logs=PASTA_LOGS):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modo", choices=MODOS, default="completo")
    parser.add_argument("--sem-abertura", action="store_true", help="Comparar sem repertório preparado")
    parser.add_argument("--adversario", choices=MODOS, default="original")
    parser.add_argument("--tempo", type=float, default=300)
    parser.add_argument("--incremento", type=float, default=1)
    parser.add_argument("--formato", choices=("melhor-de-tres", "unica", "pares", "classificacao", "armageddon"), default="melhor-de-tres")
    parser.add_argument("--fase", choices=("oitavas", "quartas", "semifinal", "final"), default="semifinal")
    parser.add_argument("--campanha", type=Path, help="Banco do teste; arquivo existente continua o confronto")
    parser.add_argument("--cor-inicial", choices=("brancas", "pretas"), default="brancas")
    parser.add_argument("--cor-armageddon", choices=("brancas", "pretas", "sortear"), default="sortear")
    parser.add_argument("--incremento-armageddon", type=float, default=0)
    parser.add_argument("--armageddon-brancas", type=float, default=300)
    parser.add_argument("--armageddon-pretas", type=float, default=240)
    parser.add_argument("--semente", type=int, default=0, help="Sorteio reprodutível somente no teste")
    parser.add_argument("--pares", type=int, default=1)
    parser.add_argument("--aberturas", choices=["variadas", "inicial"], default="variadas")
    parser.add_argument("--max-lances", type=int, default=300)
    parser.add_argument("--threads", type=int, default=THREADS_PADRAO)
    parser.add_argument("--hash", dest="hash_mb", type=int, default=HASH_PADRAO)
    parser.add_argument("--motor", type=Path)
    parser.add_argument("--afinidade", choices=["auto", "desligada"], default="auto")
    parser.add_argument("--latencia", type=float, default=0, help="Segundos de operação física simulada por lance")
    args = parser.parse_args(argv)
    if (any(not isfinite(x) or x < 0 for x in (args.tempo, args.incremento, args.latencia))
            or args.tempo == 0 or min(args.pares, args.max_lances, args.threads, args.hash_mb) < 1):
        parser.error("Use tempos finitos e recursos positivos; incremento e latência podem ser zero.")
    if args.formato != "pares":
        if args.pares != 1:
            parser.error("--pares só se aplica a --formato pares.")
        return testar_confronto(args, entrada, emitir, conectar, pasta_logs)
    linhas, resultados, codigo = [], [], 0
    repertorio = None if args.sem_abertura else Repertorio.carregar()

    def saida(texto):
        linhas.append(texto)
        emitir(texto)

    saida(f"Início do teste (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    saida(f"Versão: {VERSAO} | {args.modo} contra {args.adversario}")
    saida(f"Ritmo: {args.tempo:g}s + {args.incremento:g}s | {args.threads} threads e {args.hash_mb} MB por motor.")
    saida(f"Partidas: {args.pares * 2}, cores invertidas | latência por lance {args.latencia:g}s.")
    saida("Não digite jogadas. Ctrl+C interrompe; ao final você decide se salva o TXT.")
    fonte = Path(__file__).resolve().parents[2] / "chess_challenge" / "inteligencia.py"
    linhas.append(f"SHA256 do seletor: {hashlib.sha256(fonte.read_bytes()).hexdigest()}")
    linhas.append("Parâmetros do seletor: " + json.dumps(Parametros().__dict__))
    try:
        grupos = grupos_cpu() if args.afinidade == "auto" else None
        if grupos:
            saida(f"CPUs separadas por núcleos físicos: máscaras {hex(grupos[0])} / {hex(grupos[1])}, alternadas por partida.")
        else:
            saida("CPU compartilhada: resultados com antecipação podem ser afetados pela concorrência.")
        for indice in range(args.pares * 2):
            cor = indice % 2 == 0
            nome, sequencia = ABERTURAS[(indice // 2) % len(ABERTURAS)] if args.aberturas == "variadas" else ("Inicial", "")
            board = chess.Board()
            for uci in sequencia.split():
                board.push_uci(uci)
            saida(f"\nPartida {indice+1}/{args.pares*2} — nosso programa com {'Brancas' if cor else 'Pretas'}.")
            saida(f"Abertura de teste: {nome} | UCI: {sequencia or '(inicial)'} | relógios começam após a abertura.")
            with conectar(args.motor, args.threads, args.hash_mb) as motor_a, conectar(args.motor, args.threads, args.hash_mb) as motor_b:
                if grupos:
                    fixar_cpu(motor_a, grupos[indice % 2])
                    fixar_cpu(motor_b, grupos[1 - indice % 2])
                saida(f"Motores: {motor_a.id.get('name')} / {motor_b.id.get('name')}")
                with Jogador(motor_a, args.modo, repertorio=repertorio) as nosso, Jogador(motor_b, args.adversario, repertorio=repertorio) as outro:
                    r = disputar(nosso, outro, cor, args.tempo, args.incremento, args.max_lances,
                                  board, saida, linhas.append, latencia=args.latencia)
            resultados.append(r)
            saida(f"Resultado: {r.placar} — {r.motivo}")
            saida(f"Saldos: nossa equipe {r.relogios[cor]:.2f}s | adversário {r.relogios[not cor]:.2f}s.")
            saida(f"Antecipações certas: {r.acertos}/{r.previsoes} | trocas autorais: {r.trocas}.")
    except KeyboardInterrupt:
        saida("Teste interrompido. A partida em andamento não foi contabilizada.")
    except (OSError, chess.engine.EngineError, TimeoutError, ValueError) as erro:
        saida(f"Falha no teste: {erro}")
        codigo = 1
    v = sum(r.placar not in ("*", "1/2-1/2") and (r.placar == "1-0") == r.cor_nossa for r in resultados)
    e = sum(r.placar == "1/2-1/2" for r in resultados)
    i = sum(r.placar == "*" for r in resultados)
    saida(f"Resumo: {v} vitória(s), {e} empate(s), {len(resultados)-v-e-i} derrota(s), {i} inconclusiva(s).")
    completos = [r for r in resultados if r.placar != "*"]
    saida(f"Soma de saldos concluídos: nossa equipe {sum(r.relogios[r.cor_nossa] for r in completos):.2f}s | "
          f"adversário {sum(r.relogios[not r.cor_nossa] for r in completos):.2f}s.")
    saida("Bateria curta não comprova força nem Elo. Validar também contra ponderação, em mais aberturas e no ritmo oficial.")
    saida(f"Fim do teste (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    oferecer_log(linhas, entrada, emitir, pasta_logs)
    return codigo


def testar_confronto(args, entrada, emitir, conectar, pasta_logs):
    """Mesmo estado usado no jogo manual; relógios reais, processos separados."""
    linhas, resultados = [], []
    repertorio = None if args.sem_abertura else Repertorio.carregar()

    def saida(texto):
        linhas.append(texto)
        emitir(texto)

    caminho = args.campanha or (Path(pasta_logs) / "campanhas" / f"teste-{uuid4().hex[:12]}.sqlite3")
    repo = Repositorio(caminho)
    codigo, pendente = 0, None
    try:
        regras = Regras(tempo=args.tempo, incremento=args.incremento,
            armageddon_brancas=args.armageddon_brancas, armageddon_pretas=args.armageddon_pretas,
            incremento_armageddon=args.incremento_armageddon,
            origem_armageddon="Configuração do ensaio; padrão sem incremento por orientação da equipe.")
        regras.validar()
        if caminho.exists():
            campanha = repo.carregar()
            atuais = {k: v for k, v in asdict(campanha.regras).items() if k != "legado"}
            esperadas = {k: v for k, v in asdict(regras).items() if k != "legado"}
            if atuais != esperadas:
                raise ValueError("Os relógios/regras do banco diferem dos argumentos. Use a mesma configuração ou outro arquivo.")
            c = campanha.confrontos[-1]
            if c.ativa:
                raise ValueError("O teste anterior foi interrompido. Examine a partida pendente antes de registrar resultado ou cancelar a tentativa.")
        else:
            campanha = Campanha("Nosso programa — teste", regras=regras)
            c = campanha.novo_confronto("Stockfish de referência", fase="classificacao" if args.formato == "classificacao" else args.fase,
                formato="unica" if args.formato in ("classificacao", "unica") else "melhor-de-tres",
                primeira_cor=args.cor_inicial == "brancas")
            if args.formato == "armageddon":
                # Preparação explícita do cenário, não três jogos fictícios na medição.
                for _ in range(3):
                    p = c.iniciar(regras)
                    c.finalizar(p["id"], "1/2-1/2", "Preparação sintética do ensaio de Armageddon", 0, 0, origem="cenario_sintetico")
            repo.criar(campanha)
        saida(f"Início do teste (UTC): {data_utc()}")
        saida(f"Versão: {VERSAO} | {args.modo} contra {args.adversario}")
        saida(f"Formato: {args.formato} | fase: {c.fase} | banco: {caminho}")
        saida(f"Ritmo normal: {regras.tempo:g}s + {regras.incremento:g}s. Armageddon: {regras.armageddon_brancas:g}/{regras.armageddon_pretas:g}s + {regras.incremento_armageddon:g}s.")
        saida(f"Recursos por motor: {args.threads} threads, {args.hash_mb} MB; latência {args.latencia:g}s.")
        saida(f"Repertório no modo completo: {'ativo' if repertorio and repertorio.entradas else 'desligado/indisponível'}; original permanece sem livro.")
        saida("Banco salvo automaticamente por lance. TXT somente com autorização ao final.")
        for modulo in ("campanha.py", "estrategia.py", "inteligencia.py", "motor.py", "aberturas.py", "aberturas.json"):
            fonte = Path(__file__).resolve().parents[2] / "chess_challenge" / modulo
            linhas.append(f"SHA256 {modulo}: {hashlib.sha256(fonte.read_bytes()).hexdigest() if fonte.is_file() else 'arquivo ausente'}")
        linhas.append("Parâmetros do seletor: " + json.dumps(asdict(Parametros())))
        grupos = grupos_cpu() if args.afinidade == "auto" else None
        saida(f"Afinidade: {grupos or 'CPU compartilhada'}; grupos alternados a cada partida.")
        sorteio = random.Random(args.semente)
        while c.situacao(regras)["status"] in ("em_disputa", "armageddon"):
            if c.situacao(regras)["status"] == "armageddon" and c.cor_armageddon is None:
                c.cor_armageddon = (args.cor_armageddon == "brancas" if args.cor_armageddon != "sortear" else bool(sorteio.getrandbits(1)))
                saida(f"Sorteio de teste, semente {args.semente}: nossa equipe com {'Brancas' if c.cor_armageddon else 'Pretas'}.")
            contexto_nosso, contexto_outro = c.contexto(regras), c.contexto(regras, False)
            p = c.iniciar(regras)
            pendente = p
            repo.salvar(campanha)
            cor, board = p["cor"], chess.Board()
            saida(f"\nPartida {p['numero']}{' — Armageddon' if p['armageddon'] else '/3' if c.formato == 'melhor-de-tres' else ''}: nossa equipe com {'Brancas' if cor else 'Pretas'}.")
            saida(f"Objetivo: {contexto_nosso.objetivo} | {contexto_nosso.motivo}")

            def ao_lance(tabuleiro, registro, relogios):
                p.update(fen_inicial=tabuleiro.root().fen(), fen_atual=tabuleiro.fen(),
                    lances=[m.uci() for m in tabuleiro.move_stack], ultima_atualizacao=data_utc(),
                    saldo_estimado=relogios[cor], saldo_outro_estimado=relogios[not cor])
                p["registros"].append(asdict(registro))
                repo.salvar(campanha)

            indice = len(resultados)
            with conectar(args.motor, args.threads, args.hash_mb) as motor_a, conectar(args.motor, args.threads, args.hash_mb) as motor_b:
                if grupos:
                    fixar_cpu(motor_a, grupos[indice % 2])
                    fixar_cpu(motor_b, grupos[1 - indice % 2])
                saida(f"Motores: {motor_a.id.get('name')} / {motor_b.id.get('name')}")
                with Jogador(motor_a, args.modo, contexto=contexto_nosso, repertorio=repertorio) as nosso, Jogador(motor_b, args.adversario, contexto=contexto_outro, repertorio=repertorio) as outro:
                    tempos = {cor: p["tempo_nosso"], not cor: p["tempo_outro"]}
                    r = disputar(nosso, outro, cor, regras.tempo, p["incremento"], args.max_lances,
                        board, saida, linhas.append, latencia=args.latencia,
                        tempos_iniciais=tempos, falha_derrota=True, ao_lance=ao_lance)
            resultados.append(r)
            if r.placar == "*":
                p.update(status="inconclusiva", motivo=r.motivo)
                repo.salvar(campanha)
                saida(f"Inconclusiva: {r.motivo}. O confronto não foi decidido.")
                pendente = None
                break
            c.finalizar(p["id"], r.placar, r.motivo, max(0, r.relogios[cor]), max(0, r.relogios[not cor]), origem="simulacao_relogio_real")
            repo.salvar(campanha)
            pendente = None
            saida(f"Resultado: {r.placar} | {r.motivo} | saldos {r.relogios[cor]:.3f}s / {r.relogios[not cor]:.3f}s.")
            saida(f"Antecipações: {r.acertos}/{r.previsoes}; trocas autorais: {r.trocas}.")
            saida("Confronto: " + json.dumps(c.situacao(regras), ensure_ascii=False))
        saida("Situação final: " + json.dumps(c.situacao(regras), ensure_ascii=False))
    except KeyboardInterrupt:
        saida("Teste interrompido. Partida em andamento não foi contabilizada.")
    except (OSError, ValueError, chess.engine.EngineError, TimeoutError, sqlite3.Error) as erro:
        saida(f"Falha no teste: {erro}")
        codigo = 1
    finally:
        if pendente is not None:
            pendente.update(status="inconclusiva", motivo="Ensaio interrompido; sem resultado oficial.")
            repo.salvar(campanha)
    v = sum(r.placar in ("1-0", "0-1") and (r.placar == "1-0") == r.cor_nossa for r in resultados)
    e = sum(r.placar == "1/2-1/2" for r in resultados)
    i = sum(r.placar == "*" for r in resultados)
    saida(f"Jogos efetivamente disputados: {v} vitória(s), {e} empate(s), {len(resultados)-v-e-i} derrota(s), {i} inconclusiva(s).")
    saida("Cenários sintéticos de preparação não entram nesse resumo. Teste funcional não comprova ganho de força.")
    saida(f"Fim do teste (UTC): {data_utc()}")
    oferecer_log(linhas, entrada, emitir, pasta_logs)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
