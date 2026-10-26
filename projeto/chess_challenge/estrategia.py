"""Critérios experimentais de campanha aplicados a alternativas verificadas."""

from dataclasses import asdict

import chess
import chess.engine

from .motor import LanceCalculado

VALORES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def final_depois(board, lance):
    depois = board.copy(stack=True)
    depois.push(lance)
    if depois.is_checkmate():
        return "V"
    if (depois.is_stalemate() or depois.is_insufficient_material()
            or depois.is_repetition(3) or depois.is_fifty_moves()):
        return "E"
    return None


def final_qualificante(board, contexto):
    """Uma conclusão comprovada pelas regras dispensa heurística e busca extra."""
    empate = None
    for lance in board.legal_moves:
        fim = final_depois(board, lance)
        if fim == "V":
            return lance, "Mate imediato verificado no tabuleiro."
        if fim == "E" and contexto.empate_classifica:
            empate = lance
    if empate is not None:
        return empate, "Empate imediato garante a classificação pelo contexto do confronto."
    return None, None


def atributos(board, lance):
    cor = board.turn
    depois = board.copy(stack=True)
    depois.push(lance)

    def pressao(rei, atacante):
        if rei is None:
            return 0
        zona = chess.SquareSet(chess.BB_KING_ATTACKS[rei]) | chess.SquareSet([rei])
        return sum(len(depois.attackers(atacante, casa)) for casa in zona)

    expostos = sum(VALORES[p.piece_type] for casa, p in depois.piece_map().items()
                   if p.color == cor and depois.is_attacked_by(not cor, casa)
                   and not depois.is_attacked_by(cor, casa))
    return dict(pressao_nosso_rei=pressao(depois.king(cor), not cor),
                pressao_rei_adversario=pressao(depois.king(not cor), cor),
                material_total=sum(VALORES[p.piece_type] for p in depois.piece_map().values()),
                pecas_nossas_expostas=expostos, final=final_depois(board, lance))


def ordenar(board, alternativas, original, contexto, cp_original):
    """Não aceita candidatos novos: somente os que passaram pela verificação UCI.

    Atributos estáticos são desempates experimentais, não uma probabilidade de
    vitória nem medida comprovada de dificuldade para o adversário.
    """
    objetivo = contexto.objetivo
    if cp_original >= 150:
        objetivo = "converter_vantagem"
    avaliados = [(lance, cp, atributos(board, lance)) for lance, cp in alternativas]
    if contexto.evitar_empate and any(a[2]["final"] != "E" for a in avaliados):
        avaliados = [a for a in avaliados if a[2]["final"] != "E"]

    def nota(item):
        lance, cp, a = item
        if objetivo == "buscar_vitoria":
            estilo = (a["pressao_rei_adversario"] - 2 * a["pressao_nosso_rei"]
                      - a["pecas_nossas_expostas"] + a["material_total"] / 10)
        elif objetivo in ("preservar_empate", "proteger_vantagem", "converter_vantagem"):
            estilo = -2 * a["pressao_nosso_rei"] - a["pecas_nossas_expostas"] - a["material_total"] / 10
        else:
            estilo = 0
        return (a["final"] == "V", estilo, cp, lance == original)

    escolhido = max(avaliados, key=nota)
    diagnostico = dict(objetivo_aplicado=objetivo,
        alternativas=[dict(uci=l.uci(), cp=cp, **a) for l, cp, a in avaliados])
    return escolhido[0], diagnostico


def decisao_por_regra(lance, motivo, contexto, tempo, cor):
    # Profundidade zero e zero nós: prova das regras, não análise NNUE inventada.
    score = chess.engine.Mate(1) if motivo.startswith("Mate") else chess.engine.Cp(0)
    return LanceCalculado(lance, tempo, dict(pv=[lance], depth=0, nodes=0,
        score=chess.engine.PovScore(score, cor)), detalhes=dict(
        modo="completo", contexto=asdict(contexto), criterio=motivo, fonte="regra comprovada",
        antecipacao="dispensada por conclusão comprovada", original=None,
        escolhido=lance.uci(), troca_autoral=True))
