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
- `pc/visor_adc.py` (nuevo): hilo receptor, decodificación y gráfico de tiempo + espectro.

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

## Ojo

- No se pudo compilar ni probar en hardware desde acá (no hay toolchain ARM instalada).
  Se verificó la sintaxis con gcc y el parser/visor de la PC con datos simulados.
- Hasta que hagas los pasos de arriba en el MX, una regeneración desde el `.ioc` viejo volvería a dejar el I2S en half duplex.
