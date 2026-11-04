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
O executável é instalado separadamente. Os fontes completos, sem alterações,
estão incluídos em [terceiros/stockfish/](terceiros/stockfish/), extraídos do ZIP
oficial do commit declarado. Incluem os créditos, GPL, scripts e Makefile originais.

A contribuição própria está na camada Python em
[projeto/chess_challenge/](projeto/chess_challenge/): acompanhamento persistente
da campanha, interpretação do contexto do confronto, antecipação e seleção de
lances conforme os objetivos da competição. As decisões e verificações são
registradas para análise. Ganho competitivo ainda não foi demonstrado.

## Identificação da instalação local verificada

- Executável: `stockfish-windows-x86-64-universal.exe`.
- SHA-256 do executável local:
  `45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0`.
- Rede padrão declarada pelos fontes: `nn-1a298aa575a0.nnue`.
- Verificação em 26/10/2026: os arquivos locais `src/misc.cpp`, `src/evaluate.h`,
  `src/engine.cpp`, `AUTHORS` e `Copying.txt` correspondem aos do commit acima,
  desconsiderando apenas a diferença entre finais de linha LF e CRLF.
- Verificação completa em 04/11/2026: os 76 arquivos da pasta `src` instalada
  correspondem aos fontes oficiais incluídos, desconsiderando LF/CRLF.
  Os 119 arquivos extraídos do ZIP oficial foram conferidos byte a byte.
  A [declaração com hashes](terceiros/stockfish-origem.json) registra URL,
  commit, hash do download e SHA-256 de cada arquivo original.

O SHA-256 identifica o arquivo local utilizado; não é apresentado como um hash
publicado ou certificado pelo projeto Stockfish. Se o executável for substituído,
atualize esta identificação e declare a nova origem.

Esta declaração registra a origem solicitada pelas seções 7 e 9 do
[Manual do Participante](documentos/Manual%20do%20Participante%20-%20III%20Chess%20Challenge.pdf). A equipe também deve informar esses
dados no credenciamento e disponibilizar seu repositório à banca.
