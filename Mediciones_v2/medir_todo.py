"""
Mide toda la sesion de una sola vez, con el lazo directo armado (montaje A: VOUTL+ -> capacitor -> VINL
y VOUTR+ -> capacitor -> VINR).

Uso:  python medir_todo.py          (o doble clic en MEDIR_TODO.bat)

Hace, en este orden (unos 6 minutos):
    M3   piso de ruido de la cadena (DAC encendido, en silencio)       x3
    M4   nivel de trabajo L y R; si recorta, baja la amplitud solo
    M5   linealidad del atenuador (L)
    M7   pureza L + separacion L->R                                     x3
    M8   pureza R + separacion R->L                                     x3
    M9   seno por acumulador contra tabla, alternados                   x3
    M10  995,4 Hz por paso contra por tabla
    M15  multitono 60 Hz + 7 kHz
    M11  rango dinamico EIAJ (senal a -60 dB por I2C), L y R
    M4   control final: el nivel tiene que volver al del principio

Todo queda en capturas/sesion_AAAAMMDD_HHMM/: las capturas (.mat), sesion.txt (el registro) y, al
terminar, el analisis: resumen.txt y resultados.csv (ver analisis.py). El analisis se puede repetir con
python analizar_sesion.py, o en MATLAB con matlab/analizar_sesion.m.

En Linux: python3 medir_todo.py (el usuario tiene que estar en el grupo dialout para abrir /dev/ttyACM0).
"""

import datetime
import os
import sys
import time

import numpy as np

import analisis
import grabar as G

BASE = ["SE", "ADC:1", "DAC:1"]
AMPLITUDES = [63, 56, 50, 45]          # se prueba en este orden hasta que no recorte
PICO_MAX_DBFS = -0.5
INTENTOS = 3                            # si hay tramas perdidas, se repite


class Sesion:

    def __init__(self, ser):
        self.ser = ser
        self.carpeta = os.path.join(G.CARPETA, "sesion_" + datetime.datetime.now().strftime("%Y%m%d_%H%M"))
        os.makedirs(self.carpeta, exist_ok=True)
        self.registro = open(os.path.join(self.carpeta, "sesion.txt"), "a", encoding="utf-8")
        self.amp = AMPLITUDES[0]
        self.problemas = []
        self.alineaciones = set()
        self.modo = "LR"                    # "LR" estereo; "mono" = un canal por captura (PC con USB lento)

    def anotar(self, texto):
        print(texto)
        self.registro.write(texto + "\n")
        self.registro.flush()

    def medir(self, nombre, seg, comandos, canal, medida, amp=None, canales=None, rol=""):
        """Graba una medida (repite si hubo tramas perdidas o si la alineacion cambio) y devuelve la captura.
        canales: lo que se manda por USB ("LR", "L" o "R"); por defecto, estereo o el canal de la señal."""
        if canales is None:
            canales = "LR" if self.modo == "LR" else canal.upper()
        for intento in range(1, INTENTOS + 1):
            cap = G.capturar(self.ser, comandos, seg, eco=False, canales=canales)
            alin = G.alineacion(cap)
            if cap["perdidas"] == 0 and not cap["cortado"] and alin != "mezcla":
                break
            self.anotar(f"  {nombre}: {cap['perdidas']} tramas perdidas, dato {alin}: repito ({intento}/{INTENTOS})")
        else:
            self.problemas.append(f"{nombre}: quedo con tramas perdidas o con la alineacion cambiando")
        self.alineaciones.add(G.alineacion(cap))

        G.guardar(self.carpeta, nombre, cap, comandos,
                  extra={"canal": canal, "medida": medida, "amplitud": self.amp if amp is None else amp, "rol": rol})
        if canal and not rol:
            detalle = f"pico {G.db(np.max(np.abs(cap[canal] / G.FULL_SCALE))):6.1f} dBFS"
        else:
            detalle = "RMS " + "  ".join(f"{c.upper()} {G.db(np.std(cap[c] / G.FULL_SCALE)):6.1f}"
                                         for c in "lr" if len(cap[c])) + " dBFS"
        self.anotar(f"  {nombre:<16} {seg:>4g} s   perdidas {cap['perdidas']}   dato {G.alineacion(cap):<8} {detalle}")
        return cap

    def tono(self, nombre, seg, canal, onda, extra=(), amp=None, medida=""):
        """Un tono en un canal y el otro en silencio."""
        a = self.amp if amp is None else amp
        if canal == "l":
            cmds = BASE + [f"LWAVE:{onda}", *extra, f"LAMP:{a}", "LON", "ROFF"]
        else:
            cmds = BASE + [f"RWAVE:{onda}", *extra, f"RAMP:{a}", "RON", "LOFF"]
        medida = medida or nombre.split("_")[0]
        cap = self.medir(nombre, seg, cmds, canal, medida, amp=a)
        if self.modo != "LR" and medida in ("M7", "M8"):
            # un canal por captura: la separacion sale de grabar el OTRO canal con el mismo tono sonando
            otro = "R" if canal == "l" else "L"
            self.medir(nombre + "_otro", seg, cmds, canal, medida, amp=a, canales=otro, rol="separacion")
        return cap

    def pico(self, cap, canal):
        return G.db(np.max(np.abs(cap[canal] / G.FULL_SCALE)))


def main():
    ser = G.abrir(sys.argv[1] if len(sys.argv) > 1 else None)
    if not G.firmware_nuevo(ser):
        ser.close()
        sys.exit("La placa no responde al comando ALIN: no tiene cargado el firmware nuevo de "
                 "Blackpill_codec_USB_FD (el que detecta solo si el dato del ADC llega corrido).\n"
                 "Sin el, el dato puede salir multiplicado por 2. Cargarlo y volver a correr esto.")
    s = Sesion(ser)
    t0 = time.time()
    try:
        s.anotar(f"SESION {datetime.datetime.now():%Y-%m-%d %H:%M}   puerto {ser.port}   carpeta {s.carpeta}")
        s.anotar("Montaje A (lazo directo). No tocar nada hasta que termine (entre 7 y 10 minutos).\n")

        # prueba de 3 s en estereo: si esta PC pierde tramas, se mide un canal por vez (la mitad de bytes)
        prueba = G.capturar(ser, BASE + ["LOFF", "ROFF"], 3, eco=False)
        if prueba["perdidas"]:
            s.modo = "mono"
            s.anotar(f"Prueba en estereo: {prueba['perdidas']} tramas perdidas -> esta PC no llega: se mide UN "
                     "CANAL POR VEZ (la separacion sale de capturas extra del otro canal).\n")
        else:
            s.anotar("Prueba en estereo: 0 tramas perdidas -> se mide en estereo.\n")

        s.anotar("M3  piso de ruido de la cadena (DAC encendido, canales en silencio)")
        for i in (1, 2, 3):
            if s.modo == "LR":
                s.medir(f"M3_cadena_{i}", 10, BASE + ["LOFF", "ROFF"], "", "M3")
            else:
                for c in "LR":
                    s.medir(f"M3_cadena_{i}_{c}", 10, BASE + ["LOFF", "ROFF"], "", "M3", canales=c)

        s.anotar("\nM4  nivel de trabajo (que no recorte)")
        for a in AMPLITUDES:
            s.amp = a
            cl = s.tono(f"M4_L_{a}", 5, "l", 4)
            cr = s.tono(f"M4_R_{a}", 5, "r", 4)
            if max(s.pico(cl, "l"), s.pico(cr, "r")) <= PICO_MAX_DBFS:
                break
            s.anotar(f"  al {a} % el pico pasa de {PICO_MAX_DBFS} dBFS: bajo la amplitud")
        else:
            s.problemas.append("M4: recorta aun al menor porcentaje probado")
        s.anotar(f"  amplitud de trabajo: {s.amp} %")

        s.anotar("\nM5  linealidad (L, 1 kHz por tabla)")
        escalones = [63, 32, 16, 8] if s.amp == 63 else [s.amp, round(s.amp / 2), round(s.amp / 4), round(s.amp / 8)]
        for a in escalones:
            s.tono(f"M5_{a:02d}", 5, "l", 4, amp=a, medida="M5")

        s.anotar("\nM7  pureza L y separacion L->R")
        for i in (1, 2, 3):
            s.tono(f"M7_L_{i}", 10, "l", 4, medida="M7")

        s.anotar("\nM8  pureza R y separacion R->L")
        for i in (1, 2, 3):
            s.tono(f"M8_R_{i}", 10, "r", 4, medida="M8")

        s.anotar("\nM9  seno por acumulador contra tabla (alternados)")
        for i in (1, 2, 3):
            s.tono(f"M9_seno_{i}", 10, "l", 0, extra=["LFREQ:1000"], medida="M9")
            s.tono(f"M9_tabla_{i}", 10, "l", 4, medida="M9")

        s.anotar("\nM10 995,4 Hz por paso contra por tabla")
        s.tono("M10_paso", 10, "l", 7, medida="M10")
        s.tono("M10_tabla", 10, "l", 6, medida="M10")

        s.anotar("\nM15 multitono 60 Hz + 7 kHz")
        s.tono("M15_multi", 10, "l", 5, medida="M15")

        s.anotar("\nM11 rango dinamico (senal a -60 dB por I2C)")
        for canal, reg in (("l", 65), ("r", 66)):
            s.tono(f"M11_prep_{canal.upper()}", 1, canal, 4, medida="M11prep")
            # sin LAMP/RAMP: si el porcentaje no cambia, el firmware no pisa el volumen que se escribe a mano
            otro = "ROFF" if canal == "l" else "LOFF"
            cap = s.medir(f"M11_{canal.upper()}_-60dB", 10, [f"I2CW:{reg},135", otro], canal, "M11")
            if s.pico(cap, canal) > -40:
                s.problemas.append(f"M11 {canal.upper()}: el nivel no bajo a -60 dB (el I2CW no llego)")

        # volver el volumen al de trabajo: el firmware solo lo reescribe cuando el porcentaje cambia
        for cmd in ("LAMP", "RAMP"):
            G.mandar(ser, f"{cmd}:{s.amp - 1}")
            time.sleep(1.0)
            G.mandar(ser, f"{cmd}:{s.amp}")
            time.sleep(1.0)

        s.anotar("\nM4  control final")
        cl = s.tono("M4_L_final", 5, "l", 4, medida="M4final")
        cr = s.tono("M4_R_final", 5, "r", 4, medida="M4final")
        if min(s.pico(cl, "l"), s.pico(cr, "r")) < -20:
            s.problemas.append("M4 final: el volumen no volvio al de trabajo (desenchufar y volver a enchufar)")

    except KeyboardInterrupt:
        s.problemas.append("cortado a mano antes de terminar")
    finally:
        for c in ("LOFF", "ROFF", "STREAM:0"):
            G.mandar(ser, c)
        ser.close()

    s.anotar(f"\nTERMINADO en {(time.time() - t0) / 60:.1f} min.")
    s.anotar("Dato del ADC en la sesion: " + ", ".join(sorted(s.alineaciones))
             + "  (corrido = llego corrido un bit y el firmware lo corrigio; directo = llego bien)")
    if "?" in s.alineaciones:
        s.problemas.insert(0, "la placa NO tiene el firmware nuevo (no responde ALIN): el dato puede salir x2. "
                              "Cargar el firmware y repetir.")
    if s.problemas:
        s.anotar("PROBLEMAS:")
        for p in s.problemas:
            s.anotar("  - " + p)
    else:
        s.anotar("Sin problemas.")
    s.registro.close()

    print("\nANALISIS (tarda uno o dos minutos)")
    print("\n" + analisis.analizar_sesion(s.carpeta))
    print(f"Guardado en {s.carpeta}: resumen.txt, resultados.csv y las capturas.")


if __name__ == "__main__":
    main()
