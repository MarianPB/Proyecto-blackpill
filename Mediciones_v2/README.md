# Mediciones v2 (DAC + ADC del PCM3060)

Herramientas para grabar el ADC por el COM virtual y calcular las métricas, y la sesión de
mediciones válida del 20/10/2026 (firmware `Blackpill_codec_USB_FD` de esta misma rama).

## Cómo se usa

Con el montaje A armado (VOUTL+ -> VINL, VOUTR+ -> VINR, capacitor de acople) y la app cerrada:

```
python medir_todo.py        (o doble clic en MEDIR_TODO.bat; en Linux: python3 medir_todo.py)
```

Hace todas las medidas del montaje A (~6 min) y al final las analiza: el resultado queda en
`capturas/sesion_AAAAMMDD_HHMM/resumen.txt` y `resultados.csv`. Si la PC pierde tramas en estéreo,
mide canal por canal (`STREAM:L` / `STREAM:R`). Los comandos para repetir una medida suelta están en
`COMANDOS_MEDICIONES.txt`.

| Archivo | Qué hace |
|---|---|
| `medir_todo.py` | corre la sesión completa (M3, M4, M5, M7, M8, M9, M10, M15, M11) |
| `grabar.py`, `grabar_piso.py` | graban una captura suelta a `capturas/*.mat` |
| `analisis.py`, `analizar_sesion.py` | métricas de una sesión (THD, THD+N, SNR, SFDR, ENOB, separación, DR) |
| `matlab/` | lo mismo en MATLAB (`analizar_sesion.m` solo para sesiones en estéreo) |

## Resultados

- `capturas/sesion_20261020_1320/`: las capturas crudas (`.mat`), `resumen.txt` y `resultados.csv`.
  0 tramas perdidas, dato del ADC directo.
- `../Resultados_mediciones/`: informe imprimible con la comparación contra la hoja de datos y las
  condiciones de medición (color y blanco y negro), resumen corto e instructivo paso a paso.
- `../Hoja_resultados/`: hoja en LaTeX con las figuras (`generar_figuras.py` las rehace desde esta sesión).
