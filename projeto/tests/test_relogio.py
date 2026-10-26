import chess
import pytest

from chess_challenge.relogio import RelogioPartida, TempoEsgotado, entrada_com_prazo
from chess_challenge.partida import executar
from test_base import MotorSimulado


def test_dois_contadores_trocam_turno_aplicam_incremento_sem_cobrar_duas_vezes():
    tempo = [0]
    r = RelogioPartida(900, 900, 10, lambda: tempo[0])
    r.iniciar()
    tempo[0] = 5
    assert r.saldos() == {True: 895, False: 900}
    assert r.saldos() == {True: 895, False: 900}
    assert r.confirmar_lance(True) == 5
    tempo[0] = 8
    assert r.saldos() == {True: 905, False: 897}
    assert r.confirmar_lance(False) == 3
    assert r.parar() == {True: 905, False: 907}
    tempo[0] = 1000
    assert r.saldos() == {True: 905, False: 907}


def test_armageddon_relogios_assimetricos_sem_incremento():
    tempo = [0]
    r = RelogioPartida(300, 240, 0, lambda: tempo[0])
    r.iniciar()
    tempo[0] = 10
    r.confirmar_lance(True)
    tempo[0] = 20
    r.confirmar_lance(False)
    assert r.parar() == {True: 290, False: 230}


def test_incremento_nao_resgata_tempo_esgotado():
    tempo = [0]
    r = RelogioPartida(10, 10, 100, lambda: tempo[0])
    r.iniciar()
    tempo[0] = 10
    with pytest.raises(TempoEsgotado):
        r.confirmar_lance(True)
    assert r.saldos() == {True: 0, False: 10} and r.ativo is None


@pytest.mark.parametrize("valores", [(0, 10, 1), (10, -1, 0), (10, 10, -1), (float("nan"), 10, 1)])
def test_relogios_invalidos_rejeitados(valores):
    with pytest.raises(ValueError):
        RelogioPartida(*valores)


@pytest.mark.parametrize("cor", [True, False])
def test_partida_so_uci_mede_os_dois_lados_e_para_antes_do_txt(tmp_path, cor):
    tempo, finais = [0], []

    class Motor(MotorSimulado):
        def play(self, board, *args, **kwargs):
            tempo[0] += (2 if len(board.move_stack) == 0 else 3) if board.turn else (3 if len(board.move_stack) == 1 else 4)
            return super().play(board, *args, **kwargs)

        def __exit__(self, *args):
            tempo[0] += 100  # Fechar o motor não pode consumir o relógio da partida terminada.
            super().__exit__(*args)

    motor = Motor(["f2f3", "g2g4"] if cor else ["e7e5", "d8h4"])
    outras = iter([("e7e5", 3), ("d8h4", 4)] if cor else [("f2f3", 2), ("g2g4", 3)])

    def entrada(prompt):
        if "salvar" in prompt:
            tempo[0] += 100
            return "n"
        assert "tempo" not in prompt.lower()
        lance, gasto = next(outras)
        tempo[0] += gasto
        return lance

    def acompanhar(evento, board, registros, saldos, resultado):
        if evento == "fim":
            finais.append((saldos, registros))

    board = executar(entrada, lambda _: None, conectar=lambda: motor, cor_inicial=cor,
                     acompanhamento=acompanhar, tempo=10, incremento=1, agora=lambda: tempo[0],
                     pasta_relatorios=tmp_path, modo="original")
    assert board.is_checkmate()
    assert finais[0][0] == {True: 7, False: 5}
    assert [r.tempo for r in finais[0][1]] == [2, 3, 3, 4]
    assert all(r.fonte_tempo == "relogio_do_sistema" for r in finais[0][1])


def test_entrada_ilegal_nao_reinicia_relogio_adversario(tmp_path):
    tempo = [0]
    entradas = iter([("e2e5", 3), ("f2f3", 4), (EOFError(), 0)])
    motor = MotorSimulado(["e7e5"])

    def entrada(prompt):
        valor, gasto = next(entradas)
        tempo[0] += gasto
        if isinstance(valor, Exception):
            raise valor
        return valor

    board = executar(entrada, lambda _: None, conectar=lambda: motor, cor_inicial=False,
                     tempo=10, incremento=1, agora=lambda: tempo[0], modo="original", pasta_relatorios=tmp_path)
    assert [m.uci() for m in board.move_stack] == ["f2f3", "e7e5"]
    assert motor.consultas[0][1].white_clock == 4


@pytest.mark.parametrize("nossa_cor", [True, False])
def test_lance_recebido_apos_zero_nao_e_aplicado_nem_recebe_incremento(tmp_path, nossa_cor):
    tempo, salvos = [0], []

    class Motor(MotorSimulado):
        def play(self, *args, **kwargs):
            tempo[0] += 11
            return super().play(*args, **kwargs)

    motor = Motor(["e2e4"])

    def entrada(prompt):
        tempo[0] += 11
        return "e2e4"

    # Brancas sempre iniciam. Expira nosso cálculo ou a espera pelo adversário.
    board = executar(entrada, lambda _: None, conectar=lambda: motor,
                     cor_inicial=nossa_cor, tempo=10, incremento=100,
                     agora=lambda: tempo[0], modo="original", pasta_relatorios=tmp_path,
                     acompanhamento=lambda e, b, r, s, x: salvos.append(s) if e == "fim" else None)
    assert board.move_stack == []
    assert salvos[-1] == {True: 0, False: 10}


def test_prazo_zero_nao_espera_entrada():
    with pytest.raises(TimeoutError):
        entrada_com_prazo(lambda _: pytest.fail("Não deveria ler"), "UCI: ", 0)


@pytest.mark.motor_real
def test_partida_real_entrada_so_uci_e_contadores_automaticos(tmp_path):
    from chess_challenge.campanha import Contexto
    from test_base import entrada_programada

    salvos, prompts = [], []
    ler = entrada_programada(["e2e4", EOFError()])

    def entrada(prompt):
        prompts.append(prompt)
        return ler(prompt)

    board = executar(entrada, lambda _: None, cor_inicial=False, tempo=20, incremento=.2,
                     contexto=Contexto(), pasta_relatorios=tmp_path,
                     acompanhamento=lambda e, b, r, s, x: salvos.append((r, s)) if e == "fim" else None)
    assert len(board.move_stack) == 2 and board.is_valid()
    assert all("tempo" not in p.lower() for p in prompts)
    registros, saldos = salvos[-1]
    assert registros[1].profundidade > 0 and registros[1].nos > 0
    assert all(r.tempo >= 0 and r.fonte_tempo == "relogio_do_sistema" for r in registros)
    assert all(0 < saldo <= 20.2 for saldo in saldos.values())
