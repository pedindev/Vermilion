"""Repertório local preparado offline; uso limitado a dez meios-lances."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic

import chess
import chess.engine

from .motor import LanceCalculado, abrir_motor, THREADS_PADRAO, HASH_PADRAO


ARQUIVO = Path(__file__).with_name("aberturas.json")
LIMITE = 10
SEMENTES = (
    "", "e2e4", "d2d4", "c2c4", "g1f3",
    "e2e4 e7e5", "e2e4 c7c5", "e2e4 e7e6", "e2e4 c7c6",
)


class Repertorio:
    def __init__(self, entradas=None, origem=None, erro=None):
        self.entradas = entradas or {}
        self.origem = origem or {}
        self.erro = erro

    @classmethod
    def carregar(cls, caminho=ARQUIVO):
        try:
            dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
            if dados["formato"] != 1 or dados["limite_meios_lances"] != LIMITE:
                raise ValueError("Formato ou limite do repertório inválido.")
            origem = dados["origem"]
            if not isinstance(origem, dict) or not isinstance(dados["entradas"], list):
                raise ValueError("Repertório inválido.")
            entradas = {}
            for item in dados["entradas"]:
                historico = tuple(item["historico"].split())
                if len(historico) >= LIMITE or historico in entradas:
                    raise ValueError("Histórico repetido ou além do limite do book.")
                board = chess.Board()
                for uci in historico:
                    if chess.Move.from_uci(uci) not in board.legal_moves:
                        raise ValueError("Histórico ilegal no repertório.")
                    board.push_uci(uci)
                lance = chess.Move.from_uci(item["uci"])
                if board.fen() != item["fen"] or lance not in board.legal_moves:
                    raise ValueError("Posição ou lance preparado inválido.")
                analise = item["analise_previa"]
                if (type(analise["profundidade"]) is not int or analise["profundidade"] < 16
                        or type(analise["nos"]) is not int or analise["nos"] <= 0
                        or type(analise["avaliacao_brancas_cp"]) is not int
                        or not analise["pv"] or analise["pv"][0] != item["uci"]):
                    raise ValueError("Análise prévia incompleta.")
                futura = board.copy()
                for uci in analise["pv"]:
                    if chess.Move.from_uci(uci) not in futura.legal_moves:
                        raise ValueError("PV ilegal no repertório.")
                    futura.push_uci(uci)
                entradas[historico] = item
            return cls(entradas, origem)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as erro:
            # Falha no arquivo nunca impede uma partida: usa-se a busca normal.
            return cls(erro=str(erro))

    def consultar(self, board):
        if (board.chess960 or len(board.move_stack) >= LIMITE
                or board.root().fen() != chess.STARTING_FEN):
            return None
        item = self.entradas.get(tuple(m.uci() for m in board.move_stack))
        if (item is None or item["fen"] != board.fen()
                or chess.Move.from_uci(item["uci"]) not in board.legal_moves):
            return None
        return item

    def decidir(self, board, tempo, contexto=None):
        item = self.consultar(board)
        if item is None:
            return None
        lance = chess.Move.from_uci(item["uci"])
        detalhes = dict(fonte="abertura_preparada", criterio="abertura preparada",
            troca_autoral=False, escolhido=lance.uci(),
            meio_lance=len(board.move_stack) + 1, limite_meios_lances=LIMITE,
            origem_repertorio=self.origem, analise_previa=item["analise_previa"])
        if contexto is not None:
            detalhes["contexto"] = asdict(contexto)
        # Não apresentar a análise offline como trabalho realizado neste turno.
        return LanceCalculado(lance, tempo, {"depth": 0, "nodes": 0, "pv": [lance]},
                              detalhes=detalhes)


def preparar():
    """Executado explicitamente antes do evento, nunca pelo loop da partida."""
    entradas = {}
    with abrir_motor() as motor:
        origem = dict(motor=motor.id.get("name", "Stockfish"),
            preparado_em=datetime.now(timezone.utc).isoformat(),
            threads=THREADS_PADRAO, hash_mb=HASH_PADRAO,
            limite_nos_por_posicao=2_000_000, profundidade_minima=16,
            sementes=list(SEMENTES), metodo="Melhor PV da busca offline em cada posição")
        for semente in SEMENTES:
            board = chess.Board()
            for uci in semente.split():
                board.push_uci(uci)
            while len(board.move_stack) < LIMITE and not board.is_game_over():
                historico = " ".join(m.uci() for m in board.move_stack)
                if historico in entradas:
                    board.push_uci(entradas[historico]["uci"])
                    continue
                motor.configure({"Clear Hash": None})
                inicio = monotonic()
                info = None
                with motor.analysis(board, chess.engine.Limit(nodes=2_000_000),
                                    info=chess.engine.INFO_ALL) as busca:
                    for parcial in busca:
                        if (parcial.get("depth", 0) >= 16 and parcial.get("pv")
                                and "score" in parcial and "nodes" in parcial
                                and parcial["score"].white().score() is not None
                                and not parcial.get("lowerbound") and not parcial.get("upperbound")):
                            info = dict(parcial)
                    busca.wait()
                if info is None:
                    print(f"Posição sem análise suficiente: {historico}", flush=True)
                    break
                cp = info["score"].white().score()
                lance = info["pv"][0]
                entradas[historico] = dict(historico=historico, fen=board.fen(), uci=lance.uci(),
                    analise_previa=dict(profundidade=info["depth"], nos=info["nodes"],
                        avaliacao_brancas_cp=cp, pv=[m.uci() for m in info["pv"]],
                        segundos=round(monotonic() - inicio, 3)))
                print(f"{len(entradas)} posições | {historico or 'inicial'} -> {lance.uci()} "
                      f"| profundidade {info['depth']}", flush=True)
                board.push(lance)
    dados = dict(formato=1, limite_meios_lances=LIMITE, origem=origem,
                 entradas=list(entradas.values()))
    temporario = ARQUIVO.with_suffix(".json.tmp")
    try:
        temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        validado = Repertorio.carregar(temporario)
        if validado.erro or not validado.entradas:
            raise ValueError(validado.erro or "Repertório vazio.")
        temporario.replace(ARQUIVO)
    finally:
        temporario.unlink(missing_ok=True)
    print(f"Repertório salvo: {ARQUIVO} ({len(entradas)} posições).", flush=True)


if __name__ == "__main__":
    preparar()
