# Firmware F446 — NUCLEO-F446RE + PCM3060

Firmware del generador de señales y la adquisición del AGSE para una **NUCLEO-F446RE** con el codec
**PCM3060** armado en protoboard. Es el mismo programa que el de la Black Pill (`Firmware_PCB`), portado
al STM32F446:

- generador DDS de dos canales por el DAC del codec;
- captura del ADC del codec y envío a la PC por USB (puerto COM virtual);
- pantalla OLED, teclado 4x4 y salidas de control J7;
- mismos comandos y mismo formato de tramas que la Black Pill.

El código es el de la placa con el STM32F446RC soldado. La única diferencia es el reloj: la Nucleo no
tiene cristal y recibe 8 MHz del ST-LINK, por eso el HSE está en `RCC_HSE_BYPASS` (`Core/Src/main.c`).
En la placa con cristal de 8 MHz va `RCC_HSE_ON`.

## Características

| | Black Pill (F411) | Esta versión (F446) |
|---|---|---|
| I2S | I2S2 full duplex (I2S2 + I2S2ext) | **I2S1 maestro TX** (DAC) + **I2S2 esclavo RX** (ADC) |
| DMA | DMA1 Stream4 (TX) + Stream3 (RX) | DMA2 Stream3 ch3 (SPI1_TX) + DMA1 Stream3 ch0 (SPI2_RX) |
| Reloj externo | cristal de 25 MHz | **8 MHz** (en la Nucleo, del ST-LINK) |
| Núcleo | 96 MHz | **168 MHz** (PLL: M 8, N 336, P 2; Q 7 = 48 MHz para el USB) |
| Reloj del I2S | PLLI2S 100 MHz | PLLI2S **172 MHz** (M 8, N 344, R 2) |
| fs | 97 656,25 Hz | **95 982,14 Hz** = 172 MHz / (256 × 7) |
| MCK / BCK | 25 MHz / 6,25 MHz | 24,57 MHz (256 fs) / 6,14 MHz (64 fs) |
| I2C (codec + OLED) | I2C1, PB6 / PB7 | **I2C3, PA8 (SCL) / PC9 (SDA)** |
| Audio hacia la PC | ~586 kB/s | ~576 kB/s |

El I2S del F446 no tiene I2Sext (es simplex), por eso se usan dos periféricos: I2S1 genera los relojes
y manda el audio al DAC; I2S2, como esclavo, escucha esos mismos relojes y recibe el ADC. Primero se
habilita el esclavo y después el maestro; si igual arrancara corrido un bit, `stream.c` lo detecta y lo
corrige solo (comando `ALIN`).

## Materiales

- NUCLEO-F446RE.
- PCM3060 en su adaptador.
- Pantalla OLED SSD1306 por I2C y teclado matricial 4x4.
- Un cable USB cortado (o un adaptador de USB) para los datos.
- Resistencias:
  - 5 de 33 Ω;
  - 2 de 470 Ω para el lazo DAC → ADC, y 2 más de 470 Ω si se usa J7;
  - 2 de 4,7 kΩ y 1 de 10 kΩ;
  - 2 de 100 kΩ;
  - 1 de 10 Ω, 1 de 4,7 Ω y 1 de 2,2 Ω.
- Capacitores:
  - 2 de 470 µF;
  - 3 de 10 µF y 3 de 100 nF (desacoples del codec);
  - 2 de 4,7 µF (entradas del ADC).

## Antes de cablear

- **Reloj:** los 8 MHz del ST-LINK entran por PH0. No conectar nada a PH0 / PH1 (CN7-29 y CN7-31).
- **PA5 (BCK)** también maneja el LED verde LD2 (510 Ω, puente SB21). Si BCK se ve deformado o el
  audio sale con errores, sacar SB21.
- **PA13 / PA14** son el SWD del ST-LINK y **PA2 / PA3** su puerto serie: no se usan para otra cosa.
- Los jumpers de CN2 (ST-LINK) quedan puestos.

## Conexiones

Pines de la Nucleo según su esquemático (MB1136):

- **CN7** es la tira doble de la izquierda y **CN10** la de la derecha, mirando la placa con el USB del
  ST-LINK arriba.
- Los pines impares son la fila de afuera y los pares la de adentro.
- Entre paréntesis va el nombre del conector Arduino cuando lo tiene.

Los pines del codec son los números de patita del PCM3060 (TSSOP-28).

Las resistencias de 33 Ω van en serie, lo más cerca posible del pin de la Nucleo. Los cables de MCK y
BCK, lo más cortos posible.

### 1. I2S (audio)

Los tres relojes van a los **dos** puertos del codec.

| Señal | Pin | Nucleo | | Codec |
|---|---|---|---|---|
| MCK | PC4 | CN10-34 | 33 Ω → | SCKI1 (6) y SCKI2 (9) |
| BCK | PA5 | CN10-11 (D13) | 33 Ω → | BCK1 (5) y BCK2 (10) |
| LRCK | PA4 | CN7-32 (A2) | 33 Ω → | LRCK1 (4) y LRCK2 (11) |
| DIN | PA7 | CN10-15 (D11) | 33 Ω → | DIN (12) |

Entradas del I2S2 (esclavo):

| Señal | Pin | Nucleo | | Desde |
|---|---|---|---|---|
| BCK del esclavo | PB13 | CN10-30 | ← 33 Ω | nodo BCK del codec |
| LRCK del esclavo | PB12 | CN10-16 | ← directo | nodo LRCK del codec |
| Datos del ADC | PB15 | CN10-26 | ← directo | DOUT (3) |

PB13 y PB12 se toman **del lado del codec**, después de las resistencias de 33 Ω, no directo de PA5 y PA4.

### 2. I2C3 (codec y OLED)

| Señal | Pin | Nucleo | Va a |
|---|---|---|---|
| SCL | PA8 | CN10-23 (D7) | MC/SCL/FMT (1) del codec y SCL de la OLED |
| SDA | PC9 | CN10-1 | MD/SDA/DEMP (2) del codec y SDA de la OLED |

- Pull-ups de 4,7 kΩ de SCL y de SDA a +3V3, una de cada una para todo el bus.
- El codec responde en la dirección 0x46.
- OLED: GND, VCC a +3V3 (CN7-16), SCL y SDA.

### 3. USB de datos

El USB de la Nucleo es del ST-LINK; el del micro hay que cablearlo:

| Cable USB | Pin | Nucleo |
|---|---|---|
| D+ (verde) | PA12 | CN10-12 |
| D− (blanco) | PA11 | CN10-14 |
| GND (negro) | GND | CN10-9 o CN10-20 |
| VBUS (rojo) | — | sin conectar |

El firmware no mira VBUS (`vbus_sensing` desactivado). Quedan dos cables a la PC: el del ST-LINK, que
alimenta y programa, y este, que lleva los datos.

### 4. Control del codec

| Codec | Conexión |
|---|---|
| MODE (28) | GND (modo I2C) |
| MS/ADR/IFMD (27) | GND (dirección 0x46) |
| RST (15) | 10 kΩ a 5V_A |

### 5. Alimentación del codec

La Nucleo, alimentada por el USB del ST-LINK, da **+5V en CN7-18** y **+3V3 en CN7-16**. GND está en
CN7-8, 19, 20 y 22, y en CN10-9 y 20. Armar un solo punto de masa para el codec y unirlo a la Nucleo
con un cable.

- **VCC (24), 5 V analógico:**
  - +5V → 4,7 Ω → nodo con 470 µF a GND → 2,2 Ω → **5V_A**;
  - 5V_A → VCC (24), con 470 µF, 10 µF y 100 nF a GND pegados al pin.
  - Para una primera prueba alcanza con +5V directo y 10 µF + 100 nF, con más ruido.
- **VDD (7), 3,3 V digital:** +3V3 → 10 Ω → VDD (7), con 10 µF + 100 nF a GND.
- **VCOM (21):** 10 µF + 100 nF a GND; no va a otro lado.
- **Masas del codec:** DGND (8), SGND (16), AGND2 (22) y AGND1 (23) a GND.

### 6. Salidas del DAC

| Codec | Salida |
|---|---|
| VOUTL+ (20) | canal L + |
| VOUTL− (19) | canal L − |
| VOUTR+ (18) | canal R + |
| VOUTR− (17) | canal R − |

Para la salida diferencial se usan + y −; para la salida simple, + contra GND.

### 7. Entradas del ADC

Canal L (el R es igual, con VINR (26) y VOUTR+ (18)):

- VINL (25) ← 4,7 µF ← nodo **ADC_L**, con el + del electrolítico hacia el codec.
- ADC_L → 100 kΩ → GND.
- A ADC_L se conecta **una** de estas tres cosas:
  - **lazo DAC → ADC:** VOUTL+ (20) → 470 Ω → ADC_L;
  - **entrada externa:** la señal a medir, con su masa a GND;
  - **silencio (piso de ruido):** ADC_L a GND.

Para la primera prueba conviene el lazo DAC → ADC en los dos canales.

### 8. Teclado 4x4

| Cable del teclado | Señal | Pin | Nucleo | Modo |
|---|---|---|---|---|
| 1 | FIL1 | PB5 | CN10-29 (D4) | salida |
| 2 | FIL2 | PB4 | CN10-27 (D5) | salida |
| 3 | FIL3 | PB3 | CN10-31 (D3) | salida |
| 4 | FIL4 | PD2 | CN7-4 | salida |
| 5 | COL1 | PC12 | CN7-3 | entrada con pull-up |
| 6 | COL2 | PC11 | CN7-2 | entrada con pull-up |
| 7 | COL3 | PC10 | CN7-1 | entrada con pull-up |
| 8 | COL4 | PA15 | CN7-17 | entrada con pull-up |

PB3, PB4 y PA15 arrancan como JTAG; como se programa por SWD, el firmware los usa como GPIO.

### 9. J7: bypass y atenuador (opcional)

| Señal | Pin | Nucleo | | Va a |
|---|---|---|---|---|
| BYPASS | PC0 | CN7-38 (A5) | 470 Ω → | BYP_L |
| ATEN | PC1 | CN7-36 (A4) | 470 Ω → | BYP_R |

Más GND.

### Resumen por pin de la Nucleo

| CN7 | Uso | CN10 | Uso |
|---|---|---|---|
| 1 PC10 | COL3 | 1 PC9 | SDA |
| 2 PC11 | COL2 | 9 GND | GND |
| 3 PC12 | COL1 | 11 PA5 | BCK (33 Ω) |
| 4 PD2 | FIL4 | 12 PA12 | USB D+ |
| 8 GND | GND | 14 PA11 | USB D− |
| 16 +3V3 | VDD del codec, OLED, pull-ups | 15 PA7 | DIN (33 Ω) |
| 17 PA15 | COL4 | 16 PB12 | LRCK del esclavo |
| 18 +5V | VCC del codec (con filtro) | 20 GND | GND |
| 19, 20, 22 GND | GND | 23 PA8 | SCL |
| 32 PA4 | LRCK (33 Ω) | 26 PB15 | DOUT del ADC |
| 36 PC1 | ATEN (470 Ω) | 27 PB4 | FIL2 |
| 38 PC0 | BYPASS (470 Ω) | 29 PB5 | FIL1 |
| | | 30 PB13 | BCK del esclavo (33 Ω) |
| | | 31 PB3 | FIL3 |
| | | 34 PC4 | MCK (33 Ω) |

## Compilar y cargar

1. STM32CubeIDE: *File > Import > Existing Projects into Workspace* y elegir esta carpeta. Compilar
   (Debug). Sin abrir el IDE:
   `stm32cubeidec.exe -nosplash -application org.eclipse.cdt.managedbuilder.core.headlessbuild -data <workspace> -import <esta carpeta> -build Firmware_F446_Nucleo/Debug`
2. Cargar con *Run* usando el ST-LINK de la Nucleo (su USB). No hace falta cablear SWD.

El proyecto está configurado para el STM32F446RC (256 KB de flash). El programa ocupa unos 199 KB y
entra igual en el F446RE de la Nucleo (512 KB).

No hay `.ioc`: el proyecto está armado sobre el HAL del F4 (V1.28.3). Las funciones `MX_*_Init`,
`HAL_*_MspInit` y las interrupciones están escritas como las generaría CubeMX.

## Primeras pruebas

Conviene seguir este orden, cada paso con el anterior funcionando:

1. Nucleo y USB de datos solos: aparece el puerto COM y responde `PING` con `PONG`.
   - Si no aparece, revisar que D+ y D− no estén cruzados y que el HSE esté en BYPASS.
2. La OLED muestra el menú.
3. `I2CR:64` responde: el codec está en 0x46.
4. Con osciloscopio:
   - MCK en PC4: 24,57 MHz;
   - BCK en PA5: 6,14 MHz;
   - LRCK en PA4: 95,98 kHz.
5. DAC: seno de 1 kHz en VOUTL+ y VOUTR+.
6. ADC: con el lazo DAC → ADC, `STREAM:1` y el visor (`pc/visor_adc.py`). `ALIN` informa si el dato
   llegó corrido.
7. Teclado y J7.

## Comandos (PC → micro)

| Comando | Efecto |
|---|---|
| `STREAM:1` / `STREAM:0` | empieza / termina el envío del ADC |
| `STREAM:L` / `STREAM:R` | envía un solo canal del ADC |
| `ALIN` | responde `ALIN:corridos,directos`: bloques del ADC que llegaron corridos un bit (y se corrigieron) |
| `ADC:1` / `ADC:0`, `DAC:1` / `DAC:0` | enciende / apaga el ADC o el DAC del codec (registro 64) |
| `I2CW:reg,valor` / `I2CR:reg` | escribe / lee un registro del PCM3060 |
| `PING` | responde `PONG` |

Además están los comandos del generador: forma de onda, frecuencia, amplitud y encendido por canal.

**Tramas (micro → PC, little-endian):** `0xAA 0x55 | tipo | seq | n (2 B) | payload`.

| Tipo | Contenido |
|---|---|
| 0x01 | n frames estéreo de 24 bits |
| 0x02 | texto |
| 0x03 | un solo canal (L) |
| 0x04 | un solo canal (R) |

Es el mismo formato que la Black Pill. Lo único que cambia para los programas de la PC es la frecuencia
de muestreo, que pasa a 95 982,14 Hz.

## Formas de onda que dependen de fs

- **Seno de 1 kHz por tabla** (`WAVE:4`): tabla regenerada para esta fs; 1 kHz exacto entra en
  56 períodos = 5375 muestras.
- **Prueba tabla contra acumulador** (`WAVE:6` y `WAVE:7`): con esta fs da **~978,3 Hz**. El espurio de
  truncación del acumulador queda en ~47,0 kHz.
- **Multitono, barrido y las formas por acumulador:** usan `FS` (en `main.c` y `waveforms.c`), ya en
  95 982,14 Hz.

## Herramientas de la PC

- `pc/`: app de comandos (`comandos.py`), visor del ADC (`visor_adc.py`) y métricas (`metricas.py`),
  con `FS = 95982.142857`.
- `Mediciones/`: grabación (`grabar.py`, `grabar_piso.py`), sesión completa (`medir_todo.py` o
  `MEDIR_TODO.bat`) y análisis en Python y MATLAB. Las capturas se guardan en `Mediciones/capturas`.
  - El análisis toma la fs de cada captura.
  - La lista de comandos por medida está en `COMANDOS_MEDICIONES.txt`.

## Archivos que cambian respecto de `Firmware_PCB` (Black Pill)

- `Core/Src/main.c`: relojes (HSE en BYPASS), I2C3, I2S1 + I2S2, DMA, GPIO y callbacks.
- `Core/Src/stm32f4xx_hal_msp.c`: pines, PLLI2S y DMA.
- `Core/Src/stm32f4xx_it.c`: DMA1 Stream3 y DMA2 Stream3.
- `Core/Src/keypad.c`: pines.
- `Core/Src/oled.c`: nombres de las ondas de 978,3 Hz.
- `Core/Src/waveforms.c`: fs.
- `Core/Inc/main.h`: J7.
- `Core/Inc/ssd1306.h` y `ssd1306_conf.h`: I2C3.
- `Core/Inc/stm32f4xx_hal_conf.h`: HSE de 8 MHz.
- `Core/Inc/tabla_1khz.h` y `tabla_fea.h`.
- `Core/Startup/startup_stm32f446xx.s`, `STM32F446RCTX_FLASH.ld` y el encabezado CMSIS del F446.
- `.project` y `.cproject`: chip y nombre del proyecto.

`stream.c`, `stream.h` y todo `USB_DEVICE/` son idénticos a los de la Black Pill.
