"""Operação da campanha pelo mesmo jogar.py, sem interface gráfica nem rede."""

import argparse
from dataclasses import asdict
from functools import partial
import json
from pathlib import Path
import sqlite3

import chess
import chess.engine

from .campanha import Campanha, Regras, Repositorio, FASES, agora, numero
from .motor import abrir_motor, THREADS_PADRAO, HASH_PADRAO
from .inteligencia import MODOS
from .aberturas import Repertorio
from .partida import executar, motivo_encerramento
from .relogio import ler_tempo
from .relatorios import RegistroLance, formatar_relatorio

ARQUIVO_PADRAO = Path(__file__).resolve().parents[1] / "dados" / "campanha.sqlite3"


def segundos(texto):
    try:
        return ler_tempo(texto)
    except ValueError:
        raise argparse.ArgumentTypeError("Use segundos ou mm:ss, sem valores negativos.") from None


def perguntar_duracao(entrada, saida):
    while True:
        texto = entrada("Duração prevista de cada partida, em minutos [Enter se não informado]: ").strip()
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


def jogar_campanha(campanha, repo, args, entrada=input, saida=partial(print, flush=True), conectar=abrir_motor,
                   automatico=False):
    if not campanha.confrontos:
        raise ValueError("Cadastre o confronto antes de jogar.")
    c = campanha.confrontos[-1]
    if c.ativa:
        raise ValueError("Há uma partida pendente; registre seu resultado antes de começar outra.")
    situacao = c.situacao(campanha.regras)
    if situacao["status"] not in ("em_disputa", "armageddon"):
        raise ValueError(f"Não é possível iniciar: {situacao['status']}.")
    armageddon = situacao["status"] == "armageddon"
    if automatico:
        regras = c.regras(campanha.regras)
        formato_oficial = "melhor-de-tres" if c.fase in ("semifinal", "final") else "unica"
        if c.formato != formato_oficial:
            raise ValueError("Formato salvo incompatível com a fase no manual. Corrija o cadastro antes de jogar.")
        if ((regras.tempo, regras.incremento) != (900, 10)
                or (regras.armageddon_brancas, regras.armageddon_pretas, regras.incremento_armageddon) != (300, 240, 0)
                or not regras.encerrar_ao_decidir):
            raise ValueError("O modo campeonato exige 15+10, Armageddon 5/4 sem incremento e encerramento ao decidir o confronto. Use banco separado para testes.")
    if armageddon and not confirmar_armageddon(campanha, repo, c, entrada, saida):
        return
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
    p["duracao_prevista_minutos"] = None
    p["numero_geral"] = sum(len(confronto.partidas) for confronto in campanha.confrontos)
    if armageddon:
        c.armageddon_autorizado = False  # A confirmação vale para esta partida.
    p["cor_confirmada_na_abertura"] = True
    p["contexto"] = asdict(contexto)
    repo.salvar(campanha)
    if automatico:
        etapa = "Armageddon" if armageddon else f"Partida {p['numero']}/{3 if c.formato == 'melhor-de-tres' else 1}"
        saida(f"\n{c.adversario} | {etapa}\n")
    else:
        saida(f"Confronto: {c.adversario} | {c.fase} | partida {p['numero']} | ID {p['id']}")
    if p["duracao_prevista_minutos"] is not None and not automatico:
        saida(f"Duração prevista: {p['duracao_prevista_minutos']:g} minutos.")
    if not automatico:
        saida("O histórico é salvo automaticamente no banco local. O TXT é exportado com sua autorização.")

    def acompanhar(evento, board, registros, saldos, resultado):
        if evento == "correcao_tabuleiro":
            p.setdefault("correcoes_tabuleiro", []).append(dict(data=agora(),
                fen_anterior=p.get("fen_atual"), lances_anteriores=list(p.get("lances", [])),
                registros_anteriores=list(p["registros"]), motivo=resultado))
        p["registros"] = [asdict(r) for r in registros]
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
            fim_tabuleiro = motivo_encerramento(board)
            sugestao = board.result() if board.is_checkmate() else "1/2-1/2" if fim_tabuleiro else None
            if sugestao is None and min(saldos.values()) <= 0:
                perdeu = saldos[True] <= 0
                sugestao = "1/2-1/2" if board.has_insufficient_material(not perdeu) else "0-1" if perdeu else "1-0"
            p.update(status="aguardando_resultado" if sugestao else "inconclusiva",
                     sugestao_placar=sugestao, observacao=resultado)
            # Só a posição final confirma um resultado automaticamente. Interrupção
            # e queda do contador local não substituem a decisão do árbitro.
            # Mesmo com mate, os saldos físicos são recolhidos ao encerrar.
        repo.salvar(campanha)

    try:
        executar(entrada, saida, conectar=partial(conectar, args.motor, args.threads, args.hash_mb),
                 tempo=p["tempo_nosso"], incremento=p["incremento"], modo=args.modo,
                 cor_inicial=p["cor"], contexto=contexto, acompanhamento=acompanhar,
                 tempo_adversario=p["tempo_outro"],
                 duracao_total_minutos=None,
                 repertorio=Repertorio.carregar() if args.modo == "completo" and not args.sem_abertura else None,
                 configuracao=f"{args.threads} threads, {args.hash_mb} MB. Confronto {c.id}; partida {p['id']}.",
                 compacto=automatico, exportar_relatorio=not automatico)
    finally:
        # Uma falha não é convertida automaticamente em empate ou partida retomável.
        if p["status"] == "em_andamento":
            p.update(status="inconclusiva", observacao="Sessão encerrada; resultado oficial pendente.")
            repo.salvar(campanha)
        if automatico:
            salvar_log_partida(c, p, repo)
            repo.salvar(campanha)
    if not automatico:
        saida("Contadores locais salvos. Registre resultado e saldos físicos oficiais com: jogar.py campanha resultado.")
        saida(f"Partida pendente: {p['id']} | sugestão do tabuleiro: {p.get('sugestao_placar') or 'nenhuma'}")
    return p


def escolher(texto, opcoes, entrada, saida, padrao=None):
    while True:
        valor = entrada(texto).strip().lower()
        if not valor and padrao is not None:
            return padrao
        if valor in opcoes:
            return opcoes[valor]
        saida("Escolha uma das opções indicadas.")


def salvar_log_partida(confronto, partida, repo):
    """O FAQ exige log por partida; o banco continua sendo a fonte do histórico."""
    saldos = partida.get("relogios_sistema", {})
    restante = saldos.get("brancas" if partida["cor"] else "pretas")
    descricao = partida.get("motivo") or partida.get("observacao") or "Resultado pendente"
    if partida.get("placar"):
        descricao = f"{partida['placar']} | {descricao}"
    numero_geral = partida["numero_geral"]
    nome = f"partida_{numero_geral:03d}"
    texto = formatar_relatorio(f"{numero_geral:03d}", [RegistroLance(**r) for r in partida["registros"]],
        descricao, partida["cor"], partida["incremento"], "Stockfish", restante,
        f"ID: {partida['id']}\nAdversário: {confronto.adversario} | Fase: {confronto.fase} | Partida {partida['numero']} | "
        f"{'Armageddon' if partida['armageddon'] else confronto.formato}\n"
        + (f"Duração prevista: {partida['duracao_prevista_minutos']:g} minutos; referência de planejamento, sem encerramento automático."
           if partida.get("duracao_prevista_minutos") is not None and not partida['armageddon'] else ""),
        {True: saldos["brancas"], False: saldos["pretas"]} if saldos else None)
    if partida.get("origem_relogios") in ("fisico_oficial", "ajuste_oficial_pelo_operador"):
        oficiais = {partida["cor"]: partida["saldo_nosso_ms"] / 1000,
                    not partida["cor"]: partida["saldo_outro_ms"] / 1000}
        texto += (f"\nSALDOS OFICIAIS DO RELÓGIO FÍSICO\n"
                  f"Brancas: {oficiais[True]:.3f}s | Pretas: {oficiais[False]:.3f}s\n")
    caminho = repo.caminho.parent / "logs" / f"{nome}.log"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists() and f"ID: {partida['id']}\n" not in caminho.read_text(encoding="utf-8"):
        raise FileExistsError(f"O LOG {caminho.name} pertence a outra partida; preserve-o antes de reutilizar a pasta.")
    temporario = caminho.with_suffix(".log.tmp")
    temporario.write_text(texto, encoding="utf-8")
    temporario.replace(caminho)
    partida["arquivo_log"] = str(caminho.resolve())


def confirmar_armageddon(campanha, repo, confronto, entrada, saida, proxima_execucao=False):
    """A autorização fica salva; nenhum relógio começa ao responder esta pergunta."""
    if confronto.armageddon_autorizado:
        return True
    complemento = " na próxima execução" if proxima_execucao else ""
    resposta = escolher(f"Iniciar Armageddon{complemento}? [s/n]: ",
                       {"s": True, "sim": True, "n": False, "nao": False, "não": False},
                       entrada, saida, padrao=False)
    confronto.armageddon_autorizado = resposta
    repo.salvar(campanha)
    if not resposta:
        saida("Armageddon pendente. Nenhuma nova partida foi iniciada.")
    return resposta


def encerrar_confronto(campanha, repo, confronto, entrada, saida):
    if mostrar_situacao(confronto, campanha.regras, saida) == "armageddon":
        confirmar_armageddon(campanha, repo, confronto, entrada, saida, proxima_execucao=True)


def resolver_pendente(campanha, repo, entrada, saida):
    """Apenas encerramentos externos ao tabuleiro precisam de um resultado informado."""
    c = campanha.confrontos[-1]
    p = c.ativa
    sugestao = p.get("sugestao_placar")
    confirmado = p.get("encerramento_confirmado")
    # Uma FEN isolada não comprova repetição: recuperar o histórico completo.
    tabuleiro = chess.Board(p.get("fen_inicial") or chess.STARTING_FEN)
    for uci in p.get("lances", []):
        tabuleiro.push_uci(uci)
    if confirmado:
        placar, motivo, origem = (confirmado[k] for k in ("placar", "motivo", "origem"))
    elif sugestao and motivo_encerramento(tabuleiro):
        placar = sugestao
        motivo = p["observacao"]
        origem = "tabuleiro"
    else:
        saida("Histórico salvo. Informe o resultado confirmado pelo árbitro.")
        resultado = escolher("[1] Vitória nossa | [2] Empate | [3] Derrota nossa | Enter: deixar pendente: ",
                         {"1": "V", "2": "E", "3": "D"}, entrada, saida, padrao="pendente")
        if resultado == "pendente":
            return False
        placar = "1/2-1/2" if resultado == "E" else "1-0" if (resultado == "V") == p["cor"] else "0-1"
        motivo, origem = "Resultado informado pelo operador conforme arbitragem", "operador"
    # Preserva o resultado mesmo se a entrada dos relógios for interrompida.
    p.update(sugestao_placar=placar, observacao=motivo,
             encerramento_confirmado=dict(placar=placar, motivo=motivo, origem=origem))
    repo.salvar(campanha)
    while True:
        valores = entrada("Relógio físico final — BRANCAS PRETAS (mm:ss.sss; Enter: deixar pendente): ").split()
        if not valores:
            return False
        try:
            if len(valores) != 2:
                raise ValueError("Informe os dois saldos do árbitro.")
            saldos = dict(zip(("brancas", "pretas"), map(ler_tempo, valores)))
            break
        except ValueError as erro:
            saida(str(erro))
    c.finalizar(p["id"], placar, motivo,
                saldos["brancas" if p["cor"] else "pretas"],
                saldos["pretas" if p["cor"] else "brancas"], origem=origem)
    p["origem_relogios"] = "fisico_oficial"
    repo.salvar(campanha)
    salvar_log_partida(c, p, repo)
    repo.salvar(campanha)
    return True


def mostrar_situacao(confronto, regras, saida):
    situacao = confronto.situacao(regras)
    status = situacao["status"]
    if status == "em_disputa":
        saida(f"Próxima execução: partida {situacao['partidas'] + 1} do mesmo confronto.")
    elif status == "armageddon":
        saida("Desempate por Armageddon: brancas 5 min; pretas 4 min; sem incremento.")
    elif status in ("vitoria", "derrota", "classificado", "eliminado"):
        ganhou = status in ("vitoria", "classificado")
        saida(f"Confronto encerrado: {'vencemos' if ganhou else 'perdemos'} | {situacao['criterio']}.")
    elif status == "empate":
        saida("Empate na classificatória. Resultado salvo; próximo adversário no próximo comando.")
    else:
        saida(f"Decisão pendente: {situacao['criterio']}.")
    return status


def iniciar_campeonato(args, entrada, saida, conectar):
    """Cada execução joga uma partida e preserva o histórico para a próxima."""
    repo = Repositorio(args.arquivo)
    if repo.caminho.exists():
        campanha = repo.carregar()
    else:
        equipe = ""
        while not equipe:
            equipe = entrada("Nome da nossa equipe: ").strip()
        campanha = Campanha(equipe)
        repo.criar(campanha)
    resumo = campanha.resumo()
    saida(f"\n{campanha.equipe} | {resumo['vitorias']} vitórias, {resumo['empates']} empates, {resumo['derrotas']} derrotas.")
    saida("Salvamento automático ativo.\n")
    c = campanha.confrontos[-1] if campanha.confrontos else None
    if c and c.ativa:
        if resolver_pendente(campanha, repo, entrada, saida):
            saida("Resultado salvo.")
            encerrar_confronto(campanha, repo, c, entrada, saida)
        return
    situacao = c.situacao(campanha.regras) if c else None
    if c and situacao["status"] not in ("em_disputa", "armageddon"):
        status = mostrar_situacao(c, campanha.regras, saida)
        if status == "relogios_pendentes":
            for anterior in c.concluidas:
                if anterior.get("origem_relogios") in ("fisico_oficial", "ajuste_oficial_pelo_operador"):
                    continue
                while True:
                    valores = entrada(f"Relógios físicos da partida {anterior['numero']} — BRANCAS PRETAS (Enter: pendente): ").split()
                    if not valores:
                        return
                    try:
                        if len(valores) != 2:
                            raise ValueError("Informe os dois saldos oficiais.")
                        b, pr = map(ler_tempo, valores)
                        c.corrigir(anterior["id"], "Registro dos saldos físicos finais",
                            placar=anterior["placar"], motivo=anterior.get("motivo", "Resultado oficial"),
                            saldo_nosso=b if anterior["cor"] else pr,
                            saldo_outro=pr if anterior["cor"] else b, origem="fisico_oficial")
                        salvar_log_partida(c, anterior, repo)
                        repo.salvar(campanha)
                        break
                    except ValueError as erro:
                        saida(str(erro))
            encerrar_confronto(campanha, repo, c, entrada, saida)
            return  # Uma execução de manutenção não inicia outra partida.
        if status in ("relogios_pendentes", "revisao_pendente", "desempate_pendente"):
            return
        if c.fase in ("final", "terceiro-lugar") or (status == "eliminado" and c.fase != "semifinal"):
            return
        c = None
    if c is None:
        adversario = entrada("Adversário desta partida (Enter para encerrar): ").strip()
        if not adversario:
            return
        fase = escolher("Fase [1] Classificação [2] Oitavas [3] Quartas [4] Semifinal [5] Final [6] 3º lugar: ",
                         {str(i): f for i, f in enumerate(FASES, 1)}, entrada, saida)
        formato = "melhor-de-tres" if fase in ("semifinal", "final") else "unica"
        saida("Formato: " + ("melhor de três." if formato == "melhor-de-tres" else "partida única."))
        c = campanha.novo_confronto(adversario, fase=fase, formato=formato,
                                    rodada=len(campanha.confrontos) + 1, primeira_cor=None)
        repo.salvar(campanha)
    if c.situacao(campanha.regras)["status"] == "armageddon":
        saida("Desempate: Armageddon. Brancas 5 min; pretas 4 min; sem incremento.")
    p = jogar_campanha(campanha, repo, args, entrada, saida, conectar, automatico=True)
    if p is None:  # Cancelamento antes de iniciar os relógios.
        return
    if c.ativa and not resolver_pendente(campanha, repo, entrada, saida):
        return
    resultado = {"V": "Vitória nossa", "E": "Empate", "D": "Derrota nossa"}[p["resultado"]]
    saida(f"{resultado}. Partida salva: {Path(p['arquivo_log']).name}.\n")
    encerrar_confronto(campanha, repo, c, entrada, saida)


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
                   help="Duração prevista das partidas normais para planejamento, sem encerramento automático")
    comando("status", "Mostrar vitórias, empates, derrotas e partidas")
    p = comando("confronto", "Cadastrar o próximo pareamento da organização")
    p.add_argument("--adversario", required=True)
    p.add_argument("--fase", choices=FASES, default="classificacao")
    p.add_argument("--rodada", type=int, help="Identificação opcional; por padrão segue a sequência de confrontos")
    p.add_argument("--formato", choices=("unica", "melhor-de-tres"), required=True)
    p.add_argument("--cor", choices=("brancas", "pretas"), help="Referência opcional; a cor será perguntada antes de jogar")
    for nome, ajuda in (("jogar", "Jogar a próxima partida do confronto"),
                        ("iniciar", "Jogar uma partida e salvar o histórico da campanha")):
        p = comando(nome, ajuda)
        p.add_argument("--cor-armageddon", choices=("brancas", "pretas"), help="Referência opcional; a cor sorteada será perguntada antes de jogar")
        p.add_argument("--motor", type=Path)
        p.add_argument("--modo", choices=MODOS, default="completo")
        p.add_argument("--sem-abertura", action="store_true", help="Desativar o repertório preparado")
        p.add_argument("--threads", type=int, default=THREADS_PADRAO)
        p.add_argument("--hash", dest="hash_mb", type=int, default=HASH_PADRAO)
        if nome == "iniciar":
            p.set_defaults(arquivo=ARQUIVO_PADRAO.with_name("campeonato.sqlite3"))
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
        if args.acao == "iniciar":
            if args.threads < 1 or args.hash_mb < 1:
                raise ValueError("Threads e hash devem ser positivos.")
            iniciar_campeonato(args, entrada, saida, conectar)
            return 0
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
                    if p.get("origem_relogios") not in ("fisico_oficial", "ajuste_oficial_pelo_operador"):
                        raise ValueError("Informe --nosso-tempo e --outro-tempo com os saldos do relógio físico.")
                    nosso, outro = p["saldo_nosso_ms"] / 1000, p["saldo_outro_ms"] / 1000
                    origem = p.get("origem_relogios", "registro_anterior")
                elif p.get("relogios_sistema"):
                    raise ValueError("Informe --nosso-tempo e --outro-tempo com os saldos do relógio físico.")
                else:
                    raise ValueError("Partida antiga sem relógios automáticos: informe os dois saldos ao registrar o resultado.")
                dados = dict(placar=args.placar, motivo=args.motivo,
                             saldo_nosso=nosso, saldo_outro=outro, origem="operador")
                if args.corrigir:
                    c.corrigir(identificador, args.corrigir, **dados)
                else:
                    c.finalizar(identificador, **dados)
                p["origem_relogios"] = origem
                salvar_log_partida(c, p, repo)
            repo.salvar(campanha)
            saida(json.dumps(c.situacao(campanha.regras), ensure_ascii=False))
        return 0
    except (EOFError, KeyboardInterrupt):
        saida("Operação cancelada.")
        return 0
    except (ValueError, OSError, sqlite3.Error, chess.engine.EngineError, TimeoutError) as erro:
        saida(f"Não foi possível executar: {erro}")
        return 1
