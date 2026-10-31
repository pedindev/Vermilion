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

No Linux, use `.venv/bin/python` no lugar de `.venv/Scripts/python.exe`.
O pacote em [Versão Linux](<Versão Linux/README.md>) contém os scripts de
preparação e início para o notebook com Zorin OS e Ryzen 5 5625U.

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
se os tempos também forem iguais, o sistema prepara o Armageddon para a próxima
execução. Na melhor de três, compara a soma dos tempos ao final do confronto.
O Armageddon usa cinco minutos para brancas e quatro para pretas, sem incremento;
empate favorece as pretas. Informe a cor sorteada pela organização.

Se o árbitro encerrar a partida, digite `fim` no campo do lance adversário e
informe o resultado na própria tela. Para ajustar os relógios físicos, use
`relogios 14:30.250 14:05.125`, sempre na ordem BRANCAS PRETAS.

O banco fica em `projeto/dados/campeonato.sqlite3`. Cada partida também gera
um LOG técnico em `projeto/dados/logs/`, para entrega à banca.
O banco guarda jogadas, análises, resultados e relógios de todas as partidas;
preserve-o entre as execuções. Uma partida interrompida fica pendente de
resultado oficial. Se essa pergunta aparecer antes do cadastro do adversário,
o programa encontrou uma partida anterior ainda pendente.
Entre Windows e Linux, copie o banco para `projeto/dados/campeonato.sqlite3`
com os programas encerrados, entre partidas. Copie também `dados/logs/` para
levar os LOGs. O histórico e o confronto continuam válidos no outro sistema;
os caminhos dos LOGs são recalculados ao abrir o banco.

## Computadores da equipe e compartilhamento da campanha

| Papel | Notebook | Sistema e motor |
| --- | --- | --- |
| Principal | Acer Nitro 5, Ryzen 7 5800H, 16 GB de RAM | Windows, Stockfish 19 x86-64 Universal |
| Secundário / reserva | Ryzen 5 5625U | Zorin OS, Stockfish 19 Linux x86-64 Universal |

A equipe planeja levar os dois notebooks preparados. Um único computador opera
a partida. A eventual mudança para o secundário será feita entre partidas e
deve ser confirmada com a organização, pois o item 6 do FAQ prevê um notebook
por equipe durante as partidas.
Ambos usam o mesmo controlador Python, quatro threads, 512 MB de hash e as
mesmas regras. Cada execução acompanha uma partida e depois encerra.

O compartilhamento usa o mesmo banco SQLite, sem conversão de formato.
O transporte planejado é pelo WhatsApp Web, como documento, **somente entre
partidas e se a organização autorizar a conexão nesse intervalo**:

1. Depois do encerramento oficial da partida, feche o programa nos dois notebooks.
2. Guarde uma cópia dos dados que já estiverem no destino. Compacte a pasta
   `projeto/dados/` do notebook que acabou de jogar em `dados.zip`.
3. Envie `dados.zip` pelo WhatsApp Web como documento. No destino, baixe e
   extraia dentro de `projeto/`, mantendo `projeto/dados/campeonato.sqlite3`
   e `projeto/dados/logs/` nos mesmos caminhos relativos.
4. Encerre o uso do WhatsApp e desligue a internet antes da próxima partida,
   respeitando a verificação do árbitro. Inicie o programa no notebook de destino;
   ele recupera equipe, resultados, confronto, lances, análises e relógios salvos.

O [FAQ, item 14](documentos/rules.txt) proíbe requisições externas durante as
partidas e exige Wi-Fi e dados móveis desligados, com verificação no início de
cada jogo. O texto não autoriza expressamente WhatsApp nos intervalos. Portanto,
esse transporte é uma possibilidade técnica, com autorização ainda a confirmar,
e não deve ser apresentado como procedimento já aprovado. O pendrive é uma
alternativa de cópia sem internet, a combinar com a organização.

No Windows, a origem padrão é `D:/XADREZ/projeto/dados/`. No Linux, o destino é
`Versão Linux/projeto/dados/`, no local escolhido para a pasta no notebook.
Ao voltar ao Windows, transfira a versão mais recente dos dados no sentido inverso.
O arquivo `campeonato.sqlite3` basta para o histórico; copiar `dados/` inteira
preserva também os LOGs para a banca. Não há mesclagem de bancos nem sincronização
automática: a transferência é manual, e o GitHub não transporta a campanha.
Cada notebook mantém seu próprio ambiente `.venv`.
Uma partida interrompida continua pendente de decisão oficial, sem retomada
automática do tabuleiro em outro computador.

No Zorin OS, abra um terminal dentro de `Versão Linux`. Com o Stockfish já
extraído na pasta `stockfish/`, prepare uma vez antes do evento:

```bash
bash preparar.sh
```

Depois, para cada partida:

```bash
bash iniciar.sh
```

As dependências Python fornecidas são instaladas localmente, sem download.
O motor Linux deve ser obtido antes do evento pelo
[download oficial da versão 19](https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-linux-x86-64-universal.tar.gz).
O [README do Linux](<Versão Linux/README.md>) detalha a instalação e a conferência.

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

A validação de 31/10/2026 aprovou 280 testes, incluindo oito integrações com o
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

## Licença

[GNU General Public License v3.0](LICENSE). Stockfish é de seus respectivos autores.
