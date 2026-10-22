"""Figuras de la hoja de resultados (sesion del 20/10/2026, 13:20). Genera figuras/*.pdf de ancho de columna."""
import glob
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "Mediciones_v2"))
import analisis as A                                     # noqa: E402

SESION = os.path.join(AQUI, "..", "Mediciones_v2", "capturas", "sesion_20261020_1320")
FIG = os.path.join(AQUI, "figuras")
os.makedirs(FIG, exist_ok=True)

AZUL = "#2A78D6"        # el color "propio" de la propuesta
GRIS = "#6B6A66"
TINTA = "#1F1F1E"
GUIA = "#8A8985"
plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 7.5, "axes.labelsize": 7.5, "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
    "axes.edgecolor": GUIA, "axes.linewidth": 0.6, "axes.labelcolor": TINTA,
    "xtick.color": "#5A5955", "ytick.color": "#5A5955", "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "axes.grid": True, "grid.color": "#D9D8D4", "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42,
    "axes.formatter.use_locale": False,
})
ANCHO = 3.25             # pulgadas: una columna de la hoja A4 a dos columnas
MENOS = "−"


def captura(nombre):
    return A.cargar(glob.glob(os.path.join(SESION, f"*_{nombre}.mat"))[0])


def espectro(x, fs, nfft=65536):
    """Espectro promedio (Welch, Blackman-Harris) en dBFS: un seno de amplitud A da 20log10(A) en su pico."""
    f, p = welch(x - x.mean(), fs, window="blackmanharris", nperseg=nfft, noverlap=nfft // 2,
                 scaling="spectrum", detrend=False)
    return f, 10 * np.log10(np.maximum(p, 1e-30) / 0.5)


def pico(f, s, fx):
    k = np.argmin(abs(f - fx))
    return s[max(0, k - 3):k + 4].max()


def guia():
    return dict(arrowstyle="-", color=GUIA, lw=0.5)


# ---- Figura 1: espectro del canal L con 1 kHz por tabla ----------------------------------------------------
c = captura("M7_L_1")
f, s = espectro(c["l"], c["fs"])
fig, ax = plt.subplots(figsize=(ANCHO, 2.05))
ax.axvspan(20000, 48000, color="#EFEEEA", zorder=0, lw=0)
ax.semilogx(f[1:], s[1:], color=AZUL, lw=0.7)
ax.set_xlim(20, 48000)
ax.set_ylim(-160, 5)
ax.set_xlabel("Frecuencia [Hz]")
ax.set_ylabel("Nivel [dBFS]")
ax.set_xticks([20, 100, 1000, 10000, 40000])
ax.set_xticklabels(["20", "100", "1 k", "10 k", "40 k"])
ax.annotate(f"1 kHz, {MENOS}1,7 dBFS", (1000, pico(f, s, 1000)), xytext=(60, -14), fontsize=6.8, color=TINTA)
p2, p3 = pico(f, s, 2000), pico(f, s, 3000)
ax.annotate(f"2.° armónico\n{MENOS}{abs(p2):.0f} dBFS", (2000, p2), xytext=(330, -84), fontsize=6.3,
            color=TINTA, arrowprops=guia())
ax.annotate(f"3.° armónico\n{MENOS}{abs(p3):.0f} dBFS", (3000, p3), xytext=(4300, -84), fontsize=6.3,
            color=TINTA, arrowprops=guia())
ax.text(30500, -8, "fuera\nde la\nbanda", ha="center", va="top", fontsize=6, color="#5A5955")
fig.tight_layout(pad=0.3)
fig.savefig(os.path.join(FIG, "espectro_tabla_1k.pdf"))
plt.close(fig)

# ---- Figura 2: seno por acumulador contra seno por tabla (4 a 20 kHz) --------------------------------------
cs, ct = captura("M9_seno_1"), captura("M9_tabla_1")
f, ss = espectro(cs["l"], cs["fs"])
_, st = espectro(ct["l"], ct["fs"])
m = (f >= 4000) & (f <= 20000)
fig, ax = plt.subplots(figsize=(ANCHO, 2.05))
ax.plot(f[m] / 1000, ss[m], color=AZUL, lw=0.7, label="Acumulador de fase")
ax.plot(f[m] / 1000, st[m], color=GRIS, lw=0.6, ls=(0, (3, 1.5)), label="Tabla de 1 kHz exacto")
for fx in (10125, 12125):
    ax.annotate("", (fx / 1000, pico(f, ss, fx)), xytext=(11.1, -66), arrowprops=guia())
ax.text(11.1, -65, f"espurias de truncación en 10,1 y 12,1 kHz:\n{MENOS}80 dBFS ({MENOS}78 dBc)",
        ha="center", va="bottom", fontsize=6.3, color=TINTA)
ax.set_xlim(4, 20)
ax.set_ylim(-170, -50)
ax.set_xlabel("Frecuencia [kHz]")
ax.set_ylabel("Nivel [dBFS]")
ax.legend(loc="lower left", frameon=False, handlelength=2.2)
fig.tight_layout(pad=0.3)
fig.savefig(os.path.join(FIG, "acumulador_vs_tabla.pdf"))
plt.close(fig)
print("figuras en", FIG)
