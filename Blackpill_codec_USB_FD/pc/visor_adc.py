"""
Recepcion y visualizacion de la señal del ADC que manda el STM32 por el COM virtual.

Formato de cada trama (STM32 -> PC), little-endian (ver Core/Inc/stream.h):

    0xAA 0x55 | tipo | seq | n (2 bytes) | payload

    tipo 0x01 (audio): n frames estereo, cada uno [L0 L1 L2 R0 R1 R2] (24 bits con signo)
    tipo 0x02 (texto): n caracteres ASCII (respuesta a un comando, ej. "PONG")
"""

import threading
import collections
import time

import numpy as np
import serial
import tkinter as tk
from tkinter import ttk, messagebox

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

# visor
N_FFT = 32768                 # 2.98 Hz por bin: alcanza para ver tonos de 10 Hz
PROMEDIO_S = 1.0              # el espectro es el promedio de lo ultimo 1 s y se refresca cada 1 s
MAX_PUNTOS = 600              # columnas min/max que se dibujan por canal (la pantalla tiene ~1000 px)
VENTANAS_MS = ["0.25", "0.5", "1", "2", "5", "10", "20", "50", "100", "200", "500", "1000"]
VENTANA_MIN_MS = 0.1
VENTANA_MAX_MS = 1000.0

# mediciones (tiempo fijo / continua)
BLOQUE_S = 1.0                # los promedios se hacen siempre sobre bloques de 1 s
BLOQUE_MUESTRAS = int(round(FS * BLOQUE_S))
PROMEDIO_CONT = 5             # en modo continuo se promedian y muestran 5 bloques de 1 s cada 5 s
MAX_MEDICION_S = 60           # tope de la medicion de tiempo fijo (se guarda todo en memoria)
FINOS_EN_VIVO = 3             # bloques individuales que se dibujan en fino mientras se mide (cada linea cuesta ~1 ms)
ESPERA_DAC_S = 0.3            # con "disparar DAC": tiempo con el DAC apagado antes de empezar a medir


# ============================================================
# RECEPTOR (hilo que lee el puerto y decodifica tramas)
# ============================================================

class Receptor:

    def __init__(self, ser, capacidad=1 << 17):

        self.ser = ser
        self.capacidad = capacidad

        # buffer de recepcion del driver (por defecto pyserial pide solo 4 kB = 7 ms de audio)
        try:
            ser.set_buffer_size(rx_size=1 << 20)
        except (AttributeError, serial.SerialException, OSError):
            pass

        self.buf = bytearray()

        # ring con las ultimas 'capacidad' muestras de cada canal (normalizadas a +-1)
        self.ring = np.zeros((capacidad, 2), dtype=np.float32)
        self.pos = 0                   # proxima posicion de escritura del ring
        self.total = 0                 # muestras (frames) recibidas en total

        self.tramas = 0
        self.perdidas = 0              # tramas que el STM32 descarto o se perdieron
        self.ultimo_seq = None

        self.textos = collections.deque(maxlen=50)
        self.error = None

        self.grabadora = None          # si no es None, recibe el audio cortado en bloques (ver Grabadora)

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
            self.pos = 0
            self.ring[:] = 0
            self.grabadora = None

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

            perdidas_antes = 0
            if self.ultimo_seq is not None:
                perdidas_antes = (seq - self.ultimo_seq - 1) & 0xFF
                self.perdidas += perdidas_antes
            self.ultimo_seq = seq

            if tipo == TIPO_AUDIO:
                self._guardar_audio(payload, perdidas_antes)
            else:
                self.textos.append(payload.decode("ascii", errors="replace"))

    def _guardar_audio(self, payload, perdidas_antes=0):

        a = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 6).astype(np.int32)

        l = a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16)
        r = a[:, 3] | (a[:, 4] << 8) | (a[:, 5] << 16)

        l = ((l ^ 0x800000) - 0x800000) / FULL_SCALE      # extension de signo de 24 bits
        r = ((r ^ 0x800000) - 0x800000) / FULL_SCALE

        bloque = np.stack((l, r), axis=1).astype(np.float32)
        n = len(bloque)

        fin = self.pos + n
        if fin <= self.capacidad:
            self.ring[self.pos:fin] = bloque
        else:
            k = self.capacidad - self.pos
            self.ring[self.pos:] = bloque[:k]
            self.ring[:fin - self.capacidad] = bloque[k:]
        self.pos = fin % self.capacidad

        self.total += n
        self.tramas += 1

        g = self.grabadora
        if g is not None:
            g.agregar(bloque, perdidas_antes > 0)

    # ---- acceso desde la interfaz ----

    def ultimas(self, n):
        """Ultimas n muestras en orden (shape (m, 2), con m = min(n, validas)) y m."""
        with self._lock:
            m = min(n, self.total, self.capacidad)
            if self.pos >= m:
                datos = self.ring[self.pos - m:self.pos].copy()
            else:
                datos = np.concatenate((self.ring[self.capacidad - (m - self.pos):],
                                        self.ring[:self.pos]))
            return datos, m


class Grabadora:
    """
    Corta el flujo de audio en bloques de 'n_bloque' muestras (1 s), despues de descartar
    las primeras 'por_descartar'. Se cuenta por MUESTRAS (no por reloj de la PC), asi el
    largo de cada bloque es exacto aunque Windows se demore.

    Vive en el hilo lector (agregar); la interfaz retira los bloques completos de 'listos'.
    Un bloque que contiene una trama perdida queda marcado como 'dano' (tiene un salto).
    """

    def __init__(self, n_bloque=BLOQUE_MUESTRAS, por_descartar=0, max_bloques=None):
        self.n_bloque = n_bloque
        self.por_descartar = por_descartar
        self.descartadas = 0
        self.max_bloques = max_bloques        # None = continuo
        self.completos = 0
        self.listos = collections.deque()     # (array (n_bloque, 2), dano)
        self._partes = []
        self._n = 0
        self._dano = False

    @property
    def terminada(self):
        return self.max_bloques is not None and self.completos >= self.max_bloques

    @property
    def progreso_bloque(self):
        return self._n / self.n_bloque

    def agregar(self, bloque, hubo_perdida):
        if self.terminada:
            return

        if self.por_descartar > 0:                       # transitorio: se tira, y sus perdidas no importan
            k = min(self.por_descartar, len(bloque))
            self.por_descartar -= k
            self.descartadas += k
            bloque = bloque[k:]
            if len(bloque) == 0:
                return
            hubo_perdida = False

        if hubo_perdida:
            self._dano = True

        while len(bloque) and not self.terminada:
            falta = self.n_bloque - self._n
            parte = bloque[:falta]
            self._partes.append(parte)
            self._n += len(parte)
            bloque = bloque[falta:]
            if self._n == self.n_bloque:
                self.listos.append((np.concatenate(self._partes), self._dano))
                self.completos += 1
                self._partes, self._n, self._dano = [], 0, False


# ============================================================
# PROCESAMIENTO (funciones puras, sin interfaz)
# ============================================================

def espectro_promedio(x, n_fft=N_FFT):
    """
    Espectro promedio (Welch) de una señal 1D: segmentos de n_fft con 50 % de solape,
    ventana Hann, se promedia la POTENCIA. Devuelve (potencia por bin sin el bin DC, segmentos).
    1.0 = seno de escala completa. Si no alcanzan las muestras devuelve (None, 0).
    """
    n = len(x)
    if n < n_fft:
        return None, 0

    hop = n_fft // 2
    k = (n - n_fft) // hop + 1
    w = np.hanning(n_fft).astype(np.float32)

    idx = np.arange(n_fft)[None, :] + hop * np.arange(k)[:, None]
    segs = x[idx]
    segs = (segs - segs.mean(axis=1, keepdims=True)) * w     # sin continua: no ensucia los bins de 10 Hz

    mag = np.abs(np.fft.rfft(segs, axis=1)) / (w.sum() / 2.0)
    return np.mean(mag ** 2, axis=0)[1:], k


def estadisticas_bloque(x):
    """x (n,) -> (RMS sin continua en dBFS, continua, pico). 'Ruido' = RMS de la señal sin su valor medio."""
    x = x.astype(np.float64)
    dc = float(np.mean(x))
    rms = float(np.sqrt(np.mean((x - dc) ** 2)))
    return 20.0 * np.log10(rms + 1e-12), dc, float(np.max(np.abs(x)))


def resumen_rms(bloques):
    """Por canal: (RMS promedio en potencia [dBFS], dispersion entre bloques [dB]) de los bloques sin perdidas, o None."""
    out = []
    for c in (0, 1):
        v = np.array([b["rms"][c] for b in bloques if not b["dano"]])
        if len(v) == 0:
            out.append(None)
            continue
        prom = 10.0 * np.log10(np.mean((10.0 ** (v / 20.0)) ** 2))
        out.append((float(prom), float(np.std(v))))
    return out


def buscar_disparo(x, n_ventana, max_busqueda):
    """Indice del primer cruce ascendente por el valor medio de x (0 si no hay), para que la señal no 'corra'."""
    tope = min(max_busqueda, len(x) - n_ventana)
    if tope < 2:
        return 0
    s = x[:tope + 1]
    nivel = x.mean()
    cruces = np.flatnonzero((s[:-1] < nivel) & (s[1:] >= nivel))
    return int(cruces[0] + 1) if len(cruces) else 0


def decimar_minmax(y, max_pts=MAX_PUNTOS):
    """
    Reduce (n, c) a ~2*max_pts filas guardando el minimo y el maximo de cada tramo
    (asi no se pierden picos al mostrar ventanas largas). Devuelve (indices de muestra, datos).
    """
    n = len(y)
    if n <= 2 * max_pts:
        return np.arange(n), y

    f = n // max_pts
    m = n // f
    b = y[:m * f].reshape(m, f, -1)
    out = np.empty((2 * m, y.shape[1]), dtype=y.dtype)
    out[0::2] = b.min(axis=1)
    out[1::2] = b.max(axis=1)
    return np.repeat(np.arange(m) * f + f // 2, 2), out


# ============================================================
# VISOR (ventana con tiempo + espectro)
# ============================================================

def indices_log(f, f_min=10.0, f_max=20000.0, puntos=1500):
    """Indices de bins espaciados en log entre f_min y f_max (para dibujar el espectro con pocos puntos)."""
    i0 = int(np.searchsorted(f, f_min))
    i1 = int(np.searchsorted(f, f_max))
    idx = np.unique(np.round(np.geomspace(max(i0, 1), i1, puntos)).astype(int))   # indices sobre 'f' (sin DC)
    return idx


def limite_y_bonito(pico):
    """Sube 'pico' al siguiente 1, 2 o 5 x 10^k (asi el eje Y no cambia en cada cuadro)."""
    e = 10.0 ** np.floor(np.log10(pico))
    for m in (1, 2, 5, 10):
        if pico <= m * e:
            return m * e
    return 10 * e


class Medicion:
    """Estado de una medicion (tiempo fijo o continua)."""

    def __init__(self, modo, n_bloques, descarte_s, dac, canales_dac, apagar_dac):
        self.modo = modo                       # "fijo" | "continuo"
        self.n_bloques = n_bloques             # solo tiempo fijo
        self.descarte_s = descarte_s
        self.dac = dac                         # disparar el DAC al iniciar
        self.canales_dac = canales_dac         # "L + R" | "L" | "R"
        self.apagar_dac = apagar_dac
        self.t_inicio = None
        self.bloques = []                      # estadisticas livianas de cada bloque
        # espectros: en tiempo fijo se guardan todos; en continuo solo los ultimos 5
        self.espectros = [] if modo == "fijo" else collections.deque(maxlen=PROMEDIO_CONT)
        self.crudo = []                        # muestras de cada bloque (solo tiempo fijo)


class VisorADC:

    PERIODO_MS = 100

    def __init__(self, root, stm32):

        self.stm32 = stm32
        self.capturando = False
        self.t_espectro = 0.0
        self.fondo_t = None            # fondo del grafico de tiempo, para blitting
        self.clave_t = None            # (ventana, limite Y) con el que se hizo ese fondo
        self.fondo_f = None            # idem para el espectro
        self.med = None                # medicion en curso
        self.ultima_med = None         # ultima medicion terminada (para repintar al cambiar de canal)
        self.vista_resultado = False   # el grafico de tiempo muestra la medicion completa
        self.lineas_bloque = []

        self.win = tk.Toplevel(root)
        self.win.title("Entrada ADC - PCM3060")
        self.win.geometry("1000x930")
        self.win.protocol("WM_DELETE_WINDOW", self.cerrar)

        # ---- controles ----
        barra = ttk.Frame(self.win, padding=8)
        barra.pack(fill="x")

        self.boton = ttk.Button(barra, text="Iniciar captura", command=self.alternar)
        self.boton.pack(side="left", padx=4)

        ttk.Label(barra, text="Canal:").pack(side="left", padx=(15, 2))
        self.canal = tk.StringVar(value="L + R")
        self.combo_canal = ttk.Combobox(barra, textvariable=self.canal, state="readonly", width=6,
                                        values=["L + R", "L", "R"])
        self.combo_canal.pack(side="left")
        self.combo_canal.bind("<<ComboboxSelected>>", lambda e: self._repintar())

        ttk.Label(barra, text="Ventana [ms]:").pack(side="left", padx=(15, 2))
        self.ventana_txt = tk.StringVar(value="10")
        ttk.Combobox(barra, textvariable=self.ventana_txt, width=7,
                     values=VENTANAS_MS).pack(side="left")

        self.trigger = tk.IntVar(value=1)
        ttk.Checkbutton(barra, text="Trigger", variable=self.trigger).pack(side="left", padx=(12, 0))

        self.auto_y = tk.IntVar(value=0)
        ttk.Checkbutton(barra, text="Auto Y", variable=self.auto_y).pack(side="left", padx=(8, 0))

        self.estado = ttk.Label(barra, text="Detenido")
        self.estado.pack(side="left", padx=15)

        # ---- medicion: DAC + ADC con tiempos ----
        marco = ttk.LabelFrame(self.win, text="Medición (DAC + ADC)", padding=6)
        marco.pack(fill="x", padx=8, pady=(0, 4))

        fila1 = ttk.Frame(marco)
        fila1.pack(fill="x")

        self.modo_med = tk.StringVar(value="fijo")
        ttk.Radiobutton(fila1, text="Tiempo fijo", variable=self.modo_med, value="fijo",
                        command=self._modo_cambiado).pack(side="left")
        ttk.Label(fila1, text="Duración [s]:").pack(side="left", padx=(8, 2))
        self.dur_txt = tk.StringVar(value="3")
        self.ent_dur = ttk.Entry(fila1, textvariable=self.dur_txt, width=5)
        self.ent_dur.pack(side="left")
        ttk.Label(fila1, text="Descartar el inicio [s]:").pack(side="left", padx=(8, 2))
        self.desc_txt = tk.StringVar(value="1")
        self.ent_desc = ttk.Entry(fila1, textvariable=self.desc_txt, width=5)
        self.ent_desc.pack(side="left")

        ttk.Radiobutton(fila1, text=f"Continuo (promedia cada {PROMEDIO_CONT} s)", variable=self.modo_med,
                        value="continuo", command=self._modo_cambiado).pack(side="left", padx=(20, 0))

        self.btn_med = ttk.Button(fila1, text="Iniciar medición", command=self.alternar_medicion)
        self.btn_med.pack(side="right", padx=4)

        fila2 = ttk.Frame(marco)
        fila2.pack(fill="x", pady=(4, 0))

        ttk.Label(fila2, text="DAC:").pack(side="left")
        self.dac_modo = tk.StringVar(value="Disparar al iniciar")
        ttk.Combobox(fila2, textvariable=self.dac_modo, state="readonly", width=19,
                     values=["Disparar al iniciar", "No tocar el DAC"]).pack(side="left", padx=(2, 8))
        ttk.Label(fila2, text="Canales del DAC:").pack(side="left")
        self.dac_canales = tk.StringVar(value="L + R")
        ttk.Combobox(fila2, textvariable=self.dac_canales, state="readonly", width=6,
                     values=["L + R", "L", "R"]).pack(side="left", padx=(2, 8))
        self.apagar_dac = tk.IntVar(value=1)
        ttk.Checkbutton(fila2, text="Apagar el DAC al terminar", variable=self.apagar_dac).pack(side="left")
        ttk.Button(fila2, text="DAC ON", command=lambda: self.dac_manual(True)).pack(side="left", padx=(16, 2))
        ttk.Button(fila2, text="DAC OFF", command=lambda: self.dac_manual(False)).pack(side="left")
        ttk.Label(fila2, text="(la forma de onda, frecuencia y amplitud se eligen en la ventana principal)",
                  foreground="gray").pack(side="left", padx=10)

        # ---- registro de bloques ----
        self.txt_log = tk.Text(self.win, height=7, font=("Consolas", 9), state="disabled", wrap="none")
        self.txt_log.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        # ---- grafico de tiempo (figura propia: se refresca por blitting, casi gratis) ----
        self.fig_t = Figure(figsize=(10, 3.4), dpi=100)
        self.fig_t.subplots_adjust(left=0.08, right=0.985, top=0.95, bottom=0.17)
        self.ax_t = self.fig_t.add_subplot(1, 1, 1)

        self.linea_l, = self.ax_t.plot([], [], lw=1, label="L", animated=True)
        self.linea_r, = self.ax_t.plot([], [], lw=1, label="R", animated=True)
        self.ax_t.set_xlim(0, 10)
        self.ax_t.set_ylim(-1.05, 1.05)
        self.ax_t.set_xlabel("Tiempo [ms]")
        self.ax_t.set_ylabel("Amplitud (fs = 1)")
        self.ax_t.grid(True, alpha=0.3)
        self.ax_t.legend(loc="upper right")

        self.canvas_t = FigureCanvasTkAgg(self.fig_t, master=self.win)
        self.canvas_t.mpl_connect("draw_event", self._guardar_fondo)

        # ---- grafico de espectro (tambien por blitting: un redibujo completo frena al hilo lector) ----
        self.fig_f = Figure(figsize=(10, 3.4), dpi=100)
        self.fig_f.subplots_adjust(left=0.08, right=0.985, top=0.97, bottom=0.17)
        self.ax_f = self.fig_f.add_subplot(1, 1, 1)

        self.f = np.fft.rfftfreq(N_FFT, 1.0 / FS)[1:]      # frecuencia de cada bin (sin DC)
        self.idx_log = indices_log(self.f)
        self.f_plot = self.f[self.idx_log]
        nan = np.full(len(self.f_plot), np.nan)
        self.espec_l, = self.ax_f.plot(self.f_plot, nan, lw=1.5, label="L", color="C0", animated=True, zorder=5)
        self.espec_r, = self.ax_f.plot(self.f_plot, nan, lw=1.5, label="R", color="C1", animated=True, zorder=5)
        self.ax_f.set_xscale("log")
        self.ax_f.set_xlim(10, 20000)
        self.ax_f.set_ylim(-160, 0)
        self.ax_f.set_xlabel("Frecuencia [Hz]")
        self.ax_f.set_ylabel("Nivel [dBFS]")
        self.ax_f.grid(True, which="both", alpha=0.3)
        self.ax_f.legend(handles=[self.espec_l, self.espec_r], loc="upper right")

        self.canvas_f = FigureCanvasTkAgg(self.fig_f, master=self.win)
        self.canvas_f.mpl_connect("draw_event", self._guardar_fondo_f)

        self.canvas_t.get_tk_widget().pack(fill="both", expand=True)
        # el titulo del espectro es una etiqueta de Tk: dibujarlo dentro de matplotlib cuesta ~13 ms por cuadro
        self.lbl_espectro = ttk.Label(self.win, text=f"Espectro promedio de {PROMEDIO_S:g} s (esperando datos)", anchor="center")
        self.lbl_espectro.pack(fill="x")
        self.canvas_f.get_tk_widget().pack(fill="both", expand=True)

        self._modo_cambiado()
        self._after_id = self.win.after(self.PERIODO_MS, self.refrescar)

    def _guardar_fondo(self, evento):
        self.fondo_t = self.canvas_t.copy_from_bbox(self.ax_t.bbox)

    def _guardar_fondo_f(self, evento):
        self.fondo_f = self.canvas_f.copy_from_bbox(self.fig_f.bbox)

    def _dibujar_espectro(self):
        """Redibuja solo las lineas (el fondo se guarda en cada redibujo completo)."""
        if self.fondo_f is None:
            self.canvas_f.draw()
        self.canvas_f.restore_region(self.fondo_f)
        for ln in self.lineas_bloque:
            self.ax_f.draw_artist(ln)
        self.ax_f.draw_artist(self.espec_l)
        self.ax_f.draw_artist(self.espec_r)
        self.canvas_f.blit(self.fig_f.bbox)

    # ---- captura en vivo ----

    def alternar(self):

        if not self.capturando:

            if self.med is not None:
                self.estado.config(text="Hay una medición en curso")
                return

            if self.stm32.receptor is None:
                self.estado.config(text="Conectá el STM32 primero")
                return

            self._salir_vista_resultado()
            self.stm32.receptor.reiniciar()
            self.stm32.ser.reset_input_buffer()
            self.t_espectro = time.monotonic()      # el 1er promedio sale despues de 1 s

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
        if self.med is not None:
            self.detener_medicion("Medición interrumpida")
        if self.capturando:
            self.detener()
        try:
            self.win.after_cancel(self._after_id)
        except (AttributeError, tk.TclError, ValueError):
            pass
        self.win.destroy()

    # ---- DAC ----

    def comandos_dac(self, encendido):
        canales = self.dac_canales.get()
        cmds = []
        if canales in ("L + R", "L"):
            cmds.append("LON" if encendido else "LOFF")
        if canales in ("L + R", "R"):
            cmds.append("RON" if encendido else "ROFF")
        return cmds

    def dac_manual(self, encendido):
        for c in self.comandos_dac(encendido):
            self.stm32.enviar(c)

    # ---- medicion (tiempo fijo / continua) ----

    def _modo_cambiado(self):
        fijo = self.modo_med.get() == "fijo"
        estado = "normal" if fijo else "disabled"
        self.ent_dur.config(state=estado)
        self.ent_desc.config(state=estado)

    def _log(self, texto, limpiar=False):
        self.txt_log.config(state="normal")
        if limpiar:
            self.txt_log.delete("1.0", "end")
        self.txt_log.insert("end", texto + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _leer_medicion(self):
        """Valida los campos; devuelve una Medicion o None (con el motivo en la barra de estado)."""
        modo = self.modo_med.get()
        n_bloques, descarte = 0, 0.0
        if modo == "fijo":
            try:
                dur = float(self.dur_txt.get().replace(",", "."))
                descarte = float(self.desc_txt.get().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Medición", "Duración y descarte tienen que ser números.")
                return None
            n_bloques = int(dur)
            if n_bloques < 1 or n_bloques > MAX_MEDICION_S:
                messagebox.showwarning("Medición", f"La duración tiene que estar entre 1 y {MAX_MEDICION_S} s.")
                return None
            if descarte < 0 or descarte > 10:
                messagebox.showwarning("Medición", "El descarte tiene que estar entre 0 y 10 s.")
                return None
        return Medicion(modo, n_bloques, descarte, self.dac_modo.get() == "Disparar al iniciar",
                        self.dac_canales.get(), bool(self.apagar_dac.get()))

    def alternar_medicion(self):
        if self.med is None:
            self.iniciar_medicion()
        else:
            self.detener_medicion("Medición detenida")

    def iniciar_medicion(self):
        if self.stm32.receptor is None:
            self.estado.config(text="Conectá el STM32 primero")
            return
        if self.capturando:
            self.detener()
        m = self._leer_medicion()
        if m is None:
            return

        self._salir_vista_resultado()
        self._limpiar_espectros()
        self._predibujar()
        self.med = m
        self.boton.config(state="disabled")
        self.btn_med.config(text="Detener medición")

        if m.modo == "fijo":
            self._log(f"Tiempo fijo: se descartan los primeros {m.descarte_s:g} s y se miden {m.n_bloques} bloque(s) "
                      f"completos de {BLOQUE_S:g} s (se promedia cada bloque).", limpiar=True)
        else:
            self._log(f"Continuo: se promedian y muestran {PROMEDIO_CONT} bloques de {BLOQUE_S:g} s cada {PROMEDIO_CONT} s. "
                      f"«Detener medición» para frenar.", limpiar=True)

        if m.dac:
            # DAC apagado un momento, para que al encenderlo se vea el transitorio completo
            self.estado.config(text="Apagando el DAC y esperando...")
            for c in self.comandos_dac(False):
                self.stm32.enviar(c)
            self.win.after(int(ESPERA_DAC_S * 1000), self._arrancar_medicion)
        else:
            self._arrancar_medicion()

    def _predibujar(self):
        """
        Un redibujo completo de matplotlib tarda ~100 ms y frena al hilo lector (el ring del STM32 aguanta
        ~28 ms). Se hace ahora, antes de grabar, para que durante la medicion solo haya blitting.
        """
        ms, _ = self.ventana()
        self.clave_t = (ms, 1.05)
        self.ax_t.set_xlim(0, ms)
        self.ax_t.set_ylim(-1.05, 1.05)
        self.canvas_t.draw()
        self.canvas_f.draw()
        self._dibujar_espectro()        # primer uso de las lineas en frio (cuesta mas): que no ocurra durante la medicion

    def _arrancar_medicion(self):
        m = self.med
        rec = self.stm32.receptor
        if m is None or rec is None or not self.win.winfo_exists():     # se cancelo mientras se esperaba
            return

        rec.reiniciar()
        self.stm32.ser.reset_input_buffer()
        rec.grabadora = Grabadora(BLOQUE_MUESTRAS, int(round(m.descarte_s * FS)),
                                  m.n_bloques if m.modo == "fijo" else None)
        m.t_inicio = time.monotonic()

        if not self.stm32.enviar("STREAM:1"):
            self.detener_medicion("No se pudo iniciar el streaming")
            return
        if m.dac:
            for c in self.comandos_dac(True):        # el DAC se dispara justo despues de empezar a grabar
                self.stm32.enviar(c)

    def detener_medicion(self, motivo):
        m = self.med
        if m is None:
            return
        rec = self.stm32.receptor
        self.stm32.enviar("STREAM:0")
        if rec is not None:
            rec.grabadora = None
        if m.dac and m.apagar_dac:
            for c in self.comandos_dac(False):
                self.stm32.enviar(c)
        self.med = None
        self.ultima_med = m
        self.boton.config(state="normal")
        self.btn_med.config(text="Iniciar medición")
        self.estado.config(text=motivo)

    def _procesar_medicion(self, rec):
        m = self.med
        g = rec.grabadora
        if g is None:
            return

        while g.listos:
            arr, dano = g.listos.popleft()
            self._agregar_bloque(arr, dano)

        if m.modo == "fijo" and len(m.bloques) >= m.n_bloques:
            self._finalizar_fijo()
            return

        if rec.total == 0 and m.t_inicio is not None and time.monotonic() - m.t_inicio > 3.0:
            self.detener_medicion("Sin datos del STM32 (¿firmware nuevo cargado?)")
            return

        self.actualizar_tiempo(rec)

        if g.por_descartar > 0:
            txt = f"Descartando el transitorio: {g.descartadas / FS:.1f} / {m.descarte_s:g} s"
        elif m.modo == "fijo":
            txt = f"Midiendo: bloque {len(m.bloques) + 1} de {m.n_bloques} ({100 * g.progreso_bloque:.0f} %)"
        else:
            txt = (f"Midiendo (continuo): bloque {len(m.bloques) + 1} · "
                   f"próximo promedio en {PROMEDIO_CONT - len(m.bloques) % PROMEDIO_CONT} bloque(s)")
        self.estado.config(text=f"{txt}   Tramas perdidas: {rec.perdidas}")

    def _agregar_bloque(self, arr, dano):
        m = self.med
        pot, rms, dc, pico = [], [], [], []
        for c in (0, 1):
            p, _ = espectro_promedio(arr[:, c])
            r, d, pk = estadisticas_bloque(arr[:, c])
            pot.append(p)
            rms.append(r)
            dc.append(d)
            pico.append(pk)
        b = {"rms": rms, "dc": dc, "pico": pico, "dano": dano}
        m.bloques.append(b)
        m.espectros.append({"pot": pot, "dano": dano})
        if m.modo == "fijo":
            m.crudo.append(arr)

        n = len(m.bloques)
        self._log(f"Bloque {n:>3}: L RMS {rms[0]:7.1f} dBFS  DC {dc[0]:+.5f}  pico {pico[0]:.4f} | "
                  f"R RMS {rms[1]:7.1f} dBFS  DC {dc[1]:+.5f}  pico {pico[1]:.4f}"
                  + ("   <-- tramas perdidas: excluido del promedio" if dano else ""))

        # fijo: se actualiza con cada bloque; continuo: solo cuando se completan 5 bloques (cada 5 s)
        if m.modo == "fijo" or n % PROMEDIO_CONT == 0:
            self._pintar_espectros(m)

    def _finalizar_fijo(self):
        m = self.med
        res = resumen_rms(m.bloques)
        validos = sum(1 for b in m.bloques if not b["dano"])
        partes = []
        for nombre, r in zip(("L", "R"), res):
            partes.append(f"{nombre}: " + ("sin bloques válidos" if r is None else f"RMS {r[0]:.1f} dBFS (±{r[1]:.2f} dB entre bloques)"))
        self._log(f"Resumen ({validos}/{len(m.bloques)} bloques sin pérdidas) -> " + " | ".join(partes))
        datos = np.concatenate(m.crudo) if m.crudo else None
        self.detener_medicion(f"Medición lista: {len(m.bloques)} bloque(s) de {BLOQUE_S:g} s, "
                              f"{len(m.bloques) - validos} con pérdidas")
        self._pintar_espectros(m, final=True)
        if datos is not None:
            self._mostrar_resultado_tiempo(datos)

    # ---- graficos de la medicion ----

    def _limpiar_espectros(self):
        for ln in self.lineas_bloque:
            ln.remove()
        self.lineas_bloque = []
        nan = np.full(len(self.f_plot), np.nan)
        self.espec_l.set_ydata(nan)
        self.espec_r.set_ydata(nan)

    def _db_log(self, pot):
        db = 10.0 * np.log10(pot + 1e-18)
        return np.maximum.reduceat(db[:self.idx_log[-1] + 1], self.idx_log)    # maximo de cada grupo: no se pierden picos

    def _titulo_med(self, m):
        n = len(m.bloques)
        danados = sum(1 for e in m.espectros if e["dano"])
        validos = len(m.espectros) - danados
        if m.modo == "fijo":
            t = (f"Tiempo fijo: {n}/{m.n_bloques} bloques de {BLOQUE_S:g} s (se descartó el primer {m.descarte_s:g} s) "
                 f"· promedio de {validos}")
        else:
            t = (f"Continuo: promedio de los últimos {len(m.espectros)} bloques de {BLOQUE_S:g} s "
                 f"(se actualiza cada {PROMEDIO_CONT} s) · bloques medidos: {n}")
        if danados:
            t += f" · {danados} con pérdidas (en gris, excluidos)"
        return t

    def _pintar_espectros(self, m, final=False):
        """
        Linea gruesa = promedio de TODOS los bloques validos. Lineas finas = bloques individuales: mientras
        se mide se dibujan solo los ultimos 3 (cada linea cuesta ~1 ms con el GIL tomado, y el ring del STM32
        aguanta ~28 ms); al terminar ('final'), con el stream detenido, se dibujan todos.
        """
        ver_l, ver_r = self.canales_visibles()
        todos = list(m.espectros)
        finos = todos if (final or m.modo == "continuo") else todos[-FINOS_EN_VIVO:]
        for ln in self.lineas_bloque:
            ln.remove()
        self.lineas_bloque = []

        for c, (media, ver, color) in enumerate(((self.espec_l, ver_l, "C0"), (self.espec_r, ver_r, "C1"))):
            if not ver:
                media.set_ydata(np.full(len(self.f_plot), np.nan))
                continue
            for e in finos:
                y = self._db_log(e["pot"][c])
                if e["dano"]:
                    ln, = self.ax_f.plot(self.f_plot, y, color="0.5", lw=0.8, ls=":", animated=True)
                else:
                    ln, = self.ax_f.plot(self.f_plot, y, color=color, lw=0.8, alpha=0.3, animated=True)
                self.lineas_bloque.append(ln)
            validos = [e["pot"][c] for e in todos if not e["dano"]]
            if validos:
                media.set_ydata(self._db_log(np.mean(validos, axis=0)))
            else:
                media.set_ydata(np.full(len(self.f_plot), np.nan))

        t = self._titulo_med(m)
        if len(finos) < len(todos):
            t += f" · en fino, los últimos {len(finos)} (el resto al terminar)"
        self.lbl_espectro.config(text=t)
        self._dibujar_espectro()

    def _mostrar_resultado_tiempo(self, datos):
        """Despues de una medicion de tiempo fijo: todo el registro (envolvente min/max) en el grafico de tiempo."""
        ver_l, ver_r = self.canales_visibles()
        self.vista_resultado = True
        self.res_datos = datos
        for ln in (self.linea_l, self.linea_r):
            ln.set_animated(False)                  # ahora se dibujan con el redibujo completo
        idx, dec = decimar_minmax(datos)
        t = idx * (1000.0 / FS)
        nada = np.full(len(t), np.nan, dtype=np.float32)
        self.linea_l.set_data(t, dec[:, 0] if ver_l else nada)
        self.linea_r.set_data(t, dec[:, 1] if ver_r else nada)
        self.ax_t.set_xlim(0, len(datos) / FS * 1000.0)
        if self.auto_y.get():
            pico = max(float(np.abs(dec[:, 0]).max()) if ver_l else 0.0,
                       float(np.abs(dec[:, 1]).max()) if ver_r else 0.0)
            ylim = limite_y_bonito(max(pico * 1.1, 1e-4))
        else:
            ylim = 1.05
        self.ax_t.set_ylim(-ylim, ylim)
        self.ax_t.set_xlabel(f"Tiempo [ms] — medición completa ({len(datos) / FS:.1f} s, envolvente min/max)")
        self.canvas_t.draw()

    def _salir_vista_resultado(self):
        if not self.vista_resultado:
            return
        self.vista_resultado = False
        for ln in (self.linea_l, self.linea_r):
            ln.set_animated(True)
        self.ax_t.set_xlabel("Tiempo [ms]")
        self.clave_t = None
        self.fondo_t = None

    def _repintar(self):
        """Al cambiar de canal: repinta lo ultimo medido."""
        m = self.med or self.ultima_med
        if m is not None and m.espectros:
            self._pintar_espectros(m, final=self.med is None)
        if self.vista_resultado and getattr(self, "res_datos", None) is not None:
            self._mostrar_resultado_tiempo(self.res_datos)

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
                if self.med is not None:
                    self.detener_medicion(f"Error de puerto: {rec.error}")
                self.capturando = False
                self.boton.config(text="Iniciar captura", state="normal")

            elif self.med is not None:
                self._procesar_medicion(rec)

            elif self.capturando:

                self.actualizar_tiempo(rec)

                if time.monotonic() - self.t_espectro >= PROMEDIO_S:
                    self.t_espectro = time.monotonic()
                    self.actualizar_espectro(rec)

                total = rec.tramas + rec.perdidas
                pct = 100.0 * rec.perdidas / total if total else 0.0
                self.estado.config(
                    text=f"Tramas: {rec.tramas}   Perdidas: {rec.perdidas} ({pct:.1f} %)"
                )

            elif rec.textos and self.ultima_med is None:
                self.estado.config(text=rec.textos[-1])

        self._after_id = self.win.after(self.PERIODO_MS, self.refrescar)

    def canales_visibles(self):
        sel = self.canal.get()
        return sel in ("L + R", "L"), sel in ("L + R", "R")

    def ventana(self):
        """Ventana de tiempo elegida: (ms, muestras). Acepta cualquier valor escrito entre 0.1 y 1000 ms."""
        try:
            ms = float(self.ventana_txt.get().replace(",", "."))
        except ValueError:
            ms = 10.0
        ms = min(max(ms, VENTANA_MIN_MS), VENTANA_MAX_MS)
        return ms, max(int(round(ms / 1000.0 * FS)), 16)

    def actualizar_tiempo(self, rec):

        if self.vista_resultado:
            return

        ms, n_vent = self.ventana()
        ver_l, ver_r = self.canales_visibles()
        usar_trigger = bool(self.trigger.get())

        extra = int(0.1 * FS) if usar_trigger else 0   # margen para buscar el disparo (>= 1 periodo de 10 Hz)
        datos, m = rec.ultimas(n_vent + extra)
        if m < 16:
            return

        if usar_trigger and m > n_vent:
            col = 0 if ver_l else 1
            i0 = buscar_disparo(datos[:, col], n_vent, m - n_vent)
            seg = datos[i0:i0 + n_vent]
        else:
            seg = datos[-n_vent:]

        idx, dec = decimar_minmax(seg)
        t = idx * (1000.0 / FS)

        nada = np.full(len(t), np.nan, dtype=np.float32)
        self.linea_l.set_data(t, dec[:, 0] if ver_l else nada)
        self.linea_r.set_data(t, dec[:, 1] if ver_r else nada)

        if self.auto_y.get():
            pico = max(float(np.abs(dec[:, 0]).max()) if ver_l else 0.0,
                       float(np.abs(dec[:, 1]).max()) if ver_r else 0.0)
            ylim = limite_y_bonito(max(pico * 1.1, 1e-4))
        else:
            ylim = 1.05

        # si cambio la escala hay que redibujar todo (fondo + ejes); si no, alcanza con redibujar las lineas
        clave = (ms, ylim)
        if clave != self.clave_t or self.fondo_t is None:
            self.clave_t = clave
            self.ax_t.set_xlim(0, ms)
            self.ax_t.set_ylim(-ylim, ylim)
            self.canvas_t.draw()                    # dispara draw_event -> se guarda el fondo

        self.canvas_t.restore_region(self.fondo_t)
        self.ax_t.draw_artist(self.linea_l)
        self.ax_t.draw_artist(self.linea_r)
        self.canvas_t.blit(self.ax_t.bbox)

    def actualizar_espectro(self, rec):
        """Espectro en vivo: promedio del ultimo segundo, refrescado cada segundo."""
        ver_l, ver_r = self.canales_visibles()
        datos, m = rec.ultimas(int(PROMEDIO_S * FS))

        for ln in self.lineas_bloque:
            ln.remove()
        self.lineas_bloque = []

        k = 0
        for linea, col, ver in ((self.espec_l, 0, ver_l), (self.espec_r, 1, ver_r)):
            pot, k_col = (espectro_promedio(datos[:, col]) if ver else (None, 0))
            if pot is None:
                linea.set_ydata(np.full(len(self.f_plot), np.nan))
                continue
            k = k_col
            linea.set_ydata(self._db_log(pot))

        if k:
            self.lbl_espectro.config(
                text=f"Espectro promedio de {m / FS:.2f} s ({k} segmentos de {N_FFT / FS * 1000:.0f} ms, "
                     f"{FS / N_FFT:.1f} Hz/bin) - se actualiza cada {PROMEDIO_S:g} s")

        self._dibujar_espectro()
