"""Estado da competição, regras dos confrontos e persistência transacional local.

Resultados são sempre relativos à nossa equipe. O resultado de uma partida
empatada no Armageddon continua E; a classificação é uma informação separada.
"""

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
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


@dataclass
class Regras:
    tempo: float = 900
    incremento: float = 10
    armageddon_brancas: float = 300
    armageddon_pretas: float = 240
    incremento_armageddon: float = 0
    origem_armageddon: str = "Sem incremento por orientação da equipe; FAQ não explicita incremento."
    pontos_vitoria: float = 3
    pontos_empate: float = 1
    pontos_derrota: float = 0
    rodadas: int | None = None
    vagas: int | None = None
    equipes: int | None = None
    classificacao_por_pontos_confirmada: bool = False
    criterio_tabela: str = "Classificação oficial informada pelo operador; fórmula ELO não publicada."
    encerrar_ao_decidir: bool = True

    def validar(self):
        for nome in ("tempo", "armageddon_brancas", "armageddon_pretas"):
            numero(getattr(self, nome), nome, True)
        for nome in ("incremento", "incremento_armageddon", "pontos_vitoria", "pontos_empate", "pontos_derrota"):
            numero(getattr(self, nome), nome)
        for nome in ("rodadas", "vagas", "equipes"):
            valor = getattr(self, nome)
            if valor is not None and (type(valor) is not int or valor < 1):
                raise ValueError(f"{nome} deve ser inteiro positivo ou não informado.")
        if type(self.encerrar_ao_decidir) is not bool:
            raise ValueError("encerrar_ao_decidir deve ser booleano.")
        if type(self.classificacao_por_pontos_confirmada) is not bool:
            raise ValueError("Confirmação da pontuação deve ser booleana.")
        if self.equipes is not None and self.vagas is not None and self.vagas > self.equipes:
            raise ValueError("Vagas não podem exceder o número de equipes.")


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
    primeira_cor: bool = True
    id: str = field(default_factory=lambda: uuid4().hex)
    partidas: list = field(default_factory=list)
    cor_armageddon: bool | None = None
    objetivo_informado: str = "equilibrado"
    justificativa_objetivo: str = ""
    decisao_oficial: dict | None = None
    regras_aplicadas: dict | None = None

    def regras(self, padrao):
        return Regras(**self.regras_aplicadas) if self.regras_aplicadas is not None else padrao

    def validar(self):
        if not self.adversario.strip() or self.fase not in FASES or self.formato not in ("unica", "melhor-de-tres"):
            raise ValueError("Adversário, fase ou formato inválido.")
        if type(self.rodada) is not int or self.rodada < 1 or type(self.primeira_cor) is not bool:
            raise ValueError("Rodada ou primeira cor inválida.")
        if self.cor_armageddon is not None and type(self.cor_armageddon) is not bool:
            raise ValueError("Cor sorteada inválida.")
        if self.objetivo_informado not in OBJETIVOS:
            raise ValueError("Objetivo inválido.")
        if self.objetivo_informado != "equilibrado" and not self.justificativa_objetivo.strip():
            raise ValueError("O objetivo informado exige justificativa da situação da tabela.")
        if self.decisao_oficial is not None and self.decisao_oficial.get("status") not in ("classificado", "eliminado"):
            raise ValueError("Decisão oficial inválida.")
        if self.regras_aplicadas is not None:
            Regras(**self.regras_aplicadas).validar()
        for p in self.partidas:
            if p.get("status") not in ("em_andamento", "aguardando_resultado", "inconclusiva", "concluida", "cancelada") or type(p.get("cor")) is not bool:
                raise ValueError("Estado de partida inválido.")
            for nome in ("saldo_nosso_ms", "saldo_outro_ms"):
                if p.get(nome) is not None and (type(p[nome]) is not int or p[nome] < 0):
                    raise ValueError("Relógio final inválido no histórico.")
            if p["status"] == "concluida" and p.get("resultado") != resultado_relativo(p.get("placar"), p["cor"]):
                raise ValueError("Placar e resultado relativo não correspondem.")
            board = chess.Board(p.get("fen_inicial") or chess.STARTING_FEN)
            if not board.is_valid():
                raise ValueError("Posição inicial inválida no histórico.")
            for uci in p.get("lances", []):
                board.push_uci(uci)
            if p.get("fen_atual") and p["fen_atual"] != board.fen():
                raise ValueError("Histórico de lances não corresponde ao tabuleiro salvo.")
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
        arm = next((p for p in self.concluidas if p["armageddon"]), None)
        if arm:
            if len(normais) != 3 or diferenca or saldos is None or sum(p["saldo_nosso_ms"] for p in normais) != sum(p["saldo_outro_ms"] for p in normais):
                return dict(base, status="revisao_pendente", criterio="Correção anterior alterou a condição do Armageddon; consultar arbitragem")
            ganhou = arm["resultado"] == "V" or (arm["resultado"] == "E" and not arm["cor"])
            return dict(base, status="classificado" if ganhou else "eliminado", criterio="Armageddon")
        if self.formato == "unica":
            if not normais:
                return dict(base, status="em_disputa", criterio="Partida única")
            r = normais[0]["resultado"]
            status = {"V": "vitoria", "E": "empate", "D": "derrota"}[r] if self.fase == "classificacao" else {"V": "classificado", "E": "desempate_pendente", "D": "eliminado"}[r]
            return dict(base, status=status, criterio="Partida única")
        if len(normais) < 3:
            if regras.encerrar_ao_decidir and abs(diferenca) > 3 - len(normais):
                return dict(base, status="classificado" if diferenca > 0 else "eliminado", criterio="Placar já decidido")
            return dict(base, status="em_disputa", criterio="Melhor de três")
        if diferenca:
            return dict(base, status="classificado" if diferenca > 0 else "eliminado", criterio="Placar")
        if saldos is None:
            return dict(base, status="relogios_pendentes", criterio="Informar os dois saldos finais das três partidas")
        soma_nossa = sum(p["saldo_nosso_ms"] for p in normais)
        soma_outra = sum(p["saldo_outro_ms"] for p in normais)
        if soma_nossa != soma_outra:
            return dict(base, status="classificado" if soma_nossa > soma_outra else "eliminado", criterio="Soma dos relógios finais")
        return dict(base, status="armageddon", criterio="Placar e soma dos relógios iguais")

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
        if self.fase == "classificacao":
            objetivo = self.objetivo_informado if lado_nosso else "equilibrado"
            return Contexto(objetivo, self.justificativa_objetivo or "Tabela oficial sem necessidade de resultado informada.", **comum)
        if self.formato == "unica":
            return Contexto("buscar_vitoria", "Eliminatória em partida única; empate exige decisão da organização.", **comum)
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
        indice = len([p for p in self.concluidas if not p["armageddon"]])
        cor = self.cor_armageddon if arm else (self.primeira_cor if indice % 2 == 0 else not self.primeira_cor)
        tempos = (regras.armageddon_brancas, regras.armageddon_pretas) if arm else (regras.tempo, regras.tempo)
        p = dict(id=uuid4().hex, numero=indice + 1, armageddon=arm, cor=cor,
                 tempo_nosso=tempos[0 if cor else 1], tempo_outro=tempos[1 if cor else 0],
                 incremento=regras.incremento_armageddon if arm else regras.incremento,
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
    tabelas: list = field(default_factory=list)
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

    def registrar_tabela(self, linhas, rodada, fonte="Organização", criterio="oficial"):
        if type(rodada) is not int or rodada < 1 or not fonte.strip() or not linhas:
            raise ValueError("Informe rodada, fonte e linhas da tabela oficial.")
        equipes, posicoes = [], []
        for linha in linhas:
            if not isinstance(linha.get("equipe"), str) or not linha["equipe"].strip() or type(linha.get("posicao")) is not int or linha["posicao"] < 1:
                raise ValueError("Cada linha exige equipe e posição positiva.")
            numero(linha.get("pontos"), "Pontos")
            equipes.append(linha["equipe"])
            posicoes.append(linha["posicao"])
        if len(equipes) != len(set(equipes)) or self.equipe not in equipes:
            raise ValueError("Tabela deve conter nossa equipe, sem equipes duplicadas.")
        self.tabelas.append(dict(data=agora(), rodada=rodada, fonte=fonte, criterio=criterio,
                                linhas=sorted(linhas, key=lambda l: l["posicao"])))

    def contexto(self, confronto, lado_nosso=True):
        padrao = confronto.contexto(self.regras, lado_nosso)
        r = self.regras
        if (not lado_nosso or confronto.fase != "classificacao" or confronto.formato != "unica"
                or confronto.objetivo_informado != "equilibrado" or not self.tabelas
                or not r.classificacao_por_pontos_confirmada or None in (r.rodadas, r.vagas, r.equipes)):
            return padrao
        tabela = self.tabelas[-1]
        if tabela["rodada"] != confronto.rodada - 1 or len(tabela["linhas"]) != r.equipes or confronto.rodada > r.rodadas:
            return padrao  # Tabela incompleta/desatualizada não prova classificação.
        nossa = next(l for l in tabela["linhas"] if l["equipe"] == self.equipe)
        outros = [l for l in tabela["linhas"] if l["equipe"] != self.equipe]
        restantes = r.rodadas - confronto.rodada
        maximo = max(r.pontos_vitoria, r.pontos_empate, r.pontos_derrota)
        minimo = min(r.pontos_vitoria, r.pontos_empate, r.pontos_derrota)
        # Limites conservadores: empate em pontos nunca é tratado como vaga certa.
        nosso_minimo = nossa["pontos"] + r.pontos_empate + restantes * minimo
        ameacas = sum(l["pontos"] + (restantes + 1) * maximo >= nosso_minimo for l in outros)
        if ameacas < r.vagas:
            return Contexto("preservar_empate", "Empate garante vaga pelos limites conservadores da tabela completa e pontuação confirmada.",
                            True, False, fase=confronto.fase)
        nosso_maximo = nossa["pontos"] + r.pontos_empate + restantes * maximo
        acima = sum(l["pontos"] + (restantes + 1) * minimo > nosso_maximo for l in outros)
        if acima >= r.vagas:
            return Contexto("buscar_vitoria", "Empate não permite alcançar as vagas, mesmo vencendo todas as rodadas restantes.",
                            False, True, fase=confronto.fase)
        return padrao

    def resumo(self):
        partidas = [p for c in self.confrontos for p in c.concluidas]
        pontos = sum({"V": c.regras(self.regras).pontos_vitoria, "E": c.regras(self.regras).pontos_empate,
                      "D": c.regras(self.regras).pontos_derrota}[p["resultado"]]
                     for c in self.confrontos if c.fase == "classificacao" for p in c.concluidas if not p["armageddon"])
        nossa_linha = next((l for l in self.tabelas[-1]["linhas"] if l["equipe"] == self.equipe), None) if self.tabelas else None
        return dict(equipe=self.equipe, campeonato=self.campeonato,
                    vitorias=sum(p["resultado"] == "V" for p in partidas),
                    empates=sum(p["resultado"] == "E" for p in partidas),
                    derrotas=sum(p["resultado"] == "D" for p in partidas), pontos=pontos,
                    tabela=self.tabelas[-1] if self.tabelas else None,
                    posicao_oficial=nossa_linha["posicao"] if nossa_linha else None,
                    pontos_oficiais=nossa_linha["pontos"] if nossa_linha else None,
                    confrontos=[dict(id=c.id, adversario=c.adversario, fase=c.fase,
                                     rodada=c.rodada, **c.situacao(self.regras)) for c in self.confrontos])


class Repositorio:
    """Um banco SQLite por campanha; revisão impede sobrescrita por outra sessão."""

    def __init__(self, caminho):
        self.caminho = Path(caminho)

    def criar(self, campanha):
        campanha.validar()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.caminho) as banco:
            banco.execute("CREATE TABLE IF NOT EXISTS campanha (id INTEGER PRIMARY KEY CHECK(id=1), revisao INTEGER NOT NULL, dados TEXT NOT NULL)")
            if banco.execute("SELECT 1 FROM campanha").fetchone():
                raise ValueError("Já existe uma campanha neste arquivo.")
            banco.execute("INSERT INTO campanha VALUES (1, ?, ?)", (campanha.revisao, json.dumps(asdict(campanha), ensure_ascii=False, allow_nan=False)))

    def carregar(self):
        if not self.caminho.is_file():
            raise FileNotFoundError(f"Campanha não encontrada: {self.caminho}")
        with sqlite3.connect(self.caminho) as banco:
            linha = banco.execute("SELECT revisao,dados FROM campanha WHERE id=1").fetchone()
        if linha is None:
            raise ValueError("Banco sem campanha.")
        dados = json.loads(linha[1])
        dados["regras"] = Regras(**dados["regras"])
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
        with sqlite3.connect(self.caminho) as banco:
            alterado = banco.execute("UPDATE campanha SET revisao=?,dados=? WHERE id=1 AND revisao=?",
                (dados["revisao"], json.dumps(dados, ensure_ascii=False, allow_nan=False), campanha.revisao)).rowcount
            if alterado != 1:
                raise ValueError("Outra sessão atualizou a campanha. Reabra o arquivo antes de continuar.")
        campanha.revisao += 1
