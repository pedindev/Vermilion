# Chess Challenge — seletor de lances orientado à campanha

Programa local em Python com Stockfish 19. O seletor experimental considera a
campanha para escolher alternativas verificadas pelo motor. Autoria funcional e
ganho competitivo são questões distintas: não demonstramos ganho de força ou Elo.

## Organização

    jogar.py                         entrada única do jogo manual
    chess_challenge/
      campanha.py                    regras, confrontos, resultados, tabela e SQLite
      estrategia.py                  critérios de seleção conforme a campanha
      inteligencia.py                antecipação, busca e verificação
      motor.py                       executável Stockfish, recursos e UCI
      partida.py                     turnos, entrada e tabuleiro no terminal
      torneio.py                     operação da campanha
      relatorios.py                  registros técnicos e exportação TXT autorizada
    tests/
      test_*.py                      testes determinísticos e integrações
      testes de campeonato/
        testar_campeonato.py          ensaios automáticos com relógio real
        test_campeonato.py            testes do ambiente automático
        relatórios/                  TXT autorizados e bancos dos ensaios
    dados/                           banco da campanha real, criado no primeiro uso
    relatórios de partidas/          TXT criados quando autorizados

O padrão é quatro threads e 512 MB de hash POR MOTOR. A GPU não é utilizada.
Stockfish administra a busca principal pelos relógios UCI. Antecipação é análise
especulativa da posição prevista, com histórico completo e reaproveitamento da
tabela de transposição; não prometemos continuidade ponderhit. Só um trabalhador
controla cada processo por vez. Não há biblioteca nova: SQLite é local.

## Regras adotadas

O FAQ ../documentos/rules.txt prevalece nos conflitos com o edital antigo.

- Ritmo normal oficial: 15 minutos +10 segundos por lance.
- Ambiente automático de teste: 5 minutos +1 segundo por lance.
- Armageddon: brancas 5 minutos, pretas 4 minutos, SEM INCREMENTO por orientação
  da equipe. O FAQ informa os tempos, mas não explicita o incremento. Essa origem
  fica registrada, em vez de atribuir ao documento uma definição ausente.
- Empate no Armageddon classifica as pretas. O resultado da partida continua empate.
- Melhor de três: cores alternadas; a terceira repete a primeira. Um placar
  matematicamente decidido pode encerrar o confronto. A configuração
  --tres-obrigatorias sim exige os três jogos, caso seja a orientação oficial.
- Empate após três jogos: maior soma dos saldos finais das duas equipes.
  Igualdade de placar e soma leva ao Armageddon. Relógio ausente deixa o desempate
  pendente, sem presumir igualdade.
- O sorteio das cores vem da organização no jogo real; só o ensaio sorteia.
- Tripla repetição e 50 lances efetivamente atingidos são automáticos. Não se
  declara empate apenas porque um lance futuro poderia satisfazer a regra.
- Mate, afogamento e material insuficiente são reconhecidos. Tabuleiro físico,
  relógios físicos e árbitro são a referência para resultado e correções.
- Sem rede, APIs, opening book ou tablebases. Syzygy fica sem caminho, limitado a
  cinco peças. A antecipação é permitida.
- Anuncie UCI, obtenha a repetição adversária, mova a peça e acione o relógio físico.
  O programa não ouve o anúncio nem opera o relógio.
- Logs registram lance, autor, cor, profundidade, nós, avaliação, PV e tempo.
  Dados internos adversários indisponíveis no modo manual aparecem como N/D.
- Falha do software durante um confronto automático é derrota conforme o edital.
  Interrupção pelo operador e limite de lances do ensaio são inconclusivos.

Ainda dependem de confirmação: quantidade de rodadas/vagas, formato de cada fase,
prioridade entre pontos e ELO e fórmula de ranking. Configuramos os valores
confirmados e importamos a tabela oficial, sem inventar uma classificação.
Inscrição, composição da equipe, entrega do Git e arbitragem são procedimentos da
organização, e não tarefas que o programa possa executar automaticamente.

## Teste automático de 5+1

No Git Bash, comando completo:

    cd /d/XADREZ/projeto && ./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --formato melhor-de-tres --tempo 300 --incremento 1 --threads 4 --hash 512

Esse já é o padrão: nosso seletor completo contra Stockfish original, com recursos
iguais, começando da posição inicial. São até três partidas normais e Armageddon
quando exigido pelos desempates. O confronto pode terminar antes pelo placar.
O teste usa o MESMO modelo de campanha do jogo manual. Mostra objetivo, lance,
tempo, resultado e situação do confronto. Não é necessário digitar jogadas.

No Windows, separa núcleos físicos e seus irmãos SMT por processo, alternando os
grupos por partida. Isso reduz concorrência, mas não equivale a dois notebooks.
--afinidade desligada desativa. --latencia 1 simula um segundo de operação física
por lance, cobrado de ambos antes do incremento.

O histórico é salvo por lance num banco novo em:
tests/testes de campeonato/relatórios/campanhas/
O caminho aparece no início. O TXT legível só é criado ao responder s e informar
um nome no final. Ctrl+C encerra trabalhadores e motores e preserva a tentativa
como inconclusiva. Um banco com partida pendente exige revisão explícita.

--campanha "caminho/ensaio.sqlite3" escolhe o banco. Um arquivo existente continua
o confronto entre jogos concluídos, com a mesma configuração.
O limite padrão de 300 lances completos é uma proteção do ensaio, não regra do
campeonato: atingi-lo não produz empate nem classificação.

Outros ensaios, a partir de /d/XADREZ/projeto:

    # Partida única da fase classificatória, 5+1:
    ./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --formato classificacao

    # Exercitar diretamente o Armageddon, nossa equipe de pretas, 5/4 sem incremento:
    ./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --formato armageddon --cor-armageddon pretas

    # Medir o seletor contra um adversário que também antecipa:
    ./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --adversario ponderacao

    # Comparação em pares, cores invertidas e aberturas de até dez meios-lances:
    ./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --formato pares --pares 3

    # Ritmo oficial:
    ./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --tempo 900 --incremento 10

O ensaio direto de Armageddon prepara três empates sintéticos com saldos iguais.
Eles são identificados no banco e NÃO entram no resumo de jogos efetivamente
disputados. Não são evidência de força.

Uma partida 5+1 pode durar mais de dez minutos devido aos incrementos. Resultados
nesse ritmo não equivalem aos de 15+10. Mais vitórias não significam necessariamente
mais classificações: avalie confrontos completos, relógios e critérios de desempate.

## Preparar a campanha real

Todos os comandos usam por padrão dados/campanha.sqlite3.
--arquivo "outro.sqlite3", DEPOIS do comando, permite campanhas separadas.

    cd /d/XADREZ/projeto

    # Executar uma vez. Um arquivo com campanha existente não é sobrescrito.
    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha criar --equipe "Nome da nossa equipe"

    # Cadastrar o pareamento informado pela organização:
    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha confronto --adversario "Equipe adversária" --fase semifinal --rodada 1 --formato melhor-de-tres --cor brancas

    # Jogar a próxima partida; cor e relógios vêm do confronto:
    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha jogar

    # Consultar a campanha e IDs pendentes:
    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha status

Durante o jogo, digite o lance adversário e NOSSO relógio físico: e7e5 14:50.
Opcionalmente acrescente o saldo adversário: e7e5 14:50 14:40. Sem ele, não se
presume um saldo adversário atualizado. Nossos lances são automáticos; o tabuleiro
aparece após cada lance. Não existem confirmações por lance.

Ao final, a partida aguarda o resultado oficial. Informe placar relativo às CORES,
os DOIS saldos físicos finais e o motivo:

    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha resultado --placar 1-0 --nosso-tempo 02:30 --outro-tempo 01:40 --motivo "Mate confirmado pelo árbitro"
    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha jogar

O comando seguinte usa a cor alternada e o novo objetivo. Se houver Armageddon,
informe a cor SORTEADA PELA ORGANIZAÇÃO:

    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha jogar --cor-armageddon pretas

Reenviar o mesmo resultado não pontua duas vezes. Para corrigir um resultado,
acrescente --partida ID --corrigir "Justificativa da arbitragem" ao comando
resultado, com placar, tempos e motivo. A auditoria preserva os dados anteriores.
Correção que invalide um Armageddon realizado deixa a situação em revisão.

    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha arbitragem --situacao classificado --justificativa "Decisão oficial da organização"

Esse comando registra classificação oficial sem inventar vitória numa partida
empatada. Não deve substituir a informação da arbitragem por uma suposição.

campanha cancelar --justificativa "Ensaio cancelado" cancela uma tentativa pendente
sem contabilizar resultado. Na competição, falha não dá direito automático a
retomar: registre a decisão oficial. Persistência não altera essa regra.

Para treino manual em 5+1, crie uma campanha separada com criar --teste e use seu
--arquivo em todos os comandos. Executar jogar.py sem campanha abre uma partida
isolada em 15+10, sem histórico do confronto.

## Tabela oficial e definições pendentes

Importe um JSON local com uma linha por equipe. Campos obrigatórios: equipe,
posicao e pontos. Outros campos oficiais podem ser mantidos. Exemplo:

    [
      {"equipe": "Nome da nossa equipe", "posicao": 2, "pontos": 4},
      {"equipe": "Outra equipe", "posicao": 1, "pontos": 6}
    ]

    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha tabela --importar "tabela.json" --rodada 2 --fonte "Organização"
    ./.venv/Scripts/python.exe -X utf8 jogar.py campanha regras --rodadas 5 --vagas 8 --equipes 32

Os números são EXEMPLOS, não resolução das inconsistências do edital.
A posição e os pontos oficiais são separados dos pontos do nosso histórico.
Nenhuma fórmula ELO é inventada. Se a organização confirmar que pontos determinam
as vagas, ative campanha regras --classificacao-por-pontos sim. Só com essa
confirmação, tabela COMPLETA da rodada anterior, quantidade de equipes, rodadas e
vagas definidos, o sistema usa limites conservadores para provar empate suficiente
ou vitória necessária. Empate em pontos não é vaga garantida sem critério oficial.

Sem prova matemática, um objetivo pode ser informado ao cadastrar o confronto:
--objetivo buscar_vitoria --justificativa "Situação informada pela organização".
Isso não é rotulado como garantia matemática.

Ritmos, pontuação e número de jogos obrigatórios são configuráveis em regras.
Confrontos preservam a configuração usada. Não altere regras no meio de um
confronto; os ajustes valem para os seguintes.

## Decisões orientadas à campanha

O objetivo distingue confronto aberto, recuperação do placar, proteção de vantagem
e empate que garante classificação. No Armageddon, brancas precisam vencer e
pretas podem classificar empatando. Na terceira partida com placar igual, os
relógios conhecidos e saldos acumulados orientam o objetivo a cada turno.
Saldo corrente estimado não é tratado como classificação assegurada.

1. Mate imediato ou empate imediato que comprovadamente classifica são identificados
   pelo tabuleiro e histórico. O log marca fonte regra comprovada, profundidade
   zero e zero nós, sem atribuir uma busca fictícia ao Stockfish.
2. Nos demais casos a busca principal continua nativa, por relógios UCI.
3. Alternativas antecipadas são usadas apenas se posição E histórico coincidirem.
   Sem candidatos, objetivos diferentes de equilibrado podem receber uma sondagem
   curta de até três variantes.
4. Original e alternativas passam por verificação atual com avaliações exatas,
   sem bounds provisórios e profundidade mínima 12. Cada checagem recebe até 0,3s
   e 1% do saldo disponível. Esse trabalho adicional custa tempo real.
5. Buscar vitória considera pressão perto do rei adversário e possibilidades de
   continuar jogando. Proteger considera segurança do nosso rei, peças expostas e
   simplificação. São heurísticas estáticas experimentais.
6. Tolerância estimada de 10cp, ou 20cp ao buscar vitória. Com vantagem >=150cp,
   prioriza conversão e tolerância 10cp. A referência considera também a busca
   principal, para não autorizar facilmente uma piora grande numa verificação curta.
   Isso não prova equivalência entre lances.
7. Mate indicado pelo motor é preservado. Abaixo de cinco segundos não há busca
   adicional. Sem dados suficientes, mantém-se a preferência original.

original preserva o algoritmo nativo com relógios/recursos iguais.
ponderacao antecipa, sem seletor. completo usa a política da campanha.
Partidas isoladas e comparação em pares, sem contexto, preservam o seletor anterior.
A diferença entre defesas não é medida comprovada de dificuldade prática.

O banco guarda contexto, lances, dados técnicos e decisões. Nas trocas, os dados
da busca principal ficam separados dos da verificação do lance escolhido.
Não confunda essas contagens para comparar profundidade ou nós/segundo.
SQLite usa transações e revisão para impedir perda de atualização por duas sessões.

## Validação — 26/10/2026

    ./.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider tests
    ./.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider tests --motor-real

177 testes aprovados, incluindo cinco integrações com o Stockfish real.
Cobertura: 27 placares possíveis da melhor de três com as duas cores iniciais,
todos os resultados/cores no Armageddon, desempate pelos relógios, interrupções,
falhas, correções auditáveis, persistência e conflito de sessões, tabela incompleta,
provas de necessidade de resultado e mudanças funcionais de lance pelo contexto.

A integração em 5+1 disputou DOIS meios-lances reais com quatro threads e 512 MB
por motor, verificando lances legais, dados técnicos e relógios. As demais
integrações verificam a comunicação e a antecipação. Uma melhor de três completa
em 5+1 ainda precisa ser disputada; a validação funcional não prova ganho de força.

## Origem e licença

Stockfish 19, fontes e autores em ../stockfish. GPLv3 em LICENSE.
Declare à banca versão/commit de origem, dependências e contribuição própria.
A aceitação formal do componente decisório cabe à banca.
