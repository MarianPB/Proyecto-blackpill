"""
Analiza una sesion de medir_todo.py (ver analisis.py).

Uso:  python analizar_sesion.py                       (la sesion mas nueva de capturas/)
      python analizar_sesion.py capturas/sesion_X     (una en particular)
"""

import glob
import os
import sys

import analisis

AQUI = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) > 1:
    carpeta = sys.argv[1]
else:
    sesiones = sorted(glob.glob(os.path.join(AQUI, "capturas", "sesion_*")))
    if not sesiones:
        sys.exit("No hay sesiones en capturas/. Pasale la carpeta: python analizar_sesion.py capturas/sesion_X")
    carpeta = sesiones[-1]

print(f"Analizando {carpeta} ...")
print("\n" + analisis.analizar_sesion(carpeta))
print(f"Guardado: resultados.csv y resumen.txt en {carpeta}")
