"""Antecipação especulativa e seleção autoral de candidatos quase equivalentes.

Um único dono usa o motor por vez. Durante input, um trabalhador pesquisa a
posição prevista; antes de jogar ele é parado e o relógio real é enviado ao SF.
"""

from dataclasses import asdict, dataclass, replace
from threading import Event, Lock, Thread
from time import monotonic
from math import isfinite

import chess
import chess.engine

from .motor import calcular_lance
from .estrategia import final_qualificante, decisao_por_regra, ordenar


MODOS = ("original", "ponderacao", "completo")
VERSAO = "seletor-orientado-a-campanha-v2-experimental"


def encerrada(board):
    return board.is_game_over() or board.is_repetition(3) or board.is_fifty_moves()


def chave(board):
    return board.root().fen(), tuple(m.uci() for m in board.move_stack), board.fen(), board.chess960


def cp_exato(info, cor):
    if (not info.get("pv") or "score" not in info or info.get("lowerbound")
            or info.get("upperbound")):
        return None
    return info["score"].pov(cor).score()  # Mate não vira um número arbitrário.


@dataclass(frozen=True)
class Parametros:
    tolerancia_cp: int = 10
    pressao_min_cp: int = 75
    diferenca_pressao_cp: int = 25
    profundidade_min: int = 12
    verificacao_s: float = 0.3
    nos_raiz: int = 300_000
    nos_defesa: int = 150_000
    tolerancia_buscar_vitoria_cp: int = 20


@dataclass(frozen=True)
class Candidato:
    lance: chess.Move
    avaliacao_cp: int
    pressao_cp: int
    profundidade: int
    defesas: tuple = ()

    def resumo(self):
        return {"uci": self.lance.uci(), "avaliacao_nossa_cp": self.avaliacao_cp,
                "diferenca_defesas_cp": self.pressao_cp, "profundidade": self.profundidade,
                "defesas": list(self.defesas)}


def extrair_candidatos(board, infos, parametros):
    candidatos = []
    for info in infos:
        cp = cp_exato(info, board.turn)
        if cp is None or info.get("depth", 0) < parametros.profundidade_min:
            continue
        lance = info["pv"][0]
        if lance not in board.legal_moves:
            continue
        depois = board.copy(stack=True)
        depois.push(lance)
        if encerrada(depois):
            continue
        candidatos.append((lance, cp, info["depth"]))
    if not candidatos:
        return []
    melhor = max(cp for _, cp, _ in candidatos)
    return [x for x in candidatos if melhor - x[1] <= parametros.tolerancia_cp]


def avaliar_defesas(board, infos, parametros):
    valores = []
    for info in infos:
        cp = cp_exato(info, board.turn)
        if (cp is not None and info.get("depth", 0) >= parametros.profundidade_min
                and info["pv"][0] in board.legal_moves):
            valores.append((cp, info["pv"][0].uci()))
    valores.sort(reverse=True)
    if len(valores) < 2 or valores[0][1] == valores[1][1]:
        return 0, ()
    return max(0, valores[0][0] - valores[1][0]), tuple(x[1] for x in valores[:2])


def escolher_candidato(candidatos, original, parametros):
    if not candidatos:
        return None
    pressao_original = next((c.pressao_cp for c in candidatos if c.lance == original), 0)
    elegiveis = [c for c in candidatos if c.lance != original
                  and c.pressao_cp >= parametros.pressao_min_cp
                  and c.pressao_cp >= pressao_original + parametros.diferenca_pressao_cp]
    return max(elegiveis, key=lambda c: (c.pressao_cp, c.avaliacao_cp), default=None)


@dataclass
class Preparacao:
    chave: tuple | None = None
    previsao: str | None = None
    candidatos: tuple = ()
    segundos: float = 0
    nos: int = 0
    ciclos: int = 0
    erro: str | None = None
    acerto: bool = False


class Antecipacao:
    def __init__(self, motor, modo="completo", parametros=None):
        self.motor, self.modo = motor, modo
        self.parametros = parametros or Parametros()
        self.cancelar, self.trava = Event(), Lock()
        self.thread, self.analise = None, None
        self.preparacao = Preparacao()
        self.inicio = None

    def iniciar(self, depois, previsao):
        self.parar()
        self.preparacao = Preparacao()
        if self.modo == "original" or previsao is None or encerrada(depois):
            return
        if previsao not in depois.legal_moves:
            return
        raiz = depois.copy(stack=True)
        raiz.push(previsao)
        if encerrada(raiz):
            return
        self.preparacao = Preparacao(chave(raiz), previsao.uci())
        self.cancelar.clear()
        self.inicio = monotonic()
        self.thread = Thread(target=self._trabalhar, args=(raiz,), daemon=True,
                             name="chess-antecipacao")
        self.thread.start()

    def _buscar(self, board, limite, multipv):
        if self.cancelar.is_set():
            return []
        ultimos, nos = {}, 0
        with self.motor.analysis(board.copy(stack=True), limite, multipv=multipv,
                                 info=chess.engine.INFO_ALL) as analise:
            with self.trava:
                self.analise = analise
                if self.cancelar.is_set():
                    analise.stop()
            try:
                for info in analise:
                    nos = max(nos, info.get("nodes", 0))
                    if cp_exato(info, board.turn) is not None:
                        ultimos[info.get("multipv", 1)] = dict(info)
                    if self.cancelar.is_set():
                        analise.stop()
                analise.wait()
            finally:
                with self.trava:
                    self.analise = None
                    self.preparacao.nos += nos
        return [ultimos[k] for k in sorted(ultimos)]

    def _trabalhar(self, raiz):
        try:
            if self.modo == "ponderacao":
                self._buscar(raiz, None, 1)
                return
            rodada = 0
            while not self.cancelar.is_set():
                fator = min(2 ** rodada, 8)
                infos = self._buscar(raiz, chess.engine.Limit(nodes=self.parametros.nos_raiz * fator),
                                     min(3, len(list(raiz.legal_moves))))
                if self.cancelar.is_set():
                    break
                candidatos = []
                for lance, cp, depth in extrair_candidatos(raiz, infos, self.parametros):
                    if self.cancelar.is_set():
                        break
                    defesa = raiz.copy(stack=True)
                    defesa.push(lance)
                    if len(list(defesa.legal_moves)) < 2:
                        candidatos.append(Candidato(lance, cp, 0, depth))
                        continue
                    infos_defesa = self._buscar(defesa,
                        chess.engine.Limit(nodes=self.parametros.nos_defesa * fator), 2)
                    pressao, respostas = avaliar_defesas(defesa, infos_defesa, self.parametros)
                    candidatos.append(Candidato(lance, cp, pressao, depth, respostas))
                if self.cancelar.is_set():
                    break
                with self.trava:
                    self.preparacao.candidatos = tuple(candidatos)
                    self.preparacao.ciclos += 1
                rodada += 1
        except (chess.engine.EngineError, OSError, TimeoutError) as erro:
            with self.trava:
                self.preparacao.erro = str(erro) or type(erro).__name__

    def parar(self, board=None):
        self.cancelar.set()
        with self.trava:
            if self.analise is not None:
                self.analise.stop()
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                self.motor.close()
                self.thread.join(timeout=2)
                raise chess.engine.EngineError("Antecipação não respondeu à parada; motor encerrado.")
            self.thread = None
            self.preparacao.segundos = monotonic() - self.inicio
        with self.trava:
            preparo = replace(self.preparacao)
        preparo.acerto = board is not None and preparo.chave == chave(board)
        if not preparo.acerto:
            preparo.candidatos = ()
        return preparo


class Jogador:
    def __init__(self, motor, modo="completo", parametros=None, contexto=None, repertorio=None):
        if modo not in MODOS:
            raise ValueError(f"Modo inválido: {modo}")
        self.motor, self.modo = motor, modo
        self.parametros = parametros or Parametros()
        self.antecipacao = Antecipacao(motor, modo, self.parametros)
        self.contexto = contexto
        self.repertorio = repertorio if modo == "completo" else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.antecipacao.parar()

    def preparar(self, board, decisao):
        previsao = decisao.previsao
        if previsao is None and len(decisao.info.get("pv", [])) > 1:
            previsao = decisao.info["pv"][1]
        self.antecipacao.iniciar(board, previsao)

    def calcular(self, board, restante, incremento=10, adversario=None, agora=monotonic):
        if not isfinite(restante) or restante <= 0 or not isfinite(incremento) or incremento < 0:
            raise ValueError("Informe saldo positivo e incremento não negativo.")
        if adversario is not None and (not isfinite(adversario) or adversario < 0):
            raise ValueError("Saldo adversário inválido.")
        inicio = agora()
        preparado = self.antecipacao.parar(board)
        saldo = restante - (agora() - inicio)
        if saldo <= 0:
            raise ValueError("Tempo esgotado antes da escolha do lance.")
        contexto = self.contexto.com_relogios(saldo, adversario) if self.contexto is not None else None
        if contexto is not None and self.modo == "completo":
            lance, motivo = final_qualificante(board, contexto)
            if lance is not None:
                return decisao_por_regra(lance, motivo, contexto, agora() - inicio, board.turn)
        if self.repertorio is not None:
            abertura = self.repertorio.decidir(board, agora() - inicio, contexto)
            if abertura is not None:
                return replace(abertura, tempo=agora() - inicio)
            # Ao sair da preparação, permanece na análise normal até o fim.
            self.repertorio = None
        base = calcular_lance(self.motor, board, saldo, incremento, adversario=adversario)
        detalhes = {"versao": VERSAO, "modo": self.modo, "original": base.lance.uci(),
                    "antecipacao": "acertou" if preparado.acerto else "errou" if preparado.previsao else "sem previsão",
                    "previsao": preparado.previsao, "segundos_antecipados": round(preparado.segundos, 3),
                    "nos_antecipados": preparado.nos, "ciclos": preparado.ciclos,
                    "candidatos": [c.resumo() for c in preparado.candidatos],
                    "criterio": "preferência original do Stockfish"}
        if preparado.erro:
            detalhes["erro_antecipacao"] = preparado.erro
        if self.contexto is not None:
            return self._campanha(board, base, preparado, detalhes, restante, inicio, agora, contexto)
        escolhido, info, previsao = base.lance, base.info, base.previsao
        candidato = escolher_candidato(preparado.candidatos, base.lance, self.parametros)
        score_base = base.info.get("score")
        mate = score_base is not None and score_base.pov(board.turn).mate() is not None
        disponivel = restante - (agora() - inicio)
        if self.modo == "completo" and candidato is not None and not mate and disponivel > 5:
            if candidato.lance in board.legal_moves:
                confirmacao = self.motor.analyse(board.copy(stack=True),
                    chess.engine.Limit(time=min(self.parametros.verificacao_s, disponivel * .02)),
                    multipv=2, root_moves=[base.lance, candidato.lance], info=chess.engine.INFO_ALL)
                por_lance = {i["pv"][0]: i for i in confirmacao
                             if cp_exato(i, board.turn) is not None
                             and i.get("depth", 0) >= self.parametros.profundidade_min}
                if base.lance in por_lance and candidato.lance in por_lance:
                    valor_base = cp_exato(por_lance[base.lance], board.turn)
                    valor_candidato = cp_exato(por_lance[candidato.lance], board.turn)
                    detalhes["verificacao"] = {"original_cp": valor_base, "candidato_cp": valor_candidato,
                        "tolerancia_cp": self.parametros.tolerancia_cp,
                        "profundidade_original": por_lance[base.lance]["depth"],
                        "profundidade_candidato": por_lance[candidato.lance]["depth"]}
                    if valor_candidato >= valor_base - self.parametros.tolerancia_cp:
                        escolhido, info = candidato.lance, por_lance[candidato.lance]
                        pv = info.get("pv", [])
                        previsao = pv[1] if len(pv) > 1 else None
                        detalhes["criterio"] = "alternativa próxima com maior diferença entre defesas"
                    else:
                        detalhes["criterio"] = "candidato rejeitado na verificação"
                else:
                    detalhes["criterio"] = "verificação insuficiente; preferência original"
        detalhes["escolhido"] = escolhido.uci()
        detalhes["troca_autoral"] = escolhido != base.lance
        return replace(base, lance=escolhido, tempo=agora() - inicio, info=info,
                       previsao=previsao, detalhes=detalhes)

    def _campanha(self, board, base, preparado, detalhes, restante, inicio, agora, contexto):
        detalhes["contexto"] = asdict(contexto)
        detalhes["busca_principal"] = dict(uci=base.lance.uci(), profundidade=base.info.get("depth"),
            nos=base.info.get("nodes"), pv=[m.uci() for m in base.info.get("pv", [])],
            avaliacao=str(base.info.get("score")), segundos=base.tempo)
        escolhido, selecionada = base.lance, base.info
        cp = cp_exato(base.info, board.turn)
        disponivel = restante - (agora() - inicio)
        if self.modo == "completo" and contexto.objetivo != "equilibrado" and cp is not None and disponivel > 5:
            tolerancia = (self.parametros.tolerancia_buscar_vitoria_cp
                          if contexto.objetivo == "buscar_vitoria" and cp < 150
                          else self.parametros.tolerancia_cp)
            candidatos = [c.lance for c in preparado.candidatos if c.lance in board.legal_moves]
            limite_s = min(self.parametros.verificacao_s, disponivel * .01)
            if not candidatos:
                sondagem = self.motor.analyse(board.copy(stack=True), chess.engine.Limit(time=limite_s),
                    multipv=min(3, board.legal_moves.count()), info=chess.engine.INFO_ALL)
                candidatos = [i["pv"][0] for i in sondagem if cp_exato(i, board.turn) is not None
                              and i.get("depth", 0) >= self.parametros.profundidade_min
                              and i["pv"][0] in board.legal_moves]
            raizes = list(dict.fromkeys([base.lance, *candidatos]))[:4]
            if len(raizes) > 1:
                confirmacao = self.motor.analyse(board.copy(stack=True),
                    chess.engine.Limit(time=min(limite_s, max(0.001, (restante - (agora() - inicio)) * .01))),
                    multipv=len(raizes), root_moves=raizes, info=chess.engine.INFO_ALL)
                por_lance = {i["pv"][0]: i for i in confirmacao if cp_exato(i, board.turn) is not None
                             and i.get("depth", 0) >= self.parametros.profundidade_min
                             and i["pv"][0] in raizes}
                if base.lance in por_lance:
                    base_cp = cp_exato(por_lance[base.lance], board.turn)
                    # Verificação curta não pode rebaixar muito a avaliação da busca principal.
                    referencia = max(base_cp, cp)
                    alternativas = [(l, cp_exato(i, board.turn)) for l, i in por_lance.items()
                                    if cp_exato(i, board.turn) >= referencia - tolerancia]
                    detalhes["verificacao_campanha"] = dict(tolerancia_cp=tolerancia,
                        referencia_cp=referencia, candidatos={l.uci(): dict(cp=cp_exato(i, board.turn),
                        profundidade=i.get("depth"), nos=i.get("nodes")) for l, i in por_lance.items()})
                    if alternativas:
                        escolhido, diagnostico = ordenar(board, alternativas, base.lance, contexto, cp)
                        detalhes["selecao_campanha"] = diagnostico
                        if escolhido != base.lance:
                            selecionada = por_lance[escolhido]
                            detalhes["criterio"] = f"Campanha: {contexto.objetivo}; alternativa verificada"
                else:
                    detalhes["criterio"] = "Campanha: verificação insuficiente; preferência original"
        pv = selecionada.get("pv", [])
        previsao = pv[1] if len(pv) > 1 else (base.previsao if escolhido == base.lance else None)
        detalhes.update(escolhido=escolhido.uci(), troca_autoral=escolhido != base.lance)
        return replace(base, lance=escolhido, info=selecionada, previsao=previsao,
                       tempo=agora() - inicio, detalhes=detalhes)
