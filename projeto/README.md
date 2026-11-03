# Chess Challenge — campanha e partidas locais

Python com Stockfish 19, quatro threads e 512 MB de hash por motor.
A seleção considera o confronto atual, seus resultados e o Armageddon.
Não usamos pontuação, ELO ou posição em tabela para escolher lances.

## Jogar no campeonato

Um único comando no Git Bash:

    cd /d/XADREZ/projeto && ./.venv/Scripts/python.exe -X utf8 jogar.py campeonato

Na primeira vez, informe a equipe e a duração prevista (opcional). Depois,
informe adversário, fase, formato e cor pelas perguntas da tela. O banco existente
em `dados/campeonato.sqlite3` é reaproveitado; não precisa recriar a campanha.
A duração prevista é apenas agenda: os relógios normais continuam em 15+10.

Digite somente os lances adversários em UCI. O programa joga por nossa equipe,
mostra cada lance e o tabuleiro, mantém os relógios e salva todos os dados.
A tela omite IDs, configurações e diagnósticos extensos; as análises continuam
registradas no banco. O modo completo usa quatro threads e 512 MB de hash.

Mate e empates reconhecidos pelo tabuleiro são registrados automaticamente.
Cada execução acompanha UMA partida, salva seus dados e encerra. A próxima
partida exige uma nova execução do mesmo comando, inclusive na melhor de três
e no Armageddon. O histórico é recuperado para calcular o contexto da partida.
A pergunta da cor precede o início dos relógios; responda quando puder começar.
Na melhor de três, verifica a alternância; no Armageddon, informe a cor sorteada.

Se houver desistência, acordo ou encerramento pelo árbitro, digite `fim` no campo
do lance adversário. Informe vitória nossa, empate ou derrota nossa na própria
tela. Queda do contador local também pede o resultado oficial, pois o relógio
físico é a referência. Uma interrupção não é contabilizada como empate ou derrota.

Para sincronizar os saldos durante o jogo, use no campo do lance:

    relogios 14:30.250 14:05.125

A ordem é BRANCAS e PRETAS. O ajuste não joga nem adiciona incremento.
O contador local não lê o relógio físico e pode diferir dele pelo tempo de operação.

Ao terminar a partida, o programa encerra. Reabra com o mesmo comando quando
for jogar novamente: resultados e confrontos ainda abertos são preservados.
Uma partida interrompida fica pendente de resultado oficial, sem retomada
automática do tabuleiro. Se o programa pedir um resultado antes de cadastrar
um adversário, encontrou uma partida pendente no banco existente.

As instruções de operação também estão no [README principal](../README.md).
Os subcomandos `campanha criar`,
`confronto`, `jogar`, `resultado`, `regras` e `arbitragem` continuam disponíveis
para manutenção e compatibilidade, mas não são necessários na operação normal.

## Formatos e desempates

- Partida única empatada: vence o maior tempo restante; se os saldos forem
  iguais, um Armageddon. Vale na classificação e nas eliminatórias.
- Melhor de três: nenhum Armageddon entre as partidas. Placar decidido pode
  encerrar o confronto; `campanha regras --tres-obrigatorias sim` exige três jogos.
- Empate no placar depois das três: vence a maior soma dos tempos finais.
  Se também forem iguais, um Armageddon. Saldos ausentes deixam a decisão pendente.
- Armageddon: brancas com 5 minutos, pretas com 4, sem incremento.
  Empate dá o confronto às pretas; o resultado da partida continua registrado
  como empate. A cor vem do sorteio oficial.
- Quando os critérios indicarem Armageddon, o sistema pergunta se deseja
  autorizá-lo para a próxima execução. `n` ou Enter mantém a pendência; `s`
  salva a autorização. Ao reabrir, informe a cor sorteada antes de iniciar os
  relógios. Sem autorização anterior, a confirmação é pedida antes da cor.
- Tripla repetição e regra dos 50 lances atingidas são automáticas.
- A duração prevista na agenda não decide resultado nem interrompe cálculos.
- Na classificação, perder um confronto não impede cadastrar o seguinte.
  Nas eliminatórias, é necessário respeitar a eliminação ou uma decisão oficial.

Essas definições incorporam as orientações da equipe de 01/11/2026.
O FAQ original permanece em `../documentos/rules.txt`.

A organização define rodadas, grupos, pontos, vagas e os classificados. O sistema
registra os confrontos recebidos, permite continuar após derrotas na classificação
e respeita a eliminação na fase seguinte. Não fixa três rodadas nem dois classificados
por grupo. A fase e o formato são informados no início de cada confronto.

Na partida única, o contexto considera o saldo de tempo a cada decisão: um empate
pode ser desfavorável quando estamos atrás no relógio. O seletor só considera
alternativas verificadas e mantém a busca principal do Stockfish. Na melhor de
três, também considera os resultados anteriores do mesmo confronto. O registro
da partida continua sendo empate mesmo quando o tempo decide quem vence o confronto.

## O que é salvo

SQLite guarda adversário, fase/rodada, formato, cores, vitórias/empates/derrotas,
lances, posições, relógios, ajustes físicos, análises e correções.
Resultado de partida e vencedor do confronto são informações separadas.

O histórico e os resultados são salvos automaticamente no banco. O fluxo
`campeonato` também salva um LOG técnico por partida em `dados/logs/`, conforme
o item 9 do FAQ, sem perguntas extras. Interrupções mantêm o LOG parcial; um
resultado oficial posterior atualiza o mesmo arquivo. A exportação TXT com
autorização continua no modo manual antigo, em `relatórios de partidas/`.
Registros antigos de tabelas e pontuação são preservados como dados legados,
sem aparecer no resumo ou participar das decisões. Não é necessário apagar bancos.

Os novos LOGs se chamam `partida_001.log`, `partida_002.log`, etc. A numeração
segue todas as partidas da campanha, sem reiniciar a cada adversário, e inclui
Armageddon. O cabeçalho identifica número, adversário e fase; o ID interno
permanece para rastreabilidade. LOGs antigos com nome de ID são preservados;
quando atualizados, também recebem uma versão com o nome numerado. O banco
guarda o caminho do LOG atual. Um arquivo numerado de outra partida nunca é
sobrescrito: para uma campanha nova, use uma pasta de dados própria.

Profundidade, nós, avaliação e PV documentam as análises do nosso motor.
Os movimentos adversários são registrados com lance, cor e tempo observado;
os dados internos do motor adversário ficam `N/D` (não disponível).
A análise prévia do repertório é identificada separadamente da busca atual.

Interrupção não inventa empate nem retoma uma partida automaticamente.
Ao reabrir o campeonato, uma partida pendente pede apenas o resultado oficial;
Enter mantém a pendência sem inventar um resultado.

## Busca, aberturas e eficiência

O Stockfish continua administrando a busca pelos relógios UCI: não acrescentamos
limite de segundos, profundidade ou nós à busca principal. A GPU não é utilizada.

No modo completo, o repertório local contém 61 posições preparadas offline com
Stockfish 19: até dois milhões de nós por posição, com profundidades observadas
de 18 a 24. O primeiro lance preparado é e2e4. Há respostas para algumas linhas
de e5, Siciliana, Francesa, Caro-Kann e inícios com d4, c4 e Cf3.

Só usa o repertório se posição e histórico coincidirem, até dez meios-lances.
Ao sair da preparação, a análise normal assume até o fim. O livro não cobre
todas as variantes. Arquivo ausente ou inválido também leva à busca normal.
O registro salva `abertura preparada`, com zero nós/profundidade da busca atual;
a análise offline fica separada. Isso não é contado como troca autoral.

`--sem-abertura` desativa o repertório no jogo e nos ensaios automáticos.
Os modos original e ponderacao não usam livro. Para refazer a preparação
explicitamente, antes do evento e fora de uma partida:

    ./.venv/Scripts/python.exe -X utf8 -m chess_challenge.aberturas

O seletor continua verificando alternativas próximas com o Stockfish e
considerando o placar do confronto e o objetivo do Armageddon.
Antecipação usa um trabalhador por motor, parado antes da busca do nosso turno.

O refino reaproveita o tabuleiro nas verificações, evita recriar registros
anteriores e mantém cache limitado de históricos já validados. Mudança de
histórico ou FEN exige nova validação. A gravação SQLite continua transacional
e detecta alterações concorrentes por outra sessão.

Em uma medição local com seis posições, verificações/atributos passaram de
aproximadamente 30 ms para 7 ms, mantendo as mesmas decisões em três contextos.
Isso mede somente funções Python, não o tempo total do Stockfish nem ganho de Elo.

## Testar

Campanha automática em 5+1, mesmos recursos em ambos os motores:

    ./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --formato melhor-de-tres --tempo 300 --incremento 1 --threads 4 --hash 512

O ensaio usa o mesmo modelo de confronto. O modo completo usa o repertório;
o adversário original não. Use `--sem-abertura` para isolar essa diferença.
Também existem `--formato classificacao` (única com desempate),
`--formato armageddon` e `--formato pares`.
No ensaio direto de Armageddon, os jogos de preparação são identificados como
sintéticos e não entram no resumo de partidas efetivamente disputadas.

    ./.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider tests
    ./.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider tests --motor-real

Os testes verificam placares e cores, Armageddon nos dois formatos, frações de
segundo, ajustes físicos, migração de bancos, integridade dos históricos,
limites do repertório e comunicação real com o motor. Testes funcionais e
baterias curtas não demonstram superioridade competitiva.
Validação de 01/11/2026: 286 testes passaram, incluindo oito integrações com o
Stockfish real. Não foi executado um confronto completo de 5+1 nesta revisão.

## Organização e origem

`jogar.py` é a entrada. Em `chess_challenge/`: `motor.py` integra o Stockfish;
`inteligencia.py` coordena buscas e antecipação; `estrategia.py` seleciona
alternativas; `aberturas.py/json` mantêm a preparação; `campanha.py` guarda
confrontos e resultados; `torneio.py` opera a campanha; `partida.py` conduz
os turnos; `relogio.py` conta os tempos; `relatorios.py` formata os LOGs e o TXT.
Os testes ficam em `tests/`; bancos e relatórios gerados são ignorados pelo Git.

Stockfish 19, tag sf_19, commit edb0d9db6731067ec50ce619ff372b463bc4dd5d.
A [declaração de origem](../STOCKFISH.md) identifica autores, licença e fontes.
Não alteramos C++ nem NNUE. A equipe informou em 30/10/2026 que o seletor Python
foi aceito como componente decisório autoral; continua necessário demonstrar e
defender seu funcionamento. O repertório não substitui essa contribuição.
