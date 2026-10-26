from dataclasses import asdict
from itertools import product

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
    assert campanha.resumo()["pontos"] == 0
    assert campanha.resumo()["empates"] == 0
    with pytest.raises(ValueError):
        c.iniciar(campanha.regras)
    with pytest.raises(ValueError):
        campanha.novo_confronto("Terceira")
    with pytest.raises(ValueError):
        c.finalizar(p["id"], "*", "Limite", 5, 5)


def test_resultado_idempotente_correcao_recalcula_pontos_e_guarda_auditoria():
    campanha = Campanha("Equipe")
    c = campanha.novo_confronto("Outra")
    p = concluir(c, campanha.regras, "V")
    c.finalizar(p["id"], "1-0", "Reenvio", 30, 30)
    assert campanha.resumo()["pontos"] == 3
    with pytest.raises(ValueError):
        c.finalizar(p["id"], "0-1", "Sem correção", 30, 30)
    c.corrigir(p["id"], "Árbitro corrigiu resultado", placar="1/2-1/2", motivo="Empate", saldo_nosso=30, saldo_outro=30)
    assert campanha.resumo()["pontos"] == 1
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
    ("incremento_armageddon", float("inf")), ("rodadas", True), ("vagas", 0)])
def test_regras_invalidas_rejeitadas(nome, valor):
    r = Regras()
    setattr(r, nome, valor)
    with pytest.raises(ValueError):
        r.validar()


def tabela(campanha, pontos):
    campanha.registrar_tabela([dict(equipe=nome, pontos=p, posicao=i + 1)
        for i, (nome, p) in enumerate(zip(("Equipe", "A", "B", "C"), pontos))], 2)


def test_tabela_nao_e_inventada_e_objetivo_so_e_provado_com_regras_confirmadas():
    r = Regras(rodadas=3, vagas=2, equipes=4)
    campanha = Campanha("Equipe", regras=r)
    c = campanha.novo_confronto("Outra", rodada=3)
    tabela(campanha, [6, 6, 0, 0])
    assert campanha.resumo()["posicao_oficial"] == 1
    assert campanha.contexto(c).objetivo == "equilibrado"
    r.classificacao_por_pontos_confirmada = True
    assert campanha.contexto(c).empate_classifica
    c.rodada = 2
    assert campanha.contexto(c).objetivo == "equilibrado"  # Tabela de outra rodada.


def test_tabela_prova_vitoria_necessaria_sem_fabricar_ranking_elo():
    r = Regras(rodadas=3, vagas=2, equipes=4, classificacao_por_pontos_confirmada=True)
    campanha = Campanha("Equipe", regras=r)
    c = campanha.novo_confronto("Outra", rodada=3)
    tabela(campanha, [0, 4, 2, 0])
    assert campanha.contexto(c).evitar_empate
    assert campanha.contexto(c).objetivo == "buscar_vitoria"
    assert campanha.contexto(c, False).objetivo == "equilibrado"


def test_tabela_incompleta_e_pontos_empatados_nao_garantem_vaga():
    r = Regras(rodadas=3, vagas=2, equipes=5, classificacao_por_pontos_confirmada=True)
    campanha = Campanha("Equipe", regras=r)
    c = campanha.novo_confronto("Outra", rodada=3)
    tabela(campanha, [6, 6, 0, 0])
    assert not campanha.contexto(c).empate_classifica
    r.equipes = 4
    campanha.tabelas[-1]["linhas"][2]["pontos"] = 4
    assert not campanha.contexto(c).empate_classifica  # Pode igualar sete pontos.


def test_objetivo_manual_exige_justificativa_e_nao_inventa_empate_classificante():
    c = Confronto("Outra", objetivo_informado="preservar_empate")
    with pytest.raises(ValueError):
        c.validar()
    c.justificativa_objetivo = "Orientação da equipe pela tabela oficial"
    c.validar()
    assert c.contexto(Regras()).objetivo == "preservar_empate"
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
    campanha.regras.pontos_vitoria = 5
    assert c.regras(campanha.regras).tempo == 300
    assert campanha.resumo()["pontos"] == 3


def test_eliminacao_bloqueia_avanco_mas_permite_disputa_de_terceiro_lugar():
    campanha = Campanha("Equipe")
    c = campanha.novo_confronto("Outra", fase="semifinal", formato="unica")
    concluir(c, campanha.regras, "D")
    with pytest.raises(ValueError):
        campanha.novo_confronto("Finalista", fase="final")
    assert campanha.novo_confronto("Terceiro", fase="terceiro-lugar").fase == "terceiro-lugar"
