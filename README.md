# Chess Challenge — seletor de lances orientado à campanha

Projeto em Python para jogar localmente com Stockfish 19 e considerar o contexto
do campeonato na seleção de lances: classificação, melhor de três, relógios e
Armageddon. A melhoria é experimental; ganho competitivo ainda não foi demonstrado.

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

A validação de 26/10/2026 aprovou 191 testes, incluindo seis integrações com o
Stockfish real. Isso verifica funcionamento; uma campanha completa em 5+1 e ganho
de força ainda precisam ser avaliados.

O Git inclui os scripts de teste. Ambientes virtuais, caches, bancos das campanhas
e relatórios gerados ficam apenas no computador e são ignorados pelo Git.

No jogo manual, digite somente o lance adversário em UCI. O sistema mantém os
dois relógios, troca o turno, aplica o incremento e salva os saldos automaticamente.
O registro do resultado reutiliza esses saldos. O contador local acompanha os
eventos do programa, sem leitura sincronizada do relógio físico do árbitro.

## Licença

[GNU General Public License v3.0](LICENSE). Stockfish é de seus respectivos autores.
