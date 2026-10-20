# Diagnóstico: piso de ruido del ADC (Blackpill STM32F411 + PCM3060)

> **Para quien verifique este documento (otro Claude u otra persona):** esto salió de **leer el código**. No se
> compiló, no se probó en el hardware y en el repo no había mediciones guardadas (`mediciones/*.npz`). Tratá
> cada punto como una **hipótesis**: comprobá la evidencia en el código, corré los scripts del apéndice y marcá
> cada punto como *confirmado*, *refutado* o *sin poder verificar*. Los valores de hojas de datos que figuran
> "de memoria" hay que chequearlos contra el PDF.

## 0. Contexto

| | |
|---|---|
| Repositorio | `MarianPB/Proyecto-blackpill` |
| Rama revisada | `mediciones-metricas` (la más nueva), commit `6ea996b` del 2026-10-12 |
| Proyecto | `Blackpill_codec_USB_FD/` |
| Hardware | STM32F411CEU6 (Blackpill, HSE 25 MHz) + codec TI PCM3060, lazo DAC → ADC |
| Audio | I2S2 **full duplex, STM32 maestro**, Philips, 24 bits, MCK habilitado. El codec es esclavo del ADC y del DAC |
| Relojes | PLLI2S: 25 MHz / 16 × 192 / 2 = **I2SCLK 150 MHz** → fs = 150 MHz / (256·6) = **97 656,25 Hz**, **MCK = 25 MHz** (256 fs), **BCK = 6,25 MHz** (64 fs) |
| Hacia la PC | USB CDC, tramas `0xAA 0x55` con 256 frames de 24 bits (~586 kB/s) |
| Síntoma reportado | "Medimos el piso de ruido y nos da bastante feo". No hay números concretos. |

## Resumen de causas posibles

| # | Causa posible | Cuándo afecta | Confianza | Cómo se verifica |
|---|---|---|---|---|
| 1 | El **seno del DAC** se genera por acumulador con una tabla de 8192 puntos sin interpolar: la truncación de fase deja un error de **≈ −75 dBc en banda**, que la app cuenta como ruido | Mediciones **con señal** (SNR, THD+N, "piso" con tono) | **Alta** (simulado con el mismo algoritmo) | Script A + prueba en placa |
| 2 | **Pines del I2S en `GPIO_SPEED_FREQ_LOW`**: MCK de 25 MHz con jitter y BCK de 6,25 MHz con timing al límite. Esto explicaría el **corrimiento de 1 bit** medido el 08/10, y el `<< 1` lo corrige pero no le da margen | **Todo**, también sin señal | Media (la configuración está confirmada; la relación causal es hipótesis) | Osciloscopio + cambiar la velocidad |
| 3 | **Espurios del propio firmware**: OLED y teclado (patrón de 200 ms), ISR del DMA (381,5 Hz), USB (1 kHz) | Líneas en el espectro, "zumbido" | Baja-media (depende del armado) | Apagar cada fuente y comparar |
| 4 | **Interpretación**: la app muestra tres convenciones de dB distintas, existe la banda "20 Hz–48 kHz (todo)", la captura en vivo no excluye pérdidas y en el lazo se mide también el ruido del DAC | La **lectura** del número | **Alta** (Script B con las funciones reales de la app) | Script B |
| 5 | Si se graba el firmware de **`integracion-codec-usb`**, no tiene el `<< 1`: el ruido sale en **≈ −6 dBFS** | Solo con esa rama | **Alta** (Script C) | Script C + qué firmware está grabado |
| 6 | Menores: entrada del PLLI2S a 1,56 MHz (ST recomienda 2 MHz) y fs un 1,7 % por encima del máximo del PCM3060 | Jitter, marginal | Baja | Hojas de datos |

---

## 1. Truncación de fase del seno del DAC (≈ −75 dBc en banda)

**Evidencia en el código**
- `Core/Src/waveforms.c:51`, caso `WAVE_SINE`: `acc[c] += ftw[c]; v = sine_table[acc[c] >> 19];`. El acumulador es de 32 bits y se indexa con los **13 bits altos**, **sin interpolar**.
- `Core/Inc/sine_table.h`: `SINE_N 8192`, 24 bits con signo.
- `Core/Src/waveforms.c:26`: la forma por defecto es `{ WAVE_SINE, WAVE_SINE }`.
- `pc/metricas.py:129` y `:143`: el ruido es "lo que hay en la banda menos los lóbulos de la fundamental y los armónicos", y el THD+N es "todo menos la fundamental". Los espurios **no armónicos** se suman al ruido.

**Razonamiento**
- El error de fase queda uniforme en [0, 2π/8192). Su varianza es Δ²/12 = (2π/8192)²/12 ≈ 4,9·10⁻⁸, o sea **−73,1 dBc** de error total. Se reparte en muchos espurios.
- La simulación (Script A) da exactamente −73,1 dBc. Dentro de 20 Hz–20 kHz quedan **−74,9 dBc a 1000 Hz** y −81,5 dBc a 997 Hz; el reparto depende de la FTW. El espurio individual más grande sale en ≈ −81 dBc.
- Con el tono a −11,5 dBFS (1 kHz al 20 %), el "ruido" en banda queda cerca de **−86 dBFS**. Lo que se espera del codec está entre −95 y −99 dBFS. Con el seno común, el SNR y el THD+N quedan limitados por el generador, no por el ADC.
- El README ya avisa de un espurio de ≈ −78 dBc en 10,1 kHz con 1 kHz. Mi simulación da como máximo −81,4 dBc en 12,1 kHz. **La diferencia está sin resolver**, pero no cambia la conclusión: lo que pesa en el ruido es el **total** (−75 dBc), no el espurio mayor.
- La forma `WAVE_SINE_TAB` (`xWAVE:4`, 1 kHz exacto por tabla, 3125 muestras = 32 períodos) no trunca: su error es de ≈ −146 dBc, que es solo la cuantización de 24 bits.

**Cómo verificar**
1. Correr el Script A.
2. En la placa: misma amplitud, comparar **Seno (idx 0) a 1000 Hz** contra **1 kHz TABLA (idx 4)** con Tiempo fijo de 5 s en 20 Hz–20 kHz. Si esta es la limitación, el THD+N y el SNR mejoran bastante más de 10 dB con la tabla.

**Arreglo propuesto:** para medir, usar `LWAVE:4` / `RWAVE:4`. En el firmware se puede interpolar linealmente entre muestras de la tabla, o usar una tabla más grande.

---

## 2. Pines del I2S en velocidad LOW: jitter de MCK y timing de BCK al límite

**Evidencia en el código**
- `Core/Src/stm32f4xx_hal_msp.c:189-208`: PA3 (MCK), PB10 (CK), PB12 (WS), PB15 (SD) y PB14 (ext_SD) están todos con `GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;`.
- `Version V2.ioc`: esos pines no tienen la entrada `GPIO_Speed`, así que quedan en el valor por defecto de CubeMX (LOW). Si se regenera, sigue en LOW.
- `Core/Src/main.c:328-336`: `I2S_MODE_MASTER_TX`, `I2S_STANDARD_PHILIPS`, `I2S_DATAFORMAT_24B`, `I2S_MCLKOUTPUT_ENABLE`, `I2S_CPOL_LOW`, `FullDuplexMode` habilitado. En `main.c:170` el registro 72 vale `0x00` (ADC esclavo, I2S de 24 bits).
- `Core/Src/stream.c:60-65` y la sección "Ojo" del README: el 08/10 se midió en la placa que **el I2S2ext recibe la palabra corrida un bit a la derecha**. El bit 31 es relleno (0), el signo nunca llegaba y la señal quedaba a mitad de escala. Se compensó con `<< 1`.

**Razonamiento**
1. *Mecanismo del corrimiento.* Con CPOL bajo, el STM32 maestro cambia los datos en el flanco de bajada de BCK y muestrea en el de subida, **80 ns** después (el período es de 160 ns).
   - El codec esclavo saca DOUT respecto del BCK **que le llega**.
   - El ida y vuelta suma el retardo del pin CK (flancos lentos en LOW), el t(BCK→DOUT) del codec y el cableado.
   - Si ese total pasa de ~80 ns, el STM32 latchea el **bit anterior**. Para el MSB, el bit anterior es el último bit de relleno del slot previo, que vale 0. Eso coincide exactamente con lo medido.
2. *Alternativas que descarté*
   - Formatos distintos. Los dos están en I2S Philips. Si el codec estuviera en left-justified y el STM32 en Philips, el corrimiento sería hacia la **izquierda**, no hacia la derecha. Si el codec estuviera en Philips y el STM32 en MSB-justified, el síntoma coincidiría, pero el STM32 está configurado en Philips. *Verificar en tiempo de ejecución el campo I2SSTD de `SPI2->I2SCFGR` y de `I2S2ext->I2SCFGR`.*
   - Desincronización del I2Sext esclavo. En `Drivers/.../stm32f4xx_hal_i2s_ex.c:661` el HAL habilita el ext **antes** que el maestro (`__HAL_I2SEXT_ENABLE` y después `__HAL_I2S_ENABLE`), como pide el manual. Además, una desincronización daría corrimientos al azar, no exactamente 1 bit fijo.
3. *Evidencia a favor, débil.* En el proyecto viejo `Envio_codec_UART` (rama `main`) el codec era el **maestro**: BCK y DOUT salían del mismo chip, sin ida y vuelta. Ahí no se informó ningún corrimiento, aunque tampoco hay mediciones guardadas.
4. *Consecuencia para el ruido.* Si el retardo anda cerca de 80 ns, el muestreo cae cerca de la transición del dato y el margen es chico. Pueden aparecer errores de bit intermitentes que cambian con la temperatura, el cable o el ruido, y se ven como picos y piso alto. El `<< 1` corrige el corrimiento fijo, pero no la falta de margen.
5. *MCK de 25 MHz en un pin LOW.* Según la hoja de datos del F411 ("I/O AC characteristics", **valores de memoria a verificar**), con `OSPEEDR = 00` el pin admite fmax ≈ 4 MHz con 50 pF y ≈ 8 MHz con 10 pF, con tr/tf ≈ 100 ns. A 25 MHz los flancos son lentos y la excursión queda incompleta. El cruce de umbral en SCKI del PCM3060 tiene mucho jitter, y SCKI mueve los moduladores ΔΣ del ADC y del DAC: puede subir el piso de ruido aunque las señales "se vean bien".

**Confianza.** Que los pines están en LOW es un hecho. Que eso cause el corrimiento y el jitter es una hipótesis de confianza **media**.

**Cómo verificar**
1. Medir con osciloscopio, en el pin PB10 del STM32 y en el pin BCK del codec, el tiempo de subida y la excursión. Medir el retardo entre el flanco de bajada de BCK en el STM32 y la transición de DOUT en PB14, y compararlo con 80 ns. Mirar también MCK en el pin SCKI del codec: amplitud y forma.
2. Experimento: PA3 en `GPIO_SPEED_FREQ_VERY_HIGH` y PB10/PB12/PB15 en `GPIO_SPEED_FREQ_HIGH`. Grabar y medir **1 kHz TABLA al 20 %** con el `<< 1` todavía puesto:
   - **≈ −11,5 dBFS**: el corrimiento sigue. Esta no era la causa, o el retardo sigue siendo largo.
   - **≈ −5,5 dBFS** (6 dB más): el corrimiento **desapareció**. Ahora el `<< 1` está duplicando el dato y hay que **sacarlo** de `stream.c:64-65`.
3. Con la entrada del ADC en cortocircuito, comparar el piso de ruido (punto 9, paso 1) antes y después del cambio.

**Arreglo propuesto:** el experimento anterior, aplicado también en CubeMX (GPIO Settings → I2S2 → Maximum output speed). Cables cortos. Opcionalmente, 22–33 Ω en serie en MCK y BCK, cerca del STM32.

---

## 3. Espurios generados por la actividad del firmware

**Evidencia en el código**
- `Core/Src/main.c:216-229`: el teclado se escanea cada 20 ms y el OLED se refresca cada 200 ms.
- El OLED comparte el I2C1 con el codec (`Core/Inc/ssd1306_conf.h:7`). Va a 100 kHz (`main.c:295`) y `ssd1306_UpdateScreen` manda 8 páginas de 128 bytes con `HAL_MAX_DELAY` (`ssd1306.c:14,19`). Son ~1 kB, o sea **~0,1 s bloqueando el lazo principal cada 200 ms**. A eso se suma la bomba de carga del SSD1306.
- `Core/Src/keypad.c:38-57`: en cada escaneo las filas (PA0, PA1, PB0, PB1) bajan y suben.
- `Core/Src/main.c:447-458`: los callbacks del DMA corren cada 256 frames (2,62 ms, **381,47 Hz**). Hacen `fill()` y `stream_push_audio()` dentro de la ISR.
- USB FS: SOF cada 1 ms, con ~586 kB/s de tráfico bulk copiado por la CPU (sin DMA).

**Razonamiento.** Una actividad digital periódica modula la corriente de la alimentación y de la masa. Si se acopla a la parte analógica, aparece como líneas en esas frecuencias. Como el refresco del OLED bloquea ~100 ms, el teclado no se escanea a 50 Hz limpios: todo el patrón se repite cada 200 ms. Eso da un **peine de líneas cada 5 Hz** con energía cerca de 50 Hz y sus armónicos, que se confunde con la red (50 Hz en Argentina).

**Confianza:** baja-media. Depende del armado, del plano de masa y de la alimentación.

**Cómo verificar**
- En el espectro de `metricas` con el DAC apagado, buscar líneas en múltiplos de 5 Hz, de 381,47 Hz y de 1 kHz.
- Comentar `oled_show(...)` y `keypad_process()`, o agregar un comando para apagarlos, y volver a medir.
- Pasar el escaneo del teclado a 23 ms: si las líneas se mueven, la fuente es el firmware y no la red.

---

## 4. Interpretación: tres convenciones de dB para el mismo ruido

**Evidencia en el código**
- `pc/visor_adc.py:319`, `estadisticas_bloque`: el "RMS sin continua" en dBFS **toma 1,0 = 2²³ como referencia** (fondo de escala de continua o cuadrada) y usa toda la banda, de 0 a 48,8 kHz, sin ponderar y con el zumbido incluido. Es lo que imprime el registro "Bloque n: … RMS … dBFS".
- `pc/visor_adc.py:297-316`, `espectro_promedio`: Hann, N = 32768, `|X| / (Σw/2)`. Es un **espectro por bin** calibrado para senos.
- `pc/visor_adc.py:933-935`, `_db_log`: dibuja el **máximo** de cada grupo de bins (`np.maximum.reduceat`). En 20 kHz los grupos son de ~33 bins, así que el piso en agudos se ve más alto. Estimo 2–3 dB, a verificar.
- `pc/metricas.py:18` y `:163`: `P_FS = 0.5` toma la senoidal a fondo de escala como 0 dBFS, y "Todo lo que hay en la banda" es la potencia integrada en la banda elegida.
- `pc/visor_adc.py:59-63`: las bandas son "400 Hz – 20 kHz (datasheet)", "20 Hz – 20 kHz" y "**20 Hz – 48 kHz (todo)**".
- `pc/visor_adc.py:1132-1135`: el espectro en vivo usa `rec.ultimas(1 s)` **sin excluir tramas perdidas**. El panel Medición sí las excluye, con `Grabadora` y bloques marcados como dañados.

**Números, con las funciones reales de la app** (Script B, ruido blanco de σ = 10⁻⁵ del fondo de escala, ≈ 84 cuentas RMS):

| Dónde se lee | Valor |
|---|---|
| Registro del visor (RMS por bloque) | **−100,0 dBFS** |
| Piso del gráfico del visor (por bin) | **≈ −137,4 dB** |
| `metricas`, 20 Hz–48 kHz | **−97,1 dBFS** |
| `metricas`, 20 Hz–20 kHz | **−100,9 dBFS** |
| `metricas`, 20 Hz–20 kHz con ponderación A | **−102,9 dBFS** |

**Razonamiento y consecuencias**
- Solo `metricas` en **20 Hz–20 kHz con ponderación A** se puede comparar con el rango dinámico de la hoja de datos del ADC, **del orden de 99 dB(A), a verificar en el PDF y para fs de 96 kHz**. Además hay que medir con el DAC apagado o, mejor, con la entrada del ADC en cortocircuito.
- La banda "todo" (20 Hz–48 kHz) incluye el ruido que el ΔΣ empuja por encima de 20 kHz. La banda de paso del filtro de decimación del PCM3060 llega a ≈ 0,454·fs ≈ 44 kHz (**a verificar**). En el codec real esa banda va a dar bastante peor que lo que muestra el caso de ruido blanco de la tabla.
- En el lazo DAC→ADC, con `LOFF`/`ROFF` el DAC manda ceros (`usbd_cdc_if.c:412,418` pone `salida_activa = 0`, y `main.c:431` saca 0). Lo que se mide es el ruido del DAC **más** el del ADC.
- El espectro en vivo con tramas perdidas tiene discontinuidades que, con un tono presente, desparraman energía y levantan el piso.

---

## 5. Firmware de `integracion-codec-usb`: el dato corrido 1 bit sin corregir

**Evidencia.** `git diff origin/integracion-codec-usb origin/mediciones-metricas -- Blackpill_codec_USB_FD/Core/Src/stream.c`. La rama vieja hace `(int32_t)((hi<<16)|lo) >> 8`, sin `<< 1`, y tiene `RING_SIZE` de 16 kB (el README observó ~10 % de tramas perdidas).

**Razonamiento.** Con el corrimiento, un negativo chico (por ejemplo −5) llega como `0x7FFFFD`, casi +fondo de escala. El ruido salta entre ≈0 y ≈+1,0. El Script C da **−6,0 dBFS** con el firmware viejo y −100,0 con el nuevo, para un ruido real de −100 dBFS.

**Cómo verificar:** preguntar o confirmar qué firmware está grabado. Las mediciones viejas se reanalizan con `python pc/analizar_medicion.py archivo.npz --corrido`.

---

## 6. Menores

- **PLLI2S.** `stm32f4xx_hal_msp.c:169-171` usa PLLI2SM = 16, con 1,5625 MHz de entrada al VCO. El manual RM0383 recomienda 2 MHz para limitar el jitter del PLL (**a verificar el texto**). Con **PLLI2SM = 13, PLLI2SN = 156, PLLI2SR = 2** queda 1,923 MHz de entrada, VCO de 300 MHz e I2SCLK de 150 MHz: la misma fs.
- **fs.** 97 656,25 Hz contra el máximo de 96 kHz del ADC del PCM3060 (**a verificar**). El `.ioc` marca `ErrorAudioFreq=1.72 %`. Seguramente anda, pero está fuera de especificación.
- El comentario de `main.c:54` dice "I2SCLK 100MHz / 1024", pero el I2SCLK real es de 150 MHz (150 MHz / 1536). El valor de fs es el mismo, así que es solo el comentario.

---

## 7. Lo que revisé y está bien (para no repetirlo, o para repetirlo si se quiere)

- **HAL full duplex.** El ext se habilita antes que el maestro (`stm32f4xx_hal_i2s_ex.c:661`). Los callbacks salen **solo del DMA de RX**: los de TX quedan en `NULL` (`:606`), así que `fill()` y `stream_push_audio()` no se llaman dos veces por mitad.
- **Prioridades.** DMA1 Stream3/4 y USB tienen las dos prioridad 0, así que no se interrumpen entre sí. `stream_kick()` enmascara con PRIMASK.
- **Copia de cada mitad.** Se procesa en el callback mientras el DMA llena la otra mitad: 256 frames a 96 MHz entran sobrados en 2,62 ms.
- **Decodificación en la PC** (`visor_adc.py:147-216`): sincronismo, validación del encabezado, extensión de signo de 24 bits (`(v ^ 0x800000) - 0x800000`), conteo de `seq` y bloques con pérdidas marcados y excluidos.
- **`metricas.py`:**
  - Welch escalado en potencia (la suma de P es el valor cuadrático medio, `:42`).
  - Ponderación A según IEC 61672, normalizada a 0 dB en 1 kHz.
  - Ventana Blackman-Harris de 7 términos.
  - Los segmentos no cruzan bloques.
- **`analizar_medicion.py:corregir_corrido`:** toma el signo del bit 22 y multiplica por 2. Es correcto para el corrimiento descrito.

## 8. Lo que no se pudo verificar

- No se compiló, no hubo hardware y no había mediciones.
- Valores de hojas de datos citados de memoria, todos a chequear:
  - F411: fmax y tr/tf de los GPIO según `OSPEEDR`.
  - PCM3060: rango dinámico del ADC, t(BCK→DOUT) en modo esclavo, fs máxima y banda de paso del filtro de decimación.
- La diferencia entre el espurio de −78 dBc del README y los −81,4 dBc de la simulación.
- El tamaño real de los acoplamientos del punto 3.

## 9. Plan de verificación en la placa (en este orden)

1. **Piso del ADC solo.** DAC apagado (`LOFF ROFF`) y entrada del ADC **en cortocircuito**. Tiempo fijo de 5 s, con 1 s de descarte. "Calcular métricas" en 20 Hz–20 kHz con A. Mirar "Todo lo que hay en la banda".
   - **≈ −95 a −99 dBFS:** el ADC está bien. Pasar al paso 3.
   - **Peor:** paso 2.
2. **Si el paso 1 da mal**, mirar el espectro:
   - **Líneas** en múltiplos de 5 Hz, 381,47 Hz o 1 kHz → punto 3.
   - **Piso parejo y alto** → punto 2 (velocidad de los GPIO, osciloscopio).
   - Valores absurdos (≈ −6 dBFS) → punto 5.
3. **Con señal.** 1 kHz TABLA (idx 4) contra Seno (idx 0) a 1000 Hz, misma amplitud. Si el seno da mucho peor → punto 1.
4. **Si `metricas` da bien pero "se ve feo"** en el registro o en el gráfico → punto 4.

---

## Apéndice: scripts (Python 3 + numpy; corren sin la placa)

### Script A: error de truncación del seno por acumulador (`waveforms.c`, `WAVE_SINE`)

```python
import numpy as np
FS = 97656.25
N = 1 << 20
tab = np.round(8388607 * np.sin(2*np.pi*np.arange(8192)/8192))       # igual que sine_table.h

def analizar(f):
    ftw = int(f * 4294967296.0 / FS)                                 # igual que main.c
    fr = ftw * FS / 2**32
    acc = (np.arange(1, N+1, dtype=np.uint64) * np.uint64(ftw)) & np.uint64(0xFFFFFFFF)
    x = tab[(acc >> np.uint64(19)).astype(np.int64)] / 2**23         # 13 bits altos, sin interpolar
    n = np.arange(1, N+1)
    A = np.c_[np.sin(2*np.pi*fr*n/FS), np.cos(2*np.pi*fr*n/FS), np.ones(N)]
    c, *_ = np.linalg.lstsq(A, x, rcond=None)                        # seno ideal ajustado
    e = x - A @ c
    ps = (c[0]**2 + c[1]**2) / 2
    E = np.abs(np.fft.rfft(e))**2
    fq = np.fft.rfftfreq(N, 1/FS)
    m = (fq >= 20) & (fq <= 20000)
    tot = 10*np.log10(np.mean(e**2)/ps)
    banda = 10*np.log10(E[m].sum()/E.sum()*np.mean(e**2)/ps)
    print(f"{f:7.1f} Hz: error total {tot:6.1f} dBc | en 20 Hz-20 kHz {banda:6.1f} dBc")

for f in (1000.0, 997.0, 5000.0):
    analizar(f)
# Resultado obtenido: 1000 Hz -> -73.1 / -74.9 dBc ; 997 Hz -> -73.1 / -81.5 dBc
```

### Script B: las tres convenciones de dB, usando las funciones REALES de la app

Uso: `python3 script_b.py Blackpill_codec_USB_FD/pc`. `visor_adc.py` importa tkinter, serial y matplotlib, así que se extraen solo sus funciones puras con `ast`. `metricas` se importa tal cual.

```python
import ast, sys, os
import numpy as np
pc = sys.argv[1]
sys.path.insert(0, pc)
import metricas

src = open(os.path.join(pc, "visor_adc.py"), encoding="utf-8").read()
mod = ast.parse(src)
keep = [n for n in mod.body if (isinstance(n, ast.FunctionDef) and n.name in ("espectro_promedio", "estadisticas_bloque"))
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "N_FFT" for t in n.targets))]
ns = {"np": np}
exec(compile(ast.Module(body=keep, type_ignores=[]), "visor_adc.py", "exec"), ns)

rng = np.random.default_rng(0)
sigma = 1e-5
bloques = [np.c_[rng.normal(0, sigma, 97656), rng.normal(0, sigma, 97656)] for _ in range(5)]
rms_db, _, _ = ns["estadisticas_bloque"](bloques[0][:, 0])
pot, _ = ns["espectro_promedio"](bloques[0][:, 0])
f = np.fft.rfftfreq(ns["N_FFT"], 1/metricas.FS)[1:]
m = (f > 1000) & (f < 20000)
print(f"Registro del visor (RMS por bloque): {rms_db:.1f} dBFS")
print(f"Piso del grafico del visor (media por bin): {10*np.log10(np.mean(pot[m])):.1f} dB")
for banda in ((20.0, 48000.0), (20.0, 20000.0)):
    res, _ = metricas.medir(bloques, banda, False)
    print(f"metricas {banda}: {res['L']['total_banda_dbfs']:.1f} dBFS")
res, _ = metricas.medir(bloques, (20.0, 20000.0), True)
print(f"metricas 20-20k con A: {res['L']['total_banda_dbfs']:.1f} dBFS")
# Resultado obtenido: -100.0 | -137.4 | -97.1 | -100.9 | -102.9
```

### Script C: el corrimiento de 1 bit con el `stream.c` viejo y el nuevo

```python
import numpy as np
rng = np.random.default_rng(1)
x = np.round(rng.normal(0, 84, 100000)).astype(np.int64)            # ruido real, ~84 cuentas RMS
word = (((x & 0xFFFFFF) << 8) >> 1) & 0xFFFFFF00                     # se recibe 1 bit antes; se pierde el LSB
s32 = lambda w: ((w ^ 0x80000000) - 0x80000000)
viejo = s32(word) >> 8                                               # integracion-codec-usb
nuevo = s32((word << 1) & 0xFFFFFFFF) >> 8                           # mediciones-metricas
db = lambda v: 20*np.log10(np.std(v / 2**23))
print(f"real {db(x):.1f} | viejo {db(viejo):.1f} | nuevo {db(nuevo):.1f} dBFS")
# Resultado obtenido: real -100.0 | viejo -6.0 | nuevo -100.0
```

---

## Apéndice: proyectos viejos de la rama `main` (no aplica a esta rama)

En `Envio_codec_UART` el STM32F401 era **esclavo** del I2S y el codec el maestro. Ahí el HAL habilita el I2S sin esperar a que WS esté en el nivel correcto, y la errata del STM32F4 ("In I2S slave mode, WS level must be set by the external master when enabling the I2S") puede desincronizarlo en ~50 % de los arranques. Además ese firmware manda bloques sueltos de 256 frames por UART a 115200, que no son contiguos en el tiempo. **Nada de esto vale para `Blackpill_codec_USB_FD`**, donde el STM32 es el maestro y el envío es continuo por USB. Se deja anotado por si alguien vuelve a medir con aquellos proyectos.
