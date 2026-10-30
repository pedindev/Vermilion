from contextlib import contextmanager
from types import SimpleNamespace
import json

import chess
import pytest

from chess_challenge.campanha import Campanha, Regras, Repositorio
from chess_challenge.torneio import main, segundos
from test_base import entrada_programada, MotorSimulado
import testar_campeonato as automatico


def cli(tmp_path, *args, **kwargs):
    return main([args[0], "--arquivo", str(tmp_path / "campanha.sqlite3"), *args[1:]],
                saida=kwargs.pop("saida", lambda _: None),
                entrada=kwargs.pop("entrada", entrada_programada([""])), **kwargs)


def test_fluxo_manual_cria_joga_salva_pendente_confirma_e_consulta(tmp_path):
    assert cli(tmp_path, "criar", "--equipe", "Nossa", "--teste") == 0
    assert cli(tmp_path, "confronto", "--adversario", "Outra", "--fase", "classificacao",
               "--formato", "unica", "--cor", "pretas") == 0
    motor = MotorSimulado(["e7e5", "d8h4"])

    @contextmanager
    def conectar(caminho, threads, hash_mb):
        assert (threads, hash_mb) == (4, 512)
        yield motor

    entradas = entrada_programada(["2", "f2f3", "g2g4", "n"])
    assert cli(tmp_path, "jogar", "--modo", "original", entrada=entradas, conectar=conectar) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    campanha = repo.carregar()
    p = campanha.confrontos[-1].ativa
    assert p["status"] == "aguardando_resultado" and len(p["lances"]) == 4
    assert p["sugestao_placar"] == "0-1" and campanha.resumo()["vitorias"] == 0
    assert motor.consultas[0][1].black_inc == 1
    assert motor.consultas[0][1].white_clock == pytest.approx(301, abs=.1)
    assert p["relogios_sistema"]["brancas"] > 300
    assert p["relogios_sistema"]["pretas"] > 300
    assert cli(tmp_path, "resultado", "--placar", "0-1", "--motivo", "Mate confirmado") == 0
    campanha = repo.carregar()
    assert campanha.resumo()["vitorias"] == 1 and "pontos" not in campanha.resumo()
    assert campanha.confrontos[-1].ativa is None
    assert campanha.confrontos[-1].concluidas[0]["origem_relogios"] == "sistema"
    saidas = []
    assert cli(tmp_path, "status", saida=saidas.append) == 0
    assert json.loads(saidas[0])["resumo"]["vitorias"] == 1


def test_interrupcao_manual_preserva_historico_sem_inventar_resultado(tmp_path):
    cli(tmp_path, "criar", "--equipe", "Nossa")
    cli(tmp_path, "confronto", "--adversario", "Outra", "--fase", "final", "--formato", "melhor-de-tres", "--cor", "brancas")

    @contextmanager
    def conectar(*args):
        yield MotorSimulado(["e2e4"])

    assert cli(tmp_path, "jogar", "--modo", "original", entrada=entrada_programada(["1", EOFError()]), conectar=conectar) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    campanha = repo.carregar()
    assert campanha.confrontos[-1].ativa["lances"] == ["e2e4"]
    assert campanha.resumo()["empates"] == 0
    assert cli(tmp_path, "jogar", "--modo", "original", conectar=conectar) == 1
    assert cli(tmp_path, "cancelar", "--justificativa", "Ensaio cancelado pelo operador") == 0
    assert repo.carregar().confrontos[-1].ativa is None


def test_cli_configura_duracao_sem_mudar_relogios_e_nao_sobrescreve(tmp_path):
    assert cli(tmp_path, "criar", "--equipe", "Nossa", entrada=entrada_programada(["abc", "0", "25"])) == 0
    assert cli(tmp_path, "criar", "--equipe", "Outra") == 1
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    assert c.regras.duracao_prevista_minutos == 25
    assert cli(tmp_path, "regras", "--duracao-prevista", "30", "--tres-obrigatorias", "sim") == 0
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    assert c.regras.duracao_prevista_minutos == 30
    assert (c.regras.tempo, c.regras.incremento) == (900, 10)
    assert not {"pontos", "posicao_oficial"} & c.resumo().keys()
    assert not c.regras.encerrar_ao_decidir
    assert c.regras.incremento_armageddon == 0


def test_criacao_cancelada_nao_cria_banco(tmp_path):
    assert cli(tmp_path, "criar", "--equipe", "Nossa", entrada=entrada_programada([EOFError()])) == 0
    assert not (tmp_path / "campanha.sqlite3").exists()


def test_campanha_guarda_ajuste_fisico_com_fracoes_sem_perder_lances(tmp_path):
    cli(tmp_path, "criar", "--equipe", "Nossa", "--duracao-prevista", "25")
    cli(tmp_path, "confronto", "--adversario", "Outra", "--formato", "unica")
    motor = MotorSimulado(["e7e5"])
    @contextmanager
    def conectar(*args):
        yield motor
    cli(tmp_path, "jogar", "--modo", "original", conectar=conectar,
        entrada=entrada_programada(["2", "relogios 14:20.125 13:40.250", "e2e4", EOFError()]))
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    p = repo.carregar().confrontos[-1].ativa
    assert p["lances"] == ["e2e4", "e7e5"] and len(p["registros"]) == 2
    assert p["ajustes_relogio"][0]["brancas"] == pytest.approx(860.125, abs=.02)
    assert p["origem_relogios"] == "sistema_com_ajuste_fisico"
    cli(tmp_path, "resultado", "--placar", "1/2-1/2", "--motivo", "Confirmado pelo árbitro",
        "--nosso-tempo", "10.125", "--outro-tempo", "12.250")
    c = repo.carregar().confrontos[-1]
    assert c.concluidas[0]["saldo_nosso_ms"] == 10125
    assert c.concluidas[0]["saldo_outro_ms"] == 12250
    assert c.concluidas[0]["origem_relogios"] == "ajuste_oficial_pelo_operador"
    assert c.situacao(repo.carregar().regras)["status"] == "armageddon"


@pytest.mark.parametrize("texto", ["nan", "inf", "-1", "1:60", "1:2:3", "abc"])
def test_relogio_invalido_nao_e_aceito(texto):
    with pytest.raises(Exception):
        segundos(texto)


def test_teste_melhor_de_tres_repassa_contextos_recursos_e_persiste(tmp_path, monkeypatch):
    chamadas, recursos = [], []

    @contextmanager
    def conectar(caminho, threads, hash_mb):
        recursos.append((threads, hash_mb))
        yield SimpleNamespace(id={"name": "simulado"})

    def disputar(nosso, outro, cor, tempo, incremento, max_lances, board, *args, **kwargs):
        chamadas.append((nosso.contexto, outro.contexto, cor, tempo, incremento, kwargs))
        placar = "1-0" if len(chamadas) == 1 else "1/2-1/2"
        return automatico.Resultado(cor, placar, "Cenário validado", 0, {True: 30, False: 30})

    monkeypatch.setattr(automatico, "disputar", disputar)
    monkeypatch.setattr(automatico, "grupos_cpu", lambda: None)
    banco = tmp_path / "teste.sqlite3"
    assert automatico.main(["--campanha", str(banco)], entrada=entrada_programada(["n"]), emitir=lambda _: None,
                          conectar=conectar, pasta_logs=tmp_path) == 0
    assert [x[2] for x in chamadas] == [True, False, True]
    assert all(x[3:5] == (300, 1) for x in chamadas)
    assert chamadas[-1][0].empate_classifica and chamadas[-1][1].evitar_empate
    assert recursos == [(4, 512)] * 6
    campanha = Repositorio(banco).carregar()
    assert campanha.confrontos[0].situacao(campanha.regras)["status"] == "classificado"
    assert not list(tmp_path.glob("*.txt"))


def test_ensaio_armageddon_sem_incremento_empate_classifica_pretas(tmp_path, monkeypatch):
    chamadas = []

    @contextmanager
    def conectar(*args):
        yield SimpleNamespace(id={"name": "simulado"})

    def disputar(nosso, outro, cor, tempo, incremento, *args, **kwargs):
        chamadas.append((nosso.contexto, cor, incremento, kwargs["tempos_iniciais"]))
        return automatico.Resultado(cor, "1/2-1/2", "Repetição", 8, {True: 200, False: 200})

    monkeypatch.setattr(automatico, "disputar", disputar)
    monkeypatch.setattr(automatico, "grupos_cpu", lambda: None)
    banco = tmp_path / "armageddon.sqlite3"
    saidas = []
    assert automatico.main(["--formato", "armageddon", "--cor-armageddon", "pretas", "--campanha", str(banco)],
        entrada=entrada_programada(["n"]), emitir=saidas.append, conectar=conectar, pasta_logs=tmp_path) == 0
    assert chamadas[0][0].empate_classifica
    assert chamadas[0][1:] == (False, 0, {True: 300, False: 240})
    campanha = Repositorio(banco).carregar()
    assert campanha.confrontos[0].situacao(campanha.regras)["status"] == "classificado"
    assert campanha.confrontos[0].concluidas[-1]["resultado"] == "E"
    assert any("efetivamente disputados: 0 vitória(s), 1 empate(s)" in s for s in saidas)


def test_interrupcao_automatica_preserva_pendente_sem_pontuar(tmp_path, monkeypatch):
    @contextmanager
    def conectar(*args):
        yield SimpleNamespace(id={"name": "simulado"})

    def disputar(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(automatico, "disputar", disputar)
    monkeypatch.setattr(automatico, "grupos_cpu", lambda: None)
    banco = tmp_path / "interrompido.sqlite3"
    automatico.main(["--campanha", str(banco)], entrada=entrada_programada(["n"]), emitir=lambda _: None,
                    conectar=conectar, pasta_logs=tmp_path)
    campanha = Repositorio(banco).carregar()
    assert campanha.resumo()["empates"] == 0
    assert campanha.confrontos[0].ativa["status"] == "inconclusiva"
    assert automatico.main(["--campanha", str(banco)], entrada=entrada_programada(["n"]), emitir=lambda _: None,
                           conectar=conectar, pasta_logs=tmp_path) == 1
