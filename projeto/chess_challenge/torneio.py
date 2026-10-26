"""Operação da campanha pelo mesmo jogar.py, sem interface gráfica nem rede."""

import argparse
from dataclasses import asdict
from functools import partial
import json
from pathlib import Path
import sqlite3

import chess.engine

from .campanha import Campanha, Confronto, Regras, Repositorio, FASES, OBJETIVOS, agora, numero
from .motor import abrir_motor, THREADS_PADRAO, HASH_PADRAO
from .inteligencia import MODOS
from .partida import executar, motivo_encerramento

ARQUIVO_PADRAO = Path(__file__).resolve().parents[1] / "dados" / "campanha.sqlite3"


def segundos(texto):
    try:
        if ":" in texto:
            partes = texto.split(":")
            if len(partes) != 2 or not partes[0].isdigit():
                raise ValueError()
            minutos, s = int(partes[0]), float(partes[1])
            if not 0 <= s < 60:
                raise ValueError()
            valor = minutos * 60 + s
        else:
            valor = float(texto)
        return numero(valor, "Relógio")
    except ValueError:
        raise argparse.ArgumentTypeError("Use segundos ou mm:ss, sem valores negativos.") from None


def jogar_campanha(campanha, repo, args, entrada=input, saida=partial(print, flush=True), conectar=abrir_motor):
    if not campanha.confrontos:
        raise ValueError("Cadastre o confronto antes de jogar.")
    c = campanha.confrontos[-1]
    if args.cor_armageddon is not None:
        if c.situacao(campanha.regras)["status"] != "armageddon":
            raise ValueError("Sorteio do Armageddon só se aplica após o empate do confronto e dos relógios.")
        c.cor_armageddon = args.cor_armageddon == "brancas"
    contexto = campanha.contexto(c)
    p = c.iniciar(campanha.regras)
    p["contexto"] = asdict(contexto)
    repo.salvar(campanha)
    saida(f"Confronto: {c.adversario} | {c.fase} | partida {p['numero']} | ID {p['id']}")
    saida("O histórico é salvo automaticamente no banco local. O TXT é exportado com sua autorização.")

    def acompanhar(evento, board, registros, saldo, resultado):
        p.update(fen_inicial=board.root().fen(), lances=[m.uci() for m in board.move_stack],
                 registros=[asdict(r) for r in registros], saldo_estimado=saldo,
                 fen_atual=board.fen(), ultima_atualizacao=agora())
        if evento == "fim":
            p.update(status="aguardando_resultado" if motivo_encerramento(board) else "inconclusiva",
                     sugestao_placar=board.result() if board.is_checkmate() else "1/2-1/2" if motivo_encerramento(board) else None,
                     observacao=resultado)
        repo.salvar(campanha)

    try:
        executar(entrada, saida, conectar=partial(conectar, args.motor, args.threads, args.hash_mb),
                 tempo=p["tempo_nosso"], incremento=p["incremento"], modo=args.modo,
                 cor_inicial=p["cor"], contexto=contexto, acompanhamento=acompanhar,
                 tempo_adversario=p["tempo_outro"],
                 configuracao=f"{args.threads} threads, {args.hash_mb} MB. Confronto {c.id}; partida {p['id']}.")
    finally:
        # Uma falha não é convertida automaticamente em empate ou partida retomável.
        if p["status"] == "em_andamento":
            p.update(status="inconclusiva", observacao="Sessão encerrada; resultado oficial pendente.")
            repo.salvar(campanha)
    saida("Registre o resultado oficial e os dois relógios finais com: jogar.py campanha resultado.")
    saida(f"Partida pendente: {p['id']} | sugestão do tabuleiro: {p.get('sugestao_placar') or 'nenhuma'}")


def criar_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="acao", required=True)

    def comando(nome, ajuda):
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("--arquivo", type=Path, default=ARQUIVO_PADRAO)
        return p

    p = comando("criar", "Criar histórico local; não sobrescreve campanha existente")
    p.add_argument("--equipe", required=True)
    p.add_argument("--campeonato", default="III Chess Challenge")
    p.add_argument("--teste", action="store_true", help="Ritmo normal 300+1; Armageddon 300/240+0")
    p.add_argument("--rodadas", type=int)
    p.add_argument("--vagas", type=int)
    p.add_argument("--equipes", type=int)
    comando("status", "Mostrar histórico, tabela oficial e confronto atual")
    p = comando("confronto", "Cadastrar o próximo pareamento da organização")
    p.add_argument("--adversario", required=True)
    p.add_argument("--fase", choices=FASES, required=True)
    p.add_argument("--rodada", type=int, default=1)
    p.add_argument("--formato", choices=("unica", "melhor-de-tres"), required=True)
    p.add_argument("--cor", choices=("brancas", "pretas"), required=True, help="Nossa cor na primeira partida")
    p.add_argument("--objetivo", choices=OBJETIVOS, default="equilibrado")
    p.add_argument("--justificativa", default="")
    p = comando("jogar", "Jogar a próxima partida do confronto")
    p.add_argument("--cor-armageddon", choices=("brancas", "pretas"), help="Resultado do sorteio oficial")
    p.add_argument("--motor", type=Path)
    p.add_argument("--modo", choices=MODOS, default="completo")
    p.add_argument("--threads", type=int, default=THREADS_PADRAO)
    p.add_argument("--hash", dest="hash_mb", type=int, default=HASH_PADRAO)
    p = comando("resultado", "Registrar ou corrigir resultado confirmado pelo árbitro")
    p.add_argument("--partida", help="ID; por padrão usa a partida pendente")
    p.add_argument("--placar", choices=("1-0", "0-1", "1/2-1/2"), required=True, help="Perspectiva das cores, como no xadrez")
    p.add_argument("--nosso-tempo", type=segundos, required=True)
    p.add_argument("--outro-tempo", type=segundos, required=True)
    p.add_argument("--motivo", required=True)
    p.add_argument("--corrigir", help="Justificativa obrigatória para alterar um resultado anterior")
    p = comando("cancelar", "Cancelar uma tentativa pendente, sem inventar resultado")
    p.add_argument("--justificativa", required=True)
    p = comando("tabela", "Importar JSON da classificação oficial, obtido localmente")
    p.add_argument("--importar", type=Path, required=True)
    p.add_argument("--rodada", type=int, required=True)
    p.add_argument("--fonte", default="Organização")
    p = comando("regras", "Configurar definições confirmadas pela organização")
    for flag in ("tempo", "incremento", "incremento-armageddon", "armageddon-brancas", "armageddon-pretas",
                 "pontos-vitoria", "pontos-empate", "pontos-derrota"):
        p.add_argument("--" + flag, type=float)
    p.add_argument("--rodadas", type=int)
    p.add_argument("--vagas", type=int)
    p.add_argument("--equipes", type=int)
    p.add_argument("--classificacao-por-pontos", choices=("sim", "nao"))
    p.add_argument("--tres-obrigatorias", choices=("sim", "nao"))
    p = comando("arbitragem", "Registrar decisão oficial de classificação ou eliminação")
    p.add_argument("--situacao", choices=("classificado", "eliminado"), required=True)
    p.add_argument("--justificativa", required=True)
    return parser


def main(argv=None, entrada=input, saida=partial(print, flush=True), conectar=abrir_motor):
    parser = criar_parser()
    args = parser.parse_args(argv)
    repo = Repositorio(args.arquivo)
    try:
        if args.acao == "criar":
            regras = Regras(tempo=300 if args.teste else 900, incremento=1 if args.teste else 10,
                            rodadas=args.rodadas, vagas=args.vagas, equipes=args.equipes)
            repo.criar(Campanha(args.equipe, args.campeonato, regras))
            saida(f"Campanha criada: {args.arquivo}")
            return 0
        campanha = repo.carregar()
        if args.acao == "status":
            saida(json.dumps(dict(resumo=campanha.resumo(), regras=asdict(campanha.regras),
                pendentes=[dict(confronto=c.id, partida=c.ativa) for c in campanha.confrontos if c.ativa]),
                ensure_ascii=False, indent=2))
            return 0
        if args.acao == "confronto":
            c = campanha.novo_confronto(args.adversario, fase=args.fase, rodada=args.rodada,
                formato=args.formato, primeira_cor=args.cor == "brancas",
                objetivo_informado=args.objetivo, justificativa_objetivo=args.justificativa)
            repo.salvar(campanha)
            saida(f"Confronto cadastrado: {c.id}")
        elif args.acao == "jogar":
            if args.threads < 1 or args.hash_mb < 1:
                raise ValueError("Threads e hash devem ser positivos.")
            jogar_campanha(campanha, repo, args, entrada, saida, conectar)
        elif args.acao == "tabela":
            campanha.registrar_tabela(json.loads(args.importar.read_text(encoding="utf-8-sig")), args.rodada, args.fonte)
            repo.salvar(campanha)
            saida("Classificação oficial registrada; posições não foram estimadas por nossos resultados.")
        elif args.acao == "regras":
            if any(c.ativa for c in campanha.confrontos):
                raise ValueError("Não altere regras com partida pendente.")
            if campanha.confrontos and campanha.confrontos[-1].concluidas and campanha.confrontos[-1].situacao(campanha.regras)["status"] in ("em_disputa", "armageddon", "relogios_pendentes"):
                raise ValueError("Conclua o confronto antes de alterar as regras.")
            for nome in asdict(campanha.regras):
                valor = getattr(args, nome, None)
                if valor is not None:
                    setattr(campanha.regras, nome, valor)
            if args.tres_obrigatorias:
                campanha.regras.encerrar_ao_decidir = args.tres_obrigatorias == "nao"
            if args.classificacao_por_pontos:
                campanha.regras.classificacao_por_pontos_confirmada = args.classificacao_por_pontos == "sim"
            campanha.regras.validar()
            if campanha.confrontos and not campanha.confrontos[-1].partidas:
                campanha.confrontos[-1].regras_aplicadas = asdict(campanha.regras)
            repo.salvar(campanha)
            saida("Regras atualizadas. Partidas anteriores mantêm seus ritmos registrados.")
        else:
            if not campanha.confrontos:
                raise ValueError("Não há confronto cadastrado.")
            c = campanha.confrontos[-1]
            if args.acao == "arbitragem":
                if c.ativa or not args.justificativa.strip():
                    raise ValueError("Finalize a partida pendente e informe a justificativa da arbitragem.")
                c.decisao_oficial = dict(status=args.situacao, motivo=args.justificativa, data=agora())
            elif args.acao == "cancelar":
                if not c.ativa or not args.justificativa.strip():
                    raise ValueError("Não há tentativa pendente ou falta justificativa.")
                c.ativa.update(status="cancelada", motivo=args.justificativa, fim=agora())
            elif args.acao == "resultado":
                identificador = args.partida or (c.ativa or {}).get("id")
                if identificador is None:
                    raise ValueError("Informe o ID da partida.")
                c = next((x for x in campanha.confrontos if any(p["id"] == identificador for p in x.partidas)), None)
                if c is None:
                    raise ValueError("Partida não encontrada.")
                dados = dict(placar=args.placar, motivo=args.motivo,
                             saldo_nosso=args.nosso_tempo, saldo_outro=args.outro_tempo)
                if args.corrigir:
                    c.corrigir(identificador, args.corrigir, **dados)
                else:
                    c.finalizar(identificador, **dados)
            repo.salvar(campanha)
            saida(json.dumps(c.situacao(campanha.regras), ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error, chess.engine.EngineError, TimeoutError) as erro:
        saida(f"Não foi possível executar: {erro}")
        return 1
