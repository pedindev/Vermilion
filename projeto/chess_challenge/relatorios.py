"""Registra os dois lados e as métricas de busca do nosso motor."""

from dataclasses import dataclass
from pathlib import Path
import json
import re
from textwrap import fill

import chess


PASTA_RELATORIOS = Path(__file__).resolve().parents[1] / "relatórios de partidas"


@dataclass(frozen=True)
class RegistroLance:
    numero: int
    cor: str
    autor: str
    uci: str
    profundidade: int | None = None
    nos: int | None = None
    avaliacao: str | None = None
    pv: str | None = None
    tempo: float | None = None
    detalhes: str = ""
    saldo_brancas: float | None = None
    saldo_pretas: float | None = None
    fonte_tempo: str | None = None
    fen_antes: str | None = None


def mostrar_tabuleiro(tabuleiro):
    return "\n".join([f"{8-i}  {linha}" for i, linha in enumerate(str(tabuleiro).splitlines())]
                     + ["   a b c d e f g h"])


def registrar_lance(tabuleiro, lance, cor_equipe, calculado=None):
    cor = "Brancas" if tabuleiro.turn else "Pretas"
    autor = "Nossa equipe" if tabuleiro.turn == cor_equipe else "Adversário"
    info = calculado.info if calculado is not None else {}
    pv = info.get("pv", [])
    correspondente = bool(pv and pv[0] == lance)
    avaliacao = None
    if correspondente and "score" in info:
        score = info["score"].white()
        cp, mate = score.score(), score.mate()
        avaliacao = f"{cp / 100:+.2f}" if cp is not None else f"mate {mate:+d}"
        if info.get("lowerbound") or info.get("upperbound"):
            maior = bool(info.get("lowerbound")) == tabuleiro.turn
            avaliacao = (">= " if maior else "<= ") + avaliacao
    return RegistroLance(tabuleiro.fullmove_number, cor, autor, lance.uci(),
                          info.get("depth") if correspondente else None, info.get("nodes"),
                          avaliacao, " ".join(m.uci() for m in pv) if correspondente else None,
                          calculado.tempo if calculado is not None else None,
                          json.dumps(getattr(calculado, "detalhes", {}), ensure_ascii=False)
                          if calculado is not None and getattr(calculado, "detalhes", {}) else "",
                          fen_antes=tabuleiro.fen())


def validar_nome(nome):
    nome = nome.strip()
    if nome.lower().endswith(".txt"):
        nome = nome[:-4].rstrip()
    reservado = nome.split(".")[0].upper()
    if (not nome or len(nome) > 120 or nome.endswith(".")
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', nome)
            or reservado in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
            or re.fullmatch(r"(?:COM|LPT)[0-9¹²³]", reservado)):
        raise ValueError("Use um nome de até 120 caracteres, sem caracteres reservados do Windows.")
    return nome


def formatar_relatorio(nome, registros, resultado, cor_equipe, incremento, motor,
                       restante=None, configuracao="", relogios=None):
    nome = validar_nome(nome)
    registros = list(registros)
    linhas = [f"Partida: {nome}", f"Nossa equipe: {'Brancas' if cor_equipe else 'Pretas'}",
              f"Motor: {motor}", configuracao,
              f"Incremento: {incremento:g}s", f"Resultado: {resultado}"]
    if relogios is not None:
        linhas.append(f"Saldos finais do sistema: Brancas {relogios[True]:.3f}s | Pretas {relogios[False]:.3f}s")
    elif restante is not None:
        linhas.append(f"Nosso saldo final no sistema: {restante:.3f}s")
    linhas.extend(["", "JOGADAS", ""])
    tabuleiro = chess.Board() if not registros or (registros[0].numero == 1 and registros[0].cor == "Brancas") else None
    for r in registros:
        linhas.extend([f"{r.numero}. {r.autor} | {r.cor} | {r.uci}", ""])
        if r.fen_antes is not None:
            tabuleiro = chess.Board(r.fen_antes)
        if tabuleiro is not None:
            try:
                tabuleiro.push_uci(r.uci)
            except ValueError:
                tabuleiro = None
        linhas.extend([mostrar_tabuleiro(tabuleiro) if tabuleiro is not None
                       else "Tabuleiro indisponível: posição inicial não registrada.", "", ""])
    linhas.extend(["DADOS TÉCNICOS POR LANCE", "",
                   "Profundidade, nós, avaliação e PV são dados das análises do nosso motor.",
                   "Avaliação na perspectiva das brancas. N/D: dado não disponível, inclusive busca do motor adversário.",
                   "Tempos medidos pelo relógio do sistema; não são leitura do relógio físico.", ""])
    for r in registros:
        tempo = f"{r.tempo:.3f}s" if r.tempo is not None else "N/D"
        linhas.append(f"{r.numero}. {r.autor} | {r.cor} | {r.uci} | "
                      f"profundidade {r.profundidade if r.profundidade is not None else 'N/D'} | "
                      f"nós {r.nos if r.nos is not None else 'N/D'} | avaliação {r.avaliacao or 'N/D'} | "
                      f"PV: {r.pv or 'N/D'} | tempo {tempo}")
        if r.detalhes:
            try:
                detalhes = json.loads(r.detalhes)
            except (ValueError, TypeError):
                detalhes = {}
            if isinstance(detalhes, dict) and detalhes.get("criterio"):
                linhas.append(fill(f"Decisão: {detalhes['criterio']}", width=100,
                                   initial_indent="  ", subsequent_indent="      "))
            if isinstance(detalhes, dict) and detalhes.get("original"):
                linhas.append(f"  Preferência inicial do Stockfish: {detalhes['original']}")
            if isinstance(detalhes, dict) and detalhes.get("analise_previa"):
                linhas.append("  Origem: repertório preparado; análise prévia preservada no banco.")
        if r.saldo_brancas is not None and r.saldo_pretas is not None:
            linhas.append(f"  Relógios do sistema: Brancas {r.saldo_brancas:.3f}s | Pretas {r.saldo_pretas:.3f}s")
        linhas.append("")
    return "\n".join(linhas) + "\n"


def salvar_relatorio(nome, registros, resultado, cor_equipe, incremento, motor,
                     pasta=PASTA_RELATORIOS, restante=None, configuracao="", relogios=None):
    texto = formatar_relatorio(nome, registros, resultado, cor_equipe, incremento, motor,
                               restante, configuracao, relogios)
    return salvar_texto(nome, texto, pasta)


def salvar_texto(nome, texto, pasta):
    nome = validar_nome(nome)
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    indice = 1
    while True:
        sufixo = "" if indice == 1 else f" ({indice})"
        caminho = pasta / f"{nome}{sufixo}.txt"
        try:
            with caminho.open("x", encoding="utf-8") as arquivo:
                arquivo.write(texto)
            return caminho
        except FileExistsError:
            indice += 1
