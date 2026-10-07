"""
Corre pc/comandos.py (sin modificarlo) contra un STM32 simulado y guarda capturas de pantalla de la app.

Uso:   python capturas_app_simulada/generar_capturas.py
Salida: capturas_app_simulada/imagenes/*.png
Requiere: numpy, matplotlib, pillow (no hace falta pyserial: lo reemplaza serial_falso.py).
"""
import os
import sys
import ctypes
from ctypes import wintypes

AQUI = os.path.dirname(os.path.abspath(__file__))
PC = os.path.join(os.path.dirname(AQUI), "pc")
SALIDA = os.path.join(AQUI, "imagenes")
os.makedirs(SALIDA, exist_ok=True)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

sys.path.insert(0, AQUI)
sys.path.insert(0, PC)
import serial_falso
serial_falso.instalar()

import tkinter as tk
from PIL import ImageGrab
import comandos
from visor_adc import VisorADC


def capturar(win, nombre):
    win.update()
    hwnd = ctypes.windll.user32.GetAncestor(win.winfo_id(), 2)
    r = wintypes.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r))
    win.lift()
    win.attributes("-topmost", True)
    win.update()
    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
    win.attributes("-topmost", False)
    ruta = os.path.join(SALIDA, nombre)
    img.save(ruta)
    print("guardada", nombre, img.size, flush=True)


def pasos(root, app):
    pantalla = (root.winfo_screenwidth(), root.winfo_screenheight())
    print("pantalla", pantalla, flush=True)
    root.geometry("+20+10")
    yield 800

    app.actualizar_puertos()
    yield 300
    capturar(root, "01_ventana_principal_sin_conectar.png")

    app.conectar()
    yield 500
    capturar(root, "02_ventana_principal_conectada.png")

    # "Probar comunicacion" (PING -> PONG) se ve en la barra de estado del visor
    v = VisorADC(root, app.stm32)
    v.win.geometry("1000x930+0+0")
    v.ventana_txt.set("10")
    v.canal.set("L + R")
    yield 600
    capturar(v.win, "03_visor_detenido.png")

    app.stm32.enviar("PING")
    yield 600
    capturar(v.win, "04_visor_ping_pong.png")

    # --- DAC L: seno 1 kHz, R: triangular 2 kHz, ADC en lazo cerrado ---
    app.set_onda("L", "sine")
    app.set_onda("R", "tri")
    app.frecuencia_L.set("1000"); app.actualizar_frecuencia_L()
    app.frecuencia_R.set("2000"); app.actualizar_frecuencia_R()
    app.amplitud_R.set(30); app.actualizar_amplitud_R()
    app.encender_L()
    app.encender_R()
    yield 300
    capturar(root, "04b_ventana_principal_generando.png")
    v.alternar()                                   # Iniciar captura
    yield 3500
    capturar(v.win, "05_captura_en_vivo_L_R_10ms.png")

    v.ventana_txt.set("2")
    yield 1500
    capturar(v.win, "06_zoom_ventana_2ms.png")

    v.ventana_txt.set("10")
    v.canal.set("L")
    v._repintar()
    yield 1500
    capturar(v.win, "07_solo_canal_L.png")

    # cuadrada: se ven los armonicos impares en el espectro
    app.set_onda("L", "square")
    v.canal.set("L + R")
    v._repintar()
    yield 3000
    capturar(v.win, "08_cuadrada_con_armonicos.png")

    # DAC apagado: piso de ruido del ADC (con Auto Y para ver la senal)
    app.apagar_L()
    app.apagar_R()
    v.auto_y.set(1)
    yield 3000
    capturar(v.win, "09_dac_apagado_piso_de_ruido.png")
    v.auto_y.set(0)
    v.detener()
    yield 400

    # --- medicion de tiempo fijo: 3 s con 1 s descartado, disparando el DAC ---
    app.set_onda("L", "sine")
    v.dur_txt.set("3")
    v.desc_txt.set("1")
    v.alternar_medicion()
    yield 3000
    capturar(v.win, "10_medicion_tiempo_fijo_en_curso.png")
    t = 0
    while v.med is not None and t < 15000:
        yield 500
        t += 500
    yield 1500
    capturar(v.win, "11_medicion_tiempo_fijo_resultado.png")

    # --- medicion continua ---
    v.modo_med.set("continuo")
    v._modo_cambiado()
    v.alternar_medicion()
    yield 11500
    capturar(v.win, "12_medicion_continua.png")
    v.alternar_medicion()
    yield 600

    v.cerrar()
    yield 400
    capturar(root, "13_ventana_principal_final.png")
    root.destroy()


def main():
    root = tk.Tk()
    app = comandos.Aplicacion(root)
    gen = pasos(root, app)

    def siguiente():
        try:
            ms = next(gen)
        except StopIteration:
            return
        root.after(ms, siguiente)

    root.after(100, siguiente)
    root.mainloop()


main()
