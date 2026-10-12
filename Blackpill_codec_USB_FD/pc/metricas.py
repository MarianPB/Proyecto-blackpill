"""
Metricas de un generador de audio a partir de las muestras del ADC (ver Guia_mediciones_especificaciones.txt).

Todo trabaja con muestras normalizadas: 1.0 = fondo de escala (2^23). Un seno de pico 1.0 tiene
potencia 0.5, que es la referencia de 0 dBFS.

Espectro: Welch con segmentos de N_FFT muestras, 50 % de solape y ventana Blackman-Harris de 7 terminos.
Se usa esa ventana y no Hann porque sus lobulos laterales estan ~180 dB abajo: con Hann, la "pollera"
de la fundamental a pocos bins ya esta a -80 dBc y se sumaria como ruido en el THD+N y el SNR.
El espectro esta escalado en POTENCIA (la suma de todos los bins da el valor cuadratico medio), asi la
potencia de un tono es la suma de los bins de su lobulo y la del ruido es la suma de los bins de la banda.
"""

import numpy as np

FS = 97656.25
N_FFT = 32768
P_FS = 0.5                     # potencia de un seno de fondo de escala (0 dBFS)
LOBULO = 10                    # bins a cada lado de un tono que se le asignan (el lobulo de BH7 es de +-7)
MAX_ARMONICOS = 20

# Blackman-Harris de 7 terminos (lobulos laterales < -180 dB)
_BH7 = (0.27105140069342, 0.43329793923448, 0.21812299954311, 0.06592544638803,
        0.01081174209837, 0.00077658482522, 0.00001388721735)


def ventana_bh7(n):
    k = np.arange(n) * (2.0 * np.pi / n)
    w = np.zeros(n)
    for i, a in enumerate(_BH7):
        w += (-1) ** i * a * np.cos(i * k)
    return w


def espectro_potencia(bloques, fs=FS, n_fft=N_FFT):
    """
    bloques: lista de arrays 1D (cada uno continuo, sin saltos). Los segmentos no cruzan de un bloque a
    otro, asi un bloque con perdidas que se excluyo no deja una discontinuidad.
    Devuelve (f, P, segmentos): P[k] = potencia del bin k (una cara). Suma de P = valor cuadratico medio.
    """
    w = ventana_bh7(n_fft)
    escala = 1.0 / (n_fft * np.sum(w ** 2))
    hop = n_fft // 2
    acum = np.zeros(n_fft // 2 + 1)
    segs = 0
    for x in bloques:
        x = np.asarray(x, dtype=np.float64)
        for i0 in range(0, len(x) - n_fft + 1, hop):
            s = x[i0:i0 + n_fft]
            X = np.fft.rfft((s - s.mean()) * w)
            acum += np.abs(X) ** 2
            segs += 1
    if segs == 0:
        return None, None, 0
    P = acum / segs * escala
    P[1:-1] *= 2.0                               # una sola cara: se suma la frecuencia negativa
    f = np.fft.rfftfreq(n_fft, 1.0 / fs)
    return f, P, segs


def peso_a(f):
    """Ponderacion A (IEC 61672) en POTENCIA, normalizada a 0 dB en 1 kHz."""
    f2 = np.asarray(f, dtype=np.float64) ** 2
    ra = (12194.0 ** 2 * f2 ** 2) / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2))
                                     * (f2 + 12194.0 ** 2))
    return (ra * 10 ** (2.0 / 20.0)) ** 2


def _db(p, ref=1.0):
    return 10.0 * np.log10(max(p, 1e-30) / ref)


def _lobulo(k, n):
    return max(k - LOBULO, 1), min(k + LOBULO, n - 1)


def _tono(P, k_esperado, busqueda, piso_bin):
    """Busca el pico cerca de k_esperado y devuelve (potencia del tono sin el ruido de su lobulo, k del pico)."""
    n = len(P)
    a, b = max(k_esperado - busqueda, 1), min(k_esperado + busqueda, n - 2)
    if a > b:
        return 0.0, k_esperado
    k = a + int(np.argmax(P[a:b + 1]))
    i0, i1 = _lobulo(k, n)
    pot = float(np.sum(P[i0:i1 + 1])) - piso_bin * (i1 - i0 + 1)
    return max(pot, 0.0), k


def analizar(f, P, banda=(400.0, 20000.0), f0=None, ponderar_a=False):
    """
    Metricas de UN canal a partir de su espectro de potencia.
    f0: frecuencia de la fundamental; si es None se toma el pico mas alto entre 10 Hz y 20 kHz.
    Devuelve un dict con todo (potencias en las mismas unidades que P, niveles en dB).
    """
    df = f[1] - f[0]
    n = len(P)
    lo, hi = banda
    en_banda = (f >= lo) & (f <= hi)

    if ponderar_a:
        P = P * peso_a(f)

    # --- fundamental ---
    if f0 is None:
        busq = (f >= 10.0) & (f <= 20000.0)
        k0 = int(np.flatnonzero(busq)[np.argmax(P[busq])])
    else:
        k0 = int(round(f0 / df))
        a, b = max(k0 - 3, 1), min(k0 + 3, n - 2)
        k0 = a + int(np.argmax(P[a:b + 1]))
    i0, i1 = _lobulo(k0, n)
    p_fund = float(np.sum(P[i0:i1 + 1]))
    kk = np.arange(max(k0 - 3, 1), min(k0 + 3, n - 1) + 1)
    f_fund = float(np.sum(f[kk] * P[kk]) / np.sum(P[kk]))      # centroide del lobulo: mejor que el bin

    # --- mascara de lo que NO es ruido: lobulo de la fundamental y de los armonicos ---
    no_ruido = np.zeros(n, dtype=bool)
    no_ruido[i0:i1 + 1] = True
    k_arm = []
    h = 2
    while h <= MAX_ARMONICOS and h * f_fund <= min(hi, f[-1] - LOBULO * df):
        ke = int(round(h * f_fund / df))
        ka = ke - 2 + int(np.argmax(P[ke - 2:ke + 3]))           # el pico puede caer a +-2 bins
        a, b = _lobulo(ka, n)
        no_ruido[a:b + 1] = True
        k_arm.append((h, ka))
        h += 1

    ruido = en_banda & ~no_ruido
    piso_bin = float(np.median(P[ruido])) if np.any(ruido) else 0.0

    # armonicos (cada uno menos el ruido que cae en su lobulo)
    armonicos = []
    for h, ka in k_arm:
        if not (lo <= f[ka] <= hi):
            continue
        pot, _ = _tono(P, ka, 0, piso_bin)
        armonicos.append((h, float(f[ka]), pot))
    p_arm = sum(a[2] for a in armonicos)

    p_banda = float(np.sum(P[en_banda]))
    fund_en_banda = lo <= f_fund <= hi
    p_resto = p_banda - (p_fund if fund_en_banda else 0.0)     # todo lo que no es la fundamental (THD+N)
    # ruido para el SNR: los bins sin fundamental ni armonicos, escalados a toda la banda (los lobulos
    # sacados tambien tenian ruido; sin esto el ruido sale ~0.3 dB bajo con 1 kHz)
    n_ruido = int(np.sum(ruido))
    p_ruido = float(np.sum(P[ruido])) * np.sum(en_banda) / n_ruido if n_ruido else 0.0

    # peor espurio (armonico o no) dentro de la banda, fuera del lobulo de la fundamental
    cand = en_banda.copy()
    cand[i0:i1 + 1] = False
    if np.any(cand):
        ks = int(np.flatnonzero(cand)[np.argmax(P[cand])])
        p_esp, ks = _tono(P, ks, 0, piso_bin)
        f_esp = float(f[ks])
    else:
        p_esp, f_esp = 0.0, float("nan")

    r = {
        "banda": banda, "ponderada_a": ponderar_a, "df": df,
        "f0": f_fund, "fund_en_banda": fund_en_banda,
        "nivel_dbfs": _db(p_fund, P_FS),
        "total_banda_dbfs": _db(p_banda, P_FS),
        "ruido_dbfs": _db(p_ruido, P_FS),
        "piso_bin_dbfs": _db(piso_bin, P_FS),
        "armonicos": [(h, fh, _db(p, p_fund) if p > 0 else None) for h, fh, p in armonicos],
        "thd_db": _db(p_arm, p_fund) if p_arm > 0 else None,
        "thd_pct": 100.0 * np.sqrt(p_arm / p_fund) if p_arm > 0 and p_fund > 0 else None,
        "thdn_db": _db(p_resto, p_fund),
        "thdn_pct": 100.0 * np.sqrt(max(p_resto, 0.0) / p_fund) if p_fund > 0 else None,
        "snr_db": _db(p_fund, p_ruido),
        "snr_fs_db": _db(P_FS, p_ruido),                       # referida al fondo de escala
        "sfdr_dbc": _db(p_fund, p_esp) if p_esp > 0 else None,
        "f_espurio": f_esp,
    }
    r["sinad_db"] = -r["thdn_db"]
    r["enob"] = (r["sinad_db"] - 1.76) / 6.02
    # rango dinamico (EIAJ): (S+N+D)/(N+D) con la señal a ~-60 dBFS, mas el nivel
    r["rango_dinamico_db"] = r["sinad_db"] - r["nivel_dbfs"] if -75.0 < r["nivel_dbfs"] < -45.0 else None
    return r


def nivel_en(f, P, f0, ponderar_a=False):
    """Nivel (dBFS) del tono de frecuencia f0 en este canal, descontando el ruido de su lobulo."""
    if ponderar_a:
        P = P * peso_a(f)
    df = f[1] - f[0]
    k = int(round(f0 / df))
    a, b = max(k - 3 * LOBULO, 1), min(k + 3 * LOBULO, len(P) - 1)
    alrededor = np.r_[P[a:max(k - LOBULO, a)], P[min(k + LOBULO + 1, b):b + 1]]
    piso_bin = float(np.median(alrededor)) if len(alrededor) else 0.0
    pot, _ = _tono(P, k, 2, piso_bin)
    return _db(pot, P_FS) if pot > 0 else None


def separacion(f, P_activo, P_otro, f0, ponderar_a=False):
    """Separacion entre canales: nivel de f0 en el canal activo menos el que se cuela en el otro (dB)."""
    na = nivel_en(f, P_activo, f0, ponderar_a)
    no = nivel_en(f, P_otro, f0, ponderar_a)
    if na is None:
        return None, no
    if no is None:
        return float("inf"), None
    return na - no, no


def _fmt(v, unidad="", dec=1, signo=False):
    if v is None:
        return "—"
    if v == float("inf"):
        return "debajo del ruido"
    return f"{v:+.{dec}f}{unidad}" if signo else f"{v:.{dec}f}{unidad}"


def informe(res, meta=None):
    """
    Texto con la planilla de especificaciones. res = {"L": dict de analizar, "R": dict} (puede faltar uno);
    res["sep"] = {"L->R": (dB, nivel), "R->L": (...)} si se calculo la separacion.
    """
    meta = meta or {}
    lineas = []
    lineas.append("PLANILLA DE MEDICION - generador AGSE (lazo DAC -> ADC)")
    if meta.get("fecha"):
        lineas.append(f"Fecha: {meta['fecha']}")
    for c in ("L", "R"):
        if meta.get(f"onda_{c}"):
            lineas.append(f"Canal {c}: {meta[f'onda_{c}']}")
    if meta.get("salida"):
        lineas.append(f"Salida del DAC: {meta['salida']}")
    r0 = res.get("L") or res.get("R")
    if r0 is None:
        return "\n".join(lineas + ["Sin datos."])
    lo, hi = r0["banda"]
    lineas.append(f"Banda {lo:g} Hz - {hi / 1000:g} kHz · {'ponderación A' if r0['ponderada_a'] else 'sin ponderar'}"
                  f" · fs {FS:g} Hz · FFT {N_FFT} ({r0['df']:.2f} Hz/bin), Blackman-Harris 7, Welch 50 %"
                  + (f" · {meta['segmentos']} segmentos" if meta.get("segmentos") else ""))
    lineas.append("")

    canales = [c for c in ("L", "R") if res.get(c)]
    ancho = 16
    lineas.append(f"{'':<34}" + "".join(f"{c + (' (apagado)' if res[c].get('apagado') else ''):>{ancho}}"
                                        for c in canales))

    # en el canal apagado solo tienen sentido el ruido y lo que hay en la banda
    solo_senal = {"f0", "nivel_dbfs", "thd_db", "thd_pct", "thdn_db", "thdn_pct", "sinad_db", "enob",
                  "snr_db", "sfdr_dbc", "f_espurio", "rango_dinamico_db"}

    def fila(nombre, clave, unidad="", dec=1):
        celdas = []
        for c in canales:
            v = None if (res[c].get("apagado") and clave in solo_senal) else res[c][clave]
            celdas.append(f"{_fmt(v, unidad, dec):>{ancho}}")
        lineas.append(f"{nombre:<34}" + "".join(celdas))

    fila("Frecuencia de la fundamental", "f0", " Hz", 2)
    fila("Nivel de la fundamental", "nivel_dbfs", " dBFS")
    fila("THD (solo armónicos)", "thd_db", " dB")
    fila("THD [%]", "thd_pct", " %", 4)
    fila("THD+N", "thdn_db", " dB")
    fila("THD+N [%]", "thdn_pct", " %", 4)
    fila("SINAD", "sinad_db", " dB")
    fila("ENOB", "enob", " bits", 2)
    fila("SNR (respecto de la señal)", "snr_db", " dB")
    fila("SNR (respecto del fondo de escala)", "snr_fs_db", " dB")
    fila("SFDR", "sfdr_dbc", " dBc")
    fila("  frecuencia del peor espurio", "f_espurio", " Hz", 1)
    fila("Ruido en banda (sin señal ni arm.)", "ruido_dbfs", " dBFS")
    fila("Todo lo que hay en la banda", "total_banda_dbfs", " dBFS")
    fila("Rango dinámico (EIAJ, señal -60)", "rango_dinamico_db", " dB")

    sep = res.get("sep") or {}
    for clave, (db, nivel) in sep.items():
        lineas.append(f"{'Separación ' + clave:<34}{_fmt(db, ' dB'):>{ancho}}"
                      + (f"   (en el otro canal: {_fmt(nivel, ' dBFS')})" if nivel is not None else ""))

    lineas.append("")
    for c in canales:
        arm = [(h, fh, d) for h, fh, d in res[c]["armonicos"][:9]]
        if arm and not res[c].get("apagado"):
            lineas.append(f"Armónicos {c} (dBc): " + "  ".join(
                f"H{h} {'<ruido' if d is None else f'{d:.1f}'}" for h, fh, d in arm))
    for c in canales:
        if res[c].get("apagado"):
            continue
        if not res[c]["fund_en_banda"]:
            lineas.append(f"OJO canal {c}: la fundamental ({res[c]['f0']:.0f} Hz) está fuera de la banda; "
                          "THD/SNR no tienen sentido. Para el piso de ruido mirá 'Todo lo que hay en la banda'.")
        if res[c]["nivel_dbfs"] > -0.5:
            lineas.append(f"OJO canal {c}: nivel {res[c]['nivel_dbfs']:.1f} dBFS, el ADC puede estar recortando.")
    lineas.append("")
    lineas.append("Medición en lazo DAC -> ADC: los valores son del conjunto generador + adquisidor; el DAC solo es "
                  "igual o mejor.")
    lineas.append("La frecuencia se mide con el mismo reloj que la genera: para la EXACTITUD de frecuencia usar "
                  "el frecuencímetro.")
    lineas.append("Rango dinámico: solo se calcula con la señal entre -75 y -45 dBFS (método EIAJ, -60 dBFS).")
    lineas.append("Separación: válida solo si el otro canal está apagado (ROFF/LOFF).")
    return "\n".join(lineas)


def medir(bloques_lr, banda=(400.0, 20000.0), ponderar_a=False):
    """
    bloques_lr: lista de arrays (n, 2) validos. Devuelve (res, segmentos) listo para informe().
    La separacion se calcula si un canal esta al menos 40 dB por debajo del otro (el 'apagado').
    """
    res = {}
    espectros = {}
    segs = 0
    for i, c in enumerate(("L", "R")):
        f, P, segs = espectro_potencia([b[:, i] for b in bloques_lr])
        if P is None:
            return None, 0
        espectros[c] = P
        res[c] = analizar(f, P, banda, ponderar_a=ponderar_a)

    nl, nr = res["L"]["nivel_dbfs"], res["R"]["nivel_dbfs"]
    sep = {}
    if nl - nr > 40:
        sep["L -> R"] = separacion(f, espectros["L"], espectros["R"], res["L"]["f0"], ponderar_a)
        res["R"]["apagado"] = True
    elif nr - nl > 40:
        sep["R -> L"] = separacion(f, espectros["R"], espectros["L"], res["R"]["f0"], ponderar_a)
        res["L"]["apagado"] = True
    res["sep"] = sep
    return res, segs
