# Blackpill + PCM3060: ADC y DAC por COM virtual (USB CDC)

Combina `Proyecto_zero_envio_por_UART` / `Envio_codec_UART` (captura del ADC) con
`AGSE-Proyecto-Final` (generador por DAC + comandos por USB). Las carpetas originales
no se tocaron: esta es una copia de `Blackpill_codec_V2` con los cambios de abajo.

## Qué hace

- **DAC (salida):** igual que AGSE (seno / cuadrada / triangular / chirp, frecuencia, amplitud, ON/OFF).
- **ADC (entrada):** el I2S2 pasó a **full duplex** (STM32 maestro, 24 bits, 97656.25 Hz).
  El DAC sale por `audio_buf` y el ADC entra por `rx_buf`, los dos por DMA circular.
- **Hacia la PC:** el audio del ADC se manda binario por el COM virtual (~586 kB/s).
  Ya no hay UART.
- **Desde la PC:** los mismos comandos de texto de AGSE (terminados en `\n`) más los nuevos.

## Comandos nuevos (PC -> STM32)

| Comando | Efecto |
|---|---|
| `STREAM:1` / `STREAM:0` | empieza / termina el envío del ADC |
| `ADC:1` / `ADC:0` | enciende / apaga el ADC del codec (reg 64) |
| `DAC:1` / `DAC:0` | enciende / apaga el DAC del codec (reg 64) |
| `I2CW:reg,valor` | escribe un registro del PCM3060 (acepta `0x..`) |
| `I2CR:reg` | lee un registro; la respuesta llega como trama de texto |
| `PING` | responde `PONG` |

## Formato de trama (STM32 -> PC), little-endian

```
0xAA 0x55 | tipo | seq | n (2 B) | payload
tipo 0x01: n frames estéreo, cada uno [L0 L1 L2 R0 R1 R2]  (24 bits con signo)
tipo 0x02: n caracteres ASCII (respuestas de texto)
```

`seq` cuenta tramas (da la vuelta a 255): si salta, la PC sabe cuántas se perdieron.
Se quitó el eco de comandos que tenía AGSE, porque ensuciaría el flujo binario.

## Cambios respecto a AGSE

- `Core/Src/main.c`: I2S full duplex, callbacks `HAL_I2SEx_TxRx*Cplt`, registro 64 combinado
  (ADC+DAC), reg 72 = ADC esclavo I2S 24 bit, cola de accesos I2C pedidos por USB.
- `Core/Src/stream.c/.h` (nuevo): ring de 16 kB + envío encadenado por el callback de fin de USB.
- `Core/Src/stm32f4xx_hal_msp.c`, `stm32f4xx_it.c`: pin PB14 (I2S2ext_SD), DMA1 Stream3 (RX) y full duplex, escritos en las zonas generadas (igual a lo que produce CubeMX; ver "Configurar en CubeMX").
- `USB_DEVICE/App/usbd_cdc_if.c`: nuevos comandos, sin eco, hook `stream_tx_done()`.
- **Teclado y OLED se mantienen** como en AGSE. La entrada del ADC usa PB14 (I2S2ext_SD, el único pin posible en el F411 de 48 pines, no existe PC2), así que **la columna 4 del teclado (teclas A B C D) pasó de PB14 a PA4**: hay que recablear ese hilo.
- `pc/comandos.py`: la app de AGSE + panel "Codec PCM3060" y visor del ADC.
- `pc/visor_adc.py` (nuevo): hilo receptor, decodificación y gráfico de tiempo + espectro (ver "Visor del ADC").

## Conexiones que asume (las de AGSE + la entrada del ADC)

| Señal | Pin |
|---|---|
| I2S2_MCK | PA3 |
| I2S2_CK (BCK) | PB10 |
| I2S2_WS (LRCK) | PB12 |
| I2S2_SD (DAC DIN) | PB15 |
| **I2S2ext_SD (ADC DOUT)** | **PB14** |
| Teclado columna 4 | **PA4** (antes PB14) |
| I2C1 | PB6 / PB7 |
| USB | PA11 / PA12 |

El codec queda **esclavo** del STM32 para ADC y DAC (en `Envio_codec_UART` el ADC era maestro
y el reloj salía por MCO1/PA8; acá el reloj es el MCLK del I2S, como en AGSE).

## Cómo usarlo

1. Abrir la carpeta como proyecto en STM32CubeIDE, compilar y cargar (chip **STM32F411CEUx**, como AGSE).
2. En la PC: `pip install pyserial numpy matplotlib` y `python pc/comandos.py`.
3. Elegir el COM del STM32, **Conectar**, y en "Codec PCM3060" → **Ver señal del ADC** → **Iniciar captura**.

## Configurar en CubeMX (para que el .ioc coincida con el código y se pueda regenerar)

El `.ioc` de esta carpeta sigue siendo el de AGSE. Hay que hacer estos cambios en el MX:

1. **PB14:** quitarle la función actual (hoy es entrada GPIO de la columna 4 del teclado).
2. **PA4:** `GPIO_Input`, Pull-up (nueva columna 4 del teclado).
3. **I2S2:** en `Connectivity > I2S2`, modo **Full-Duplex Master** (queda en Philips, 24 bits, MCLK output enabled, 96 kHz, clock source PLL, como está). Al activarlo aparece `I2S2_ext_SD`: que quede en **PB14**.
4. **DMA Settings de I2S2:** dejar `SPI2_TX` (DMA1 Stream4, circular, half word) y agregar **`I2S2_EXT_RX`** (DMA1 Stream3, Channel 3, Peripheral-to-Memory, **Circular**, data width **Half Word** en periférico y memoria, memory increment ON).
5. **NVIC:** habilitar `DMA1 stream3 global interrupt` (y dejar la de stream4).
6. Regenerar. Las partes de aplicación (comandos, stream, cola I2C, keypad, OLED) están en `USER CODE` y no se pisan.

## Cómo funciona el envío STM32 -> PC

**Camino de los datos** (`main.c`, `stream.c`, `usbd_cdc_if.c`):

1. El I2S2 full duplex (97 656,25 Hz, 24 bits) llena `rx_buf` por DMA circular (2048 halfwords). Cada muestra
   son 2 halfwords, así que un frame estéreo son 4.
2. Cada 256 frames (2,62 ms) el DMA dispara `HAL_I2SEx_TxRxHalfCpltCallback` / `HAL_I2SEx_TxRxCpltCallback`
   (una por mitad del buffer). Cada callback rellena la mitad libre de `audio_buf` (DAC) con `fill()` y llama a
   `stream_push_audio()`.
3. `stream_push_audio()` reempaqueta a 3 bytes por canal y escribe encabezado + payload en un ring de 16 kB.
4. `stream_kick()` arranca `CDC_Transmit_FS()` con hasta 4096 bytes contiguos del ring.
5. Al terminar el USB se ejecuta `CDC_TransmitCplt_FS` -> `stream_tx_done()`, que avanza el `tail` y vuelve a
   llamar a `stream_kick()`: los bloques salen encadenados sin pasar por el lazo principal.
6. Si el ring no tiene lugar para una trama completa, se descarta y se hace `seq++` (así la PC ve el salto).
   El contador `stream_dropped` cuenta esos descartes, pero hoy no se manda a la PC.

Los callbacks de DMA y la interrupción USB tienen ambos prioridad 0, así que no se interrumpen entre sí;
`stream_kick()` además enmascara interrupciones (PRIMASK) mientras toca el ring.

### Por qué este diseño

- **USB CDC y no UART:** el flujo es ~586 kB/s (97 656 x 6 B). Una UART a 115 200 baudios da ~11 kB/s y ni a
  3 Mbaudios alcanza.
- **Binario y no texto:** el texto ocuparía varias veces más bytes.
- **3 bytes por muestra:** es el tamaño real de 24 bits, sin rellenar a 4.
- **`0xAA 0x55`:** permite resincronizar si se pierde un trozo del flujo. **`seq`:** permite contar tramas
  perdidas. **Sin checksum:** el USB ya lleva CRC y reintenta.
- **Texto en el mismo flujo (tipo 0x02):** las respuestas (`PONG`, `I2CR`) comparten el ring y el COM con el
  audio, por eso se quitó el eco de comandos.

### El puerto COM

El STM32 se enumera como CDC-ACM y Windows lo muestra como COM virtual (`usbser.sys`). El baudrate no se usa
(`CDC_Control_FS` está vacío). Los endpoints bulk son de 64 B; el límite teórico de USB Full Speed es ~1,2 MB/s,
así que este flujo usa cerca de la mitad. El USB FS del F411 corre sin DMA (`dma_enable = DISABLE`): la
interrupción USB copia los datos al FIFO con la CPU.

### Comandos (PC -> STM32): sí es bidireccional

Los endpoints IN y OUT son independientes, se puede mandar mientras se hace streaming. `CDC_Receive_FS` (en la
interrupción USB) acumula bytes en un buffer de 128 hasta ver `\n` y llama a `parse_command()`, que compara con
`strncmp` y escribe variables globales (`frecuencia`, `amplitud`, `waveform`, `stream_on`...). El lazo principal
las aplica: recalcula la FTW y escribe el volumen al codec por I2C solo cuando cambia. Los accesos I2C pasan por
una cola de 8 posiciones porque no se puede bloquear dentro de la interrupción.

Limitación: no hay confirmación ni aviso de error para los comandos; solo responden `PING` e `I2CR`.

## Pérdida de tramas (~10 % observado)

Una trama "perdida" solo puede ser un descarte por **ring lleno** en el STM32: el USB no pierde datos (CRC y
reintento). O sea, el host no vació el ring a 586 kB/s. El ring de 16 kB aguanta apenas **28 ms** de audio.

**Causa más probable: la GUI de la PC.** Con el visor anterior (`tight_layout`, FFT de 4096, `draw_idle` cada
60 ms) cada redibujo tardaba 300-700 ms. Midiendo con un hilo de prueba, el hilo lector se frenaba hasta 67 ms
durante un redibujo, más del doble de lo que aguanta el ring. **No está confirmado con el hardware.**

Otras causas secundarias:
- pyserial pide al driver de Windows un buffer de recepción de solo 4 kB (~7 ms de audio).
- `np.roll` copiaba 256 kB en cada trama.
- Otros dispositivos en el mismo bus USB le quitan ancho de banda al flujo.

**Cómo confirmarlo:** mandar `stream_dropped` a la PC (por ejemplo al hacer `STREAM:0`). Si coincide con las
perdidas contadas por `seq`, es el ring lleno. Con el visor nuevo la pérdida debería bajar de ~10 % a ~0.

**Mejora recomendada (NO aplicada):** `RING_SIZE` de 16384 a 65536 en `stream.c` (112 ms de margen; debería
caber en los 128 kB de RAM del F411, hay que verificar el mapa de memoria al compilar).

## Visor del ADC (`pc/visor_adc.py`)

- **Ventana de tiempo variable:** combo editable de 0,1 a 1000 ms (sugeridos 0,25 ... 1000). Para ver 20 kHz usar
  0,25-0,5 ms; para 10 Hz, 200-500 ms. En ventanas largas se dibuja el mínimo y el máximo de cada tramo
  (`decimar_minmax`, 600 columnas) para no perder picos. A 97,6 kHz un tono de 20 kHz tiene ~5 muestras por ciclo,
  así que se ve poligonal (no se interpola).
- **Espectro promedio:** Welch con segmentos de 32 768 muestras (~3 Hz/bin), 50 % de solape, ventana Hann,
  promediando la **potencia** del último segundo (4 segmentos). Se refresca cada 1 s. Eje log de 10 Hz a 20 kHz;
  a cada segmento se le saca la continua para no ensuciar los bins bajos. Para dibujar se toma el máximo de cada
  grupo de bins (picos preservados; el piso de ruido en alta frecuencia se ve algo más alto de lo real).
- **Extras:** Trigger por cruce ascendente (la onda no "corre"), Auto Y (escala 1-2-5) y el estado muestra el
  porcentaje de pérdida.
- **Para no bloquear al hilo lector:** dos figuras separadas, las dos refrescadas por blitting (solo se
  redibujan las líneas: 4-43 ms por cuadro el tiempo, ~10-14 ms el espectro). El título del espectro es una
  etiqueta de Tk porque dibujarlo dentro de matplotlib costaba 13 ms por cuadro. El ring del receptor es circular
  de verdad (131 072 muestras = 1,34 s, sin `np.roll`) y se pide al driver un buffer de recepción de 1 MB.

**Probado solo con tramas simuladas** (no con el hardware): tono de 15 Hz a -14,0 dBFS (esperado -14,0), 20 kHz a
-10,5 (esperado -10,46), 1 kHz 1,2 dB bajo (pérdida de la ventana Hann entre bins; para amplitudes absolutas
conviene flat-top). La pausa máxima del hilo lector en 5 s de uso simulado fue de 13-27 ms en tres corridas y de
145 ms en una; mejora lo anterior (67 ms) pero no elimina el riesgo, por eso se recomienda el ring de 64 kB.

## Mediciones: DAC + ADC con tiempos (`pc/visor_adc.py`, panel "Medición")

Implementado **en la PC, sin cambios de firmware**. Todo se mide en **bloques de 1 s** (97 656 muestras) y se
cuenta por muestras, no por reloj de la PC, así el largo de cada bloque es exacto aunque Windows se demore.

| Modo | Qué hace |
|---|---|
| **Tiempo fijo** (ej. 3 s) | Descarta el primer segundo (configurable) y mide `N` bloques completos de 1 s. Calcula el espectro y el RMS de **cada bloque** (para ver el ruido) y el promedio de todos. Al terminar muestra la señal completa. |
| **Continuo** | Mide sin parar hasta que apretás «Detener medición». Promedia y muestra **cada 5 s** los últimos 5 bloques de 1 s. No guarda muestras crudas (memoria acotada). No descarta el inicio. |

**DAC:** «Disparar al iniciar» apaga los canales elegidos (`LOFF`/`ROFF`), espera 0,3 s, empieza a grabar
(`STREAM:1`) y recién entonces los enciende (`LON`/`RON`), así el transitorio queda dentro del segundo que se
descarta. «No tocar el DAC» mide con lo que esté sonando. Hay botones manuales DAC ON/OFF y la opción de apagarlo al
terminar. La forma de onda, frecuencia y amplitud se eligen en la ventana principal.

**Qué se muestra:** línea gruesa = promedio (en potencia) de los bloques válidos; líneas finas = bloques
individuales (mientras se mide, solo los últimos 3; al terminar, todos). Un registro de texto lista por bloque el
RMS sin continua (dBFS), la continua y el pico de cada canal, y al final de la medición fija el RMS promedio y su
dispersión entre bloques.

**Tramas perdidas:** si un bloque contiene una trama perdida (salto de `seq`) queda marcado como dañado, se dibuja
en gris y **se excluye del promedio**. Las pérdidas durante el segundo descartado no cuentan.

**Verificado con un STM32 simulado** (tramas binarias reales, 3 s fijos + 1 s de descarte): bloques de exactamente
97 656 muestras; ruido de -80 dBFS medido en -80,0 ±0,03 dB; tono de 0,5 en -9,03 dBFS; con descarte el transitorio
desaparece (dispersión < 0,05 dB entre bloques) y sin descarte el primer bloque sale 0,5 dB más alto; una trama
perdida a propósito marca solo su bloque; el modo continuo actualiza a los 5 y a los 10 bloques; el orden de
comandos al STM32 es `LOFF ROFF STREAM:1 LON RON ... STREAM:0 LOFF ROFF`. **No se probó con el hardware.**

**Límite importante:** durante una medición hay un pico de unos 10-15 ms de GUI por bloque (medido: la pausa máxima
del hilo lector pasó de 29-35 ms a 15-17 ms). El ring del STM32 aguanta ~28 ms, o sea que el margen existe
pero no es grande. Si en el hardware aparecen bloques dañados seguidos, subir `RING_SIZE` a 65536 en `stream.c`
(112 ms de margen) es el arreglo; no se aplicó porque no se pudo probar en la placa.

**Opción B, no implementada:** temporizar en el firmware con un comando `CAP:t_descarte_ms,t_captura_ms` y un
contador en el callback del DMA (resolución de 2,62 ms); es más preciso porque usa el reloj del I2S. No hace falta
para lo de arriba, porque el conteo por muestras ya es exacto.

No se puede capturar en el STM32 y mandar después: 3 s son 1,7 MB y la RAM es de 128 kB. Hay que transmitir en vivo.

## Documentación interactiva

`docs/viaje_de_datos.html` (un solo archivo, sin dependencias) explica el envío STM32 -> PC con simulaciones: mapa
del recorrido, ring buffer con host que se congela, formato de trama byte por byte, USB CDC y puerto COM,
comandos PC -> STM32 e interrupciones. Los parámetros marcados como "supuestos" no son mediciones.

## Ojo

- No se pudo compilar ni probar en hardware desde acá (no hay toolchain ARM instalada).
  Se verificó la sintaxis con gcc y el parser/visor de la PC con datos simulados.
- Hasta que hagas los pasos de arriba en el MX, una regeneración desde el `.ioc` viejo volvería a dejar el I2S en half duplex.
