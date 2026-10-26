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
                saida=kwargs.pop("saida", lambda _: None), **kwargs)


def test_fluxo_manual_cria_joga_salva_pendente_confirma_e_consulta(tmp_path):
    assert cli(tmp_path, "criar", "--equipe", "Nossa", "--teste") == 0
    assert cli(tmp_path, "confronto", "--adversario", "Outra", "--fase", "classificacao",
               "--formato", "unica", "--cor", "pretas") == 0
    motor = MotorSimulado(["e7e5", "d8h4"])

    @contextmanager
    def conectar(caminho, threads, hash_mb):
        assert (threads, hash_mb) == (4, 512)
        yield motor

    entradas = entrada_programada(["f2f3 04:59 04:58", "g2g4 04:57 04:56", "n"])
    assert cli(tmp_path, "jogar", "--modo", "original", entrada=entradas, conectar=conectar) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    campanha = repo.carregar()
    p = campanha.confrontos[-1].ativa
    assert p["status"] == "aguardando_resultado" and len(p["lances"]) == 4
    assert p["sugestao_placar"] == "0-1" and campanha.resumo()["vitorias"] == 0
    assert motor.consultas[0][1].black_inc == 1
    assert motor.consultas[0][1].white_clock == 298
    assert cli(tmp_path, "resultado", "--placar", "0-1", "--nosso-tempo", "04:55",
               "--outro-tempo", "04:56", "--motivo", "Mate confirmado") == 0
    campanha = repo.carregar()
    assert campanha.resumo()["vitorias"] == 1 and campanha.resumo()["pontos"] == 3
    assert campanha.confrontos[-1].ativa is None
    saidas = []
    assert cli(tmp_path, "status", saida=saidas.append) == 0
    assert json.loads(saidas[0])["resumo"]["vitorias"] == 1


def test_interrupcao_manual_preserva_historico_sem_inventar_resultado(tmp_path):
    cli(tmp_path, "criar", "--equipe", "Nossa")
    cli(tmp_path, "confronto", "--adversario", "Outra", "--fase", "final", "--formato", "melhor-de-tres", "--cor", "brancas")

    @contextmanager
    def conectar(*args):
        yield MotorSimulado(["e2e4"])

    assert cli(tmp_path, "jogar", "--modo", "original", entrada=entrada_programada([EOFError()]), conectar=conectar) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    campanha = repo.carregar()
    assert campanha.confrontos[-1].ativa["lances"] == ["e2e4"]
    assert campanha.resumo()["empates"] == 0
    assert cli(tmp_path, "jogar", "--modo", "original", conectar=conectar) == 1
    assert cli(tmp_path, "cancelar", "--justificativa", "Ensaio cancelado pelo operador") == 0
    assert repo.carregar().confrontos[-1].ativa is None


def test_cli_configura_regras_importa_tabela_e_nao_sobrescreve(tmp_path):
    assert cli(tmp_path, "criar", "--equipe", "Nossa") == 0
    assert cli(tmp_path, "criar", "--equipe", "Outra") == 1
    assert cli(tmp_path, "regras", "--rodadas", "5", "--vagas", "8", "--equipes", "32",
               "--classificacao-por-pontos", "sim", "--tres-obrigatorias", "sim") == 0
    tabela = tmp_path / "tabela.json"
    tabela.write_text(json.dumps([dict(equipe="Nossa", posicao=4, pontos=7)]), encoding="utf-8")
    assert cli(tmp_path, "tabela", "--importar", str(tabela), "--rodada", "3") == 0
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    assert c.resumo()["posicao_oficial"] == 4
    assert c.resumo()["pontos_oficiais"] == 7
    assert not c.regras.encerrar_ao_decidir
    assert c.regras.incremento_armageddon == 0


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
