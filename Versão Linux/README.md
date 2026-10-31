# Chess Challenge no Zorin OS / Linux

Pacote para o notebook com Ryzen 5 5625U e Zorin OS: Stockfish 19 Linux x86-64 Universal,
nosso controlador Python, repertório, testes e dependências locais. O motor
seleciona os recursos adequados do processador. Usamos quatro threads e 512 MB
de hash, ritmo normal 15+10 e Armageddon 5/4 sem incremento.

Este é o computador secundário da equipe. O principal usa Windows. Cada partida
é operada em um único notebook. O uso do Linux como substituto entre partidas
deve ser confirmado com a organização, pois o item 6 do FAQ prevê um notebook
por equipe durante as partidas.

## Obter o Stockfish após clonar o GitHub

O repositório inclui nosso código e as dependências Python em `dependencias/`.
A distribuição do Stockfish é uma dependência externa e fica fora do Git.
Se você recebeu esta pasta completa por pendrive, o motor já pode estar presente.

Se a pasta veio de um clone do GitHub, baixe o
[Stockfish 19 Linux x86-64 Universal](https://github.com/official-stockfish/Stockfish/releases/download/sf_19/stockfish-linux-x86-64-universal.tar.gz)
e extraia a pasta `stockfish` para dentro de `Versão Linux`.
O executável deve ficar em `stockfish/stockfish-linux-x86-64-universal`.
Faça o download antes do evento; os scripts não baixam o motor durante o jogo.

## Preparar uma vez, antes do campeonato

Copie esta pasta inteira para o disco do notebook Linux. Abra um terminal dentro
dela. É necessário Python 3.10 ou superior com suporte a ambientes virtuais.
O [Zorin OS 17 e 18 usa base Ubuntu](https://zorin.com/os/details/).
Nessas versões, se necessário, instale previamente o suporte a Python:

```bash
sudo apt update
sudo apt install python3 python3-venv
```

Depois execute:

```bash
bash preparar.sh
```

O script cria o ambiente Linux, instala os pacotes fornecidos em `dependencias/`
sem acessar a internet e verifica a conexão com Stockfish. Não cria uma campanha.
Não transporte um `.venv` do Windows: cada computador prepara seu próprio ambiente.

## Uma execução por partida

No terminal aberto nesta pasta:

```bash
bash iniciar.sh
```

Informe os dados pedidos na tela e digite somente os lances adversários em UCI.
Ao terminar, o sistema salva e encerra. Execute o mesmo comando para a próxima
partida, inclusive na melhor de três ou no Armageddon. O histórico é recuperado.

## Trazer a campanha do Windows

Sim, o mesmo banco SQLite funciona nos dois sistemas, sem conversão.

O transporte será por um meio físico autorizado pela organização, **entre
partidas e sem internet**. A equipe está consultando a organização sobre o uso
de um cabo USB de transferência. Após a confirmação:

1. Encerre o programa nos dois computadores após o fim oficial da partida.
2. Guarde uma cópia dos dados do destino.
3. Copie `D:/XADREZ/projeto/dados/` pelo meio físico aprovado para `projeto/dados/`
   nesta pasta no Linux, preservando o banco `campeonato.sqlite3` e a pasta `logs/`.
4. Mantenha a internet desligada e respeite a verificação do árbitro.
   Execute `bash iniciar.sh` para recuperar a campanha.

O [FAQ, item 14](../documentos/rules.txt) proíbe acesso externo durante as
partidas e exige Wi-Fi e dados móveis desligados no início de cada jogo.
A troca de notebook e o meio físico de transferência ainda precisam ser
confirmados com a organização antes de adotar esse procedimento.

O banco `campeonato.sqlite3` basta para recuperar o estado da campanha.
A pasta `projeto/dados/` inteira leva também os LOGs já gerados para a banca.
Os caminhos dos LOGs são ajustados ao novo diretório ao abrir o banco.
Se já houver outro banco no destino, guarde uma cópia dele antes de substituir.
Ao voltar ao Windows, faça o mesmo processo com a versão mais recente dos dados.
Use uma campanha em um computador por vez; bancos separados não são mesclados.
O compartilhamento é uma cópia manual entre partidas, sem sincronização automática
nem uso do GitHub para transportar o banco. Não transporte os ambientes `.venv`.
O formato SQLite é [portável entre sistemas](https://www.sqlite.org/onefile.html).

A transferência preserva o histórico, mas uma partida interrompida continua
pendente de resultado oficial; o programa não retoma seu tabuleiro automaticamente.

Banco: `projeto/dados/campeonato.sqlite3`. LOGs: `projeto/dados/logs/`.

## Conferir o pacote

Depois da preparação, a partir desta pasta:

```bash
cd projeto
./.venv/bin/python -X utf8 -m pytest -q -p no:cacheprovider tests --motor-real
```

O ambiente de confrontos automáticos 5+1 também está em `projeto/tests/`.
Detalhes do software estão em [projeto/README.md](projeto/README.md).
As origens, a licença e a identificação do motor estão em [STOCKFISH.md](STOCKFISH.md).

A execução nativa ainda precisa ser confirmada nesse notebook. O próprio
`preparar.sh` abre o Stockfish para verificar compatibilidade antes do campeonato.
