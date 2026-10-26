"""Registro legível e técnico da partida; escrita somente após autorização."""

from dataclasses import dataclass
from pathlib import Path
import json
import re

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
                          if calculado is not None and getattr(calculado, "detalhes", {}) else "")


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


def salvar_relatorio(nome, registros, resultado, cor_equipe, incremento, motor,
                     pasta=PASTA_RELATORIOS, restante=None, configuracao=""):
    nome = validar_nome(nome)
    linhas = [f"Partida: {nome}", f"Nossa equipe: {'Brancas' if cor_equipe else 'Pretas'}",
              f"Motor: {motor}", "Gestão da busca principal: original do Stockfish", configuracao,
              f"Incremento: {incremento:g}s", f"Resultado: {resultado}",
              f"Nosso último saldo estimado: {restante:.3f}s" if restante is not None else "",
              "Avaliação na perspectiva das brancas.",
              "N/D: dado não fornecido. Não temos os dados de busca nem o tempo do adversário.", ""]
    for r in registros:
        tempo = f"{r.tempo:.3f}s" if r.tempo is not None else "N/D"
        linhas.append(f"{r.numero}. {r.autor} | {r.cor} | {r.uci} | "
                      f"profundidade {r.profundidade if r.profundidade is not None else 'N/D'} | "
                      f"nós {r.nos if r.nos is not None else 'N/D'} | avaliação {r.avaliacao or 'N/D'} | "
                      f"PV {r.pv or 'N/D'} | tempo {tempo}")
        if r.detalhes:
            linhas.append(f"  Decisão: {r.detalhes}")
    return salvar_texto(nome, "\n".join(linhas) + "\n", pasta)


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
