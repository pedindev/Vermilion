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
            valor = next(respostas)
            if isinstance(valor, BaseException):
                raise valor
            return valor
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
    assert cli(tmp_path, "resultado", "--placar", "0-1", "--motivo", "Mate confirmado", "--nosso-tempo", "295", "--outro-tempo", "294") == 0
    campanha = repo.carregar()
    assert campanha.resumo()["vitorias"] == 1 and "pontos" not in campanha.resumo()
    assert campanha.confrontos[-1].ativa is None
    assert campanha.confrontos[-1].concluidas[0]["origem_relogios"] == "ajuste_oficial_pelo_operador"
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
    assert c.situacao(repo.carregar().regras)["status"] == "empate"


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


@contextmanager
def motor_vazio(*args):
    yield MotorSimulado([])


def executar_sessao(tmp_path, respostas, lances=(), saidas=None):
    @contextmanager
    def conectar(*args):
        yield MotorSimulado(list(lances))
    return cli(tmp_path, "iniciar", "--modo", "original", conectar=conectar,
               entrada=entrada_da_partida(respostas), saida=(saidas.append if saidas is not None else lambda _: None))


def test_comando_unico_mate_salva_relogios_fisicos_e_log_limpo(tmp_path):
    saidas = []
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "1", "2", "f2f3", "g2g4", "02:10.125 01:40.250"],
                           ["e7e5", "d8h4"], saidas) == 0
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0]
    p = c.concluidas[0]
    assert p["lances"] == ["f2f3", "e7e5", "g2g4", "d8h4"]
    assert p["origem"] == "tabuleiro" and p["origem_relogios"] == "fisico_oficial"
    assert (p["saldo_nosso_ms"], p["saldo_outro_ms"]) == (100250, 130125)
    assert p["duracao_prevista_minutos"] is None
    assert p["relogios_sistema"]["brancas"] > 800
    texto = Path(p["arquivo_log"]).read_text(encoding="utf-8")
    assert "SALDOS OFICIAIS DO RELÓGIO FÍSICO" in texto
    assert "Brancas: 130.125s | Pretas: 100.250s" in texto
    assert texto.count("a b c d e f g h") == 4
    linha = next(x for x in texto.splitlines() if "e7e5 | profundidade" in x)
    assert all(campo in linha for campo in ("Pretas", "nós", "avaliação", "PV:", "tempo"))
    assert all(x not in "\n".join(saidas) for x in ("ID ", "Análise:", "Campanha:"))
    assert "Saldos finais do sistema" in "\n".join(saidas)


@pytest.mark.parametrize("fase,formato", [("1", "unica"), ("2", "unica"), ("3", "unica"),
                                          ("4", "melhor-de-tres"), ("5", "melhor-de-tres")])
def test_formato_definido_pela_fase_sem_pergunta_de_duracao(tmp_path, fase, formato):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", fase, "2", "fim", "1", "10 20"]) == 0
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0]
    assert c.formato == formato and len(c.concluidas) == 1


@pytest.mark.parametrize("saldos", ["100 200", "200 100", "100 100"])
def test_classificacao_empate_nao_decide_por_tempo_nem_armageddon(tmp_path, saldos):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "1", "2", "fim", "2", saldos]) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    campanha = repo.carregar()
    assert campanha.confrontos[0].situacao(campanha.regras)["status"] == "empate"
    ctx = campanha.contexto(campanha.confrontos[0])
    assert not ctx.desempate_por_tempo and not ctx.com_relogios(200, 100).empate_classifica
    assert executar_sessao(tmp_path, ["Próximo", "1", "2", "fim", "1", "90 80"]) == 0
    assert len(repo.carregar().confrontos) == 2


def test_desempate_fisico_contrario_ao_contador_interno(tmp_path):
    # Our black local clock is near 900; only white physical balance is larger.
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "2", "2", "fim", "2", "200 100"]) == 0
    campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
    c = campanha.confrontos[0]
    assert c.situacao(campanha.regras)["status"] == "eliminado"
    assert not c.armageddon_autorizado


@pytest.mark.parametrize("cor", ["1", "2"])
def test_armageddon_so_na_proxima_execucao_e_cor_sorteada(tmp_path, cor):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "2", "2", "fim", "2", "100 100", "s"]) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    c = repo.carregar().confrontos[0]
    assert len(c.partidas) == 1 and c.armageddon_autorizado
    lances, entradas = (["e2e4"], ["fim"]) if cor == "1" else ([], ["fim"])
    assert executar_sessao(tmp_path, [cor, *entradas, "2", "50 50"], lances) == 0
    campanha = repo.carregar()
    c = campanha.confrontos[0]
    arm = c.concluidas[-1]
    assert len(c.partidas) == 2 and arm["armageddon"] and arm["incremento"] == 0
    assert sorted((arm["tempo_nosso"], arm["tempo_outro"])) == [240, 300]
    assert c.situacao(campanha.regras)["status"] == ("eliminado" if cor == "1" else "classificado")


@pytest.mark.parametrize("confirmacao", ["n", "", EOFError()])
def test_armageddon_sem_confirmacao_nao_inicia(tmp_path, confirmacao):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "2", "2", "fim", "2", "100 100", confirmacao]) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    c = repo.carregar().confrontos[0]
    assert len(c.partidas) == 1 and not c.armageddon_autorizado
    def proibido(*args):
        pytest.fail("Motor não deve abrir sem autorização.")
    assert cli(tmp_path, "iniciar", entrada=entrada_da_partida(["n"]), conectar=proibido) == 0
    assert len(repo.carregar().confrontos[0].partidas) == 1


def test_melhor_de_tres_alterna_e_desempata_so_apos_confronto(tmp_path):
    for i, cor in enumerate(["2", "1", "2"]):
        inicio = ["Nossa", "Outra", "4"] if i == 0 else []
        lances = ["e2e4"] if cor == "1" else []
        assert executar_sessao(tmp_path, [*inicio, cor, "fim", "2", "100 100", *(["s"] if i == 2 else [])], lances) == 0
        campanha = Repositorio(tmp_path / "campanha.sqlite3").carregar()
        c = campanha.confrontos[0]
        assert len(c.partidas) == i + 1
        assert c.situacao(campanha.regras)["status"] == ("armageddon" if i == 2 else "em_disputa")
    assert [p["cor"] for p in c.partidas] == [False, True, False]


def test_melhor_de_tres_duas_vitorias_encerram_sem_terceira(tmp_path):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "5", "2", "fim", "1", "100 100"]) == 0
    assert executar_sessao(tmp_path, ["1", "fim", "1", "100 100"], ["e2e4"]) == 0
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0]
    assert len(c.partidas) == 2 and c.situacao(Regras())["status"] == "classificado"
    assert executar_sessao(tmp_path, []) == 0


def test_relogio_fisico_obrigatorio_invalido_pendente_e_reabertura(tmp_path):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "2", "2", "f2f3", "g2g4", "nan 20", "10", ""],
                           ["e7e5", "d8h4"]) == 0
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    p = repo.carregar().confrontos[0].ativa
    assert p and p["saldo_nosso_ms"] is None
    assert executar_sessao(tmp_path, ["20.125 30.250"]) == 0
    c = repo.carregar().confrontos[0]
    assert c.ativa is None and len(c.partidas) == 1
    assert c.concluidas[0]["saldo_nosso_ms"] == 30250


def test_resultado_externo_preservado_se_relogios_ficam_pendentes(tmp_path):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "2", "2", "fim", "1", ""]) == 0
    p = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0].ativa
    assert p["encerramento_confirmado"]["placar"] == "0-1"
    assert executar_sessao(tmp_path, ["10 20"]) == 0
    p = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0].concluidas[0]
    assert p["resultado"] == "V"


@pytest.mark.parametrize("alteracao", ["tempo", "incremento", "incremento_armageddon", "encerrar_ao_decidir"])
def test_modo_campeonato_recusa_configuracao_de_teste(tmp_path, alteracao):
    campanha = Campanha("Nossa")
    setattr(campanha.regras, alteracao, False if alteracao == "encerrar_ao_decidir" else 1)
    campanha.novo_confronto("Outra", fase="oitavas", primeira_cor=None)
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    repo.criar(campanha)
    def proibido(*args):
        pytest.fail("Não deve perguntar cor nem abrir motor com regras incompatíveis.")
    assert cli(tmp_path, "iniciar", entrada=proibido, conectar=proibido) == 1
    assert not repo.carregar().confrontos[0].partidas


def test_cadastro_antigo_com_formato_errado_nao_inicia(tmp_path):
    campanha = Campanha("Nossa")
    campanha.novo_confronto("Outra", fase="final", formato="unica", primeira_cor=None)
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    repo.criar(campanha)
    def proibido(*args):
        pytest.fail("Não deve jogar final em partida única.")
    assert cli(tmp_path, "iniciar", entrada=proibido, conectar=proibido) == 1
    assert not repo.carregar().confrontos[0].partidas


def test_legado_com_tempos_sistema_nao_decide_desempate(tmp_path):
    campanha = Campanha("Nossa")
    c = campanha.novo_confronto("Outra", fase="oitavas")
    p = c.iniciar(campanha.regras)
    c.finalizar(p["id"], "1/2-1/2", "Empate", 900, 1)
    p.update(numero_geral=1, origem_relogios="sistema")
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    repo.criar(campanha)
    assert c.situacao(campanha.regras)["status"] == "relogios_pendentes"
    assert executar_sessao(tmp_path, ["1 100"]) == 0
    campanha = repo.carregar()
    assert campanha.confrontos[0].situacao(campanha.regras)["status"] == "eliminado"
    assert campanha.confrontos[0].concluidas[0]["correcoes"]


def test_cor_cancelada_nao_cria_partida(tmp_path):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "1", EOFError()]) == 0
    c = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0]
    assert not c.partidas


def test_alias_campeonato_e_banco_padrao(monkeypatch):
    chamadas = []
    monkeypatch.setattr(torneio, "main", lambda args: chamadas.append(args) or 0)
    assert partida.main(["campeonato"]) == 0
    assert chamadas == [["iniciar"]]
    args = torneio.criar_parser().parse_args(["iniciar"])
    assert args.arquivo.name == "campeonato.sqlite3"
    assert (args.threads, args.hash_mb, args.modo) == (4, 512, "completo")


def test_correcao_desfaz_erro_preserva_auditoria_e_salva_tabuleiro_correto(tmp_path):
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "1", "2", "e2e4", "desfazer",
        "d2d4", "fim", "2", "100 90"], ["e7e5", "d7d5"]) == 0
    p = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0].concluidas[0]
    assert p["lances"] == ["d2d4", "d7d5"]
    assert [r["uci"] for r in p["registros"]] == p["lances"]
    assert p["correcoes_tabuleiro"][0]["lances_anteriores"] == ["e2e4", "e7e5"]
    texto = Path(p["arquivo_log"]).read_text(encoding="utf-8")
    assert "d2d4" in texto and "e2e4" not in texto


@pytest.mark.parametrize("comando", ["fen invalida", "fen 8/8/8/8/8/8/8/8 w - - 0 1",
                                     "lances e2e4 e7e4", "desfazer 0", "desfazer 99"])
def test_correcao_invalida_atomica(comando):
    from chess_challenge.relatorios import registrar_lance
    b = chess.Board()
    r = registrar_lance(b, chess.Move.from_uci("e2e4"), False)
    b.push_uci("e2e4")
    fen = b.fen()
    with pytest.raises(ValueError):
        partida.corrigir_tabuleiro(comando, b, [r], False)
    assert b.fen() == fen and len(b.move_stack) == 1


def test_lista_completa_preserva_repeticoes_e_fen_avisa_limite(tmp_path):
    b, r = partida.corrigir_tabuleiro("lances g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1 f6g8",
                                      chess.Board(), [], True)
    assert b.is_repetition(3) and len(r) == 8
    novo, novos = partida.corrigir_tabuleiro("fen " + b.fen(), b, r, True)
    assert novo.fen() == b.fen() and not novo.is_repetition(3) and novos == []


def test_carrega_fen_valida_no_loop_preserva_raiz_e_auditoria(tmp_path):
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    saidas = []
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "1", "2", "fen " + fen,
        "g1f3", "fim", "2", "100 90"], ["b8c6"], saidas) == 0
    p = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0].concluidas[0]
    assert p["fen_inicial"] == fen
    assert p["lances"] == ["g1f3", "b8c6"]
    assert p["registros"][0]["numero"] == 2
    assert "FEN não recupera repetições" in "\n".join(saidas)
    assert p["correcoes_tabuleiro"]


def test_carrega_historico_terminal_salva_empate_sem_reiniciar(tmp_path):
    hist = "g1f3 g8f6 f3g1 f6g8 g1f3 g8f6 f3g1 f6g8"
    assert executar_sessao(tmp_path, ["Nossa", "Outra", "1", "2", "lances " + hist, "100 90"]) == 0
    p = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0].concluidas[0]
    assert p["resultado"] == "E" and len(p["lances"]) == 8
    assert p["registros"][-1]["profundidade"] is None


def test_correcao_relogio_nao_devolve_tempo_ou_incremento():
    from chess_challenge.relogio import RelogioPartida
    instante = [0]
    r = RelogioPartida(900, 900, 10, lambda: instante[0])
    r.iniciar(True)
    instante[0] = 20
    r.reposicionar(False)
    assert r.saldos() == {True: 880, False: 900}
    instante[0] = 25
    assert r.saldos() == {True: 880, False: 895}


def test_ensaio_classificacao_empate_nao_abre_armageddon(tmp_path, monkeypatch):
    chamadas = []
    @contextmanager
    def conectar(*args):
        yield SimpleNamespace(id={"name": "simulado"})
    def disputar(*args, **kwargs):
        chamadas.append(1)
        return automatico.Resultado(True, "1/2-1/2", "Repetição", 8, {True: 200, False: 200})
    monkeypatch.setattr(automatico, "disputar", disputar)
    monkeypatch.setattr(automatico, "grupos_cpu", lambda: None)
    banco = tmp_path / "simulacao.sqlite3"
    assert automatico.main(["--formato", "classificacao", "--campanha", str(banco)],
        entrada=entrada_programada(["n"]), emitir=lambda _: None, conectar=conectar, pasta_logs=tmp_path) == 0
    campanha = Repositorio(banco).carregar()
    assert chamadas == [1]
    assert campanha.confrontos[0].situacao(campanha.regras)["status"] == "empate"


def test_log_nao_sobrescreve_outra_partida(tmp_path):
    campanha = Campanha("Nossa")
    c = campanha.novo_confronto("Outra")
    p = c.iniciar(campanha.regras)
    p["numero_geral"] = 1
    caminho = tmp_path / "logs" / "partida_001.log"
    caminho.parent.mkdir()
    caminho.write_text("Outra partida", encoding="utf-8")
    with pytest.raises(FileExistsError):
        torneio.salvar_log_partida(c, p, Repositorio(tmp_path / "campanha.sqlite3"))
    assert caminho.read_text() == "Outra partida"


@pytest.mark.motor_real
def test_sessao_real_completo_book_e_saldos_fisicos(tmp_path):
    assert cli(tmp_path, "iniciar", entrada=entrada_da_partida(
        ["Nossa", "Outra", "2", "1", "e7e5", "fim", "3", "800 810"])) == 0
    p = Repositorio(tmp_path / "campanha.sqlite3").carregar().confrontos[0].concluidas[0]
    assert p["resultado"] == "D" and p["origem_relogios"] == "fisico_oficial"
    assert json.loads(p["registros"][0]["detalhes"])["fonte"] == "abertura_preparada"
