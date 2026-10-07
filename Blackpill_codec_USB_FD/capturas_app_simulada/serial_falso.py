"""
STM32 simulado: reemplaza al modulo `serial` (pyserial) para poder correr pc/comandos.py sin hardware.

Imita lo que hace el firmware: entiende los comandos de texto (STREAM, ADC, DAC, xWAVE, xFREQ, xAMP, xON/xOFF,
PING) y manda por el "COM" tramas binarias 0xAA 0x55 | tipo | seq | n | payload en tiempo real a 97656.25 Hz.
El ADC se simula en lazo cerrado con el DAC: si el DAC esta encendido el ADC "ve" la onda generada
(+ ruido, un poco de zumbido de red y distorsion); si esta apagado, solo el piso de ruido.
"""
import sys
import time
import types
import threading
import numpy as np

FS = 97656.25
FRAMES_POR_TRAMA = 512


class SerialException(Exception):
    pass


class _Canal:
    def __init__(self):
        self.on = False
        self.onda = 0          # 0 seno, 1 cuadrada, 2 triangular, 3 chirp
        self.f = 1000.0
        self.amp = 50.0        # % de la escala


class Serial:
    def __init__(self, puerto, baudrate=115200, timeout=0.05, **kw):
        self.port = puerto
        self.timeout = timeout
        self.is_open = True
        self._lock = threading.Lock()
        self._tx = bytearray()          # lo que "mando" el STM32 y la PC aun no leyo
        self._rx_cmd = b""
        self._streaming = False
        self._n_emitidas = 0            # frames ya generados (fase continua)
        self._t0 = 0.0
        self._seq = 0
        self.ch = {"L": _Canal(), "R": _Canal()}
        self.ch["R"].f = 2000.0
        self.adc_on = True
        self._rng = np.random.default_rng(7)

    # ---- API de pyserial que usa la app ----
    def set_buffer_size(self, rx_size=0, tx_size=0):
        pass

    def reset_input_buffer(self):
        with self._lock:
            self._generar()
            self._tx.clear()

    @property
    def in_waiting(self):
        with self._lock:
            self._generar()
            return len(self._tx)

    def read(self, n=1):
        fin = time.monotonic() + self.timeout
        while True:
            with self._lock:
                self._generar()
                if self._tx:
                    datos = bytes(self._tx[:n])
                    del self._tx[:n]
                    return datos
            if time.monotonic() >= fin:
                return b""
            time.sleep(0.002)

    def write(self, datos):
        with self._lock:
            self._rx_cmd += bytes(datos)
            while b"\n" in self._rx_cmd:
                linea, self._rx_cmd = self._rx_cmd.split(b"\n", 1)
                self._comando(linea.decode(errors="replace").strip())
        return len(datos)

    def close(self):
        self.is_open = False

    # ---- firmware simulado ----
    def _texto(self, s):
        b = s.encode("ascii")
        self._tx += bytes([0xAA, 0x55, 0x02, self._seq & 0xFF, len(b) & 0xFF, len(b) >> 8]) + b
        self._seq += 1

    def _comando(self, c):
        u = c.upper()
        if u == "PING":
            self._texto("PONG")
        elif u.startswith("STREAM:"):
            self._generar()
            self._streaming = u.endswith("1")
            if self._streaming:
                self._t0 = time.monotonic()
                self._n_emitidas = 0
        elif u.startswith("ADC:"):
            self.adc_on = u.endswith("1")
        elif u.startswith("DAC:"):
            for k in self.ch.values():
                k.on = u.endswith("1")
        elif u in ("LON", "LOFF"):
            self.ch["L"].on = u == "LON"
        elif u in ("RON", "ROFF"):
            self.ch["R"].on = u == "RON"
        elif u[:1] in "LR" and ":" in u:
            k = self.ch[u[0]]
            nombre, val = u[1:].split(":", 1)
            try:
                if nombre == "WAVE":
                    k.onda = int(val)
                elif nombre == "FREQ":
                    k.f = float(val)
                elif nombre == "AMP":
                    k.amp = float(val)
            except ValueError:
                pass

    def _onda(self, k, n):
        t = n / FS
        if k.onda == 0:
            y = np.sin(2 * np.pi * k.f * t)
        elif k.onda == 1:
            y = np.sign(np.sin(2 * np.pi * k.f * t))
        elif k.onda == 2:
            y = 2 / np.pi * np.arcsin(np.sin(2 * np.pi * k.f * t))
        else:                                  # chirp 100 Hz -> 10 kHz cada 2 s
            tt = np.mod(t, 2.0)
            y = np.sin(2 * np.pi * (100 * tt + (10000 - 100) * tt * tt / 4.0))
        return y * k.amp / 100.0 * 0.9

    def _generar(self):
        if not self._streaming:
            return
        debidas = int((time.monotonic() - self._t0) * FS) - self._n_emitidas
        while debidas >= FRAMES_POR_TRAMA:
            n = self._n_emitidas + np.arange(FRAMES_POR_TRAMA)
            t = n / FS
            cols = []
            for nombre, k in self.ch.items():
                y = self._rng.normal(0, 3e-6, FRAMES_POR_TRAMA)               # piso de ruido ~ -110 dBFS
                y += 4e-5 * np.sin(2 * np.pi * 50 * t)                         # zumbido de red
                if k.on and self.adc_on:
                    y += self._onda(k, n) * 0.97 + 2e-4 * np.sin(2 * np.pi * 2 * k.f * t)
                if not self.adc_on:
                    y = np.zeros(FRAMES_POR_TRAMA)
                cols.append(y)
            lr = (np.clip(np.stack(cols, 1), -1, 1) * (2**23 - 1)).astype(np.int32)
            b = (lr & 0xFFFFFF).astype("<u4").view(np.uint8).reshape(-1, 4)[:, :3]
            payload = b.reshape(-1, 6).tobytes()
            self._tx += bytes([0xAA, 0x55, 0x01, self._seq & 0xFF,
                               FRAMES_POR_TRAMA & 0xFF, FRAMES_POR_TRAMA >> 8]) + payload
            self._seq += 1
            self._n_emitidas += FRAMES_POR_TRAMA
            debidas -= FRAMES_POR_TRAMA


def instalar():
    """Hace que `import serial` / `serial.tools.list_ports` devuelvan este STM32 simulado."""
    serial = types.ModuleType("serial")
    serial.Serial = Serial
    serial.SerialException = SerialException
    tools = types.ModuleType("serial.tools")
    lp = types.ModuleType("serial.tools.list_ports")

    class _P:
        device = "COM7 (simulado)"

    lp.comports = lambda: [_P()]
    tools.list_ports = lp
    serial.tools = tools
    sys.modules.update({"serial": serial, "serial.tools": tools, "serial.tools.list_ports": lp})
