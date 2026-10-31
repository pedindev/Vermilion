# Referência do Stockfish utilizado

## Identificação do projeto-base

- **Projeto:** Stockfish.
- **Versão utilizada:** Stockfish 19.
- **Tag oficial:** [`sf_19`](https://github.com/official-stockfish/Stockfish/tree/sf_19).
- **Commit da versão:** [`edb0d9db6731067ec50ce619ff372b463bc4dd5d`](https://github.com/official-stockfish/Stockfish/commit/edb0d9db6731067ec50ce619ff372b463bc4dd5d).
- **Repositório oficial:** https://github.com/official-stockfish/Stockfish.
- **Código-fonte dessa versão:** [diretório src no commit declarado](https://github.com/official-stockfish/Stockfish/tree/edb0d9db6731067ec50ce619ff372b463bc4dd5d/src).
- **Fontes para download:** [arquivo ZIP do commit declarado](https://github.com/official-stockfish/Stockfish/archive/edb0d9db6731067ec50ce619ff372b463bc4dd5d.zip).

## Autores e licença

Stockfish é de autoria de **The Stockfish developers**. A lista completa de
créditos desta versão está no arquivo
[AUTHORS original](https://github.com/official-stockfish/Stockfish/blob/edb0d9db6731067ec50ce619ff372b463bc4dd5d/AUTHORS).

Os cabeçalhos dos fontes declaram Copyright (C) 2004–2026 The Stockfish developers
e licença **GNU GPL versão 3 ou posterior**. O texto original está em
[Copying.txt](https://github.com/official-stockfish/Stockfish/blob/edb0d9db6731067ec50ce619ff372b463bc4dd5d/Copying.txt).
Este repositório também contém a [GPLv3](LICENSE).

## Uso e contribuição deste projeto

O executável do Stockfish é utilizado localmente por meio do protocolo UCI.
Não fizemos alterações nos fontes C++ nem treinamos a rede NNUE do Stockfish.
A distribuição Linux original fica em `stockfish/`, com fontes, autores e licença
preservados quando extraída do download oficial. Ela não é incluída no Git;
consulte o [README](README.md) para baixar a versão declarada antes do evento.

A contribuição própria está na camada Python em
[projeto/chess_challenge/](projeto/chess_challenge/): acompanhamento persistente
da campanha, interpretação do contexto do confronto, antecipação e seleção de
lances conforme os objetivos da competição. As decisões e verificações são
registradas para análise. Ganho competitivo ainda não foi demonstrado.

## Identificação da instalação local verificada

- Executável: `stockfish-linux-x86-64-universal`.
- SHA-256 do executável local:
  `0f83d24cc46d2c66c60f16001af5444873bc112b7d028594513426894c12da19`.
- Rede padrão declarada pelos fontes: `nn-1a298aa575a0.nnue`.
- Verificação do pacote Linux em 31/10/2026: os arquivos locais `src/misc.cpp`, `src/evaluate.h`,
  `src/engine.cpp`, `AUTHORS` e `Copying.txt` correspondem aos do commit acima,
  desconsiderando apenas a diferença entre finais de linha LF e CRLF.

O SHA-256 identifica o arquivo local utilizado; não é apresentado como um hash
publicado ou certificado pelo projeto Stockfish. Se o executável for substituído,
atualize esta identificação e declare a nova origem.

Esta declaração registra a origem solicitada pelo item 1 do
[FAQ da competição](../documentos/rules.txt). A equipe também deve informar esses
dados no credenciamento e disponibilizar seu repositório à banca.

Pacote Linux preparado em 31/10/2026; executável ELF x86-64, fornecido localmente.
Os cinco arquivos de origem citados também foram comparados com a instalação
original verificada e correspondem após normalizar os finais de linha.
