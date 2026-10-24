# PCB DAC + ADC (Black Pill + PCM3060)

Placa de una capa para fabricar por planchado de tóner. Proyectos de KiCad 10 que abren solos (huellas, símbolos
y modelo 3D incluidos). El firmware de la placa es `../Firmware_PCB`.

| Carpeta | Qué es |
|---|---|
| `v1_fabricada/` | La placa que se fabricó. **La huella de la Black Pill está mal** (columna izquierda invertida y columnas cambiadas de lado): no enchufar la Black Pill directo, usar el acople. |
| `acople_blackpill/` | Placa intermedia que corrige la v1: va entre la placa y la Black Pill, que queda girada 180° (USB hacia abajo) y corrida 7,62 mm. Ver `LEEME_acople.txt`. |
| `v2_corregida/` | Para rehacer la placa de cero: huella corregida y Black Pill girada 180°, sin acople y con el mismo firmware. No fabricada. Ver `LEEME_v2.txt`. |
| `3D/` | Modelo de la Black Pill que usan los tres proyectos. |
| `Guia_de_diseno_PCB.txt` | Criterios de diseño (masas, alimentación, reglas de fabricación artesanal) y el historial de la placa. |

En cada carpeta, `Planchado/` tiene el cobre para planchar (imprimir a tamaño real), la guía de armado y la
serigrafía. DRC sin errores en los tres proyectos.
