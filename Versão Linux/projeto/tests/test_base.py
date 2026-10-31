from contextlib import contextmanager
from types import SimpleNamespace

import chess
import chess.engine
import pytest

from chess_challenge import partida as entrada_lances
from chess_challenge import motor as motor_stockfish
from chess_challenge.partida import executar, ler_entrada, motivo_encerramento
from chess_challenge.motor import abrir_motor, calcular_lance
from chess_challenge.relatorios import registrar_lance, salvar_relatorio


def entrada_programada(valores):
    valores = iter(valores)

    def ler(_):
        try:
            valor = next(valores)
        except StopIteration:
            raise EOFError from None
        if isinstance(valor, BaseException):
            raise valor
        return valor
    return ler


class MotorSimulado:
    id = {"name": "Stockfish simulado"}

    def __init__(self, lances):
        self.lances = iter(lances)
        self.consultas = []
        self.fechado = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.fechado = True

    def play(self, board, limit, *, ponder, info):
        assert ponder is False
        assert limit.time is None and limit.depth is None and limit.nodes is None
        assert info == chess.engine.INFO_ALL
        self.consultas.append((board.copy(stack=True), limit))
        uci = next(self.lances)
        if isinstance(uci, BaseException):
            raise uci
        move = chess.Move.from_uci(uci)
        return chess.engine.PlayResult(move, None, {
            "pv": [move], "score": chess.engine.PovScore(chess.engine.Cp(20), board.turn),
            "depth": 20, "nodes": 10000})


@pytest.mark.parametrize("brancas", [True, False])
def test_envia_relogio_e_incremento_ao_motor_sem_movetime(brancas):
    board = chess.Board()
    if not brancas:
        board.push_uci("e2e4")
    motor = MotorSimulado(["e2e4" if brancas else "e7e5"])
    tempos = iter([100, 102])
    d = calcular_lance(motor, board, 890, 10, agora=lambda: next(tempos))
    enviado, limite = motor.consultas[0]
    assert limite.time is None and d.tempo == 2
    assert enviado.move_stack == board.move_stack and enviado is not board
    assert (limite.white_clock, limite.black_clock) == ((890, None) if brancas else (None, 890))
    assert (limite.white_inc, limite.black_inc) == ((10, None) if brancas else (None, 10))


@pytest.mark.parametrize("texto", ["e2e5", "e7e5", "e4", "e2e4 14:60", "e2e4 14:50", "0000"])
def test_entrada_invalida_nao_altera_tabuleiro(texto):
    board = chess.Board()
    with pytest.raises(ValueError):
        ler_entrada(texto, board)
    assert board.fen() == chess.STARTING_FEN and not board.move_stack


def test_entrada_valida_aceita_apenas_uci_sem_aplicar_antes_da_validacao():
    board = chess.Board()
    lance = ler_entrada(" E2E4 ", board)
    assert lance.uci() == "e2e4" and not board.move_stack


def test_partida_automatica_da_equipe_relogio_e_tabuleiro_apos_cada_lance(tmp_path):
    motor = MotorSimulado(["e2e4", "g1f3"])
    saidas = []
    board = executar(entrada_programada(["1", "e7e5"]), saidas.append,
                      conectar=lambda: motor, pasta_relatorios=tmp_path, agora=lambda: 0)
    assert [m.uci() for m in board.move_stack] == ["e2e4", "e7e5", "g1f3"]
    assert motor.consultas[0][1].white_clock == pytest.approx(900, abs=.02)
    assert motor.consultas[0][1].white_inc == 10
    assert motor.consultas[1][1].white_clock == pytest.approx(910, abs=.02)
    assert motor.consultas[1][1].black_clock == 910
    assert sum("a b c d e f g h" in s for s in saidas) == 3
    assert motor.fechado and not list(tmp_path.iterdir())


@pytest.mark.parametrize("cor", ["1", "2"])
def test_mate_salva_log_so_apos_consentimento_e_nome(tmp_path, cor):
    motor = MotorSimulado(["f2f3", "g2g4"] if cor == "1" else ["e7e5", "d8h4"])
    valores = [cor] + (["e7e5", "d8h4"] if cor == "1" else ["f2f3", "g2g4"]) + ["s", "Final"]
    ler = entrada_programada(valores)

    def entrada(prompt):
        assert not list(tmp_path.iterdir())
        if "salvar" in prompt or "Nome da partida" in prompt:
            assert motor.fechado
        return ler(prompt)

    board = executar(entrada, lambda _: None, conectar=lambda: motor, pasta_relatorios=tmp_path)
    texto = (tmp_path / "Final.txt").read_text(encoding="utf-8")
    assert board.is_checkmate()
    for campo in ["Xeque-mate", "Brancas", "Pretas", "profundidade 20", "nós 10000", "PV", "tempo", "N/D"]:
        assert campo in texto


@pytest.mark.parametrize("resposta", ["n", "", EOFError()])
def test_recusa_nao_cria_relatorio(tmp_path, resposta):
    motor = MotorSimulado(["e7e5", "d8h4"])
    executar(entrada_programada(["2", "f2f3", "g2g4", resposta]),
             lambda _: None, conectar=lambda: motor, pasta_relatorios=tmp_path)
    assert not list(tmp_path.iterdir())


def test_ctrl_c_permite_salvar_partida_incompleta(tmp_path):
    motor = MotorSimulado(["e2e4"])
    executar(entrada_programada(["1", KeyboardInterrupt(), "s", "Parcial"]),
             lambda _: None, conectar=lambda: motor, pasta_relatorios=tmp_path)
    assert motor.fechado
    texto = (tmp_path / "Parcial.txt").read_text(encoding="utf-8")
    assert "Partida interrompida" in texto and "e2e4" in texto


def test_erro_motor_permite_salvar_lances_anteriores(tmp_path):
    motor = MotorSimulado(["e2e4", chess.engine.EngineTerminatedError("encerrado")])
    with pytest.raises(chess.engine.EngineTerminatedError):
        executar(entrada_programada(["1", "e7e5", "s", "Falha"]), lambda _: None,
                 conectar=lambda: motor, pasta_relatorios=tmp_path)
    assert "e7e5" in (tmp_path / "Falha.txt").read_text(encoding="utf-8")


def test_repete_tres_vezes_e_encerra_no_lance_correto():
    board = chess.Board()
    for uci in ["g1f3", "g8f6", "f3g1", "f6g8"] * 2:
        board.push_uci(uci)
    assert motivo_encerramento(board) == "Empate por tripla repetição."


@pytest.mark.parametrize("fen,motivo", [
    ("7k/8/8/8/8/8/8/K7 w - - 0 1", "material insuficiente"),
    ("7k/5Q2/5K2/8/8/8/8/8 b - - 0 1", "afogamento"),
    ("7k/8/8/8/8/8/8/KR6 w - - 100 60", "50 lances"),
])
def test_encerramentos_previstos_nas_regras(fen, motivo):
    assert motivo in motivo_encerramento(chess.Board(fen))


def test_dados_de_busca_nao_sao_atribuidos_a_outro_lance():
    board = chess.Board()
    move = chess.Move.from_uci("e2e4")
    d = SimpleNamespace(tempo=1, info={"pv": [chess.Move.from_uci("d2d4")],
        "score": chess.engine.PovScore(chess.engine.Cp(50), chess.WHITE), "depth": 20, "nodes": 100})
    r = registrar_lance(board, move, True, d)
    assert r.avaliacao is None and r.pv is None and r.profundidade is None


def test_avaliacao_de_pretas_normalizada_para_brancas():
    board = chess.Board()
    board.push_uci("e2e4")
    d = calcular_lance(MotorSimulado(["e7e5"]), board, 900)
    r = registrar_lance(board, d.lance, False, d)
    assert r.avaliacao == "-0.20"


def test_nomes_repetidos_nao_sobrescrevem_e_nome_invalido_nao_cria_pasta(tmp_path):
    pasta = tmp_path / "logs"
    with pytest.raises(ValueError):
        salvar_relatorio("../fora", [], "teste", True, 10, "Stockfish", pasta)
    assert not pasta.exists()
    primeiro = salvar_relatorio("Final", [], "primeiro", True, 10, "Stockfish", pasta)
    segundo = salvar_relatorio("Final", [], "segundo", True, 10, "Stockfish", pasta)
    assert primeiro != segundo and "primeiro" in primeiro.read_text(encoding="utf-8")


def test_motor_ilegal_nao_e_aplicado():
    with pytest.raises(chess.engine.EngineError):
        calcular_lance(MotorSimulado(["e2e5"]), chess.Board(), 900)


@pytest.mark.parametrize("args", [["--politica", "adaptativa"], ["--tempo", "nan"], ["--incremento", "-1"], ["--threads", "0"]])
def test_cli_rejeita_opcoes_removidas_e_valores_invalidos(args):
    with pytest.raises(SystemExit):
        entrada_lances.main(args)


def test_configuracao_local_sem_recursos_experimentais(tmp_path, monkeypatch):
    exe = tmp_path / "stockfish.exe"
    exe.touch()
    recebido = {}

    class Motor:
        def configure(self, config):
            recebido.update(config)

        def ping(self):
            pass

    @contextmanager
    def iniciar(caminho, timeout):
        assert caminho == str(exe.resolve()) and timeout == 30
        yield Motor()

    monkeypatch.setattr(motor_stockfish.chess.engine.SimpleEngine, "popen_uci", iniciar)
    with abrir_motor(exe):
        pass
    assert recebido == {"Threads": 4, "Hash": 512, "SyzygyPath": "", "SyzygyProbeLimit": 5}


@pytest.mark.motor_real
@pytest.mark.parametrize("brancas", [True, False])
def test_stockfish_real_com_gestao_original(brancas):
    board = chess.Board()
    if not brancas:
        board.push_uci("e2e4")
    historico = list(board.move_stack)
    with abrir_motor() as motor:
        d = calcular_lance(motor, board, 20, 0.2)
    assert d.lance in board.legal_moves and 0 < d.tempo < 20
    assert d.info.get("nodes", 0) > 0
    assert board.move_stack == historico
