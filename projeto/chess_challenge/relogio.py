"""Relógios locais por turno, medidos com tempo monotônico e incremento Fischer."""

from math import isfinite
import sys
from time import monotonic, sleep


class TempoEsgotado(Exception):
    def __init__(self, cor):
        self.cor = cor
        super().__init__(f"Tempo das {'brancas' if cor else 'pretas'} esgotado no sistema.")


class RelogioPartida:
    def __init__(self, brancas, pretas, incremento, agora=monotonic):
        if (any(not isfinite(v) or v <= 0 for v in (brancas, pretas))
                or not isfinite(incremento) or incremento < 0):
            raise ValueError("Relógios devem ser positivos e incremento não negativo.")
        self._saldos = {True: float(brancas), False: float(pretas)}
        self.incremento, self.agora = incremento, agora
        self.ativo, self.inicio = None, None

    def iniciar(self, cor=True):
        if self.ativo is not None:
            raise ValueError("O relógio já está em andamento.")
        if self._saldos[cor] <= 0:
            raise TempoEsgotado(cor)
        self.ativo, self.inicio = cor, self.agora()

    def saldos(self):
        valores = dict(self._saldos)
        if self.ativo is not None:
            valores[self.ativo] = max(0, valores[self.ativo] - (self.agora() - self.inicio))
        return valores

    def confirmar_lance(self, cor):
        if self.ativo is None or self.ativo != cor:
            raise ValueError("Lance não corresponde ao relógio ativo.")
        instante = self.agora()
        gasto = instante - self.inicio
        self._saldos[cor] = max(0, self._saldos[cor] - gasto)
        if self._saldos[cor] <= 0:
            self.ativo, self.inicio = None, None
            raise TempoEsgotado(cor)  # Incremento nunca resgata um relógio zerado.
        self._saldos[cor] += self.incremento
        self.ativo, self.inicio = not cor, instante
        return gasto

    def parar(self):
        self._saldos = self.saldos()
        self.ativo, self.inicio = None, None
        return dict(self._saldos)


def formatar_relogios(saldos):
    def formato(valor):
        minutos, segundos = divmod(int(max(0, valor)), 60)
        return f"{minutos:02d}:{segundos:02d}"
    return f"Relógios — Brancas: {formato(saldos[True])} | Pretas: {formato(saldos[False])}"


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
