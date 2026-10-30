"""Operação da campanha pelo mesmo jogar.py, sem interface gráfica nem rede."""

import argparse
from dataclasses import asdict
from functools import partial
import json
from pathlib import Path
import sqlite3

import chess.engine

from .campanha import Campanha, Regras, Repositorio, FASES, agora, numero
from .motor import abrir_motor, THREADS_PADRAO, HASH_PADRAO
from .inteligencia import MODOS
from .aberturas import Repertorio
from .partida import executar, motivo_encerramento
from .relogio import ler_tempo

ARQUIVO_PADRAO = Path(__file__).resolve().parents[1] / "dados" / "campanha.sqlite3"


def segundos(texto):
    try:
        return ler_tempo(texto)
    except ValueError:
        raise argparse.ArgumentTypeError("Use segundos ou mm:ss, sem valores negativos.") from None


def perguntar_duracao(entrada, saida):
    while True:
        texto = entrada("Duração total prevista de cada partida, em minutos [Enter se não informado]: ").strip()
        if not texto:
            return None
        try:
            return numero(float(texto.replace(",", ".")), "Duração prevista", True)
        except ValueError:
            saida("Informe um número positivo de minutos.")


def perguntar_cor(entrada, saida, esperada=None, armageddon=False):
    if armageddon:
        saida("Armageddon: informe a cor definida pelo sorteio oficial.")
    elif esperada is not None:
        saida(f"Alternância da melhor de três: nesta partida esperamos {'Brancas' if esperada else 'Pretas'}.")
    while True:
        texto = entrada("Nossa equipe nesta partida — [1] Brancas ou [2] Pretas? ").strip().lower()
        if texto in ("1", "brancas"):
            cor = True
        elif texto in ("2", "pretas"):
            cor = False
        else:
            saida("Escolha 1 para Brancas ou 2 para Pretas.")
            continue
        if esperada is not None and cor != esperada:
            saida(f"A alternância deste confronto exige {'Brancas' if esperada else 'Pretas'}. Confira a cor antes de começar.")
            continue
        return cor


def jogar_campanha(campanha, repo, args, entrada=input, saida=partial(print, flush=True), conectar=abrir_motor):
    if not campanha.confrontos:
        raise ValueError("Cadastre o confronto antes de jogar.")
    c = campanha.confrontos[-1]
    if c.ativa:
        raise ValueError("Há uma partida pendente; registre seu resultado antes de começar outra.")
    situacao = c.situacao(campanha.regras)
    if situacao["status"] not in ("em_disputa", "armageddon"):
        raise ValueError(f"Não é possível iniciar: {situacao['status']}.")
    armageddon = situacao["status"] == "armageddon"
    if args.cor_armageddon is not None:
        if not armageddon:
            raise ValueError("Sorteio do Armageddon só se aplica após o empate do confronto e dos relógios.")
        saida(f"Referência informada no comando: {args.cor_armageddon}. Confirme a cor na pergunta abaixo.")
    normais = [p for p in c.concluidas if not p["armageddon"]]
    esperada = None
    if not armageddon and normais:
        esperada = c.primeira_cor if len(normais) % 2 == 0 else not c.primeira_cor
    try:
        cor = perguntar_cor(entrada, saida, esperada, armageddon)
    except (EOFError, KeyboardInterrupt):
        saida("Início cancelado antes de abrir o motor ou iniciar os relógios.")
        return
    if armageddon:
        c.cor_armageddon = cor
    elif not normais:
        c.primeira_cor = cor
    contexto = campanha.contexto(c)
    p = c.iniciar(campanha.regras)
    p["cor_confirmada_na_abertura"] = True
    p["contexto"] = asdict(contexto)
    repo.salvar(campanha)
    saida(f"Confronto: {c.adversario} | {c.fase} | partida {p['numero']} | ID {p['id']}")
    if p["duracao_prevista_minutos"] is not None:
        saida(f"Duração prevista: {p['duracao_prevista_minutos']:g} minutos. É uma referência de agenda, sem corte automático.")
    saida("O histórico é salvo automaticamente no banco local. O TXT é exportado com sua autorização.")

    def acompanhar(evento, board, registros, saldos, resultado):
        quantidade = len(p["registros"])
        p["registros"].extend(asdict(r) for r in registros[quantidade:])
        p.update(fen_inicial=board.root().fen(), lances=[m.uci() for m in board.move_stack],
                 saldo_estimado=saldos[p["cor"]],
                 saldo_outro_estimado=saldos[not p["cor"]],
                 relogios_sistema={"brancas": saldos[True], "pretas": saldos[False]},
                 origem_relogios="sistema",
                 fen_atual=board.fen(), ultima_atualizacao=agora())
        if evento == "relogio_fisico":
            p.setdefault("ajustes_relogio", []).append(dict(data=agora(),
                meio_lance=len(board.move_stack), brancas=saldos[True], pretas=saldos[False]))
        if p.get("ajustes_relogio"):
            p["origem_relogios"] = "sistema_com_ajuste_fisico"
        if evento == "fim":
            sugestao = board.result() if board.is_checkmate() else "1/2-1/2" if motivo_encerramento(board) else None
            if sugestao is None and min(saldos.values()) <= 0:
                perdeu = saldos[True] <= 0
                sugestao = "1/2-1/2" if board.has_insufficient_material(not perdeu) else "0-1" if perdeu else "1-0"
            p.update(status="aguardando_resultado" if sugestao else "inconclusiva",
                     sugestao_placar=sugestao, observacao=resultado)
        repo.salvar(campanha)

    try:
        executar(entrada, saida, conectar=partial(conectar, args.motor, args.threads, args.hash_mb),
                 tempo=p["tempo_nosso"], incremento=p["incremento"], modo=args.modo,
                 cor_inicial=p["cor"], contexto=contexto, acompanhamento=acompanhar,
                 tempo_adversario=p["tempo_outro"],
                 repertorio=Repertorio.carregar() if args.modo == "completo" and not args.sem_abertura else None,
                 configuracao=f"{args.threads} threads, {args.hash_mb} MB. Confronto {c.id}; partida {p['id']}.")
    finally:
        # Uma falha não é convertida automaticamente em empate ou partida retomável.
        if p["status"] == "em_andamento":
            p.update(status="inconclusiva", observacao="Sessão encerrada; resultado oficial pendente.")
            repo.salvar(campanha)
    saida("Os dois relógios foram salvos automaticamente. Registre o resultado oficial com: jogar.py campanha resultado.")
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
    p.add_argument("--duracao-prevista", dest="duracao_prevista_minutos", type=float,
                   help="Minutos previstos na agenda; se omitido, será perguntado")
    comando("status", "Mostrar vitórias, empates, derrotas e partidas")
    p = comando("confronto", "Cadastrar o próximo pareamento da organização")
    p.add_argument("--adversario", required=True)
    p.add_argument("--fase", choices=FASES, default="classificacao")
    p.add_argument("--rodada", type=int, help="Identificação opcional; por padrão segue a sequência de confrontos")
    p.add_argument("--formato", choices=("unica", "melhor-de-tres"), required=True)
    p.add_argument("--cor", choices=("brancas", "pretas"), help="Referência opcional; a cor será perguntada antes de jogar")
    p = comando("jogar", "Jogar a próxima partida do confronto")
    p.add_argument("--cor-armageddon", choices=("brancas", "pretas"), help="Referência opcional; a cor sorteada será perguntada antes de jogar")
    p.add_argument("--motor", type=Path)
    p.add_argument("--modo", choices=MODOS, default="completo")
    p.add_argument("--sem-abertura", action="store_true", help="Desativar o repertório preparado")
    p.add_argument("--threads", type=int, default=THREADS_PADRAO)
    p.add_argument("--hash", dest="hash_mb", type=int, default=HASH_PADRAO)
    p = comando("resultado", "Registrar ou corrigir resultado confirmado pelo árbitro")
    p.add_argument("--partida", help="ID; por padrão usa a partida pendente")
    p.add_argument("--placar", choices=("1-0", "0-1", "1/2-1/2"), required=True, help="Perspectiva das cores, como no xadrez")
    p.add_argument("--nosso-tempo", type=segundos, help="Opcional: ajuste pelo relógio oficial")
    p.add_argument("--outro-tempo", type=segundos, help="Opcional: ajuste pelo relógio oficial")
    p.add_argument("--motivo", required=True)
    p.add_argument("--corrigir", help="Justificativa obrigatória para alterar um resultado anterior")
    p = comando("cancelar", "Cancelar uma tentativa pendente, sem inventar resultado")
    p.add_argument("--justificativa", required=True)
    p = comando("regras", "Configurar definições confirmadas pela organização")
    for flag in ("tempo", "incremento", "incremento-armageddon", "armageddon-brancas", "armageddon-pretas"):
        p.add_argument("--" + flag, type=float)
    p.add_argument("--duracao-prevista", dest="duracao_prevista_minutos", type=float)
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
            if args.arquivo.exists():
                raise ValueError("Já existe um arquivo nesse caminho. Use outra campanha.")
            duracao = args.duracao_prevista_minutos
            if duracao is None:
                duracao = perguntar_duracao(entrada, saida)
            regras = Regras(tempo=300 if args.teste else 900, incremento=1 if args.teste else 10,
                            duracao_prevista_minutos=duracao)
            repo.criar(Campanha(args.equipe, args.campeonato, regras))
            saida(f"Campanha criada: {args.arquivo}")
            saida(f"Relógios: {regras.tempo / 60:g} minutos por equipe + {regras.incremento:g} segundos por lance.")
            return 0
        campanha = repo.carregar()
        if args.acao == "status":
            regras_publicas = {k: v for k, v in asdict(campanha.regras).items() if k != "legado"}
            saida(json.dumps(dict(resumo=campanha.resumo(), regras=regras_publicas,
                pendentes=[dict(confronto=c.id, partida=c.ativa) for c in campanha.confrontos if c.ativa]),
                ensure_ascii=False, indent=2))
            return 0
        if args.acao == "confronto":
            c = campanha.novo_confronto(args.adversario, fase=args.fase,
                rodada=args.rodada if args.rodada is not None else len(campanha.confrontos) + 1,
                formato=args.formato, primeira_cor=None if args.cor is None else args.cor == "brancas")
            repo.salvar(campanha)
            saida(f"Confronto cadastrado: {c.id}")
        elif args.acao == "jogar":
            if args.threads < 1 or args.hash_mb < 1:
                raise ValueError("Threads e hash devem ser positivos.")
            jogar_campanha(campanha, repo, args, entrada, saida, conectar)
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
                p = c.partida(identificador)
                if (args.nosso_tempo is None) != (args.outro_tempo is None):
                    raise ValueError("Para um ajuste oficial, informe os dois relógios juntos.")
                if args.nosso_tempo is not None:
                    nosso, outro = args.nosso_tempo, args.outro_tempo
                    origem = "ajuste_oficial_pelo_operador"
                elif p.get("saldo_nosso_ms") is not None and p.get("saldo_outro_ms") is not None:
                    nosso, outro = p["saldo_nosso_ms"] / 1000, p["saldo_outro_ms"] / 1000
                    origem = p.get("origem_relogios", "registro_anterior")
                elif p.get("relogios_sistema"):
                    relogios = p["relogios_sistema"]
                    nosso = relogios["brancas" if p["cor"] else "pretas"]
                    outro = relogios["pretas" if p["cor"] else "brancas"]
                    origem = p.get("origem_relogios", "sistema")
                else:
                    raise ValueError("Partida antiga sem relógios automáticos: informe os dois saldos ao registrar o resultado.")
                dados = dict(placar=args.placar, motivo=args.motivo,
                             saldo_nosso=nosso, saldo_outro=outro, origem="operador")
                if args.corrigir:
                    c.corrigir(identificador, args.corrigir, **dados)
                else:
                    c.finalizar(identificador, **dados)
                p["origem_relogios"] = origem
            repo.salvar(campanha)
            saida(json.dumps(c.situacao(campanha.regras), ensure_ascii=False))
        return 0
    except (EOFError, KeyboardInterrupt):
        saida("Operação cancelada.")
        return 0
    except (ValueError, OSError, sqlite3.Error, chess.engine.EngineError, TimeoutError) as erro:
        saida(f"Não foi possível executar: {erro}")
        return 1
