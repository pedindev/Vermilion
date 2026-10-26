from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import chess
import chess.engine
import pytest

import testar_campeonato as campeonato
from chess_challenge.motor import LanceCalculado
from test_base import entrada_programada


class Cenario:
    def __init__(self, lances, duracoes):
        self.lances, self.duracoes = iter(lances), iter(duracoes)
        self.tempo = 0
        self.chamadas, self.preparacoes = [], []

    def calcular(self, board, saldo, incremento, adversario=None):
        self.chamadas.append((board.copy(stack=True), saldo, incremento, adversario))
        self.tempo += next(self.duracoes)
        valor = next(self.lances)
        if isinstance(valor, BaseException):
            raise valor
        return LanceCalculado(chess.Move.from_uci(valor), 1, {}, detalhes={})

    def preparar(self, board, decisao):
        self.preparacoes.append(board.copy(stack=True))

    def disputar(self, cor=True, tempo=10, incremento=1, max_lances=20, latencia=0):
        return campeonato.disputar(self, self, cor, tempo, incremento, max_lances,
            saida=lambda _: None, agora=lambda: self.tempo, latencia=latencia,
            dormir=lambda s: setattr(self, "tempo", self.tempo + s))


@pytest.mark.parametrize("cor", [True, False])
def test_relogios_incremento_historico_e_mate(cor):
    c = Cenario(["f2f3", "e7e5", "g2g4", "d8h4"], [2, 1, 3, 2])
    r = c.disputar(cor)
    assert r.placar == "0-1" and r.meios_lances == 4
    assert r.relogios == {True: 7, False: 9}
    assert len(c.chamadas[-1][0].move_stack) == 3
    assert len(c.preparacoes) == 3
    assert all(incremento == 1 for _, _, incremento, _ in c.chamadas)


def test_latencia_e_cobrada_no_relogio_antes_do_incremento():
    c = Cenario(["e2e4"], [9])
    r = c.disputar(incremento=100, latencia=2)
    assert r.placar == "0-1" and r.meios_lances == 0
    assert r.relogios[True] == -1


def test_arranque_da_antecipacao_tambem_e_cobrado():
    c = Cenario(["e2e4"], [9])

    def preparar(*args):
        c.tempo += 2

    c.preparar = preparar
    r = c.disputar(incremento=100)
    assert r.placar == "0-1" and r.meios_lances == 0


def test_falha_nao_e_inventada_como_derrota_por_tempo():
    r = Cenario([chess.engine.EngineError("falha")], [1]).disputar()
    assert r.placar == "*" and "Falha" in r.motivo


def test_limite_nao_e_contado_como_empate():
    r = Cenario(["e2e4", "e7e5"], [1, 1]).disputar(max_lances=1)
    assert r.placar == "*" and r.meios_lances == 2


def test_tripla_repeticao_tem_historico_completo():
    r = Cenario(["g1f3", "g8f6", "f3g1", "f6g8"] * 2, [.1] * 8).disputar()
    assert r.placar == "1/2-1/2" and r.meios_lances == 8


@pytest.mark.parametrize("resposta", ["n", "", EOFError()])
def test_log_sem_autorizacao_nao_cria_pasta(tmp_path, resposta):
    pasta = tmp_path / "logs"
    campeonato.oferecer_log(["conteúdo"], entrada_programada([resposta]), lambda _: None, pasta)
    assert not pasta.exists()


def test_nome_do_log_e_obrigatorio_e_nao_sobrescreve(tmp_path):
    for conteudo in ("primeiro", "segundo"):
        campeonato.oferecer_log([conteudo], entrada_programada(["s", "Teste"]), lambda _: None, tmp_path)
    assert (tmp_path / "Teste.txt").read_text(encoding="utf-8") == "primeiro\n"
    assert (tmp_path / "Teste (2).txt").read_text(encoding="utf-8") == "segundo\n"


def test_pares_cores_aberturas_e_configuracao_iguais(tmp_path, monkeypatch):
    motores, partidas, afinidades = [], [], []

    @contextmanager
    def conectar(caminho, threads, hash_mb):
        m = SimpleNamespace(id={"name": "simulado"})
        motores.append((m, caminho, threads, hash_mb))
        yield m

    def disputar(nosso, outro, cor, tempo, incremento, max_lances, board, *args, **kwargs):
        partidas.append((cor, tempo, incremento, board.fen(), list(board.move_stack)))
        return campeonato.Resultado(cor, "1/2-1/2", "teste", 8, {True: 20, False: 10})

    monkeypatch.setattr(campeonato, "disputar", disputar)
    monkeypatch.setattr(campeonato, "grupos_cpu", lambda: (0xF, 0xF0))
    monkeypatch.setattr(campeonato, "fixar_cpu", lambda m, mask: afinidades.append(mask))
    pasta = tmp_path / "logs"
    assert campeonato.main(["--formato", "pares", "--pares", "2"], entrada=entrada_programada(["n"]), emitir=lambda _: None,
                           conectar=conectar, pasta_logs=pasta) == 0
    assert len(motores) == 8 and all(m[2:] == (4, 512) for m in motores)
    for i in (0, 2):
        assert partidas[i][0] is True and partidas[i+1][0] is False
        assert partidas[i][3:] == partidas[i+1][3:]
    assert partidas[0][3] != partidas[2][3]
    assert all(p[1:3] == (300, 1) for p in partidas)
    assert afinidades == [0xF, 0xF0, 0xF0, 0xF] * 2
    assert not pasta.exists()


def test_log_parcial_apos_interrupcao_nao_contabiliza_partida(tmp_path, monkeypatch):
    @contextmanager
    def conectar(*args):
        yield SimpleNamespace(id={"name": "simulado"})

    def interromper(*args, **kwargs):
        args[8]("1. Nosso programa | Brancas | e2e4")
        raise KeyboardInterrupt

    monkeypatch.setattr(campeonato, "grupos_cpu", lambda: None)
    monkeypatch.setattr(campeonato, "disputar", interromper)
    campeonato.main(["--formato", "pares"], entrada=entrada_programada(["s", "Parcial"]), emitir=lambda _: None,
                     conectar=conectar, pasta_logs=tmp_path)
    texto = (tmp_path / "Parcial.txt").read_text(encoding="utf-8")
    assert "não foi contabilizada" in texto and "0 vitória(s)" in texto
    assert "e2e4" in texto and "300s + 1s" in texto
    assert "SHA256" in texto and "Parâmetros do seletor" in texto


def test_aberturas_sao_legais_e_respeitam_dez_meios_lances():
    for _, sequencia in campeonato.ABERTURAS:
        b = chess.Board()
        for uci in sequencia.split():
            b.push_uci(uci)
        assert b.is_valid() and len(b.move_stack) <= 10


def test_falha_em_modo_campeonato_e_derrota_conforme_edital():
    c = Cenario([chess.engine.EngineError("falha")], [1])
    r = campeonato.disputar(c, c, True, 300, 1, agora=lambda: c.tempo,
                           falha_derrota=True, saida=lambda _: None)
    assert r.placar == "0-1" and "derrota conforme edital" in r.motivo


def test_armageddon_repassa_relogios_assimetricos_sem_incremento():
    c = Cenario(["f2f3", "e7e5", "g2g4", "d8h4"], [2, 1, 3, 2])
    r = campeonato.disputar(c, c, False, 300, 0, tempos_iniciais={True: 300, False: 240},
                           agora=lambda: c.tempo, saida=lambda _: None)
    assert r.relogios == {True: 295, False: 237}
    assert c.chamadas[0][1:] == (300, 0, 240)
    assert c.chamadas[1][1:] == (240, 0, 298)


@pytest.mark.motor_real
def test_integracao_loop_real_5mais1_com_recursos_iguais():
    from chess_challenge.campanha import Contexto
    from chess_challenge.inteligencia import Jogador
    from chess_challenge.motor import abrir_motor

    registros = []
    with abrir_motor(threads=4, hash_mb=512) as a, abrir_motor(threads=4, hash_mb=512) as b:
        grupos = campeonato.grupos_cpu()
        if grupos:
            campeonato.fixar_cpu(a, grupos[0])
            campeonato.fixar_cpu(b, grupos[1])
        with Jogador(a, contexto=Contexto("buscar_vitoria")) as nosso, Jogador(b, "original") as outro:
            r = campeonato.disputar(nosso, outro, True, 300, 1, max_lances=1,
                                   saida=lambda _: None,
                                   ao_lance=lambda board, registro, relogios: registros.append((board.copy(stack=True), registro)))
    assert r.placar == "*" and len(r.historico) == 2  # Limite técnico, sem inventar empate.
    assert len(registros) == 2 and all(b.is_valid() for b, _ in registros)
    assert all(x.nos > 0 and x.profundidade > 0 and x.pv for _, x in registros)
    assert all(0 < s <= 301 for s in r.relogios.values())
