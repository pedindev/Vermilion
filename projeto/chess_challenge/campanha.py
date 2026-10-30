"""Estado da competição, regras dos confrontos e persistência transacional local.

Resultados são sempre relativos à nossa equipe. O resultado de uma partida
empatada no Armageddon continua E; a classificação é uma informação separada.
"""

from dataclasses import asdict, dataclass, field, fields, replace
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
import json
from math import isfinite
from pathlib import Path
import sqlite3
from uuid import uuid4

import chess

FASES = ("classificacao", "oitavas", "quartas", "semifinal", "final", "terceiro-lugar")
OBJETIVOS = ("equilibrado", "buscar_vitoria", "proteger_vantagem", "preservar_empate")
PLACARES = ("1-0", "0-1", "1/2-1/2")


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def numero(valor, nome, positivo=False):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not isfinite(valor) or valor < 0 or (positivo and valor == 0):
        raise ValueError(f"{nome} deve ser finito e {'positivo' if positivo else 'não negativo'}.")
    return valor


def resultado_relativo(placar, cor):
    if placar not in PLACARES:
        raise ValueError("Informe 1-0, 0-1 ou 1/2-1/2; interrupção não é resultado.")
    return "E" if placar == "1/2-1/2" else "V" if (placar == "1-0") == cor else "D"


@lru_cache(maxsize=512)
def validar_historico(fen_inicial, lances, fen_atual):
    """Revalida quando o conteúdo muda; partidas anteriores não são rejogadas a cada salvamento."""
    board = chess.Board(fen_inicial)
    if not board.is_valid():
        raise ValueError("Posição inicial inválida no histórico.")
    for uci in lances:
        lance = chess.Move.from_uci(uci)
        if lance not in board.legal_moves:
            raise ValueError("Lance ilegal no histórico.")
        board.push(lance)
    if fen_atual and fen_atual != board.fen():
        raise ValueError("Histórico de lances não corresponde ao tabuleiro salvo.")


@dataclass
class Regras:
    tempo: float = 900
    incremento: float = 10
    armageddon_brancas: float = 300
    armageddon_pretas: float = 240
    incremento_armageddon: float = 0
    origem_armageddon: str = "Sem incremento, confirmado pela equipe em 30/10/2026 após consulta à organização."
    encerrar_ao_decidir: bool = True
    duracao_prevista_minutos: float | None = None
    legado: dict = field(default_factory=dict, repr=False)  # Preserva configurações antigas, sem usá-las.

    @classmethod
    def de_dict(cls, dados):
        nomes = {f.name for f in fields(cls)}
        atuais = {k: v for k, v in dados.items() if k in nomes}
        atuais["legado"] = {**atuais.get("legado", {}),
                            **{k: v for k, v in dados.items() if k not in nomes}}
        return cls(**atuais)

    def validar(self):
        for nome in ("tempo", "armageddon_brancas", "armageddon_pretas"):
            numero(getattr(self, nome), nome, True)
        for nome in ("incremento", "incremento_armageddon"):
            numero(getattr(self, nome), nome)
        if self.duracao_prevista_minutos is not None:
            numero(self.duracao_prevista_minutos, "Duração prevista", True)
        if type(self.encerrar_ao_decidir) is not bool:
            raise ValueError("encerrar_ao_decidir deve ser booleano.")


@dataclass(frozen=True)
class Contexto:
    objetivo: str = "equilibrado"
    motivo: str = "Confronto aberto."
    empate_classifica: bool = False
    evitar_empate: bool = False
    fase: str = "classificacao"
    partida: int = 1
    saldo_acumulado: float | None = None
    armageddon: bool = False
    desempate_por_tempo: bool = False

    def __post_init__(self):
        if self.objetivo not in OBJETIVOS:
            raise ValueError("Objetivo de campanha inválido.")

    def com_relogios(self, nosso, outro):
        if not self.desempate_por_tempo or self.saldo_acumulado is None or outro is None:
            return self
        margem = self.saldo_acumulado + nosso - outro
        if margem < -2:
            return replace(self, objetivo="buscar_vitoria", evitar_empate=True,
                motivo=f"Confronto empatado; saldo total estimado desfavorável em {-margem:.2f}s. Evitar empate imediato.")
        if margem > 2:
            return replace(self, objetivo="preservar_empate",
                motivo=f"Confronto empatado; saldo total estimado favorável em {margem:.2f}s. Não é classificação assegurada.")
        return self


@dataclass
class Confronto:
    adversario: str
    fase: str = "classificacao"
    rodada: int = 1
    formato: str = "unica"
    primeira_cor: bool | None = True
    id: str = field(default_factory=lambda: uuid4().hex)
    partidas: list = field(default_factory=list)
    cor_armageddon: bool | None = None
    objetivo_informado: str = "equilibrado"
    justificativa_objetivo: str = ""
    decisao_oficial: dict | None = None
    regras_aplicadas: dict | None = None

    def regras(self, padrao):
        return Regras.de_dict(self.regras_aplicadas) if self.regras_aplicadas is not None else padrao

    def validar(self):
        if not self.adversario.strip() or self.fase not in FASES or self.formato not in ("unica", "melhor-de-tres"):
            raise ValueError("Adversário, fase ou formato inválido.")
        if type(self.rodada) is not int or self.rodada < 1 or (self.primeira_cor is not None and type(self.primeira_cor) is not bool):
            raise ValueError("Rodada ou primeira cor inválida.")
        if self.primeira_cor is None and any(not p["armageddon"] and p["status"] != "cancelada" for p in self.partidas):
            raise ValueError("Partida normal registrada sem a definição da primeira cor.")
        if self.cor_armageddon is not None and type(self.cor_armageddon) is not bool:
            raise ValueError("Cor sorteada inválida.")
        if self.objetivo_informado not in OBJETIVOS:
            raise ValueError("Objetivo inválido.")
        if self.objetivo_informado != "equilibrado" and not self.justificativa_objetivo.strip():
            raise ValueError("O objetivo informado exige justificativa da situação da tabela.")
        if self.decisao_oficial is not None and self.decisao_oficial.get("status") not in ("classificado", "eliminado"):
            raise ValueError("Decisão oficial inválida.")
        if self.regras_aplicadas is not None:
            Regras.de_dict(self.regras_aplicadas).validar()
        for p in self.partidas:
            if p.get("status") not in ("em_andamento", "aguardando_resultado", "inconclusiva", "concluida", "cancelada") or type(p.get("cor")) is not bool:
                raise ValueError("Estado de partida inválido.")
            for nome in ("saldo_nosso_ms", "saldo_outro_ms"):
                if p.get(nome) is not None and (type(p[nome]) is not int or p[nome] < 0):
                    raise ValueError("Relógio final inválido no histórico.")
            if p["status"] == "concluida" and p.get("resultado") != resultado_relativo(p.get("placar"), p["cor"]):
                raise ValueError("Placar e resultado relativo não correspondem.")
            validar_historico(p.get("fen_inicial") or chess.STARTING_FEN,
                              tuple(p.get("lances", [])), p.get("fen_atual"))
        if sum(p["status"] in ("em_andamento", "aguardando_resultado", "inconclusiva") for p in self.partidas) > 1:
            raise ValueError("Mais de uma partida pendente no mesmo confronto.")

    @property
    def concluidas(self):
        return [p for p in self.partidas if p["status"] == "concluida"]

    @property
    def ativa(self):
        return next((p for p in self.partidas if p["status"] in ("em_andamento", "aguardando_resultado", "inconclusiva")), None)

    def situacao(self, regras):
        regras = self.regras(regras)
        normais = [p for p in self.concluidas if not p["armageddon"]]
        diferenca = sum({"V": 1, "E": 0, "D": -1}[p["resultado"]] for p in normais)
        saldos = None
        if normais and all(p.get("saldo_nosso_ms") is not None and p.get("saldo_outro_ms") is not None for p in normais):
            saldos = [sum(p[k] for p in normais) / 1000 for k in ("saldo_nosso_ms", "saldo_outro_ms")]
        base = {"partidas": len(normais), "diferenca": diferenca, "saldos": saldos}
        if self.decisao_oficial is not None:
            return dict(base, status=self.decisao_oficial["status"], criterio=self.decisao_oficial["motivo"])
        def vencedor(ganhou):
            if self.fase == "classificacao":
                return "vitoria" if ganhou else "derrota"
            return "classificado" if ganhou else "eliminado"

        quantidade = 1 if self.formato == "unica" else 3
        if len(normais) < quantidade:
            decidido = regras.encerrar_ao_decidir and abs(diferenca) > quantidade - len(normais)
            status = vencedor(diferenca > 0) if decidido else "em_disputa"
            criterio = "Placar já decidido" if decidido else "Confronto em andamento"
        elif diferenca:
            status, criterio = vencedor(diferenca > 0), "Placar"
        elif self.formato == "unica":
            status, criterio = "armageddon", "Partida única empatada"
        elif saldos is None:
            status, criterio = "relogios_pendentes", "Informar os dois saldos finais das três partidas"
        else:
            diferenca_ms = sum(p["saldo_nosso_ms"] - p["saldo_outro_ms"] for p in normais)
            status = vencedor(diferenca_ms > 0) if diferenca_ms else "armageddon"
            criterio = "Soma dos relógios finais" if diferenca_ms else "Placar e soma dos relógios iguais"

        arm = next((p for p in self.concluidas if p["armageddon"]), None)
        if arm:
            if status != "armageddon":
                return dict(base, status="revisao_pendente", criterio="Correção anterior alterou a condição do Armageddon; consultar arbitragem")
            ganhou = arm["resultado"] == "V" or (arm["resultado"] == "E" and not arm["cor"])
            status, criterio = vencedor(ganhou), "Armageddon"
        return dict(base, status=status, criterio=criterio)

    def contexto(self, regras, lado_nosso=True):
        regras = self.regras(regras)
        normais = [p for p in self.concluidas if not p["armageddon"]]
        n = len(normais)
        situacao = self.situacao(regras)
        saldo = None if situacao["saldos"] is None else situacao["saldos"][0] - situacao["saldos"][1]
        if saldo is not None and not lado_nosso:
            saldo = -saldo
        comum = dict(fase=self.fase, partida=n + 1, saldo_acumulado=saldo)
        if situacao["status"] == "armageddon":
            if self.cor_armageddon is None:
                raise ValueError("Informe a cor do sorteio oficial antes do Armageddon.")
            cor = self.cor_armageddon if lado_nosso else not self.cor_armageddon
            return Contexto("buscar_vitoria" if cor else "preservar_empate",
                "Armageddon: brancas precisam vencer; empate classifica pretas.", not cor, cor,
                **comum, armageddon=True)
        if self.formato == "unica":
            return Contexto(motivo="Partida única: buscar o melhor resultado no tabuleiro; empate leva ao Armageddon.", **comum)
        diferenca = situacao["diferenca"] * (1 if lado_nosso else -1)
        if diferenca > 2 - n:
            return Contexto("preservar_empate", "Empate nesta partida garante o confronto.", True, False, **comum)
        if n == 2 and diferenca < 0:
            return Contexto("buscar_vitoria", "Só a vitória permite igualar o confronto e chegar ao desempate.", False, True, **comum)
        if diferenca > 0:
            return Contexto("proteger_vantagem", "Estamos à frente; empate ajuda, mas o confronto ainda pode continuar.", **comum)
        if diferenca < 0:
            return Contexto("buscar_vitoria", "Precisamos recuperar o placar; um empate ainda pode permitir recuperação posterior.", **comum)
        return Contexto(motivo="Confronto equilibrado; empate final depende dos relógios.",
                        desempate_por_tempo=n == 2, **comum)

    def iniciar(self, regras):
        regras = self.regras(regras)
        self.validar()
        regras.validar()
        if self.ativa:
            raise ValueError("Há uma partida pendente; finalize seu resultado ou cancele a tentativa.")
        situacao = self.situacao(regras)
        if situacao["status"] not in ("em_disputa", "armageddon"):
            raise ValueError(f"Não é possível iniciar: {situacao['status']}.")
        arm = situacao["status"] == "armageddon"
        if arm and self.cor_armageddon is None:
            raise ValueError("Informe a cor sorteada no Armageddon.")
        if not arm and self.primeira_cor is None:
            raise ValueError("Informe a cor antes de iniciar a primeira partida.")
        indice = len([p for p in self.concluidas if not p["armageddon"]])
        cor = self.cor_armageddon if arm else (self.primeira_cor if indice % 2 == 0 else not self.primeira_cor)
        tempos = (regras.armageddon_brancas, regras.armageddon_pretas) if arm else (regras.tempo, regras.tempo)
        p = dict(id=uuid4().hex, numero=indice + 1, armageddon=arm, cor=cor,
                 tempo_nosso=tempos[0 if cor else 1], tempo_outro=tempos[1 if cor else 0],
                 incremento=regras.incremento_armageddon if arm else regras.incremento,
                 duracao_prevista_minutos=regras.duracao_prevista_minutos,
                 status="em_andamento", inicio=agora(), fen_inicial=None, lances=[], registros=[],
                 resultado=None, placar=None, saldo_nosso_ms=None, saldo_outro_ms=None,
                 contexto=asdict(self.contexto(regras)))
        self.partidas.append(p)
        return p

    def partida(self, identificador):
        try:
            return next(p for p in self.partidas if p["id"] == identificador)
        except StopIteration:
            raise ValueError("Partida não encontrada.") from None

    def finalizar(self, identificador, placar, motivo, saldo_nosso=None, saldo_outro=None, origem="operador"):
        p = self.partida(identificador)
        resultado = resultado_relativo(placar, p["cor"])
        valores = [None if x is None else round(numero(x, "Saldo final") * 1000) for x in (saldo_nosso, saldo_outro)]
        if p["status"] == "concluida":
            if (p["placar"], p["saldo_nosso_ms"], p["saldo_outro_ms"]) == (placar, *valores):
                return  # Reenvio idempotente, sem pontuar duas vezes.
            raise ValueError("Resultado já registrado. Use a correção com justificativa.")
        if p["status"] == "cancelada":
            raise ValueError("Uma tentativa cancelada não pode receber resultado.")
        p.update(status="concluida", placar=placar, resultado=resultado, motivo=motivo,
                 saldo_nosso_ms=valores[0], saldo_outro_ms=valores[1], origem=origem, fim=agora())

    def corrigir(self, identificador, justificativa, **resultado):
        p = self.partida(identificador)
        if p["status"] != "concluida" or not justificativa.strip():
            raise ValueError("Correção exige uma partida concluída e justificativa.")
        anterior = dict(p)
        p["status"] = "aguardando_resultado"
        try:
            self.finalizar(identificador, **resultado)
        except Exception:
            p.clear()
            p.update(anterior)
            raise
        p.setdefault("correcoes", []).append(dict(data=agora(), justificativa=justificativa,
            anterior={k: anterior.get(k) for k in ("placar", "motivo", "saldo_nosso_ms", "saldo_outro_ms")}))


@dataclass
class Campanha:
    equipe: str
    campeonato: str = "III Chess Challenge"
    regras: Regras = field(default_factory=Regras)
    confrontos: list = field(default_factory=list)
    tabelas: list = field(default_factory=list)  # Histórico legado; não participa das decisões.
    revisao: int = 0
    versao: int = 1

    def validar(self):
        if not self.equipe.strip() or not self.campeonato.strip() or self.versao != 1:
            raise ValueError("Campanha ou versão inválida.")
        self.regras.validar()
        ids = []
        for c in self.confrontos:
            c.validar()
            ids.append(c.id)
            ids.extend(p["id"] for p in c.partidas)
        if len(ids) != len(set(ids)):
            raise ValueError("Identificadores duplicados no histórico.")

    def novo_confronto(self, adversario, **dados):
        if any(c.ativa for c in self.confrontos):
            raise ValueError("Finalize a partida pendente antes de iniciar outro confronto.")
        if self.confrontos and self.confrontos[-1].situacao(self.regras)["status"] in ("em_disputa", "armageddon", "relogios_pendentes", "desempate_pendente", "revisao_pendente"):
            raise ValueError("O confronto anterior ainda não foi resolvido.")
        if self.confrontos:
            anterior = self.confrontos[-1]
            if anterior.situacao(self.regras)["status"] == "eliminado" and not (anterior.fase == "semifinal" and dados.get("fase") == "terceiro-lugar"):
                raise ValueError("Equipe eliminada. Uma mudança exige decisão oficial da arbitragem.")
        c = Confronto(adversario, regras_aplicadas=asdict(self.regras), **dados)
        c.validar()
        self.confrontos.append(c)
        return c

    def contexto(self, confronto, lado_nosso=True):
        return confronto.contexto(self.regras, lado_nosso)

    def resumo(self):
        partidas = [p for c in self.confrontos for p in c.concluidas]
        return dict(equipe=self.equipe, campeonato=self.campeonato,
                    vitorias=sum(p["resultado"] == "V" for p in partidas),
                    empates=sum(p["resultado"] == "E" for p in partidas),
                    derrotas=sum(p["resultado"] == "D" for p in partidas),
                    confrontos=[dict(id=c.id, adversario=c.adversario, fase=c.fase,
                                     rodada=c.rodada, **c.situacao(self.regras)) for c in self.confrontos])


class Repositorio:
    """Um banco SQLite por campanha; revisão impede sobrescrita por outra sessão."""

    def __init__(self, caminho):
        self.caminho = Path(caminho)

    def criar(self, campanha):
        campanha.validar()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.caminho)) as banco, banco:
            banco.execute("CREATE TABLE IF NOT EXISTS campanha (id INTEGER PRIMARY KEY CHECK(id=1), revisao INTEGER NOT NULL, dados TEXT NOT NULL)")
            if banco.execute("SELECT 1 FROM campanha").fetchone():
                raise ValueError("Já existe uma campanha neste arquivo.")
            banco.execute("INSERT INTO campanha VALUES (1, ?, ?)", (campanha.revisao, json.dumps(asdict(campanha), ensure_ascii=False, allow_nan=False)))

    def carregar(self):
        if not self.caminho.is_file():
            raise FileNotFoundError(f"Campanha não encontrada: {self.caminho}")
        with closing(sqlite3.connect(self.caminho)) as banco, banco:
            linha = banco.execute("SELECT revisao,dados FROM campanha WHERE id=1").fetchone()
        if linha is None:
            raise ValueError("Banco sem campanha.")
        dados = json.loads(linha[1])
        dados["regras"] = Regras.de_dict(dados["regras"])
        dados["confrontos"] = [Confronto(**c) for c in dados["confrontos"]]
        campanha = Campanha(**dados)
        if campanha.revisao != linha[0]:
            raise ValueError("Revisão do banco inconsistente.")
        campanha.validar()
        return campanha

    def salvar(self, campanha):
        campanha.validar()
        if not self.caminho.is_file():
            raise FileNotFoundError("Crie a campanha antes de salvar.")
        dados = asdict(campanha)
        dados["revisao"] += 1
        with closing(sqlite3.connect(self.caminho)) as banco, banco:
            alterado = banco.execute("UPDATE campanha SET revisao=?,dados=? WHERE id=1 AND revisao=?",
                (dados["revisao"], json.dumps(dados, ensure_ascii=False, allow_nan=False), campanha.revisao)).rowcount
            if alterado != 1:
                raise ValueError("Outra sessão atualizou a campanha. Reabra o arquivo antes de continuar.")
        campanha.revisao += 1
