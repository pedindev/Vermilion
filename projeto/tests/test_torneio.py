from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path
import json

import chess
import pytest

from chess_challenge.campanha import Campanha, Regras, Repositorio
from chess_challenge.torneio import main, segundos
from test_base import entrada_programada, MotorSimulado
import testar_campeonato as automatico
from chess_challenge import torneio, partida


def cli(tmp_path, *args, **kwargs):
    return main([args[0], "--arquivo", str(tmp_path / "campanha.sqlite3"), *args[1:]],
                saida=kwargs.pop("saida", lambda _: None),
                entrada=kwargs.pop("entrada", entrada_programada([""])), **kwargs)


def entrada_da_partida(valores):
    respostas = iter(valores)

    def ler(prompt):
        try:
            return next(respostas)
        except StopIteration:
            pytest.fail(f"Pergunta indevida após terminar a partida: {prompt}")
    return ler


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
    assert c.situacao(repo.carregar().regras)["status"] == "derrota"


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


def test_comando_unico_cria_joga_salva_resultado_e_simplifica_tela(tmp_path):
    motor, saidas, perguntas = MotorSimulado(["e7e5", "d8h4"]), [], []
    respostas = entrada_da_partida(["Nossa", "25", "Outra", "1", "1", "2", "f2f3", "g2g4"])

    def entrada(prompt):
        perguntas.append(prompt)
        return respostas(prompt)

    @contextmanager
    def conectar(caminho, threads, hash_mb):
        assert (threads, hash_mb) == (4, 512)
        yield motor

    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada,
               saida=saidas.append, conectar=conectar) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    c = campanha.confrontos[0]
    assert c.ativa is None and len(c.concluidas) == 1
    p = c.concluidas[0]
    assert p["placar"] == "0-1" and p["resultado"] == "V" and p["origem"] == "tabuleiro"
    assert p["lances"] == ["f2f3", "e7e5", "g2g4", "d8h4"]
    assert p["registros"][-1]["profundidade"] == 20
    assert p["registros"][-1]["nos"] == 10000
    assert p["saldo_nosso_ms"] > 0 and p["saldo_outro_ms"] > 0
    assert campanha.regras.duracao_prevista_minutos == 25
    assert motor.consultas[0][1].black_clock == pytest.approx(1499 * 900 / 1810, abs=.5)
    assert motor.consultas[0][1].black_inc == 0
    assert p["tempo_nosso"] == 900 and p["incremento"] == 10
    planejamento = json.loads(p["registros"][1]["detalhes"])["planejamento_tempo"]
    assert planejamento["janela_restante_s"] <= 1500
    texto = "\n".join(saidas)
    assert texto.count("a b c d e f g h") == 4
    assert "Partida salva" in texto and "vencemos" in texto
    assert all(t not in texto for t in ("ID ", "Análise:", "Campanha:", "Modo:", "campanha resultado"))
    assert not any("relatório" in p or "Resultado" in p for p in perguntas)
    assert not list(tmp_path.rglob("*.txt"))
    log = Path(p["arquivo_log"])
    assert log.name == "partida_001.log" and p["numero_geral"] == 1
    assert list((tmp_path / "logs").glob("*.log")) == [log]
    texto_log = log.read_text(encoding="utf-8")
    assert all(campo in texto_log for campo in ("Outra", "0-1", "Brancas", "Pretas", "e7e5",
                                               "profundidade 20", "nós 10000", "avaliação", "PV", "tempo"))


def test_tres_execucoes_jogam_uma_partida_cada_e_repassam_resultados_ao_contexto(tmp_path):
    lances = iter([["f2f3", "g2g4"], ["e7e5", "d8h4"], ["f2f3", "g2g4"]])

    @contextmanager
    def conectar(*args):
        yield MotorSimulado(next(lances))

    entradas = [["Nossa", "", "Outra", "5", "2", "1", "e7e5", "d8h4"],
                ["2", "f2f3", "g2g4"], ["1", "e7e5", "d8h4"]]
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    for numero, respostas in enumerate(entradas, 1):
        assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_da_partida(respostas), conectar=conectar) == 0
        assert len(repo.carregar().confrontos[0].concluidas) == numero
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    c = campanha.confrontos[0]
    assert [p["cor"] for p in c.concluidas] == [True, False, True]
    assert [p["resultado"] for p in c.concluidas] == ["D", "V", "D"]
    assert c.concluidas[1]["contexto"]["objetivo"] == "buscar_vitoria"
    assert c.concluidas[2]["contexto"]["desempate_por_tempo"]
    assert all(not p["armageddon"] for p in c.concluidas)
    assert c.situacao(campanha.regras)["status"] == "eliminado"


@pytest.mark.parametrize("cor_arm", [True, False])
def test_armageddon_so_e_jogado_na_execucao_seguinte_apos_tres_empates(tmp_path, monkeypatch, cor_arm):
    executar_real = torneio.executar
    janelas = []

    def executar(*args, **kwargs):
        janelas.append(kwargs["duracao_total_minutos"])
        return executar_real(*args, **kwargs, agora=lambda: 0)

    monkeypatch.setattr(torneio, "executar", executar)
    brancas, pretas = ["g1f3", "f3g1"] * 2, ["g8f6", "f6g8"] * 2
    cores = [True, False, True, cor_arm]
    motores = []
    entradas = []
    for cor in cores:
        motores.append(MotorSimulado(brancas if cor else pretas))
        entradas.append(["1" if cor else "2", *(pretas if cor else brancas)])
    entradas[0] = ["Nossa", "25", "Outra", "5", "2", *entradas[0]]
    entradas[2].append("s")  # Autoriza somente depois de concluir o confronto.
    disponiveis = iter(motores)

    @contextmanager
    def conectar(*args):
        yield next(disponiveis)

    repo = Repositorio(tmp_path / "campanha.sqlite3")
    for numero, respostas in enumerate(entradas, 1):
        assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_da_partida(respostas), conectar=conectar) == 0
        c = repo.carregar().confrontos[0]
        assert len(c.concluidas) == numero
        if numero < 4:
            assert not any(p["armageddon"] for p in c.partidas)
        if numero == 3:
            assert c.situacao(repo.carregar().regras)["status"] == "armageddon"
            assert c.armageddon_autorizado
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    c = campanha.confrontos[0]
    assert len(c.concluidas) == 4 and c.ativa is None
    assert [p["armageddon"] for p in c.concluidas] == [False, False, False, True]
    assert all(p["resultado"] == "E" for p in c.concluidas)
    arm = c.concluidas[-1]
    assert arm["cor"] == cor_arm and arm["incremento"] == 0
    assert (arm["tempo_nosso"], arm["tempo_outro"]) == ((300, 240) if cor_arm else (240, 300))
    limite = motores[-1].consultas[0][1]
    assert (limite.white_clock, limite.black_clock) == pytest.approx((300, 240), abs=.5)
    assert (limite.white_inc, limite.black_inc) == (0, 0)
    assert c.situacao(campanha.regras)["status"] == ("eliminado" if cor_arm else "classificado")
    assert campanha.resumo()["empates"] == 4
    assert janelas == [25, 25, 25, None]
    assert not c.armageddon_autorizado
    assert [Path(p["arquivo_log"]).name for p in c.concluidas] == [
        f"partida_{n:03d}.log" for n in range(1, 5)]


def test_sessao_tempos_desiguais_decidem_sem_abrir_armageddon(tmp_path):
    banco = Repositorio(tmp_path / "campanha.sqlite3")
    campanha = Campanha("Nossa")
    c = campanha.novo_confronto("Outra", fase="final", formato="melhor-de-tres")
    for _ in range(3):
        p = c.iniciar(campanha.regras)
        c.finalizar(p["id"], "1/2-1/2", "Cenário de teste", 20.125, 20.124)
    banco.criar(campanha)

    def proibido(*args):
        pytest.fail("Não deve abrir motor nem perguntar cor após confronto decidido.")

    assert cli(tmp_path, "iniciar", entrada=proibido, conectar=proibido) == 0
    c = banco.carregar().confrontos[0]
    assert len(c.partidas) == 3 and c.situacao(campanha.regras)["status"] == "classificado"


def test_sessao_fim_externo_pede_resultado_na_propria_tela(tmp_path):
    @contextmanager
    def conectar(*args):
        yield MotorSimulado([])

    respostas = ["Nossa", "", "Outra", "5", "1", "2", "fim", "1"]
    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_programada(respostas), conectar=conectar) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    p = campanha.confrontos[0].concluidas[0]
    assert p["placar"] == "0-1" and p["resultado"] == "V" and p["origem"] == "operador"
    assert not p["lances"]


def test_duracao_total_termina_partida_com_relogios_positivos_e_resultado_pendente(tmp_path, monkeypatch):
    instante = [0]
    executar_real = torneio.executar
    monkeypatch.setattr(torneio, "executar", lambda *a, **kw: executar_real(*a, **kw, agora=lambda: instante[0]))
    respostas = entrada_programada(["Nossa", ".05", "Outra", "1", "1", "2", "e2e4", ""])

    def entrada(prompt):
        resposta = respostas(prompt)
        if "digite o lance" in prompt:
            instante[0] = 4  # Janela de três segundos, relógios ainda em 15 minutos.
        return resposta

    @contextmanager
    def conectar(*args):
        yield MotorSimulado([])

    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada, conectar=conectar) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    p = campanha.confrontos[0].ativa
    assert not p["lances"] and p["resultado"] is None and p["sugestao_placar"] is None
    assert min(p["relogios_sistema"].values()) > 0
    texto = Path(p["arquivo_log"]).read_text(encoding="utf-8")
    assert "Duração total informada atingida" in texto and "Resultado oficial pendente" in texto
    assert "Duração total informada: 0.05 minutos" in texto


def test_sessao_interrompida_reabre_pendente_sem_perder_historico(tmp_path):
    @contextmanager
    def conectar(*args):
        yield MotorSimulado(["e7e5"])

    respostas = ["Nossa", "", "Outra", "5", "1", "2", "e2e4", EOFError()]
    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_programada(respostas), conectar=conectar) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    campanha = repo.carregar()
    identificador = campanha.confrontos[0].ativa["id"]
    log = Path(campanha.confrontos[0].ativa["arquivo_log"])
    assert "Partida interrompida" in log.read_text(encoding="utf-8")
    assert campanha.confrontos[0].ativa["lances"] == ["e2e4", "e7e5"]
    assert campanha.resumo()["vitorias"] == campanha.resumo()["empates"] == campanha.resumo()["derrotas"] == 0
    assert cli(tmp_path, "iniciar", entrada=entrada_programada([""])) == 0
    assert repo.carregar().confrontos[0].ativa["id"] == identificador
    assert cli(tmp_path, "iniciar", entrada=entrada_programada(["1"])) == 0
    c = repo.carregar().confrontos[0]
    assert c.ativa is None and len(c.partidas) == 1
    assert c.concluidas[0]["id"] == identificador and c.concluidas[0]["resultado"] == "V"
    assert Path(c.concluidas[0]["arquivo_log"]) == log
    assert list((tmp_path / "logs").glob("*.log")) == [log]
    assert "0-1 | Resultado informado" in log.read_text(encoding="utf-8")


def test_sessao_cancelar_cor_nao_abre_motor_nem_cria_partida(tmp_path):
    def proibido(*args):
        pytest.fail("Não abrir o motor antes de informar a cor.")

    assert cli(tmp_path, "iniciar", entrada=entrada_programada(["Nossa", "", "Outra", "1", "1", EOFError()]),
               conectar=proibido) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    assert len(campanha.confrontos) == 1 and not campanha.confrontos[0].partidas


def test_comando_campeonato_encaminha_para_sessao_e_banco_correto(monkeypatch):
    chamadas = []
    monkeypatch.setattr(torneio, "main", lambda args: chamadas.append(args) or 0)
    assert partida.main(["campeonato"]) == 0
    assert chamadas == [["iniciar"]]
    args = torneio.criar_parser().parse_args(["iniciar"])
    assert args.arquivo.name == "campeonato.sqlite3"
    assert (args.modo, args.threads, args.hash_mb) == ("completo", 4, 512)


def test_sessao_unica_empatada_encaminha_armageddon_e_guarda_os_dois_resultados(tmp_path, monkeypatch):
    executar_real = torneio.executar
    monkeypatch.setattr(torneio, "executar", lambda *a, **kw: executar_real(*a, **kw, agora=lambda: 0))
    @contextmanager
    def conectar(*args):
        yield MotorSimulado([])

    respostas = ["Nossa", "", "Outra", "5", "1", "2", "fim", "2", "s"]
    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_da_partida(respostas), conectar=conectar) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    c = repo.carregar().confrontos[0]
    assert len(c.partidas) == 1 and c.situacao(repo.carregar().regras)["status"] == "armageddon"
    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_da_partida(["2", "fim", "2"]), conectar=conectar) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    c = campanha.confrontos[0]
    assert [p["armageddon"] for p in c.concluidas] == [False, True]
    assert [p["resultado"] for p in c.concluidas] == ["E", "E"]
    assert c.situacao(campanha.regras)["status"] == "classificado"


@pytest.mark.parametrize("resposta", ["n", "", EOFError()])
def test_armageddon_sem_confirmacao_nao_cria_partida_nem_abre_motor(tmp_path, resposta):
    campanha = Campanha("Nossa")
    c = campanha.novo_confronto("Outra", formato="unica")
    p = c.iniciar(campanha.regras)
    c.finalizar(p["id"], "1/2-1/2", "Teste", 100, 100)
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    repo.criar(campanha)

    def proibido(*args):
        pytest.fail("Não abrir motor sem confirmação do Armageddon.")

    perguntas = []
    ler = entrada_programada([resposta])

    def entrada(prompt):
        perguntas.append(prompt)
        return ler(prompt)

    assert cli(tmp_path, "iniciar", entrada=entrada, conectar=proibido) == 0
    atual = repo.carregar().confrontos[0]
    assert len(atual.partidas) == 1 and atual.ativa is None
    assert not atual.armageddon_autorizado
    assert atual.situacao(campanha.regras)["status"] == "armageddon"
    assert len(perguntas) == 1 and "Iniciar Armageddon" in perguntas[0]


def test_recusa_ao_fim_e_confirmacao_na_proxima_execucao(tmp_path, monkeypatch):
    executar_real = torneio.executar
    monkeypatch.setattr(torneio, "executar", lambda *a, **kw: executar_real(*a, **kw, agora=lambda: 0))

    @contextmanager
    def conectar(*args):
        yield MotorSimulado([])

    respostas = ["Nossa", "", "Outra", "5", "1", "2", "fim", "2", "n"]
    assert cli(tmp_path, "iniciar", "--modo", "original",
               entrada=entrada_da_partida(respostas), conectar=conectar) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    c = repo.carregar().confrontos[0]
    assert len(c.partidas) == 1 and not c.armageddon_autorizado
    assert cli(tmp_path, "iniciar", "--modo", "original",
               entrada=entrada_da_partida(["s", "2", "fim", "2"]), conectar=conectar) == 0
    campanha = repo.carregar()
    c = campanha.confrontos[0]
    assert len(c.partidas) == 2 and c.partidas[-1]["armageddon"]
    assert c.situacao(campanha.regras)["status"] == "classificado"


def test_log_numerado_nao_sobrescreve_arquivo_de_outra_campanha(tmp_path):
    campanha = Campanha("Nossa")
    c = campanha.novo_confronto("Outra")
    p = c.iniciar(campanha.regras)
    p.update(numero_geral=1, registros=[])
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    pasta = tmp_path / "logs"
    pasta.mkdir()
    caminho = pasta / "partida_001.log"
    caminho.write_text("LOG anterior de outra campanha", encoding="utf-8")
    with pytest.raises(FileExistsError, match="outra partida"):
        torneio.salvar_log_partida(c, p, repo)
    assert caminho.read_text(encoding="utf-8") == "LOG anterior de outra campanha"


@pytest.mark.parametrize("fase", ["1", "2"])
@pytest.mark.parametrize("cor", [True, False])
def test_sessao_unica_empate_e_relogio_maior_decidem_sem_armageddon(tmp_path, monkeypatch, fase, cor):
    instante = [0]
    executar_real = torneio.executar
    monkeypatch.setattr(torneio, "executar", lambda *a, **kw: executar_real(*a, **kw, agora=lambda: instante[0]))
    brancas, pretas = ["g1f3", "f3g1"] * 2, ["g8f6", "f6g8"] * 2
    motor = MotorSimulado(brancas if cor else pretas)
    respostas = entrada_programada(["Nossa", "", "Outra", fase, "1", "1" if cor else "2",
                                     *(pretas if cor else brancas), ""])

    def entrada(prompt):
        resposta = respostas(prompt)
        if "digite o lance" in prompt:
            instante[0] += 1
        return resposta

    @contextmanager
    def conectar(*args):
        yield motor

    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada, conectar=conectar) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    c = campanha.confrontos[0]
    assert len(c.partidas) == 1 and c.ativa is None
    p = c.concluidas[0]
    assert p["resultado"] == "E" and p["saldo_nosso_ms"] > p["saldo_outro_ms"]
    assert c.situacao(campanha.regras)["status"] == ("vitoria" if fase == "1" else "classificado")


def test_duas_execucoes_vencedoras_encerram_confronto_sem_terceiro_jogo(tmp_path):
    motores = iter([MotorSimulado(["e7e5", "d8h4"]), MotorSimulado(["e2e4", "d2d4", "d1h5"])])

    @contextmanager
    def conectar(*args):
        yield next(motores)

    respostas = ["Nossa", "", "Outra", "5", "2", "2", "f2f3", "g2g4"]
    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_da_partida(respostas), conectar=conectar) == 0
    assert len(Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0].partidas) == 1
    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_da_partida(["1", "f7f6", "g7g5"]), conectar=conectar) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    c = campanha.confrontos[0]
    assert [p["resultado"] for p in c.concluidas] == ["V", "V"]
    assert c.situacao(campanha.regras)["status"] == "classificado"


def test_nova_execucao_troca_adversario_preservando_a_partida_anterior(tmp_path):
    @contextmanager
    def conectar(*args):
        yield MotorSimulado(["e7e5", "d8h4"])

    respostas = ["Nossa", "", "Primeiro", "1", "1", "2", "f2f3", "g2g4"]
    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_da_partida(respostas), conectar=conectar) == 0
    assert len(Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos) == 1
    assert cli(tmp_path, "iniciar", "--modo", "original",
               entrada=entrada_da_partida(["Segundo", "1", "1", "2", "f2f3", "g2g4"]), conectar=conectar) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    assert [(c.adversario, c.rodada) for c in campanha.confrontos] == [("Primeiro", 1), ("Segundo", 2)]
    assert campanha.resumo()["vitorias"] == 2
    assert [Path(c.partidas[0]["arquivo_log"]).name for c in campanha.confrontos] == [
        "partida_001.log", "partida_002.log"]
    assert cli(tmp_path, "iniciar", entrada=entrada_programada([""])) == 0
    assert Repositorio(tmp_path / "campanha.sqlite3").carregar().resumo() == campanha.resumo()


def test_queda_do_contador_local_nao_inventa_resultado_oficial(tmp_path, monkeypatch):
    instante = [0]
    executar_real = torneio.executar
    monkeypatch.setattr(torneio, "executar", lambda *a, **kw: executar_real(*a, **kw, agora=lambda: instante[0]))
    respostas = entrada_programada(["Nossa", "", "Outra", "5", "1", "2", "e2e4", ""])

    def entrada(prompt):
        resposta = respostas(prompt)
        if "digite o lance" in prompt:
            instante[0] = 901
        return resposta

    @contextmanager
    def conectar(*args):
        yield MotorSimulado([])

    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada, conectar=conectar) == 0
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0]
    assert not c.concluidas and c.ativa
    assert c.ativa["sugestao_placar"] == "0-1"


def test_sessao_falha_do_motor_preserva_lances_sem_iniciar_outro_jogo(tmp_path):
    @contextmanager
    def conectar(*args):
        yield MotorSimulado([chess.engine.EngineTerminatedError("simulada")])

    respostas = ["Nossa", "", "Outra", "5", "2", "2", "e2e4"]
    assert cli(tmp_path, "iniciar", "--modo", "original", entrada=entrada_programada(respostas), conectar=conectar) == 1
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0]
    assert len(c.partidas) == 1 and not c.concluidas
    assert c.ativa["lances"] == ["e2e4"]


@pytest.mark.motor_real
def test_sessao_real_modo_completo_salva_jogo_sem_comandos_adicionais(tmp_path):
    respostas = ["Nossa", "", "Outra", "5", "1", "1", "e7e5", "fim", "3"]
    assert cli(tmp_path, "iniciar", entrada=entrada_programada(respostas)) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    p = campanha.confrontos[0].concluidas[0]
    assert p["resultado"] == "D" and p["origem"] == "operador"
    assert p["lances"][:2] == ["e2e4", "e7e5"] and len(p["lances"]) == 3
    assert json.loads(p["registros"][0]["detalhes"])["fonte"] == "abertura_preparada"
    assert p["incremento"] == 10 and p["tempo_nosso"] == 900
