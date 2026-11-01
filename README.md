# Chess Challenge — seletor de lances orientado à campanha

Projeto em Python para jogar localmente com Stockfish 19 e considerar o contexto
do confronto na seleção de lances: resultados, melhor de três, relógios e
Armageddon. Não usa pontuação ou tabela para decidir jogadas. A melhoria é
experimental; ganho competitivo ainda não foi demonstrado.

## Conteúdo

- [Código, uso e arquitetura](projeto/README.md): aplicação, campanha persistente
  e instruções de operação pelo terminal.
- [Testes](projeto/tests/): testes automatizados e ambiente de confrontos.
- [Regras mais recentes](documentos/rules.txt): FAQ adotado pelo projeto.
- [Edital original](documentos/Chess-Challenge-III-1_cópia.pdf).

## Instalação

Use Python 3.13, versão utilizada na validação. A partir da pasta do repositório:

```bash
cd projeto
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

O ambiente preparado para a competição é Windows, no notebook da equipe.

O Stockfish é uma dependência externa. Obtenha a versão 19 no
[site oficial](https://stockfishchess.org/download/) e coloque o executável em
`stockfish/stockfish-windows-x86-64-universal.exe`, na raiz do repositório.
Também é possível fornecer o caminho com `--motor` ou instalar o comando
`stockfish` no PATH. Não há download nem acesso à rede durante as partidas.

**Projeto-base declarado:** [Stockfish 19, tag sf_19](https://github.com/official-stockfish/Stockfish/tree/sf_19),
commit [`edb0d9db6731067ec50ce619ff372b463bc4dd5d`](https://github.com/official-stockfish/Stockfish/commit/edb0d9db6731067ec50ce619ff372b463bc4dd5d).
Os fontes C++ e a rede NNUE do motor não foram alterados por esta equipe.
Nossa camada de decisão fica em `projeto/chess_challenge/`.

A [declaração de origem do Stockfish](STOCKFISH.md) reúne os links do código-fonte
da versão utilizada, seus autores, a licença e a identificação do executável local.
O executável e seus fontes são instalados separadamente e não estão neste Git.

## Operar o campeonato

No Git Bash, um único comando:

```bash
cd /d/XADREZ/projeto && ./.venv/Scripts/python.exe -X utf8 jogar.py campeonato
```

Cada execução acompanha uma única partida, salva os dados e encerra. Execute
o mesmo comando antes da próxima; o histórico e os desempates são recuperados.

Na primeira vez, informe equipe e duração prevista (Enter se não souber).
Em cada novo confronto, informe adversário, fase, formato e nossa cor.
As fases disponíveis são classificação, oitavas, quartas, semifinal, final e
terceiro lugar; os formatos são partida única e melhor de três, conforme o
pareamento da organização. Durante a partida, digite somente o lance adversário
em UCI, por exemplo `e7e5`. O programa calcula e aplica nossos lances.

O ritmo normal é **15 minutos +10 segundos por lance**, com quatro threads e
512 MB de hash. A duração prevista é uma referência de agenda, sem corte da análise.

Em qualquer fase, um empate no placar é decidido pelo maior tempo restante;
se os tempos também forem iguais, pergunta se deseja iniciar o Armageddon na
próxima execução. Responda `s` para autorizar ou `n` para deixar pendente.
Ao executar novamente, informe apenas a cor sorteada; sem autorização salva,
o sistema pede confirmação antes de perguntar a cor. Nenhum relógio começa
antes dessa escolha. Na melhor de três, compara a soma dos tempos ao final
do confronto; não oferece Armageddon entre as partidas normais.
O Armageddon usa cinco minutos para brancas e quatro para pretas, sem incremento;
empate favorece as pretas. Informe a cor sorteada pela organização.

Se o árbitro encerrar a partida, digite `fim` no campo do lance adversário e
informe o resultado na própria tela. Para ajustar os relógios físicos, use
`relogios 14:30.250 14:05.125`, sempre na ordem BRANCAS PRETAS.

O banco fica em `projeto/dados/campeonato.sqlite3`. Cada partida também gera
um LOG técnico em `projeto/dados/logs/`, para entrega à banca. Os novos arquivos
são `partida_001.log`, `partida_002.log`, etc., seguindo a ordem geral da campanha,
inclusive melhor de três e Armageddon. A tela informa o nome ao terminar.
Atualizar um resultado pendente atualiza o mesmo LOG. Arquivos antigos com nome
de ID são preservados; ao atualizar a partida, também é gerado o nome numerado.
O banco guarda jogadas, análises, resultados e relógios de todas as partidas;
preserve-o entre as execuções. Uma partida interrompida fica pendente de
resultado oficial. Se essa pergunta aparecer antes do cadastro do adversário,
o programa encontrou uma partida anterior ainda pendente.

## Notebook da equipe

A equipe usará um Acer Nitro 5 com Ryzen 7 5800H, 16 GB de RAM e Windows,
com Stockfish 19 x86-64 Universal, quatro threads e 512 MB de hash.
O uso de um notebook segue o item 6 do [FAQ](documentos/rules.txt).
O banco e os LOGs permanecem nesse computador entre as partidas.
Wi-Fi e dados móveis devem estar desligados durante os jogos, conforme o item 14.

## Entrega à organização

O [edital](documentos/Chess-Challenge-III-1_cópia.pdf), na seção Requisitos de
Software, determina o envio via Git em **04/11/2026**, pelo e-mail
**icev@somosicev.com**. Envie o link do repositório e a identificação da versão
entregue. Como o repositório é privado, conceda à organização acesso para validar
o código. O edital não informa horário-limite nesse item.

Ao final de cada partida, entregue o respectivo `.log` à banca pelo meio indicado
pela organização. Bancos e LOGs reais ficam apenas no computador; não são
publicados neste repositório.

## Verificar e testar

Dentro de `projeto`, no Git Bash:

```bash
# Testes sem exigir a instalação do motor:
./.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider tests

# Incluir integrações com o executável instalado:
./.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider tests --motor-real

# Melhor de três automática, ritmo de teste 5+1:
./.venv/Scripts/python.exe -X utf8 "tests/testes de campeonato/testar_campeonato.py" --tempo 300 --incremento 1 --threads 4 --hash 512
```

O Armageddon usa 5 minutos para brancas, 4 para pretas e nenhum incremento,
conforme a configuração adotada pela equipe. Detalhes e pendências do regulamento
estão no [manual do projeto](projeto/README.md).

A validação de 01/11/2026 aprovou 286 testes, incluindo oito integrações com o
Stockfish real. Isso verifica funcionamento; uma campanha completa em 5+1 e ganho
de força ainda precisam ser avaliados.

O Git inclui os scripts de teste. Ambientes virtuais, caches, bancos das campanhas
e relatórios gerados ficam apenas no computador e são ignorados pelo Git.

No jogo manual, digite somente o lance adversário em UCI. O sistema mantém os
dois relógios, troca o turno, aplica o incremento e salva os saldos automaticamente.
O resultado reconhecido pelo tabuleiro é salvo automaticamente com esses saldos.
O contador local acompanha os eventos do programa, sem leitura sincronizada
do relógio físico do árbitro.
É possível ajustar os dois saldos durante o jogo com o comando opcional
`relogios TEMPO_BRANCAS TEMPO_PRETAS`, ou informar os saldos oficiais no resultado.
A criação da campanha pergunta a duração prevista da partida; essa informação
não altera o ritmo de 15+10 nem impõe um corte à análise.

O jogo manual no modo completo também usa um repertório local preparado com
Stockfish, até dez meios-lances. Ao sair da linha conhecida, volta à análise
normal. Os detalhes e o comando de preparação estão no manual do projeto.

Na revisão do item 9, permanece uma questão de interpretação: os lances
adversários têm métricas de busca `N/D`, pois não temos acesso ao motor adversário;
as jogadas de repertório registram busca atual zero e análise prévia separada.
O LOG identifica essas situações sem inventar dados. A aceitação desse formato
deve ser alinhada com a banca.

## Licença

[GNU General Public License v3.0](LICENSE). Stockfish é de seus respectivos autores.
