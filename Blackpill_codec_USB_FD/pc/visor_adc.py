"""
Recepcion y visualizacion de la señal del ADC que manda el STM32 por el COM virtual.

Formato de cada trama (STM32 -> PC), little-endian (ver Core/Inc/stream.h):

    0xAA 0x55 | tipo | seq | n (2 bytes) | payload

    tipo 0x01 (audio): n frames estereo, cada uno [L0 L1 L2 R0 R1 R2] (24 bits con signo)
    tipo 0x02 (texto): n caracteres ASCII (respuesta a un comando, ej. "PONG")
"""

import threading
import collections

import numpy as np
import serial
import tkinter as tk
from tkinter import ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


FS = 97656.25                 # frecuencia de muestreo del codec (debe coincidir con el firmware)
SYNC = b"\xAA\x55"
TIPO_AUDIO = 0x01
TIPO_TEXTO = 0x02
HDR = 6
MAX_FRAMES = 4096             # tope razonable para validar el encabezado
MAX_TEXTO = 64
FULL_SCALE = float(1 << 23)   # 24 bits con signo


# ============================================================
# RECEPTOR (hilo que lee el puerto y decodifica tramas)
# ============================================================

class Receptor:

    def __init__(self, ser, capacidad=1 << 15):

        self.ser = ser
        self.capacidad = capacidad

        self.buf = bytearray()

        # ring con las ultimas 'capacidad' muestras de cada canal (normalizadas a +-1)
        self.ring = np.zeros((capacidad, 2), dtype=np.float32)
        self.total = 0                 # muestras (frames) recibidas en total

        self.tramas = 0
        self.perdidas = 0              # tramas que el STM32 descarto o se perdieron
        self.ultimo_seq = None

        self.textos = collections.deque(maxlen=50)
        self.error = None

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._hilo = None

    # ---- ciclo de vida ----

    def iniciar(self):
        self._hilo = threading.Thread(target=self._loop, daemon=True)
        self._hilo.start()

    def detener(self):
        self._stop.set()

    def reiniciar(self):
        """Descarta lo acumulado (se llama antes de empezar una captura)."""
        with self._lock:
            self.buf.clear()
            self.ultimo_seq = None
            self.perdidas = 0
            self.tramas = 0
            self.total = 0
            self.ring[:] = 0

    # ---- lectura ----

    def _loop(self):
        while not self._stop.is_set():
            try:
                datos = self.ser.read(self.ser.in_waiting or 1)
            except (serial.SerialException, OSError) as e:
                self.error = str(e)
                return
            if datos:
                with self._lock:
                    self.buf.extend(datos)
                    self._procesar()

    def alimentar(self, datos):
        """Mismo procesamiento pero con bytes dados (para pruebas sin hardware)."""
        with self._lock:
            self.buf.extend(datos)
            self._procesar()

    def _procesar(self):
        buf = self.buf

        while True:

            i = buf.find(SYNC)

            if i < 0:
                del buf[:-1]           # por si el ultimo byte es el 0xAA de un encabezado partido
                return

            if i > 0:
                del buf[:i]

            if len(buf) < HDR:
                return

            tipo = buf[2]
            seq = buf[3]
            n = buf[4] | (buf[5] << 8)

            if tipo == TIPO_AUDIO and 0 < n <= MAX_FRAMES:
                largo = n * 6
            elif tipo == TIPO_TEXTO and n <= MAX_TEXTO:
                largo = n
            else:
                del buf[:1]            # falso sincronismo: sigo buscando
                continue

            if len(buf) < HDR + largo:
                return                 # falta llegar el resto de la trama

            payload = bytes(buf[HDR:HDR + largo])
            del buf[:HDR + largo]

            if self.ultimo_seq is not None:
                self.perdidas += (seq - self.ultimo_seq - 1) & 0xFF
            self.ultimo_seq = seq

            if tipo == TIPO_AUDIO:
                self._guardar_audio(payload)
            else:
                self.textos.append(payload.decode("ascii", errors="replace"))

    def _guardar_audio(self, payload):

        a = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 6).astype(np.int32)

        l = a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16)
        r = a[:, 3] | (a[:, 4] << 8) | (a[:, 5] << 16)

        l = ((l ^ 0x800000) - 0x800000) / FULL_SCALE      # extension de signo de 24 bits
        r = ((r ^ 0x800000) - 0x800000) / FULL_SCALE

        bloque = np.stack((l, r), axis=1).astype(np.float32)
        n = len(bloque)

        self.ring = np.roll(self.ring, -n, axis=0)
        self.ring[-n:] = bloque

        self.total += n
        self.tramas += 1

    # ---- acceso desde la interfaz ----

    def ultimas(self, n):
        """Ultimas n muestras (n, 2) y cuantas son validas."""
        with self._lock:
            validas = min(n, self.total)
            return self.ring[-n:].copy(), validas


# ============================================================
# VISOR (ventana con tiempo + espectro)
# ============================================================

class VisorADC:

    N_TIEMPO = 1024               # ~10 ms a 97.6 kHz
    N_FFT = 4096
    PERIODO_MS = 60

    def __init__(self, root, stm32):

        self.stm32 = stm32
        self.capturando = False

        self.win = tk.Toplevel(root)
        self.win.title("Entrada ADC - PCM3060")
        self.win.geometry("900x640")
        self.win.protocol("WM_DELETE_WINDOW", self.cerrar)

        # ---- controles ----
        barra = ttk.Frame(self.win, padding=8)
        barra.pack(fill="x")

        self.boton = ttk.Button(barra, text="Iniciar captura", command=self.alternar)
        self.boton.pack(side="left", padx=4)

        ttk.Label(barra, text="Canal:").pack(side="left", padx=(15, 2))
        self.canal = tk.StringVar(value="L + R")
        combo = ttk.Combobox(barra, textvariable=self.canal, state="readonly", width=6,
                             values=["L + R", "L", "R"])
        combo.pack(side="left")

        self.estado = ttk.Label(barra, text="Detenido")
        self.estado.pack(side="left", padx=15)

        # ---- graficos ----
        self.fig = Figure(figsize=(9, 6), dpi=100, tight_layout=True)
        self.ax_t = self.fig.add_subplot(2, 1, 1)
        self.ax_f = self.fig.add_subplot(2, 1, 2)

        t = np.arange(self.N_TIEMPO) / FS * 1000.0
        self.linea_l, = self.ax_t.plot(t, np.zeros(self.N_TIEMPO), lw=1, label="L")
        self.linea_r, = self.ax_t.plot(t, np.zeros(self.N_TIEMPO), lw=1, label="R")
        self.ax_t.set_xlim(0, t[-1])
        self.ax_t.set_ylim(-1.05, 1.05)
        self.ax_t.set_xlabel("Tiempo [ms]")
        self.ax_t.set_ylabel("Amplitud (fs = 1)")
        self.ax_t.grid(True, alpha=0.3)
        self.ax_t.legend(loc="upper right")

        f = np.fft.rfftfreq(self.N_FFT, 1.0 / FS)
        self.f = f[1:]
        self.espec_l, = self.ax_f.plot(self.f, np.full(len(self.f), -140.0), lw=1, label="L")
        self.espec_r, = self.ax_f.plot(self.f, np.full(len(self.f), -140.0), lw=1, label="R")
        self.ax_f.set_xscale("log")
        self.ax_f.set_xlim(20, FS / 2)
        self.ax_f.set_ylim(-140, 0)
        self.ax_f.set_xlabel("Frecuencia [Hz]")
        self.ax_f.set_ylabel("Nivel [dBFS]")
        self.ax_f.grid(True, which="both", alpha=0.3)

        self.ventana = np.hanning(self.N_FFT).astype(np.float32)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.win)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        self.win.after(self.PERIODO_MS, self.refrescar)

    # ---- captura ----

    def alternar(self):

        if not self.capturando:

            if self.stm32.receptor is None:
                self.estado.config(text="Conectá el STM32 primero")
                return

            self.stm32.receptor.reiniciar()
            self.stm32.ser.reset_input_buffer()

            if self.stm32.enviar("STREAM:1"):
                self.capturando = True
                self.boton.config(text="Detener captura")

        else:
            self.detener()

    def detener(self):
        self.stm32.enviar("STREAM:0")
        self.capturando = False
        self.boton.config(text="Iniciar captura")

    def cerrar(self):
        if self.capturando:
            self.detener()
        self.win.destroy()

    # ---- refresco periodico ----

    def refrescar(self):

        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return

        rec = self.stm32.receptor

        if rec is not None:

            if rec.error:
                self.estado.config(text=f"Error de puerto: {rec.error}")
                self.capturando = False
                self.boton.config(text="Iniciar captura")

            elif self.capturando:

                datos, validas = rec.ultimas(self.N_FFT)

                if validas >= self.N_TIEMPO:
                    self.actualizar_graficos(datos, validas)

                self.estado.config(
                    text=f"Tramas: {rec.tramas}   Perdidas: {rec.perdidas}"
                )

            elif rec.textos:
                self.estado.config(text=rec.textos[-1])

        self.win.after(self.PERIODO_MS, self.refrescar)

    def actualizar_graficos(self, datos, validas):

        sel = self.canal.get()
        ver_l = sel in ("L + R", "L")
        ver_r = sel in ("L + R", "R")

        tiempo = datos[-self.N_TIEMPO:]

        self.linea_l.set_ydata(tiempo[:, 0] if ver_l else np.full(self.N_TIEMPO, np.nan))
        self.linea_r.set_ydata(tiempo[:, 1] if ver_r else np.full(self.N_TIEMPO, np.nan))

        if validas >= self.N_FFT:
            for linea, col, ver in ((self.espec_l, 0, ver_l), (self.espec_r, 1, ver_r)):
                if not ver:
                    linea.set_ydata(np.full(len(self.f), np.nan))
                    continue
                x = datos[:, col] * self.ventana
                mag = np.abs(np.fft.rfft(x))[1:] / (self.N_FFT / 4.0)   # 1.0 = seno de escala completa
                linea.set_ydata(20.0 * np.log10(mag + 1e-9))

        self.canvas.draw_idle()
