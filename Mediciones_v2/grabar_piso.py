"""
Graba el piso de ruido del ADC en paquetes de 1 segundo y lo guarda en un .mat para MATLAB.

Uso:  python grabar_piso.py                M2: ruido del ADC solo (DAC apagado), 10 paquetes de 1 s
      python grabar_piso.py 20             lo mismo con 20 paquetes
      python grabar_piso.py 10 cadena      M3: ruido de la cadena (DAC encendido mandando silencio)

Junta los paquetes y los guarda en capturas/piso_AAAAMMDD_HHMMSS.mat
(o piso_cadena_AAAAMMDD_HHMMSS.mat) con:
    L, R      matriz [muestras x paquetes], cada columna es 1 s de un canal (+-1 = fondo de escala)
    fs        frecuencia de muestreo [Hz]
    perdidas  tramas perdidas (si no es 0, repetir)
"""

import datetime
import os
import sys
import time

import numpy as np
import scipy.io
import serial
import serial.tools.list_ports

FS = 97656.25
N_PAQUETE = 97656                       # 1 s de muestras
CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capturas")

paquetes = int(sys.argv[1]) if len(sys.argv) > 1 else 10
cadena = len(sys.argv) > 2 and sys.argv[2] == "cadena"

# el STM32 aparece como un COM con el vendor id de ST
puertos = [p.device for p in serial.tools.list_ports.comports() if p.vid == 0x0483]
if not puertos:
    sys.exit("No encuentro el STM32. ¿Está enchufado? ¿Está abierta la app (ocupa el puerto)?")
ser = serial.Serial(puertos[0], timeout=0.02)
try:
    ser.set_buffer_size(rx_size=1 << 20)
except (AttributeError, serial.SerialException, OSError):
    pass

def mandar(cmd):
    ser.write((cmd + "\n").encode())
    time.sleep(0.05)

mandar("STREAM:0")
if cadena:
    for c in ("SE", "LOFF", "ROFF", "DAC:1"):   # DAC andando, los dos canales en silencio
        mandar(c)
else:
    mandar("DAC:0")                     # DAC apagado: solo queda el ruido del ADC
mandar("ADC:1")
time.sleep(1.0)
ser.reset_input_buffer()
mandar("STREAM:1")

# cada trama: AA 55 | tipo | seq | n (2 bytes) | n x [L0 L1 L2 R0 R1 R2]
buf = bytearray()
crudo = bytearray()
ultimo_seq = None
perdidas = 0
donde = []                              # segundo de la grabacion donde hubo cada hueco
total = paquetes * N_PAQUETE * 6
descartar = 20000 * 6                   # ~0,2 s del arranque se tiran

print(f"Grabando {paquetes} paquetes de 1 s en {puertos[0]}...")
while len(crudo) < descartar + total:
    buf += ser.read(65536)             # pedidos grandes: el driver USB de Windows rinde mas
    while True:
        i = buf.find(b"\xAA\x55")
        if i < 0 or len(buf) < i + 6:
            break
        tipo, seq, n = buf[i + 2], buf[i + 3], buf[i + 4] | (buf[i + 5] << 8)
        largo = n * 6 if tipo == 1 else n
        if len(buf) < i + 6 + largo:
            break
        if tipo == 1:
            if ultimo_seq is not None and len(crudo) >= descartar:
                salto = (seq - ultimo_seq - 1) & 0xFF
                if salto:
                    perdidas += salto
                    donde.append((len(crudo) - descartar) / 6 / FS)
            ultimo_seq = seq
            antes = max(0, len(crudo) - descartar) // (N_PAQUETE * 6)
            crudo += buf[i + 6:i + 6 + largo]
            ahora = max(0, len(crudo) - descartar) // (N_PAQUETE * 6)
            if ahora > antes:
                print(f"  paquete {ahora} de {paquetes}")
        del buf[:i + 6 + largo]

mandar("STREAM:0")
ser.close()

# bytes -> muestras de 24 bits con signo -> +-1
a = np.frombuffer(bytes(crudo[descartar:descartar + total]), np.uint8).reshape(-1, 6).astype(np.int32)
l = a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16)
r = a[:, 3] | (a[:, 4] << 8) | (a[:, 5] << 16)
l = ((l ^ 0x800000) - 0x800000) / 2**23
r = ((r ^ 0x800000) - 0x800000) / 2**23

os.makedirs(CARPETA, exist_ok=True)
archivo = os.path.join(CARPETA, ("piso_cadena_" if cadena else "piso_") + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".mat")
scipy.io.savemat(archivo, {
    "L": l.reshape(paquetes, N_PAQUETE).T,      # columnas = paquetes
    "R": r.reshape(paquetes, N_PAQUETE).T,
    "fs": FS,
    "perdidas": perdidas,
    "seg_perdidas": np.array(donde, dtype=float).reshape(-1, 1),
})

print(f"\nGuardado: {archivo}")
print(f"Tramas perdidas: {perdidas}" + ("   <- REPETIR" if perdidas else ""))
if donde:
    print("  huecos en los segundos: " + ", ".join(f"{t:.2f}" for t in donde[:20]) + (" ..." if len(donde) > 20 else ""))
