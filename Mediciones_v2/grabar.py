"""
Graba lo que mide el ADC del codec a un archivo .mat para analizarlo despues en MATLAB.

No dibuja ni calcula nada: abre el COM virtual del STM32, manda los comandos que le pases,
prende el streaming, junta N segundos de muestras y las guarda tal cual llegaron (24 bits).

Uso (desde esta carpeta):

    python grabar.py --nombre M2_masa --seg 10 --cmd DAC:0
    python grabar.py --nombre M7_L_1k_50 --seg 10 --cmd SE --cmd LWAVE:0 --cmd LFREQ:1000 --cmd LAMP:50 --cmd LON --cmd ROFF --cmd DAC:1

Cada --cmd se manda tal cual (los mismos comandos que manda la app, ver usbd_cdc_if.c).
El archivo queda en capturas/AAAAMMDD_HHMMSS_<nombre>.mat con:

    L, R         muestras de cada canal en cuentas enteras (int32, fondo de escala = 2^23)
    fs           frecuencia de muestreo [Hz]
    full_scale   2^23
    perdidas     tramas perdidas durante la grabacion (si no es 0, conviene repetir)
    pos_perdidas indice (base 1, como MATLAB) de la primera muestra despues de cada hueco
    comandos     los comandos que se mandaron antes de grabar
    nombre, fecha, nota
"""

import argparse
import datetime
import os
import sys
import time

import numpy as np
import scipy.io
import serial
import serial.tools.list_ports

FS = 97656.25                 # frecuencia de muestreo del codec (debe coincidir con el firmware)
FULL_SCALE = 1 << 23          # 24 bits con signo
SYNC = b"\xAA\x55"
TIPO_AUDIO = 0x01
TIPO_TEXTO = 0x02
TIPO_AUDIO_L = 0x03           # un solo canal (STREAM:L / STREAM:R): la mitad de bytes
TIPO_AUDIO_R = 0x04
BYTES_FRAME = {TIPO_AUDIO: 6, TIPO_AUDIO_L: 3, TIPO_AUDIO_R: 3}
HDR = 6
MAX_FRAMES = 4096
MAX_TEXTO = 64
VID_ST = 0x0483               # vendor id de ST (el COM virtual del STM32)

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")


class Decodificador:
    """Separa las tramas del flujo de bytes y junta las muestras en orden."""

    def __init__(self):
        self.buf = bytearray()
        self.partes = {"L": [], "R": []}   # bloques (n, 3) de bytes crudos de cada canal
        self.frames = 0
        self.perdidas = 0
        self.pos_perdidas = []     # frame donde arranca lo que vino despues de cada hueco
        self.ultimo_seq = None
        self.textos = []

    def alimentar(self, datos):
        buf = self.buf
        buf.extend(datos)

        while True:
            i = buf.find(SYNC)
            if i < 0:
                del buf[:-1]
                return
            if i > 0:
                del buf[:i]
            if len(buf) < HDR:
                return

            tipo, seq = buf[2], buf[3]
            n = buf[4] | (buf[5] << 8)

            if tipo in BYTES_FRAME and 0 < n <= MAX_FRAMES:
                largo = n * BYTES_FRAME[tipo]
            elif tipo == TIPO_TEXTO and n <= MAX_TEXTO:
                largo = n
            else:
                del buf[:1]            # falso sincronismo
                continue

            if len(buf) < HDR + largo:
                return

            payload = bytes(buf[HDR:HDR + largo])
            del buf[:HDR + largo]

            if self.ultimo_seq is not None:
                salto = (seq - self.ultimo_seq - 1) & 0xFF
                if salto:
                    self.perdidas += salto
                    self.pos_perdidas.append(self.frames)
            self.ultimo_seq = seq

            if tipo in BYTES_FRAME:
                a = np.frombuffer(payload, dtype=np.uint8).reshape(n, -1)
                if tipo == TIPO_AUDIO:
                    self.partes["L"].append(a[:, :3])
                    self.partes["R"].append(a[:, 3:])
                else:
                    self.partes["L" if tipo == TIPO_AUDIO_L else "R"].append(a)
                self.frames += n
            else:
                self.textos.append(payload.decode("ascii", errors="replace"))

    def muestras(self):
        """(L, R) como int32 con signo, en cuentas de 24 bits (vacio el canal que no se mando)."""
        out = []
        for c in ("L", "R"):
            if not self.partes[c]:
                out.append(np.zeros(0, np.int32))
                continue
            a = np.concatenate(self.partes[c]).astype(np.int32)
            v = a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16)
            out.append((v ^ 0x800000) - 0x800000)
        return out[0], out[1]


def buscar_puerto():
    st = [p.device for p in serial.tools.list_ports.comports() if p.vid == VID_ST]
    if len(st) == 1:
        return st[0]
    todos = [p.device for p in serial.tools.list_ports.comports()]
    msg = "no encontre el STM32" if not st else "hay mas de un STM32 conectado (" + ", ".join(st) + ")"
    sys.exit(msg + ". Pasale --puerto COMx. Puertos: " + (", ".join(todos) or "ninguno"))


def abrir(puerto=None):
    ser = serial.Serial(puerto or buscar_puerto(), 115200, timeout=0.02)
    try:
        ser.set_buffer_size(rx_size=1 << 20)       # el default de Windows (4 kB) son 7 ms de audio
    except (AttributeError, serial.SerialException, OSError):
        pass
    return ser


def mandar(ser, comando):
    ser.write((comando + "\n").encode("ascii"))
    ser.flush()
    time.sleep(0.05)               # que el firmware lo procese antes del siguiente


def db(x):
    return 20 * np.log10(max(x, 1e-12))


def capturar(ser, comandos, seg, espera=1.0, descartar=0.2, eco=True, canales="LR"):
    """Manda los comandos, espera, graba 'seg' segundos y devuelve las muestras (cuentas de 24 bits).
    canales: "LR" (estereo), "L" o "R" (un solo canal: la mitad de bytes, para PC cuyo USB no llega)."""
    n_grabar = int(round(seg * FS))
    n_descartar = int(round(descartar * FS))

    mandar(ser, "STREAM:0")
    time.sleep(0.2)
    ser.reset_input_buffer()

    for c in comandos:
        if eco:
            print("  ->", c)
        mandar(ser, c)
    time.sleep(espera)

    ser.reset_input_buffer()
    dec = Decodificador()
    mandar(ser, {"LR": "STREAM:1", "L": "STREAM:L", "R": "STREAM:R"}[canales])

    cortado = False
    limite = time.time() + seg + descartar + 5.0
    while dec.frames < n_descartar + n_grabar:
        if time.time() > limite:
            cortado = True
            break
        dec.alimentar(ser.read(65536))             # pedidos grandes: el driver USB de Windows rinde mas
    mandar(ser, "STREAM:0")

    l, r = dec.muestras()
    l, r = l[n_descartar:n_descartar + n_grabar], r[n_descartar:n_descartar + n_grabar]
    pos = [p - n_descartar + 1 for p in dec.pos_perdidas if n_descartar < p < n_descartar + n_grabar]

    # el firmware detecta solo si el dato del ADC llega corrido un bit (ver stream.c): le preguntamos cuantos
    # bloques de esta captura corrigio, para saber si la alineacion cambio en el medio
    fin = time.time() + 0.3
    while time.time() < fin:
        dec.alimentar(ser.read(65536))
    mandar(ser, "ALIN")
    alin = None
    fin = time.time() + 1.0
    while alin is None and time.time() < fin:
        dec.alimentar(ser.read(65536))
        for t in dec.textos:
            if t.startswith("ALIN:"):
                c, d = t[5:].split(",")
                alin = (int(c), int(d))
    textos = [t for t in dec.textos if not t.startswith("ALIN:")]

    return {"l": l, "r": r, "perdidas": len(pos), "pos": pos, "textos": textos, "cortado": cortado,
            "alin": alin, "canales": canales}


def firmware_nuevo(ser):
    """True si la placa responde al comando ALIN (firmware con la deteccion de alineacion)."""
    mandar(ser, "STREAM:0")
    time.sleep(0.3)
    ser.reset_input_buffer()
    dec = Decodificador()
    mandar(ser, "ALIN")
    fin = time.time() + 1.5
    while time.time() < fin:
        dec.alimentar(ser.read(65536))
        if any(t.startswith("ALIN:") for t in dec.textos):
            return True
    return False


def alineacion(cap):
    """'corrido' (el firmware corrigio todo), 'directo', 'mezcla' (cambio en el medio: repetir) o '?'."""
    if cap.get("alin") is None:
        return "?"                                   # firmware sin el comando ALIN
    c, d = cap["alin"]
    return "mezcla" if c and d else ("corrido" if c else "directo")


def guardar(carpeta, nombre, cap, comandos, nota="", extra=None):
    os.makedirs(carpeta, exist_ok=True)
    ahora = datetime.datetime.now()
    archivo = os.path.join(carpeta, ahora.strftime("%Y%m%d_%H%M%S") + "_" + nombre + ".mat")
    datos = {
        "L": cap["l"].astype(np.int32).reshape(-1, 1),
        "R": cap["r"].astype(np.int32).reshape(-1, 1),
        "fs": FS,
        "full_scale": float(FULL_SCALE),
        "perdidas": cap["perdidas"],
        "pos_perdidas": np.array(cap["pos"], dtype=np.float64).reshape(-1, 1),
        "comandos": np.array(comandos, dtype=object).reshape(-1, 1),
        "nombre": nombre,
        "fecha": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "nota": nota,
        "alineacion": alineacion(cap),
        "canales": cap.get("canales", "LR"),
    }
    datos.update(extra or {})
    scipy.io.savemat(archivo, datos, do_compression=True)
    return archivo


def resumen(cap):
    """Texto corto: muestras, perdidas y DC/RMS/pico de cada canal."""
    l = cap["l"]
    lineas = [f"  muestras: {len(l)} por canal ({len(l) / FS:.2f} s), tramas perdidas: {cap['perdidas']}, "
              f"dato del ADC: {alineacion(cap)}"]
    for nombre, x in (("L", cap["l"]), ("R", cap["r"])):
        if len(x):
            x = x / FULL_SCALE
            lineas.append(f"  {nombre}: DC {x.mean():+.5f}   RMS {db(np.sqrt(np.mean((x - x.mean()) ** 2))):6.1f} dBFS"
                          f"   pico {db(np.max(np.abs(x))):6.1f} dBFS")
    if cap["cortado"]:
        lineas.append("  !! se corto por tiempo: llegaron menos muestras de las esperadas")
    if cap["perdidas"]:
        lineas.append("  !! hubo tramas perdidas: la señal tiene huecos, conviene repetir")
    if alineacion(cap) == "mezcla":
        lineas.append("  !! la alineacion del dato cambio durante la captura: repetir")
    if cap["textos"]:
        lineas.append("  textos del STM32: " + " | ".join(cap["textos"]))
    return "\n".join(lineas)


def main():
    ap = argparse.ArgumentParser(description="Graba el ADC del codec a un .mat")
    ap.add_argument("--nombre", required=True, help="nombre corto de la medida, ej. M7_L_1k_50")
    ap.add_argument("--seg", type=float, default=10.0, help="segundos a grabar (default 10)")
    ap.add_argument("--cmd", action="append", default=[], help="comando a mandar antes de grabar (se puede repetir)")
    ap.add_argument("--espera", type=float, default=1.0, help="segundos entre los comandos y la grabacion (default 1)")
    ap.add_argument("--descartar", type=float, default=0.2, help="segundos del principio que se tiran (default 0.2)")
    ap.add_argument("--puerto", help="COMx (si no, busca el STM32 solo)")
    ap.add_argument("--nota", default="", help="texto libre que queda guardado en el archivo")
    ap.add_argument("--canales", default="LR", choices=["LR", "L", "R"],
                    help="LR = estereo (default); L o R = un solo canal, la mitad de bytes por segundo")
    args = ap.parse_args()

    ser = abrir(args.puerto)
    try:
        print(f"grabando {args.seg:g} s en {ser.port} ...")
        cap = capturar(ser, args.cmd, args.seg, args.espera, args.descartar, canales=args.canales)
    finally:
        ser.close()

    archivo = guardar(CARPETA, args.nombre, cap, args.cmd, args.nota)
    print(f"\nguardado: {archivo}")
    print(resumen(cap))


if __name__ == "__main__":
    main()
