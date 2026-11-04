"""Registra os dois lados e as métricas de busca do nosso motor."""

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
    saldo_brancas: float | None = None
    saldo_pretas: float | None = None
    fonte_tempo: str | None = None


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


def formatar_relatorio(nome, registros, resultado, cor_equipe, incremento, motor,
                       restante=None, configuracao="", relogios=None):
    nome = validar_nome(nome)
    linhas = [f"Partida: {nome}", f"Nossa equipe: {'Brancas' if cor_equipe else 'Pretas'}",
              f"Motor: {motor}", "Busca principal: Stockfish; orçamento temporal do controlador quando há duração prevista.", configuracao,
              f"Incremento: {incremento:g}s", f"Resultado: {resultado}",
              f"Nosso saldo final no sistema: {restante:.3f}s" if restante is not None else "",
              "Avaliação na perspectiva das brancas.",
              "Tempos medidos pelo relógio do sistema; não são leitura do relógio físico.",
              "Profundidade, nós, avaliação e PV documentam as análises do nosso motor.",
              "Nos movimentos adversários, registramos o lance e o tempo observado; as métricas do motor adversário ficam N/D.",
              "N/D: dado não disponível. A análise prévia do repertório é identificada separadamente da busca atual.", ""]
    if relogios is not None:
        linhas.append(f"Saldos finais do sistema: Brancas {relogios[True]:.3f}s | Pretas {relogios[False]:.3f}s")
    for r in registros:
        tempo = f"{r.tempo:.3f}s" if r.tempo is not None else "N/D"
        linhas.append(f"{r.numero}. {r.autor} | {r.cor} | {r.uci} | "
                      f"profundidade {r.profundidade if r.profundidade is not None else 'N/D'} | "
                      f"nós {r.nos if r.nos is not None else 'N/D'} | avaliação {r.avaliacao or 'N/D'} | "
                      f"PV {r.pv or 'N/D'} | tempo {tempo}")
        if r.detalhes:
            linhas.append(f"  Decisão: {r.detalhes}")
        if r.saldo_brancas is not None and r.saldo_pretas is not None:
            linhas.append(f"  Relógios do sistema: Brancas {r.saldo_brancas:.3f}s | Pretas {r.saldo_pretas:.3f}s")
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
