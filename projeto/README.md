# Chess Challenge — campanha e partidas locais

Python com Stockfish 19, quatro threads e 512 MB de hash por motor.
A seleção considera o confronto atual, seus resultados e o Armageddon.
Não usamos pontuação, ELO ou posição em tabela para escolher lances.

## Jogar no campeonato

No Git Bash:

    cd /d/XADREZ/projeto
    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha criar --arquivo "dados/campeonato.sqlite3" --equipe "NOSSA EQUIPE"

Crie a campanha uma vez. O programa pergunta a duração total prevista de cada
partida. Por exemplo, 25 minutos é uma referência de agenda: não corta a busca
nem altera os relógios de 15 minutos por equipe +10 segundos por lance.
Enter deixa a duração não informada. Para preencher sem pergunta, use
`--duracao-prevista 25`.

Cadastre um confronto em um dos formatos:

    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha confronto --arquivo "dados/campeonato.sqlite3" --adversario "OUTRA EQUIPE" --formato unica
    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha confronto --arquivo "dados/campeonato.sqlite3" --adversario "OUTRA EQUIPE" --fase final --formato melhor-de-tres

Use somente o cadastro correspondente ao pareamento. Fase e rodada são
identificações opcionais. Fases: classificacao, oitavas, quartas, semifinal,
final e terceiro-lugar. A rodada segue a sequência de confrontos, ou pode ser
informada com `--rodada`. Não representam pontuação ou posição em tabela.

Inicie cada partida, inclusive a próxima da melhor de três e o Armageddon:

    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha jogar --arquivo "dados/campeonato.sqlite3"

A cor é perguntada antes de começar. Na melhor de três o programa verifica a
alternância; no Armageddon, informe a cor sorteada pela organização.
Nossos lances são aplicados automaticamente. Digite apenas o lance adversário
em UCI, como `e7e5`; o tabuleiro aparece após cada lance.

## Relógio físico e registro do resultado

O contador local funciona automaticamente. Ele não lê o relógio físico.
Quando necessário, no campo de entrada do adversário, ajuste os dois saldos:

    relogios 14:30.250 14:05.125

A ordem é SEMPRE brancas e pretas. O ajuste não joga, não troca a vez e não
adiciona incremento. O sistema registra o ajuste e continua contando.
O relógio físico e a decisão do árbitro são a referência oficial; o contador
local pode diferir pelo tempo de anunciar, mover peças e digitar.

Após a partida, registre o placar por COR:

    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha resultado --arquivo "dados/campeonato.sqlite3" --placar 1-0 --motivo "Mate confirmado"

Placar: `1-0` = vitória das brancas; `0-1` = vitória das pretas;
`1/2-1/2` = empate. O programa reaproveita os saldos locais.
Para registrar os saldos do relógio físico, acrescente ambos os argumentos:

    --nosso-tempo 02:10.125 --outro-tempo 01:40.250

Esses dois argumentos são relativos à NOSSA equipe e ao adversário.
São opcionais, aceitam frações de segundo e prevalecem sobre os saldos locais.
Uma correção posterior usa `--partida ID --corrigir "Justificativa"`.
O banco armazena os saldos finais com precisão de milissegundos.

    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha status --arquivo "dados/campeonato.sqlite3"

## Formatos e desempates

- Partida única empatada: um Armageddon, em qualquer fase.
- Melhor de três: nenhum Armageddon entre as partidas. Placar decidido pode
  encerrar o confronto; `campanha regras --tres-obrigatorias sim` exige três jogos.
- Empate no placar depois das três: vence a maior soma dos tempos finais.
  Se também forem iguais, um Armageddon. Saldos ausentes deixam a decisão pendente.
- Armageddon: brancas com 5 minutos, pretas com 4, sem incremento.
  Empate dá o confronto às pretas; o resultado da partida continua registrado
  como empate. A cor vem do sorteio oficial.
- Tripla repetição e regra dos 50 lances atingidas são automáticas.
- A duração prevista na agenda não decide resultado nem interrompe cálculos.
- Na classificação, perder um confronto não impede cadastrar o seguinte.
  Nas eliminatórias, é necessário respeitar a eliminação ou uma decisão oficial.

Essas definições incorporam as orientações da equipe de 30/10/2026.
O FAQ original permanece em `../documentos/rules.txt`.

## O que é salvo

SQLite guarda adversário, fase/rodada, formato, cores, vitórias/empates/derrotas,
lances, posições, relógios, ajustes físicos, análises e correções.
Resultado de partida e vencedor do confronto são informações separadas.

O histórico é salvo automaticamente por lance. O TXT só é gerado após
autorização e nome informado pelo operador, em `relatórios de partidas/`.
Registros antigos de tabelas e pontuação são preservados como dados legados,
sem aparecer no resumo ou participar das decisões. Não é necessário apagar bancos.

Interrupção não inventa empate nem retoma uma partida automaticamente.
Use `campanha cancelar --justificativa "Motivo"` para uma tentativa de teste;
na competição, registre a decisão do árbitro.

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
O log marca `abertura preparada`, com zero nós/profundidade da busca atual;
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
Validação de 30/10/2026: 238 testes passaram, incluindo sete integrações com o
Stockfish real. Não foi executado um confronto completo de 5+1 nesta revisão.

## Organização e origem

`jogar.py` é a entrada. Em `chess_challenge/`: `motor.py` integra o Stockfish;
`inteligencia.py` coordena buscas e antecipação; `estrategia.py` seleciona
alternativas; `aberturas.py/json` mantêm a preparação; `campanha.py` guarda
confrontos e resultados; `torneio.py` opera a campanha; `partida.py` conduz
os turnos; `relogio.py` conta os tempos; `relatorios.py` exporta TXT.
Os testes ficam em `tests/`; bancos e relatórios gerados são ignorados pelo Git.

Stockfish 19, tag sf_19, commit edb0d9db6731067ec50ce619ff372b463bc4dd5d.
A [declaração de origem](../STOCKFISH.md) identifica autores, licença e fontes.
Não alteramos C++ nem NNUE. A equipe informou em 30/10/2026 que o seletor Python
foi aceito como componente decisório autoral; continua necessário demonstrar e
defender seu funcionamento. O repertório não substitui essa contribuição.
