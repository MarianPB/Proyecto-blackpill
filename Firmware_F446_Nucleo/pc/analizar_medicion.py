"""
Reanaliza una medicion guardada por el visor (archivo .npz de la carpeta mediciones/).

    python pc/analizar_medicion.py mediciones/20261009_101500_tab1k_sine.npz
    python pc/analizar_medicion.py archivo.npz --banda 20 20000 --a
    python pc/analizar_medicion.py mediciones/*.npz              (varias de una)

Imprime la planilla de la guia (THD, THD+N, SNR, SFDR, ENOB, ruido, separacion) y la guarda en un .txt
al lado del .npz. Los bloques con tramas perdidas se excluyen.
"""

import argparse
import glob
import json
import os

import numpy as np

import metricas


def corregir_corrido(datos):
    """
    Mediciones hechas con el firmware anterior al 08/10, que no realineaba el I2S2ext: el dato llegaba
    corrido un bit a la derecha (signo en el bit 22, mitad de escala). Se toma el signo del bit 22 y se
    multiplica por 2 (el LSB original se perdio: queda en 23 bits, de sobra para -100 dB).
    """
    raw = np.round(datos.astype(np.float64) * 2 ** 23).astype(np.int64) & 0xFFFFFF
    v = ((raw & 0x7FFFFF) ^ 0x400000) - 0x400000
    return (2 * v / 2 ** 23).astype(np.float32)


def analizar_archivo(ruta, banda, ponderar_a, corrido=False):
    with np.load(ruta) as z:
        datos, dano = z["datos"], z["dano"]
        meta = json.loads(str(z["meta"])) if "meta" in z else {}
    if corrido:
        datos = corregir_corrido(datos)
        meta["salida"] = (meta.get("salida", "") + " · REALINEADO 1 bit (firmware anterior al 08/10)").strip(" ·")
    validos = [b for b, d in zip(datos, dano) if not d]
    if not validos:
        return f"{ruta}: todos los bloques tienen tramas perdidas."
    res, segs = metricas.medir(validos, banda, ponderar_a)
    meta["segmentos"] = segs
    texto = metricas.informe(res, meta)
    if len(validos) < len(datos):
        texto += f"\n\nSe excluyeron {len(datos) - len(validos)} bloque(s) con tramas perdidas."
    ruta_txt = os.path.splitext(ruta)[0] + \
        f"_{banda[0]:g}-{banda[1]:g}Hz{'_A' if ponderar_a else ''}{'_realineado' if corrido else ''}.txt"
    with open(ruta_txt, "w", encoding="utf-8") as fh:
        fh.write(texto + "\n")
    return texto


def main():
    p = argparse.ArgumentParser(description="Metricas de una medicion guardada por el visor del ADC")
    p.add_argument("archivos", nargs="+", help=".npz guardados por el visor (acepta comodines)")
    p.add_argument("--banda", nargs=2, type=float, default=(400.0, 20000.0), metavar=("F_MIN", "F_MAX"),
                   help="banda de medicion en Hz (por defecto 400 20000, como el datasheet)")
    p.add_argument("--a", action="store_true", help="ponderacion A")
    p.add_argument("--corrido", action="store_true",
                   help="medicion hecha con el firmware anterior al 08/10 (dato corrido 1 bit): la realinea")
    args = p.parse_args()

    rutas = []
    for a in args.archivos:
        rutas += sorted(glob.glob(a)) or [a]
    for ruta in rutas:
        print("=" * 100)
        print(ruta)
        print(analizar_archivo(ruta, tuple(args.banda), args.a, args.corrido))


if __name__ == "__main__":
    main()
