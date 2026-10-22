"""
Analisis de una sesion de medir_todo.py, en Python (numpy + scipy; no hace falta MATLAB).

Uso:  python analizar_sesion.py                       (la sesion mas nueva de capturas/)
      python analizar_sesion.py capturas/sesion_X     (una en particular)

Deja en la carpeta de la sesion:
    resultados.csv   una fila por captura
    resumen.txt      medida por medida, contra la propuesta y la hoja de datos del PCM3060

Convencion: 0 dBFS = seno de fondo de escala (potencia 0,5). Mismas cuentas que matlab/metricas_banda.m.
"""

import csv
import glob
import os

import numpy as np
import scipy.io
from scipy.signal import welch
from scipy.signal.windows import blackmanharris

P_FS = 0.5
_trapz = getattr(np, "trapezoid", None) or np.trapz      # numpy 2 lo renombro
ANCHO = 5                       # bins a cada lado de un tono (lobulo principal de Blackman-Harris: +-4)


def ponderacion_a(f):
    """Ponderacion A en POTENCIA (IEC 61672), 1 en 1 kHz."""
    f = np.asarray(f, dtype=float)
    ra = lambda f: (12194.0**2 * f**4) / ((f**2 + 20.6**2) * np.sqrt((f**2 + 107.7**2) * (f**2 + 737.9**2)) * (f**2 + 12194.0**2))
    return (ra(f) / ra(1000.0)) ** 2


def cargar(archivo):
    d = scipy.io.loadmat(archivo)
    txt = lambda k: str(np.squeeze(d[k])) if k in d and d[k].size else ""
    fs = float(np.squeeze(d["fs"]))
    full = float(np.squeeze(d["full_scale"])) if "full_scale" in d else 1.0
    return {
        "archivo": archivo,
        "nombre": txt("nombre"),
        "medida": txt("medida"),
        "canal": txt("canal"),
        "amplitud": float(np.squeeze(d["amplitud"])) if "amplitud" in d else float("nan"),
        "perdidas": int(np.squeeze(d["perdidas"])),
        "alineacion": txt("alineacion") or "?",
        "rol": txt("rol"),                  # "separacion": captura del otro canal (sesiones de un canal por vez)
        "fs": fs,
        "l": d["L"].astype(float).ravel(order="F") / full,
        "r": d["R"].astype(float).ravel(order="F") / full,
    }


def _tono(p, k, ancho=ANCHO):
    b = slice(max(0, k - ancho), min(len(p), k + ancho + 1))
    return p[b].sum(), b


def _espectro(x):
    x = x - x.mean()
    n = len(x)
    w = blackmanharris(n, sym=True)
    p = np.abs(np.fft.rfft(x * w)) ** 2
    return p, n, w


def metricas_banda(x, fs, banda=(20.0, 20000.0), n_arm=7, ponderar_a=False):
    """THD, THD+N, SINAD, SNR, ENOB y SFDR de un tono, integrando solo dentro de la banda."""
    p, n, w = _espectro(x)
    f = np.arange(len(p)) * fs / n
    df = fs / n
    p0 = p.copy()
    if ponderar_a:
        p = p * ponderacion_a(f)

    en_banda = (f >= banda[0]) & (f <= banda[1])
    idx = np.flatnonzero(en_banda)
    k1 = idx[np.argmax(p[idx])]
    f0 = f[k1]

    usado = np.zeros(len(p), bool)
    usado[:ANCHO + 1] = True
    P1, b = _tono(p, k1)
    usado[b] = True

    Ph = 0.0
    arm = []
    for h in range(2, n_arm + 1):
        fh = h * f0
        if fh > banda[1] or fh > fs / 2:
            break
        kh = int(round(fh / df))
        cerca = np.arange(max(0, kh - 2), min(len(p), kh + 3))
        kk = cerca[np.argmax(p[cerca])]
        ph, b = _tono(p, kk)
        Ph += ph
        usado[b] = True
        arm.append((fh, 10 * np.log10(ph / P1)))

    Pn = p[en_banda & ~usado].sum()
    otros = en_banda.copy()
    otros[max(0, k1 - ANCHO):k1 + ANCHO + 1] = False
    otros[:ANCHO + 1] = False
    ke = int(np.argmax(p * otros))
    p_esp, _ = _tono(p, ke)

    thdn = 10 * np.log10((Ph + Pn) / P1)
    return {
        "f0": f0,
        "nivel": 10 * np.log10(4 * _tono(p0, k1)[0] / (n * np.sum(w**2))),
        "thd": 10 * np.log10(Ph / P1) if Ph > 0 else float("nan"),
        "thdn": thdn,
        "sinad": -thdn,
        "snr": 10 * np.log10(P1 / Pn),
        "enob": (-thdn - 1.76) / 6.02,
        "sfdr": 10 * np.log10(P1 / p_esp),
        "f_peor": f[ke],
        "armonicos": arm,
    }


def ruido_banda(x, fs):
    """Ruido sin señal en dBFS: total, 400 Hz-20 kHz, ponderado A, y sin la red (50 Hz y armonicos)."""
    f, pxx = welch(x - x.mean(), fs, window="blackmanharris", nperseg=65536, noverlap=32768, detrend=False)
    red = np.zeros(len(f), bool)
    for h in range(1, 401):
        red |= np.abs(f - 50 * h) < 4
    en = lambda a, b: (f >= a) & (f <= b)
    A = ponderacion_a(f)
    I = lambda wt, m: 10 * np.log10(_trapz(pxx[m] * wt[m], f[m]) / P_FS)
    uno = np.ones(len(f))
    return {
        "ruido_20k": I(uno, en(20, 20e3)),
        "ruido_400": I(uno, en(400, 20e3)),
        "ruido_A": I(A, en(20, 20e3)),
        "ruido_sinred": I(uno, en(20, 20e3) & ~red),
        "ruido_A_sinred": I(A, en(20, 20e3) & ~red),
    }


def nivel_cruce(y, fs, f0):
    """Nivel (dBFS) del tono f0 en un canal que no lo genera; si no asoma sobre el ruido, el nivel del ruido
    en esos mismos bins (la separacion queda como 'mayor que')."""
    p, n, w = _espectro(y)
    k0 = int(round(f0 / (fs / n)))
    a_db = lambda pot: 10 * np.log10(4 * pot / (n * np.sum(w**2)))
    vecinos = np.r_[k0 - 60:k0 - 20, k0 + 20:k0 + 60]
    return max(a_db(_tono(p, k0)[0]), a_db(11 * p[vecinos].mean()))


def extras_tono(x, otro, fs, f0):
    """Separacion, peor espurio NO armonico, pico cerca de 47,8 kHz e intermodulacion alrededor de 7 kHz."""
    px, n, w = _espectro(x)
    f = np.arange(len(px)) * fs / n
    nivel = lambda p, k: 10 * np.log10(4 * _tono(p, k)[0] / (n * np.sum(w**2)))
    k_de = lambda fx: int(round(fx / (fs / n)))
    e = {}

    k0 = k_de(f0)
    n0 = nivel(px, k0)
    if len(otro):
        e["separacion"] = n0 - nivel_cruce(otro, fs, f0)
    else:
        e["separacion"] = float("nan")             # un canal por vez: sale de la captura "_otro"

    # peor componente que no sea el fundamental, un armonico o la red, en 400 Hz - 20 kHz
    libre = (f >= 400) & (f <= 20e3)
    for h in range(1, int(np.ceil(20e3 / f0)) + 2):
        libre &= np.abs(f - h * f0) >= 20
    for h in range(1, 21):                     # la red (hasta 1 kHz; arriba ya no pesa)
        libre &= np.abs(f - 50 * h) >= 3
    k = int(np.argmax(px * libre))
    e["esp_no_arm"] = nivel(px, k) - n0
    e["f_esp_no_arm"] = f[k]

    zona = (f >= 46e3) & (f <= 48.8e3)
    k = int(np.argmax(px * zona))
    e["esp_478"] = nivel(px, k) - n0
    e["f_esp_478"] = f[k]

    k7 = k_de(7000)
    k7 = k7 - 3 + int(np.argmax(px[k7 - 3:k7 + 4]))
    n7 = nivel(px, k7)
    lat = lambda d: max(nivel(px, k_de(7000 - d)), nivel(px, k_de(7000 + d))) - n7
    e["imd_60"] = lat(60)
    e["imd_120"] = lat(120)
    return e


CAMPOS = ["nombre", "medida", "canal", "amplitud", "perdidas", "alineacion", "rol", "nivel_cruce",
          "nivel", "thd_400", "thdn_400", "sinad_400", "snr_400", "enob_400", "sfdr_400", "f_peor",
          "thdn_20k", "snr_20k", "sinad_20k", "thdn_A", "snr_A", "sinad_A", "separacion",
          "esp_no_arm", "f_esp_no_arm", "esp_478", "f_esp_478", "imd_60", "imd_120",
          "ruido_20k", "ruido_400", "ruido_A", "ruido_sinred", "ruido_A_sinred"]


def analizar_captura(c):
    """Una o dos filas (sin señal: una por canal) con todas las metricas."""
    base = {k: float("nan") for k in CAMPOS}
    base.update(nombre=c["nombre"], medida=c["medida"], amplitud=c["amplitud"], perdidas=c["perdidas"],
                alineacion=c["alineacion"], rol=c["rol"])
    if not c["canal"]:
        filas = []
        for ch in "lr":
            if len(c[ch]):                         # en las sesiones de un canal por vez viene uno solo
                fila = dict(base, canal=ch.upper())
                fila.update(ruido_banda(c[ch], c["fs"]))
                filas.append(fila)
        return filas

    ch = c["canal"]
    if c["rol"] == "separacion":
        # captura del canal que NO genera (M7/M8 de a un canal): solo el nivel del tono de 1 kHz que se cruza
        y = c["r"] if ch == "l" else c["l"]
        return [dict(base, canal=("R" if ch == "l" else "L"), nivel_cruce=nivel_cruce(y, c["fs"], 1000.0))]
    x, otro = (c["l"], c["r"]) if ch == "l" else (c["r"], c["l"])
    b4 = metricas_banda(x, c["fs"], (400, 20e3))
    b20 = metricas_banda(x, c["fs"], (20, 20e3))
    bA = metricas_banda(x, c["fs"], (20, 20e3), ponderar_a=True)
    fila = dict(base, canal=ch.upper(), nivel=b4["nivel"],
                thd_400=b4["thd"], thdn_400=b4["thdn"], sinad_400=b4["sinad"], snr_400=b4["snr"],
                enob_400=b4["enob"], sfdr_400=b4["sfdr"], f_peor=b4["f_peor"],
                thdn_20k=b20["thdn"], snr_20k=b20["snr"], sinad_20k=b20["sinad"],
                thdn_A=bA["thdn"], snr_A=bA["snr"], sinad_A=bA["sinad"])
    fila.update(extras_tono(x, otro, c["fs"], b4["f0"]))
    return [fila]


def _pdb(v):
    v = np.asarray(v, float)
    return 10 * np.log10(np.mean(10 ** (v / 10)))


def _rango(v):
    v = np.asarray([x for x in v if not np.isnan(x)], float)
    if len(v) == 0:
        return "-"
    if len(v) == 1:
        return f"{v[0]:.1f}"
    return f"{v.mean():.1f} [{v.min():.1f} a {v.max():.1f}]"


def resumen(filas, carpeta):
    T = lambda med: [f for f in filas if f["medida"] in med and f["rol"] != "separacion"]
    col = lambda F, k: [f[k] for f in F]
    r = [f"RESUMEN DE LA SESION  {carpeta}",
         f"Tramas perdidas en total: {sum(int(f['perdidas']) for f in filas if f['canal'] != 'R' or f['medida'] != 'M3')} (tiene que ser 0)",
         "Dato del ADC: " + ", ".join(sorted({f['alineacion'] for f in filas}))
         + "  (corrido = corregido por el firmware; directo = llego bien; ? = firmware viejo, puede estar x2)", ""]

    M = T(["M3"])
    if M:
        r.append("M3  PISO DE RUIDO DE LA CADENA (DAC encendido en silencio), promedio de las capturas")
        for ch in "LR":
            m = [f for f in M if f["canal"] == ch]
            r.append(f"  {ch}: 20-20k {_pdb(col(m, 'ruido_20k')):.1f} | 400-20k {_pdb(col(m, 'ruido_400')):.1f} | "
                     f"A {_pdb(col(m, 'ruido_A')):.1f} | sin red {_pdb(col(m, 'ruido_sinred')):.1f} | "
                     f"A sin red {_pdb(col(m, 'ruido_A_sinred')):.1f} dBFS")
            r.append(f"     RANGO DINAMICO (A): {-_pdb(col(m, 'ruido_A')):.1f} dB  (sin la red: "
                     f"{-_pdb(col(m, 'ruido_A_sinred')):.1f} dB)   hoja de datos ADC: tip. 99, min. 95")
        r.append("")

    M = T(["M4", "M4final"])
    if M:
        r.append("M4  NIVEL DE TRABAJO (1 kHz por tabla)")
        for f in M:
            r.append(f"  {f['nombre']:<12} {f['canal']}  amplitud {f['amplitud']:g} %  nivel {f['nivel']:.2f} dBFS")
        r.append("  Esperado: ~-1,5 dBFS al 63 % (sin Rs), L y R a menos de 0,5 dB; el control final igual al inicial.")
        r.append("")

    M = sorted(T(["M5"]), key=lambda f: -f["amplitud"])
    if len(M) > 1:
        r.append("M5  LINEALIDAD DEL ATENUADOR (canal L)")
        pedido = [-0.5 * round(-20 * np.log10(f["amplitud"] / 100) / 0.5) for f in M]   # lo que escribe el firmware
        for i, f in enumerate(M):
            linea = f"  {f['amplitud']:3g} %  pedido {pedido[i]:6.1f} dB  nivel {f['nivel']:7.2f} dBFS"
            if i:
                esc, esp = f["nivel"] - M[i - 1]["nivel"], pedido[i] - pedido[i - 1]
                linea += f"   escalon {esc:6.2f} dB (esperado {esp:5.1f}, error {esc - esp:+.2f})"
            r.append(linea)
        r.append("  Esperado: error de cada escalon menor que 0,1 dB.")
        r.append("")

    for med in ("M7", "M8"):
        M = T([med])
        if not M:
            continue
        r += [f"{med}  PUREZA canal {M[0]['canal']}, 1 kHz por tabla ({len(M)} capturas: promedio [min. a max.])",
              f"  nivel             {_rango(col(M, 'nivel'))} dBFS",
              f"  THD               {_rango(col(M, 'thd_400'))} dB",
              f"  THD+N 400-20k     {_rango(col(M, 'thdn_400'))} dB     (20-20k: {_rango(col(M, 'thdn_20k'))}, A: {_rango(col(M, 'thdn_A'))})",
              f"  SNR   400-20k     {_rango(col(M, 'snr_400'))} dB     (20-20k: {_rango(col(M, 'snr_20k'))}, A: {_rango(col(M, 'snr_A'))})",
              f"  SINAD 400-20k     {_rango(col(M, 'sinad_400'))} dB   ENOB {_rango(col(M, 'enob_400'))} bits",
              f"  SFDR  400-20k     {_rango(col(M, 'sfdr_400'))} dB   (peor componente en "
              + ", ".join(f"{v:.0f}" for v in col(M, 'f_peor')) + " Hz)",
              f"  separacion        {_rango(col(M, 'separacion'))} dB",
              "  Propuesta (minimo): THD+N < -60 dB, SNR > 80 dB, SFDR > 70 dB, separacion > 80 dB.",
              "  Hoja de datos ADC: THD+N -93 dB tip. (-85 max.), separacion 96 dB tip.", ""]

    M = T(["M9"])
    if M:
        s = [f for f in M if "seno" in f["nombre"]]
        t = [f for f in M if "tabla" in f["nombre"]]
        hz = lambda F: ", ".join(f"{v:.0f}" for v in col(F, "f_esp_no_arm"))
        r += ["M9  SENO POR ACUMULADOR CONTRA TABLA (1 kHz, canal L)",
              "                       seno (acumulador)         tabla",
              f"  THD+N 400-20k        {_rango(col(s, 'thdn_400')):<25}{_rango(col(t, 'thdn_400'))} dB",
              f"  SNR 400-20k          {_rango(col(s, 'snr_400')):<25}{_rango(col(t, 'snr_400'))} dB",
              f"  SFDR 400-20k         {_rango(col(s, 'sfdr_400')):<25}{_rango(col(t, 'sfdr_400'))} dB",
              f"  peor NO armonico     {_rango(col(s, 'esp_no_arm')):<25}{_rango(col(t, 'esp_no_arm'))} dBc",
              f"    en                 {hz(s):<25}{hz(t)} Hz",
              "  Esperado: con el seno por acumulador, un espurio de ~-78 dBc cerca de 10,1 kHz; con la tabla no.", ""]

    M = T(["M10"])
    if M:
        r.append("M10 995,4 Hz POR PASO CONTRA POR TABLA (mayor componente entre 46 y 48,8 kHz)")
        for f in M:
            r.append(f"  {f['nombre']:<10} {f['esp_478']:7.1f} dBc en {f['f_esp_478']:.0f} Hz")
        r.append('  Esperado: en "paso" un pico en ~47,8 kHz que en "tabla" no esta (cualitativo: el filtro del codec atenua ahi).')
        r.append("")

    M = T(["M15"])
    if M:
        r += ["M15 MULTITONO 60 Hz + 7 kHz: bandas laterales respecto del tono de 7 kHz",
              f"  7000 +- 60 Hz: {M[0]['imd_60']:.1f} dBc     7000 +- 120 Hz: {M[0]['imd_120']:.1f} dBc",
              "  Cuanto mas abajo, menos intermodulacion (mezcla entre los dos tonos).", ""]

    M = T(["M11"])
    if M:
        r.append("M11 RANGO DINAMICO (EIAJ: senal a -60 dB, 20 Hz-20 kHz, ponderado A)")
        for f in M:
            if -75 < f["nivel"] < -45:
                r.append(f"  {f['canal']}: nivel {f['nivel']:.1f} dBFS  ->  RANGO DINAMICO {f['sinad_A'] - f['nivel']:.1f} dB (A)"
                         f"   (sin ponderar {f['sinad_20k'] - f['nivel']:.1f} dB)")
            else:
                r.append(f"  {f['canal']}: nivel {f['nivel']:.1f} dBFS: NO quedo en -60 dB, esta captura no sirve para el rango dinamico")
        r.append("  Hoja de datos ADC: tip. 99 dB, min. 95 dB (a fs = 48 kHz).")
        r.append("")
    return "\n".join(r)


def analizar_sesion(carpeta, eco=True):
    archivos = sorted(glob.glob(os.path.join(carpeta, "*.mat")))
    filas = []
    for i, a in enumerate(archivos, 1):
        c = cargar(a)
        if eco:
            print(f"  analizando {i:2d}/{len(archivos)}  {c['nombre']}")
        filas += analizar_captura(c)

    # sesiones de un canal por vez: la separacion de cada M7/M8 sale de su captura "_otro"
    por_nombre = {f["nombre"]: f for f in filas}
    for f in filas:
        if f["rol"] == "separacion" and f["nombre"].endswith("_otro"):
            principal = por_nombre.get(f["nombre"][:-len("_otro")])
            if principal is not None:
                principal["separacion"] = principal["nivel"] - f["nivel_cruce"]

    with open(os.path.join(carpeta, "resultados.csv"), "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=CAMPOS, extrasaction="ignore")
        wr.writeheader()
        for f in filas:
            wr.writerow({k: (f"{v:.3f}" if isinstance(v, float) else v) for k, v in f.items()})

    texto = resumen(filas, carpeta)
    with open(os.path.join(carpeta, "resumen.txt"), "w", encoding="utf-8") as fh:
        fh.write(texto + "\n")
    return texto
