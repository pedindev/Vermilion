"""Relógios locais por turno, medidos com tempo monotônico e incremento Fischer."""

from math import isfinite
import sys
from time import monotonic, sleep


def ler_tempo(texto):
    """Segundos ou mm:ss, incluindo frações decimais."""
    texto = texto.strip().replace(",", ".")
    if ":" in texto:
        partes = texto.split(":")
        if len(partes) != 2 or not partes[0].isdigit():
            raise ValueError("Use segundos ou mm:ss.")
        minutos, segundos = int(partes[0]), float(partes[1])
        if not 0 <= segundos < 60:
            raise ValueError("Segundos devem estar entre 0 e 60.")
        valor = minutos * 60 + segundos
    else:
        valor = float(texto)
    if not isfinite(valor) or valor < 0:
        raise ValueError("Relógio deve ser finito e não negativo.")
    return valor


def ler_saldos(texto):
    valores = texto.split()
    if len(valores) != 2:
        raise ValueError("Informe os dois tempos na ordem BRANCAS PRETAS.")
    brancas, pretas = map(ler_tempo, valores)
    return {True: brancas, False: pretas}


class TempoEsgotado(Exception):
    def __init__(self, cor):
        self.cor = cor
        super().__init__(f"Tempo das {'brancas' if cor else 'pretas'} esgotado no sistema.")


class JanelaPartida:
    """Previsão de duração para planejamento, sem poder encerrar a partida."""
    def __init__(self, minutos=None, agora=monotonic):
        if minutos is not None and (isinstance(minutos, bool) or not isinstance(minutos, (int, float))
                                   or not isfinite(minutos * 60) or minutos <= 0):
            raise ValueError("A duração total deve ser positiva e finita.")
        self.total = None if minutos is None else minutos * 60
        self.agora, self.inicio = agora, None

    def iniciar(self):
        if self.inicio is not None:
            raise ValueError("A previsão da partida já está em andamento.")
        self.inicio = self.agora()

    def restante(self):
        if self.total is None:
            return None
        return max(0, self.total - (self.agora() - self.inicio)) if self.inicio is not None else self.total


class RelogioPartida:
    def __init__(self, brancas, pretas, incremento, agora=monotonic):
        if (any(not isfinite(v) or v <= 0 for v in (brancas, pretas))
                or not isfinite(incremento) or incremento < 0):
            raise ValueError("Relógios devem ser positivos e incremento não negativo.")
        self._saldos = {True: float(brancas), False: float(pretas)}
        self.incremento, self.agora = incremento, agora
        self.ativo, self.inicio = None, None
        self.gasto_antes_ajuste = 0
        self.fonte = "relogio_do_sistema"

    def iniciar(self, cor=True):
        if self.ativo is not None:
            raise ValueError("O relógio já está em andamento.")
        if self._saldos[cor] <= 0:
            raise TempoEsgotado(cor)
        self.ativo, self.inicio = cor, self.agora()
        self.gasto_antes_ajuste = 0

    def ajustar(self, brancas, pretas):
        """Sincronização manual com o relógio físico, sem trocar turno nem dar incremento."""
        if any(not isfinite(v) or v < 0 for v in (brancas, pretas)):
            raise ValueError("Informe os dois saldos físicos, finitos e não negativos.")
        if self.ativo is None:
            raise ValueError("O relógio não está em andamento.")
        instante = self.agora()
        self.gasto_antes_ajuste += instante - self.inicio
        self._saldos = {True: float(brancas), False: float(pretas)}
        self.inicio = instante
        self.fonte = "sistema_com_ajuste_fisico"

    def saldos(self):
        valores = dict(self._saldos)
        if self.ativo is not None:
            valores[self.ativo] = max(0, valores[self.ativo] - (self.agora() - self.inicio))
        return valores

    def reposicionar(self, cor):
        """Troca o turno após corrigir o tabuleiro, sem devolver tempo ou incremento."""
        self._saldos = self.saldos()
        self.ativo, self.inicio = cor, self.agora()
        self.gasto_antes_ajuste = 0

    def confirmar_lance(self, cor):
        if self.ativo is None or self.ativo != cor:
            raise ValueError("Lance não corresponde ao relógio ativo.")
        instante = self.agora()
        trecho = instante - self.inicio
        gasto = self.gasto_antes_ajuste + trecho
        self._saldos[cor] = max(0, self._saldos[cor] - trecho)
        if self._saldos[cor] <= 0:
            self.ativo, self.inicio = None, None
            raise TempoEsgotado(cor)  # Incremento nunca resgata um relógio zerado.
        self._saldos[cor] += self.incremento
        self.ativo, self.inicio = not cor, instante
        self.gasto_antes_ajuste = 0
        return gasto

    def parar(self):
        self._saldos = self.saldos()
        self.ativo, self.inicio = None, None
        return dict(self._saldos)


def formatar_tempo(valor):
    total_ms = round(max(0, valor) * 1000)
    minutos, restante = divmod(total_ms, 60_000)
    segundos, ms = divmod(restante, 1000)
    return f"{minutos:02d}:{segundos:02d}.{ms:03d}"


def formatar_relogios(saldos):
    return f"Relógios — Brancas: {formatar_tempo(saldos[True])} | Pretas: {formatar_tempo(saldos[False])}"


def entrada_com_prazo(entrada, prompt, limite):
    """Entrada interativa expira mesmo sem Enter; entradas injetadas são testáveis.

    Windows usa o console nativo. Em POSIX o terminal entrega linhas via select.
    Pipes e entradas de teste continuam usando a função de entrada fornecida.
    """
    if limite <= 0:
        raise TimeoutError("Relógio esgotado durante a entrada.")
    if entrada is not input or not sys.stdin.isatty():
        return entrada(prompt)
    if sys.platform != "win32":
        import select
        print(prompt, end="", flush=True)
        if not select.select([sys.stdin], [], [], limite)[0]:
            print()
            raise TimeoutError("Relógio esgotado durante a entrada.")
        return input()

    import msvcrt
    print(prompt, end="", flush=True)
    prazo, caracteres = monotonic() + limite, []
    while True:
        restante = prazo - monotonic()
        if restante <= 0:
            print()
            raise TimeoutError("Relógio esgotado durante a entrada.")
        if not msvcrt.kbhit():
            sleep(min(.02, restante))
            continue
        tecla = msvcrt.getwch()
        if tecla in ("\x00", "\xe0"):
            msvcrt.getwch()  # Prefixo de tecla especial, não é texto UCI.
        elif tecla in ("\r", "\n"):
            print()
            return "".join(caracteres)
        elif tecla == "\x03":
            raise KeyboardInterrupt
        elif tecla == "\x1a":
            raise EOFError
        elif tecla == "\b":
            if caracteres:
                caracteres.pop()
                print("\b \b", end="", flush=True)
        elif tecla.isprintable():
            caracteres.append(tecla)
            print(tecla, end="", flush=True)
