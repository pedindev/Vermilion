from dataclasses import asdict
from itertools import product
from contextlib import closing
import json
import sqlite3

import chess
import pytest

from chess_challenge.campanha import Campanha, Confronto, Contexto, Regras, Repositorio


def concluir(c, regras, resultado="E", nosso=30, outro=30):
    p = c.iniciar(regras)
    placar = "1/2-1/2" if resultado == "E" else "1-0" if (resultado == "V") == p["cor"] else "0-1"
    c.finalizar(p["id"], placar, "Resultado confirmado", nosso, outro)
    return p


@pytest.mark.parametrize("cor,resultados", list(product((True, False), product("VED", repeat=3))))
def test_todos_os_placares_da_melhor_de_tres_e_cores(cor, resultados):
    r = Regras(encerrar_ao_decidir=False)
    c = Confronto("Outra equipe", "semifinal", formato="melhor-de-tres", primeira_cor=cor)
    partidas = [concluir(c, r, x) for x in resultados]
    assert [p["cor"] for p in partidas] == [cor, not cor, cor]
    diferenca = resultados.count("V") - resultados.count("D")
    esperado = "classificado" if diferenca > 0 else "eliminado" if diferenca < 0 else "armageddon"
    assert c.situacao(r)["status"] == esperado
    assert c.situacao(r)["saldos"] == [90, 90]


@pytest.mark.parametrize("primeiro,segundo,objetivo,empate,evitar", [
    ("V", "E", "preservar_empate", True, False),
    ("D", "E", "buscar_vitoria", False, True),
    ("V", "D", "equilibrado", False, False),
    ("E", "E", "equilibrado", False, False),
])
def test_objetivo_da_terceira_partida(primeiro, segundo, objetivo, empate, evitar):
    r = Regras()
    c = Confronto("Outra", "final", formato="melhor-de-tres")
    concluir(c, r, primeiro)
    concluir(c, r, segundo)
    ctx = c.contexto(r)
    assert (ctx.objetivo, ctx.empate_classifica, ctx.evitar_empate) == (objetivo, empate, evitar)
    if empate:
        assert c.contexto(r, False).evitar_empate


def test_vencer_primeira_nao_faz_empate_segunda_classificar():
    r = Regras()
    c = Confronto("Outra", "final", formato="melhor-de-tres")
    concluir(c, r, "V")
    assert c.contexto(r).objetivo == "proteger_vantagem"
    assert not c.contexto(r).empate_classifica
    concluir(c, r, "V")
    assert c.situacao(r)["status"] == "classificado"
    with pytest.raises(ValueError):
        c.iniciar(r)


@pytest.mark.parametrize("nosso,outro,esperado", [(10.001, 10, "classificado"), (10, 10.001, "eliminado"), (10, 10, "armageddon")])
def test_desempate_por_soma_dos_tres_relogios(nosso, outro, esperado):
    r = Regras()
    c = Confronto("Outra", "final", formato="melhor-de-tres")
    for _ in range(3):
        concluir(c, r, nosso=nosso, outro=outro)
    assert c.situacao(r)["status"] == esperado


def test_falta_de_relogio_nao_inventa_empate_dos_tempos():
    r = Regras()
    c = Confronto("Outra", "final", formato="melhor-de-tres")
    for _ in range(3):
        concluir(c, r, nosso=None)
    assert c.situacao(r)["status"] == "relogios_pendentes"
    with pytest.raises(ValueError):
        c.iniciar(r)


@pytest.mark.parametrize("cor,resultado", list(product((True, False), "VED")))
def test_armageddon_tempos_objetivo_e_classificacao_separada(cor, resultado):
    r = Regras(tempo=300, incremento=1)
    campanha = Campanha("Equipe", regras=r)
    c = campanha.novo_confronto("Outra", fase="final", formato="melhor-de-tres")
    for _ in range(3):
        concluir(c, r)
    with pytest.raises(ValueError):
        c.iniciar(r)
    c.cor_armageddon = cor
    ctx = c.contexto(r)
    assert ctx.armageddon and ctx.empate_classifica == (not cor)
    assert ctx.evitar_empate == cor
    p = concluir(c, r, resultado)
    assert (p["tempo_nosso"], p["tempo_outro"], p["incremento"]) == ((300, 240, 0) if cor else (240, 300, 0))
    passou = resultado == "V" or (resultado == "E" and not cor)
    assert c.situacao(r)["status"] == ("classificado" if passou else "eliminado")
    assert campanha.resumo()["empates"] == 3 + (resultado == "E")


def test_interrupcao_nao_pontua_e_bloqueia_nova_partida():
    campanha = Campanha("Equipe")
    c = campanha.novo_confronto("Outra")
    p = c.iniciar(campanha.regras)
    p["status"] = "inconclusiva"
    assert "pontos" not in campanha.resumo()
    assert campanha.resumo()["empates"] == 0
    with pytest.raises(ValueError):
        c.iniciar(campanha.regras)
    with pytest.raises(ValueError):
        campanha.novo_confronto("Terceira")
    with pytest.raises(ValueError):
        c.finalizar(p["id"], "*", "Limite", 5, 5)


def test_resultado_idempotente_correcao_recalcula_resultados_e_guarda_auditoria():
    campanha = Campanha("Equipe")
    c = campanha.novo_confronto("Outra")
    p = concluir(c, campanha.regras, "V")
    c.finalizar(p["id"], "1-0", "Reenvio", 30, 30)
    assert campanha.resumo()["vitorias"] == 1
    with pytest.raises(ValueError):
        c.finalizar(p["id"], "0-1", "Sem correção", 30, 30)
    c.corrigir(p["id"], "Árbitro corrigiu resultado", placar="1/2-1/2", motivo="Empate", saldo_nosso=30, saldo_outro=30)
    assert campanha.resumo()["empates"] == 1
    assert campanha.resumo()["vitorias"] == 0
    assert p["correcoes"][0]["anterior"]["placar"] == "1-0"


def test_correcao_anterior_nao_mantem_armageddon_incompativel():
    r = Regras()
    c = Confronto("Outra", "final", formato="melhor-de-tres")
    for _ in range(3):
        concluir(c, r)
    c.cor_armageddon = False
    concluir(c, r)
    c.corrigir(c.partidas[0]["id"], "Revisão oficial", placar="1-0", motivo="Vitória", saldo_nosso=30, saldo_outro=30)
    assert c.situacao(r)["status"] == "revisao_pendente"


def test_persistencia_reabre_historico_e_impede_duas_sessoes(tmp_path):
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    original = Campanha("Equipe")
    repo.criar(original)
    a, b = repo.carregar(), repo.carregar()
    c = a.novo_confronto("Outra")
    p = c.iniciar(a.regras)
    p["lances"] = ["e2e4", "e7e5"]
    board = chess.Board()
    for uci in p["lances"]:
        board.push_uci(uci)
    p["fen_atual"] = board.fen()
    repo.salvar(a)
    assert repo.carregar().confrontos[0].ativa["lances"] == p["lances"]
    with pytest.raises(ValueError, match="Outra sessão"):
        repo.salvar(b)
    with pytest.raises(ValueError):
        repo.criar(Campanha("Não sobrescrever"))
    assert repo.carregar().equipe == "Equipe"


def test_banco_rejeita_historico_ilegal_sem_perder_estado_anterior(tmp_path):
    repo = Repositorio(tmp_path / "campanha.sqlite3")
    campanha = Campanha("Equipe")
    repo.criar(campanha)
    c = campanha.novo_confronto("Outra")
    p = c.iniciar(campanha.regras)
    p["lances"] = ["e2e5"]
    with pytest.raises(ValueError):
        repo.salvar(campanha)
    assert repo.carregar().confrontos == []


@pytest.mark.parametrize("nome,valor", [("tempo", 0), ("tempo", float("nan")), ("incremento", -1),
    ("incremento_armageddon", float("inf")), ("duracao_prevista_minutos", True), ("duracao_prevista_minutos", 0)])
def test_regras_invalidas_rejeitadas(nome, valor):
    r = Regras()
    setattr(r, nome, valor)
    with pytest.raises(ValueError):
        r.validar()


def test_banco_antigo_preserva_tabelas_sem_usar_pontuacao(tmp_path):
    repo = Repositorio(tmp_path / "antigo.sqlite3")
    campanha = Campanha("Equipe")
    campanha.novo_confronto("Outra", rodada=3)
    repo.criar(campanha)
    antigas = dict(pontos_vitoria=3, pontos_empate=1, pontos_derrota=0,
                   rodadas=3, vagas=2, equipes=4, classificacao_por_pontos_confirmada=True)
    tabela = [dict(rodada=2, linhas=[dict(equipe="Equipe", posicao=1, pontos=900)])]
    with closing(sqlite3.connect(repo.caminho)) as banco, banco:
        dados = json.loads(banco.execute("SELECT dados FROM campanha").fetchone()[0])
        dados["regras"].update(antigas)
        dados["confrontos"][0]["regras_aplicadas"].update(antigas)
        dados["tabelas"] = tabela
        banco.execute("UPDATE campanha SET dados=?", (json.dumps(dados),))
    atual = repo.carregar()
    assert atual.regras.legado == antigas and atual.tabelas == tabela
    assert atual.contexto(atual.confrontos[0]).objetivo == "equilibrado"
    assert not atual.contexto(atual.confrontos[0]).empate_classifica
    assert not {"pontos", "pontos_oficiais", "posicao_oficial", "tabela"} & atual.resumo().keys()
    repo.salvar(atual)
    reaberta = repo.carregar()
    assert reaberta.tabelas == tabela and reaberta.regras.legado == antigas
    assert reaberta.confrontos[0].regras(reaberta.regras).legado == antigas


def test_objetivo_legado_da_tabela_nao_influencia_a_partida():
    c = Confronto("Outra", objetivo_informado="preservar_empate")
    with pytest.raises(ValueError):
        c.validar()
    c.justificativa_objetivo = "Orientação da equipe pela tabela oficial"
    c.validar()
    assert c.contexto(Regras()).objetivo == "equilibrado"
    assert not c.contexto(Regras()).empate_classifica


def test_terceira_empatada_considera_relogios_sem_promessa_de_classificacao():
    r = Regras()
    c = Confronto("Outra", "final", formato="melhor-de-tres")
    concluir(c, r)
    concluir(c, r)
    ctx = c.contexto(r)
    assert ctx.com_relogios(100, 200).evitar_empate
    favoravel = ctx.com_relogios(200, 100)
    assert favoravel.objetivo == "preservar_empate" and not favoravel.empate_classifica
    assert ctx.com_relogios(100, None).objetivo == "equilibrado"


def test_regras_historicas_nao_mudam_quando_configuramos_proximo_confronto():
    campanha = Campanha("Equipe", regras=Regras(tempo=300, incremento=1))
    c = campanha.novo_confronto("Outra")
    concluir(c, campanha.regras, "V")
    campanha.regras.tempo = 900
    assert c.regras(campanha.regras).tempo == 300
    assert campanha.resumo()["vitorias"] == 1


def test_eliminacao_bloqueia_avanco_mas_permite_disputa_de_terceiro_lugar():
    campanha = Campanha("Equipe")
    c = campanha.novo_confronto("Outra", fase="semifinal", formato="unica")
    concluir(c, campanha.regras, "D")
    with pytest.raises(ValueError):
        campanha.novo_confronto("Finalista", fase="final")
    assert campanha.novo_confronto("Terceiro", fase="terceiro-lugar").fase == "terceiro-lugar"


@pytest.mark.parametrize("fase,cor,resultado", list(product(
    ("classificacao", "oitavas", "quartas", "semifinal", "final", "terceiro-lugar"),
    (True, False), "VED")))
def test_partida_unica_empatada_e_tempos_iguais_tem_um_armageddon_em_qualquer_fase(fase, cor, resultado):
    campanha = Campanha("Equipe", regras=Regras(duracao_prevista_minutos=25))
    c = campanha.novo_confronto("Outra", fase=fase)
    normal = concluir(c, campanha.regras, "E", nosso=10.001, outro=10.001)
    assert normal["duracao_prevista_minutos"] == 25
    assert (normal["tempo_nosso"], normal["tempo_outro"], normal["incremento"]) == (900, 900, 10)
    assert c.situacao(campanha.regras)["status"] == "armageddon"
    c.cor_armageddon = cor
    arm = concluir(c, campanha.regras, resultado)
    assert arm["armageddon"] and arm["incremento"] == 0
    assert sorted((arm["tempo_nosso"], arm["tempo_outro"])) == [240, 300]
    ganhou = resultado == "V" or (resultado == "E" and not cor)
    esperado = ("vitoria" if ganhou else "derrota") if fase == "classificacao" else ("classificado" if ganhou else "eliminado")
    assert c.situacao(campanha.regras)["status"] == esperado
    assert campanha.resumo()["empates"] == 1 + (resultado == "E")
    with pytest.raises(ValueError):
        c.iniciar(campanha.regras)
    if fase == "classificacao":
        assert campanha.novo_confronto("Próxima equipe")


@pytest.mark.parametrize("fase", ("classificacao", "oitavas", "quartas", "semifinal", "final", "terceiro-lugar"))
@pytest.mark.parametrize("nosso,outro,ganhou", [(10.001, 10, True), (10, 10.001, False)])
def test_unica_empatada_decide_por_tempo_antes_do_armageddon(fase, nosso, outro, ganhou):
    campanha = Campanha("Equipe")
    c = campanha.novo_confronto("Outra", fase=fase)
    p = concluir(c, campanha.regras, "E", nosso=nosso, outro=outro)
    situacao = c.situacao(campanha.regras)
    esperado = ("vitoria" if ganhou else "derrota") if fase == "classificacao" else ("classificado" if ganhou else "eliminado")
    assert situacao["status"] == esperado and situacao["criterio"] == "Soma dos relógios finais"
    assert p["resultado"] == "E" and campanha.resumo()["empates"] == 1
    with pytest.raises(ValueError):
        c.iniciar(campanha.regras)


def test_unica_sem_saldos_finais_fica_pendente_sem_inventar_armageddon():
    c, regras = Confronto("Outra", "oitavas"), Regras()
    concluir(c, regras, "E", nosso=None, outro=None)
    assert c.situacao(regras)["status"] == "relogios_pendentes"
    with pytest.raises(ValueError):
        c.iniciar(regras)


@pytest.mark.parametrize("fase", ("classificacao", "oitavas", "final"))
def test_contexto_da_unica_usa_apenas_relogios_do_confronto_atual(fase):
    campanha = Campanha("Equipe")
    concluir(campanha.novo_confronto("Anterior"), campanha.regras, "D", nosso=1, outro=800)
    c = campanha.novo_confronto("Atual", fase=fase)
    ctx = campanha.contexto(c)
    assert ctx.desempate_por_tempo and ctx.saldo_acumulado == 0
    assert ctx.com_relogios(100, 100).objetivo == "equilibrado"
    atras = ctx.com_relogios(100, 200)
    assert atras.objetivo == "buscar_vitoria" and atras.evitar_empate
    frente = ctx.com_relogios(200, 100)
    assert frente.objetivo == "preservar_empate" and not frente.empate_classifica
    assert not ctx.com_relogios(100, None).evitar_empate


@pytest.mark.parametrize("rodadas", (1, 3, 5))
def test_classificacao_nao_elimina_por_derrota_nem_fixa_numero_de_rodadas(rodadas):
    campanha = Campanha("Equipe")
    for rodada in range(1, rodadas + 1):
        c = campanha.novo_confronto(f"Equipe {rodada}", rodada=rodada)
        concluir(c, campanha.regras, "D")
        assert c.situacao(campanha.regras)["status"] == "derrota"
    eliminatoria = campanha.novo_confronto("Oitavas", fase="oitavas", rodada=rodadas + 1)
    concluir(eliminatoria, campanha.regras, "D")
    with pytest.raises(ValueError):
        campanha.novo_confronto("Quartas", fase="quartas")


def test_armageddon_antigo_incompativel_com_saldos_nao_apaga_historico():
    c, regras = Confronto("Outra", "final"), Regras()
    p = concluir(c, regras, "E", nosso=30, outro=30)
    c.cor_armageddon = False
    arm = concluir(c, regras, "E")
    c.corrigir(p["id"], "Correção do relógio oficial", placar="1/2-1/2", motivo="Empate",
               saldo_nosso=30, saldo_outro=40)
    assert c.situacao(regras)["status"] == "revisao_pendente"
    assert len(c.concluidas) == 2 and c.concluidas[-1]["id"] == arm["id"]


def test_melhor_de_tres_nao_tem_armageddon_entre_as_partidas():
    c, regras = Confronto("Outra", "final", formato="melhor-de-tres"), Regras()
    for _ in range(2):
        concluir(c, regras)
        assert c.situacao(regras)["status"] == "em_disputa"
    concluir(c, regras)
    assert c.situacao(regras)["status"] == "armageddon"


def test_cache_de_validacao_detecta_alteracao_no_historico_e_no_fen():
    from chess_challenge.campanha import validar_historico
    c, regras = Confronto("Outra"), Regras()
    p = c.iniciar(regras)
    board = chess.Board()
    board.push_uci("e2e4")
    p.update(lances=["e2e4"], fen_atual=board.fen())
    c.validar()
    hits = validar_historico.cache_info().hits
    c.validar()
    assert validar_historico.cache_info().hits > hits
    p["lances"][0] = "e2e5"
    with pytest.raises(ValueError):
        c.validar()
    p["lances"][0] = "e2e4"
    p["fen_atual"] = chess.STARTING_FEN
    with pytest.raises(ValueError):
        c.validar()
