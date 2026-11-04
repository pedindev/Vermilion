# Vermilion - III Chess Challenge

Controlador Python local com Stockfish 19, seletor de lances orientado ao confronto,
antecipação durante o turno adversário e histórico SQLite. A contribuição própria
é experimental: os testes funcionais não demonstram ganho de Elo ou garantem vitória.

## Instalação no Windows

Python 3.13, Git Bash e Stockfish 19 instalados antes do evento. Na raiz do clone:

```bash
cd projeto
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

Baixe o executável no [site oficial do Stockfish](https://stockfishchess.org/download/)
e coloque-o em `stockfish/stockfish-windows-x86-64-universal.exe`, na raiz.
Pode também indicar `--motor "D:/caminho/stockfish.exe"`. O executável não é
distribuído no Git. Os [fontes originais completos](terceiros/stockfish/) estão incluídos.
Não há download, API ou consulta externa durante as partidas.

## Jogar no campeonato

```bash
cd /d/XADREZ/projeto && ./.venv/Scripts/python.exe -X utf8 jogar.py campeonato
```

**Uma execução joga uma partida.** Repita o mesmo comando para a próxima partida.
Na primeira utilização informe o nome da equipe; depois informe adversário, fase
e nossa cor. Não é perguntada duração total da partida. O formato é definido
pela fase: classificação, oitavas e quartas em partida única; semifinal e final
em melhor de três. A opção legada de terceiro lugar só deve ser usada se houver
orientação expressa da organização; o manual não define uma disputa separada.

Digite somente o lance adversário em UCI (`e7e5`, `e1g1`, `e7e8q`). O software
calcula e aplica nossos lances, mostrando o tabuleiro após cada jogada.
Anuncie o lance, aguarde a repetição pelo adversário, mova a peça e acione o
relógio físico. O tabuleiro e o relógio físicos são a referência oficial.
O contador interno é uma estimativa: a troca automática de turno no software
não observa o instante em que a equipe aciona o relógio físico.

**Ritmo normal: 15 minutos por equipe +10 segundos por lance.** Sem limite total
separado por partida ou rodada. Quatro threads e 512 MB de hash por padrão.
O Stockfish distribui sua análise pelos saldos disponíveis; não há tempo fixo por lance.
Reserve tempo para digitação, anúncio, confirmação e movimento físico; tudo
é descontado no relógio físico. É possível sincronizar as estimativas pelo comando abaixo.

### Comandos durante a partida

No campo de lance adversário:

| Entrada | Função |
| --- | --- |
| `e7e5` | Registra o lance adversário e calcula nossa resposta |
| `fim` | Encerra a sessão de jogo para registrar o resultado do árbitro |
| `relogios 14:30.250 14:05.125` | Ajusta os contadores, sempre BRANCAS PRETAS |
| `desfazer` | Desfaz os últimos dois meios-lances, normalmente adversário e nossa resposta |
| `desfazer 1` | Desfaz exatamente um meio-lance |
| `lances e2e4 e7e5 g1f3` | Reconstrói a partida com o histórico UCI completo desde o início |
| `fen POSICAO_FEN` | Carrega uma FEN válida; não recupera repetições anteriores |

Correções são validadas antes de alterar o tabuleiro, interrompem a antecipação
antiga e ficam auditadas no banco. Não devolvem tempo nem concedem incremento.
Prefira a lista completa de lances para preservar repetição e regra dos 50 lances.
Depois de corrigir, sincronize os contadores com o relógio físico quando necessário.
Não reinicie o programa para corrigir um erro: o manual exige mantê-lo aberto.

### Encerramento e desempates

Ao terminar, informe **os saldos finais do relógio físico anotados pelo árbitro**,
na ordem BRANCAS PRETAS, por exemplo `02:10.125 01:40.250`. Enter deixa o registro
pendente; nenhum desempate é decidido com contadores internos. O resultado de
mate/empate no tabuleiro é reconhecido; em encerramento externo, informe também
vitória, empate ou derrota. Confirme qualquer divergência com a arbitragem.

- Classificação: empate continua empate. Sem desempate por tempo ou Armageddon.
- Oitavas/quartas: empate é decidido pelo maior saldo físico; igualdade leva a Armageddon.
- Semifinal/final: cores alternadas, terceira repete a primeira. Encerra assim que
  o adversário não puder alcançar o placar. Somente se o confronto terminar empatado
  compara a soma dos saldos físicos das partidas disputadas; igualdade leva a Armageddon.
- Armageddon: o sistema pergunta se deseja autorizar para a próxima execução.
  Não inicia automaticamente. Na próxima execução, informe a cor sorteada oficialmente.
  Brancas 5 minutos, pretas 4 minutos, sem incremento; empate classifica pretas.

Cinco rodadas classificatórias; 16 melhores no ELO avançam. A organização calcula
ELO, faz pareamentos e decide quem avança. O software guarda resultados e não
inventa ranking ou pontuação 3/1/0. Uma partida adicional por igualdade de ELO
pode ser registrada como novo confronto de classificação conforme o pareamento.

### Histórico e entrega dos LOGs

Banco: `projeto/dados/campeonato.sqlite3`. Preserve-o entre execuções.
Cada partida gera `projeto/dados/logs/partida_001.log`, `partida_002.log`, etc.
O LOG mostra jogadas UCI com jogador, cor e tabuleiro. Na seção técnica há uma
linha completa por lance: número, cor, UCI, profundidade, nós, avaliação, PV e tempo.
Avaliação na perspectiva das brancas. Métricas do motor adversário ficam `N/D`.
Jogadas do book são identificadas; sua análise prévia não é apresentada como busca ao vivo.
Saldos físicos oficiais ficam separados dos contadores do sistema.
**Entregue o LOG à banca ao final de cada partida**, por exemplo em pen drive.
Os dados reais e LOGs não são publicados no GitHub.

Sessão interrompida ou entrada dos saldos incompleta fica pendente. Ao executar
novamente, o programa recolhe as informações restantes e encerra, sem começar
outra partida nessa execução. Software travado/falha implica derrota conforme
o manual; salvar o histórico não constitui autorização para retomar um jogo.

### Opções opcionais

Acrescente ao comando: `--threads 4`, `--hash 512`, `--sem-abertura`,
`--motor "D:/caminho/stockfish.exe"` ou `--arquivo "dados/outro/campeonato.sqlite3"`.
Use outra pasta de dados para ensaios, preservando o banco do campeonato.
O padrão `--modo completo` ativa a contribuição decisória. `--modo original`
e `--modo ponderacao` são modos de comparação, não a configuração autoral principal.

## Autoria e arquitetura

- `projeto/jogar.py`: entrada única.
- `chess_challenge/partida.py`: turnos, UCI, tabuleiro e correções.
- `torneio.py`: operação, saldos físicos finais, salvamento e relatórios.
- `campanha.py`: resultados, melhor de três, desempates e persistência transacional.
- `inteligencia.py`: **componente autoral**, coordena antecipação e verificação de candidatos.
- `estrategia.py`: **seleção autoral**, compara alternativas próximas e defesas conforme
  a situação do confronto. Pode escolher outro lance após verificação; respeita mates.
  Na classificação não trata maior saldo como vitória. Nas eliminatórias o saldo
  interno é apenas estimativa para planejamento; resultado usa saldos físicos oficiais.
- `motor.py`: protocolo UCI, parâmetros e análise do Stockfish.
- `aberturas.py/json`: repertório local, no máximo dez meios-lances (cinco de cada cor).
- `relogio.py`: contadores locais; `relatorios.py`: LOG e tabuleiro legível.

Histórico de commits, código e decisões registradas permitem defender a autoria.
Todos os três integrantes devem saber explicá-la na arguição. Não há relatório
ou apresentação formal adicional obrigatório. A validação cabe à organização.

## Origem e recursos

Base: **Stockfish 19**, tag `sf_19`, commit
`edb0d9db6731067ec50ce619ff372b463bc4dd5d`, sem alterações em C++ ou NNUE.
[Fontes incluídos](terceiros/stockfish/) e [origem, licença e créditos](STOCKFISH.md).
O diretório de terceiros mantém seu README, AUTHORS, Copying.txt, scripts e fontes originais.

Book: `projeto/chess_challenge/aberturas.json`, preparado offline com Stockfish 19;
origem e análises constam no JSON. É preparação derivada do motor, não a contribuição
autoral reivindicada. Sai da preparação ao atingir dez meios-lances ou desviar da linha.
NNUE: rede original do Stockfish `nn-1a298aa575a0.nnue`; não treinada pela equipe.
Tablebases não são usadas (`SyzygyPath` vazio, limite configurado em cinco peças).
GPU não é utilizada. Bibliotecas declaradas em `requirements.txt` e `requirements-dev.txt`.

Notebook: Acer Nitro 5, Ryzen 7 5800H, 16 GB RAM, Windows. Um notebook por equipe.
Dependências, executável e book instalados antes do evento. Wi-Fi e dados móveis
desligados durante as partidas. A versão Linux de distribuição foi cancelada.

## Testes

Na pasta `projeto`, Git Bash:

```bash
./.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider tests
./.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider tests --motor-real
```

Ambiente de campeonato, ritmo de teste **5+1**, quatro threads/512 MB para ambos:

```bash
./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --tempo 300 --incremento 1 --threads 4 --hash 512
```

Ensaio padrão: melhor de três. Opções: `--formato classificacao` (sem desempate),
`--formato unica --fase oitavas`, `--formato armageddon`, `--formato pares`.
Armageddon de teste também sem incremento, 300/240 segundos. Os saldos no ensaio
são simulados por relógios locais e identificados como simulação; nunca substituir
os saldos físicos em jogos reais. TXT da bateria só é exportado com autorização.
Testes não garantem força competitiva nem ausência de falhas.

Validação em 04/11/2026 após a revisão do manual: **316 testes passaram**,
incluindo dez integrações com o Stockfish real. Foram verificados classificação
sem desempate, formatos por fase, melhor de três, saldos físicos, Armageddon,
correções de tabuleiro, histórico de repetição, LOGs e comunicação com o motor.
O ensaio real 5+1 dessa bateria é curto; não equivale a um confronto completo.

## Entrega e regras oficiais

O [Manual do Participante](documentos/Manual%20do%20Participante%20-%20III%20Chess%20Challenge.pdf)
prevalece sobre o edital e FAQ anteriores. Enviar **até 04/11/2026, 23h59** para
**coordenacao.engsoftware@somosicev.com**, com nome da equipe e link do GitHub.
Pode ser público ou privado; se privado, compartilhar com **dimmykarson**.
O envio e a validação são obrigatórios. Não é necessário enviar executável.
Declare Stockfish e o commit de origem no credenciamento de 06/11.

Código sob [GPLv3](LICENSE); Stockfish mantém os créditos dos seus autores.
