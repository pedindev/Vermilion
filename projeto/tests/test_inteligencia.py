from contextlib import contextmanager
from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import chess
import chess.engine
import pytest

import chess_challenge.inteligencia as inteligencia
from chess_challenge.inteligencia import (Antecipacao, Candidato, Jogador, Parametros,
    Preparacao, avaliar_defesas, chave, cp_exato, escolher_candidato, extrair_candidatos)
from chess_challenge.motor import LanceCalculado
from chess_challenge.campanha import Contexto
from chess_challenge.estrategia import ordenar
from test_base import MotorSimulado, entrada_programada


def info(uci, cp=0, cor=chess.WHITE, depth=20, **outros):
    return {"pv": [chess.Move.from_uci(uci)],
            "score": chess.engine.PovScore(chess.engine.Cp(cp), cor),
            "depth": depth, "nodes": 1000, **outros}


def test_chave_distingue_mesma_posicao_com_historicos_diferentes():
    a, b = chess.Board(), chess.Board()
    for uci in ["g1f3", "g8f6", "f3g1", "f6g8"]:
        a.push_uci(uci)
    b.set_fen(a.fen())
    assert a.fen() == b.fen() and chave(a) != chave(b)


@pytest.mark.parametrize("extras", [{"lowerbound": True}, {"upperbound": True}])
def test_avaliacao_provisoria_nao_e_usada_como_exata(extras):
    assert cp_exato(info("e2e4", **extras), True) is None


def test_mate_nao_e_convertido_em_cp_para_selecao():
    i = info("e2e4")
    i["score"] = chess.engine.PovScore(chess.engine.Mate(2), True)
    assert cp_exato(i, True) is None


def test_candidatos_limitados_a_proximidade_e_profundidade():
    raiz = chess.Board()
    candidatos = extrair_candidatos(raiz, [info("e2e4", 30), info("d2d4", 25),
        info("c2c4", 0), info("g1f3", 29, depth=4)], Parametros())
    assert [c[0].uci() for c in candidatos] == ["e2e4", "d2d4"]


def test_nao_escolhe_candidato_que_encerra_por_repeticao():
    board = chess.Board()
    for uci in ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"]:
        board.push_uci(uci)
    assert extrair_candidatos(board, [info("f6g8", 0, False)], Parametros()) == []


def test_pressao_e_diferenca_entre_duas_defesas_na_perspectiva_do_adversario():
    board = chess.Board()
    board.push_uci("e2e4")
    gap, lances = avaliar_defesas(board, [info("e7e5", -20, False), info("c7c5", -120, False)], Parametros())
    assert gap == 100 and lances == ("e7e5", "c7c5")


def test_uma_unica_defesa_analisada_nao_prova_dificuldade():
    board = chess.Board()
    board.push_uci("e2e4")
    assert avaliar_defesas(board, [info("e7e5", 0, False)], Parametros()) == (0, ())


def test_escolhe_alternativa_com_maior_pressao_sem_trocar_por_ruido():
    e4, d4 = map(chess.Move.from_uci, ["e2e4", "d2d4"])
    assert escolher_candidato([Candidato(e4, 30, 10, 20), Candidato(d4, 25, 100, 20)], e4, Parametros()).lance == d4
    assert escolher_candidato([Candidato(e4, 30, 90, 20), Candidato(d4, 25, 100, 20)], e4, Parametros()) is None


class MotorComConfirmacao(MotorSimulado):
    def __init__(self, score_alternativa=25):
        super().__init__(["e2e4"])
        self.score_alternativa = score_alternativa
        self.confirmacoes = []

    def analyse(self, board, limite, **opcoes):
        self.confirmacoes.append((board, limite, opcoes))
        return [info("e2e4", 30), info("d2d4", self.score_alternativa)]


def preparar_jogador(motor):
    j = Jogador(motor)
    preparado = Preparacao(chave(chess.Board()), "e7e5",
                           (Candidato(chess.Move.from_uci("d2d4"), 25, 100, 20),), acerto=True)
    j.antecipacao.parar = lambda board=None: preparado
    return j


def test_seletor_realmente_troca_lance_e_registra_justificativa():
    motor = MotorComConfirmacao()
    d = preparar_jogador(motor).calcular(chess.Board(), 900)
    assert d.lance.uci() == "d2d4"
    assert d.detalhes["original"] == "e2e4" and d.detalhes["troca_autoral"]
    assert d.info["pv"][0] == d.lance
    assert motor.confirmacoes[0][2]["root_moves"] == list(map(chess.Move.from_uci, ["e2e4", "d2d4"]))
    assert motor.confirmacoes[0][1].time <= .3


def test_rejeita_alternativa_que_piora_na_verificacao():
    d = preparar_jogador(MotorComConfirmacao(0)).calcular(chess.Board(), 900)
    assert d.lance.uci() == "e2e4" and not d.detalhes["troca_autoral"]
    assert "rejeitado" in d.detalhes["criterio"]


def test_verificacao_rasa_nao_autoriza_troca():
    motor = MotorComConfirmacao()
    motor.analyse = lambda *args, **kwargs: [info("e2e4", 30, depth=4), info("d2d4", 25, depth=4)]
    d = preparar_jogador(motor).calcular(chess.Board(), 900)
    assert d.lance.uci() == "e2e4" and "insuficiente" in d.detalhes["criterio"]


def test_verificacao_provisoria_nao_autoriza_troca():
    motor = MotorComConfirmacao()
    motor.analyse = lambda *args, **kwargs: [info("e2e4", 30), info("d2d4", 25, lowerbound=True)]
    d = preparar_jogador(motor).calcular(chess.Board(), 900)
    assert d.lance.uci() == "e2e4" and not d.detalhes["troca_autoral"]


def test_apuro_pula_analise_adicional():
    motor = MotorComConfirmacao()
    d = preparar_jogador(motor).calcular(chess.Board(), 4)
    assert d.lance.uci() == "e2e4" and not motor.confirmacoes


def test_mate_anunciado_preserva_lance_original():
    motor = MotorComConfirmacao()
    original_play = motor.play

    def play(*args, **kwargs):
        r = original_play(*args, **kwargs)
        r.info["score"] = chess.engine.PovScore(chess.engine.Mate(2), True)
        return r

    motor.play = play
    d = preparar_jogador(motor).calcular(chess.Board(), 900)
    assert d.lance.uci() == "e2e4" and not motor.confirmacoes


class AnaliseBloqueada:
    def __init__(self, board):
        self.board = board
        self.parada = Event()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stop()

    def __iter__(self):
        yield info(next(iter(self.board.legal_moves)).uci(), 0, self.board.turn)
        assert self.parada.wait(2), "A busca não recebeu stop"

    def stop(self):
        self.parada.set()

    def wait(self):
        return None


class MotorEmSegundoPlano:
    def __init__(self):
        self.comecou = Event()
        self.analises = []

    def analysis(self, board, limite, **opcoes):
        a = AnaliseBloqueada(board)
        self.analises.append(a)
        self.comecou.set()
        return a


def test_antecipacao_para_e_valida_previsao_sem_perder_historico():
    motor = MotorEmSegundoPlano()
    a = Antecipacao(motor, "ponderacao")
    board = chess.Board()
    board.push_uci("e2e4")
    a.iniciar(board, chess.Move.from_uci("e7e5"))
    assert motor.comecou.wait(1)
    board.push_uci("e7e5")
    r = a.parar(board)
    assert r.acerto and r.previsao == "e7e5"
    assert motor.analises[0].parada.is_set() and a.thread is None
    assert len(motor.analises[0].board.move_stack) == 2


def test_previsao_errada_descarta_candidatos():
    motor = MotorEmSegundoPlano()
    a = Antecipacao(motor, "ponderacao")
    board = chess.Board()
    board.push_uci("e2e4")
    a.iniciar(board, chess.Move.from_uci("e7e5"))
    assert motor.comecou.wait(1)
    a.preparacao.candidatos = (Candidato(chess.Move.from_uci("d2d4"), 0, 100, 20),)
    board.push_uci("c7c5")
    r = a.parar(board)
    assert not r.acerto and r.candidatos == ()


def test_contexto_fecha_trabalhador_em_interrupcao():
    motor = MotorEmSegundoPlano()
    board = chess.Board()
    board.push_uci("e2e4")
    j = Jogador(motor, "ponderacao")
    with pytest.raises(KeyboardInterrupt):
        with j:
            j.antecipacao.iniciar(board, chess.Move.from_uci("e7e5"))
            assert motor.comecou.wait(1)
            raise KeyboardInterrupt
    assert j.antecipacao.thread is None


def test_entrada_invalida_mantem_antecipacao_e_eof_fecha_trabalhador():
    from chess_challenge.partida import executar

    class Motor(MotorEmSegundoPlano):
        id = {"name": "Teste"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            assert all(a.parada.is_set() for a in self.analises)

        def play(self, board, limit, **kwargs):
            move, pred = map(chess.Move.from_uci, ["e2e4", "e7e5"])
            return chess.engine.PlayResult(move, pred, {**info("e2e4"), "pv": [move, pred]})

    motor = Motor()
    entradas = iter(["1", "e7e6 14:99", EOFError()])

    def entrada(prompt):
        valor = next(entradas)
        if not prompt.startswith("Sua equipe"):
            assert motor.comecou.wait(1)
            assert not motor.analises[0].parada.is_set()
        if isinstance(valor, BaseException):
            raise valor
        return valor

    board = executar(entrada, lambda _: None, conectar=lambda: motor, modo="ponderacao")
    assert [m.uci() for m in board.move_stack] == ["e2e4"]


def test_original_nao_inicia_trabalhador():
    motor = MotorEmSegundoPlano()
    a = Antecipacao(motor, "original")
    board = chess.Board()
    board.push_uci("e2e4")
    a.iniciar(board, chess.Move.from_uci("e7e5"))
    assert a.thread is None and not motor.analises


def test_correcao_do_relogio_e_custo_da_parada_chegam_a_busca_nativa(monkeypatch):
    tempo = [0]
    j = Jogador(None)

    def parar(board):
        tempo[0] += 2
        return Preparacao()

    def calcular(motor, board, restante, incremento, **kwargs):
        assert restante == 888 and incremento == 10
        tempo[0] += 3
        return LanceCalculado(chess.Move.from_uci("e2e4"), 3, {})

    j.antecipacao.parar = parar
    monkeypatch.setattr(inteligencia, "calcular_lance", calcular)
    d = j.calcular(chess.Board(), 890, agora=lambda: tempo[0])
    assert d.tempo == 5


def posicao_antes_da_tripla():
    board = chess.Board()
    for uci in ["g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"]:
        board.push_uci(uci)
    return board


def test_empate_que_classifica_e_escolhido_sem_busca_e_com_prova():
    board = posicao_antes_da_tripla()
    ctx = Contexto("preservar_empate", "Empate classifica", True)
    d = Jogador(None, contexto=ctx).calcular(board, 300, 1)
    assert d.lance.uci() == "f6g8" and d.info["nodes"] == 0
    assert d.detalhes["fonte"] == "regra comprovada"
    assert len(board.move_stack) == 7  # Análise não alterou o tabuleiro real.
    board.push(d.lance)
    assert board.is_repetition(3)


def test_precisar_vencer_evitaria_empate_automatico_entre_alternativas_verificadas():
    board = posicao_antes_da_tripla()
    original = chess.Move.from_uci("f6g8")
    alternativa = chess.Move.from_uci("e7e5")
    ctx = Contexto("buscar_vitoria", "Só vitória serve", False, True)
    escolhido, detalhes = ordenar(board, [(original, 0), (alternativa, -5)], original, ctx, 0)
    assert escolhido == alternativa
    assert all(x["uci"] != "f6g8" for x in detalhes["alternativas"])


def test_contexto_realmente_muda_a_escolha_com_mesmos_lances_e_avaliacoes():
    board = chess.Board("6k1/5pp1/7p/8/8/8/5PPP/3Q2K1 w - - 0 1")
    # Qd7 pressiona as casas próximas do rei; Qd2 mantém a dama distante.
    original, ataque = map(chess.Move.from_uci, ["d1d2", "d1d7"])
    alternativas = [(original, 0), (ataque, 0)]
    ofensivo, _ = ordenar(board, alternativas, original, Contexto("buscar_vitoria"), 0)
    defensivo, _ = ordenar(board, alternativas, original, Contexto("preservar_empate"), 0)
    assert ofensivo == ataque and defensivo == original


def test_pipeline_stockfish_verificacao_e_campanha_mudam_o_lance_e_o_log():
    board = chess.Board("6k1/5pp1/7p/8/8/8/5PPP/3Q2K1 w - - 0 1")

    class Motor(MotorSimulado):
        def analyse(self, *args, **kwargs):
            return [info("d1d2", 0), info("d1d7", 0)]

    motor = Motor(["d1d2"])
    original = motor.play

    def play(*args, **kwargs):
        r = original(*args, **kwargs)
        r.info["score"] = chess.engine.PovScore(chess.engine.Cp(0), True)
        return r

    motor.play = play
    d = Jogador(motor, contexto=Contexto("buscar_vitoria")).calcular(board, 300, 1)
    assert d.lance.uci() == "d1d7"
    assert d.detalhes["troca_autoral"] and d.detalhes["busca_principal"]["uci"] == "d1d2"
    assert d.detalhes["contexto"]["objetivo"] == "buscar_vitoria"
    assert "verificacao_campanha" in d.detalhes


def test_contexto_respeita_lance_de_mate_da_busca_principal():
    motor = MotorComConfirmacao()
    play = motor.play

    def com_mate(*args, **kwargs):
        r = play(*args, **kwargs)
        r.info["score"] = chess.engine.PovScore(chess.engine.Mate(2), True)
        return r

    motor.play = com_mate
    d = Jogador(motor, contexto=Contexto("buscar_vitoria")).calcular(chess.Board(), 300, 1)
    assert d.lance.uci() == "e2e4" and not motor.confirmacoes


def test_sem_tempo_nao_se_aplica_nem_empate_qualificante():
    with pytest.raises(ValueError):
        Jogador(None, contexto=Contexto("preservar_empate", empate_classifica=True)).calcular(posicao_antes_da_tripla(), 0, 0)


def test_repertorio_inteiro_tem_lances_legais_e_nao_dispara_busca():
    from chess_challenge.aberturas import Repertorio
    livro = Repertorio.carregar()
    assert livro.entradas and livro.erro is None
    for historico, item in livro.entradas.items():
        board = chess.Board()
        for uci in historico:
            board.push_uci(uci)
        antes = board.fen(), list(board.move_stack)
        with Jogador(None, contexto=Contexto(), repertorio=livro) as j:
            d = j.calcular(board, 900, 10, adversario=900)
            assert d.lance.uci() == item["uci"] and d.lance in board.legal_moves
            assert d.info["nodes"] == d.info["depth"] == 0 and "score" not in d.info
            assert d.detalhes["fonte"] == "abertura_preparada"
            assert d.detalhes["analise_previa"]["profundidade"] >= 16
            assert not d.detalhes["troca_autoral"]
        assert (board.fen(), board.move_stack) == antes


def test_repertorio_termina_em_dez_meios_lances_e_nao_reentra():
    from chess_challenge.aberturas import Repertorio
    livro, board = Repertorio.carregar(), chess.Board()
    with Jogador(None, repertorio=livro) as j:
        for _ in range(10):
            board.push(j.calcular(board, 900).lance)
        assert livro.consultar(board) is None
        m = MotorSimulado([next(iter(board.legal_moves)).uci(), "e2e4"])
        j.motor = m
        assert j.calcular(board, 900).lance in board.legal_moves
        j.calcular(chess.Board(), 900)
        assert j.repertorio is None and len(m.consultas) == 2


def test_desvio_da_abertura_e_modos_de_referencia_usam_motor():
    from chess_challenge.aberturas import Repertorio
    livro, board = Repertorio.carregar(), chess.Board()
    board.push_uci("e2e4")
    board.push_uci("a7a6")
    motor = MotorSimulado(["g1f3"])
    with Jogador(motor, repertorio=livro) as j:
        j.calcular(board, 900)
        assert j.repertorio is None and len(motor.consultas) == 1
    for modo in ("original", "ponderacao"):
        motor = MotorSimulado(["e2e4"])
        with Jogador(motor, modo, repertorio=livro) as j:
            j.calcular(chess.Board(), 900)
            assert len(motor.consultas) == 1


@pytest.mark.parametrize("conteudo", ["{", "{}", '{"formato": 1, "limite_meios_lances": 11}'])
def test_repertorio_corrompido_nao_impede_busca(tmp_path, conteudo):
    from chess_challenge.aberturas import Repertorio
    caminho = tmp_path / "book.json"
    assert Repertorio.carregar(caminho).erro
    caminho.write_text(conteudo, encoding="utf-8")
    livro = Repertorio.carregar(caminho)
    assert livro.erro and not livro.entradas
    with Jogador(MotorSimulado(["e2e4"]), repertorio=livro) as j:
        assert j.calcular(chess.Board(), 900).lance.uci() == "e2e4"


@pytest.mark.motor_real
def test_repertorio_e_retorno_a_busca_com_stockfish_real():
    from chess_challenge.aberturas import Repertorio
    from chess_challenge.motor import abrir_motor
    with abrir_motor() as motor, Jogador(motor, repertorio=Repertorio.carregar()) as j:
        board = chess.Board()
        d = j.calcular(board, 900, 10)
        assert d.lance.uci() == "e2e4" and d.info["nodes"] == 0
        board.push(d.lance)
        board.push_uci("a7a6")
        resposta = j.calcular(board, 2, 0)
        assert resposta.lance in board.legal_moves and resposta.info["nodes"] > 0
        assert j.repertorio is None


@pytest.mark.motor_real
@pytest.mark.parametrize("modo", ["ponderacao", "completo"])
def test_integracao_antecipacao_e_resposta_com_motor_real(modo):
    from time import sleep
    from chess_challenge.motor import abrir_motor
    board = chess.Board()
    with abrir_motor(threads=2, hash_mb=64) as motor, Jogador(motor, modo) as j:
        d = j.calcular(board, 20, .2)
        board.push(d.lance)
        previsao = d.previsao or (d.info["pv"][1] if len(d.info.get("pv", [])) > 1 else None)
        assert previsao in board.legal_moves
        j.preparar(board, d)
        sleep(1)
        board.push(previsao)
        resposta = j.calcular(board, 19, .2)
        assert resposta.lance in board.legal_moves
        assert resposta.detalhes["antecipacao"] == "acertou"
        assert resposta.detalhes["nos_antecipados"] > 0
        assert j.antecipacao.thread is None
