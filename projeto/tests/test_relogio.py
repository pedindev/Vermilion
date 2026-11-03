import chess
import pytest

from chess_challenge.relogio import (RelogioPartida, TempoEsgotado, entrada_com_prazo,
                                    JanelaPartida, DuracaoEsgotada)
from chess_challenge.partida import executar
from test_base import MotorSimulado


def test_duracao_total_conta_os_dois_turnos_sem_receber_incremento_ou_ajuste():
    agora = [0]
    janela = JanelaPartida(1, lambda: agora[0])
    relogio = RelogioPartida(900, 900, 10, lambda: agora[0])
    janela.iniciar()
    relogio.iniciar()
    agora[0] = 20
    relogio.confirmar_lance(True)
    agora[0] = 35
    relogio.ajustar(900, 900)
    assert janela.restante() == 25 and relogio.saldos() == {True: 900, False: 900}
    with pytest.raises(ValueError, match="já está"):
        janela.iniciar()
    agora[0] = 60
    with pytest.raises(DuracaoEsgotada):
        janela.verificar()
    assert min(relogio.saldos().values()) > 0


@pytest.mark.parametrize("minutos", [0, -1, True, "25", float("nan"), float("inf"), 1e308])
def test_duracao_total_invalida_e_rejeitada(minutos):
    with pytest.raises(ValueError):
        JanelaPartida(minutos)


@pytest.mark.parametrize("nossa_cor", [True, False])
def test_janela_termina_durante_calculo_ou_entrada_sem_aplicar_lance_tardio(tmp_path, nossa_cor):
    agora, finais, saidas = [0], [], []

    class Motor(MotorSimulado):
        def play(self, *args, **kwargs):
            agora[0] += 7
            return super().play(*args, **kwargs)

    def entrada(prompt):
        agora[0] += 7
        return "e2e4"

    board = executar(entrada, saidas.append, conectar=lambda: Motor(["e2e4"]),
        cor_inicial=nossa_cor, modo="original", tempo=900, incremento=10,
        duracao_total_minutos=.1, agora=lambda: agora[0], exportar_relatorio=False,
        acompanhamento=lambda e,b,r,s,x: finais.append((s,x)) if e == "fim" else None)
    assert not board.move_stack
    assert finais[-1][0] == {True: 893, False: 900}
    assert "Duração total informada atingida" in finais[-1][1]
    assert "Resultado oficial pendente" in finais[-1][1]
    assert "Vitória" not in finais[-1][1] and "Empate" not in finais[-1][1]


def test_prazo_de_entrada_e_limitado_pela_duracao_da_partida(tmp_path, monkeypatch):
    import chess_challenge.partida as partida
    prazos = []

    def entrada_com_prazo(entrada, prompt, prazo):
        prazos.append(prazo)
        raise EOFError()

    monkeypatch.setattr(partida, "entrada_com_prazo", entrada_com_prazo)
    executar(lambda _: "", lambda _: None, conectar=lambda: MotorSimulado([]),
        cor_inicial=False, modo="original", tempo=900, duracao_total_minutos=2,
        agora=lambda: 0, exportar_relatorio=False)
    assert prazos == [120]


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


def test_ajuste_fisico_preserva_turno_gasto_e_incremento_sem_cobrar_duas_vezes():
    from chess_challenge.relogio import formatar_relogios, ler_tempo
    agora = [0]
    r = RelogioPartida(900, 900, 10, lambda: agora[0])
    r.iniciar()
    agora[0] = 5
    r.ajustar(ler_tempo("14:40.125"), ler_tempo("15:00"))
    assert r.ativo is True and r.saldos() == {True: 880.125, False: 900}
    assert "14:40.125" in formatar_relogios(r.saldos())
    agora[0] = 8
    assert r.confirmar_lance(True) == 8
    assert r.saldos() == {True: 887.125, False: 900}
    assert r.fonte == "sistema_com_ajuste_fisico"


def test_comando_de_ajuste_so_muda_relogios_e_repassa_saldo_ao_motor(tmp_path):
    from test_base import entrada_programada
    motor = MotorSimulado(["e7e5"])
    eventos, finais = [], []
    def acompanhar(evento, board, registros, saldos, resultado):
        eventos.append((evento, len(board.move_stack), saldos))
        if evento == "fim":
            finais.extend(registros)
    board = executar(entrada_programada(["relogios 14:20.125 13:40.250", "e2e4", EOFError()]),
        lambda _: None, conectar=lambda: motor, cor_inicial=False, modo="original", agora=lambda: 0,
        acompanhamento=acompanhar, pasta_relatorios=tmp_path)
    assert [m.uci() for m in board.move_stack] == ["e2e4", "e7e5"]
    assert eventos[0] == ("relogio_fisico", 0, {True: 860.125, False: 820.250})
    limite = motor.consultas[0][1]
    assert (limite.white_clock, limite.black_clock, limite.black_inc) == pytest.approx((870.125, 820.250, 10), abs=.02)
    assert all(r.fonte_tempo == "sistema_com_ajuste_fisico" for r in finais)


@pytest.mark.motor_real
def test_partida_real_com_duracao_total_e_relogios_independentes(tmp_path):
    import json
    from test_base import entrada_programada
    finais = []
    board = executar(entrada_programada(["e2e4", EOFError()]), lambda _: None,
        cor_inicial=False, tempo=900, incremento=10, modo="completo",
        duracao_total_minutos=.1, exportar_relatorio=False,
        acompanhamento=lambda e,b,r,s,x: finais.append((r,s)) if e == "fim" else None)
    assert len(board.move_stack) == 2 and board.is_valid()
    registros, saldos = finais[-1]
    assert registros[1].profundidade > 0 and registros[1].nos > 0
    detalhes = json.loads(registros[1].detalhes)
    assert 0 < detalhes["planejamento_tempo"]["janela_restante_s"] <= 6
    assert detalhes["duracao_partida"]["total_s"] == 6
    assert all(890 < saldo <= 910 for saldo in saldos.values())


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
