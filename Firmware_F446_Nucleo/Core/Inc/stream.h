#ifndef STREAM_H
#define STREAM_H

#include <stdint.h>

/*
 * Envio del ADC del codec a la PC por el COM virtual (USB CDC).
 *
 * Formato de cada trama (STM32 -> PC), todo little-endian:
 *
 *   byte 0     0xAA
 *   byte 1     0x55
 *   byte 2     tipo      0x01 = audio estereo, 0x02 = texto (respuesta a un comando),
 *                        0x03 = audio solo L, 0x04 = audio solo R (la mitad de bytes, para PC con USB lento)
 *   byte 3     seq       contador de tramas (uint8, da la vuelta) -> detecta perdidas
 *   byte 4..5  n         audio: cantidad de frames / texto: cantidad de caracteres
 *   byte 6..   payload   audio estereo: n x [L0 L1 L2 R0 R1 R2]  (24 bits con signo, LSB primero)
 *                        audio de un canal: n x [X0 X1 X2]
 *                        texto: n caracteres ASCII
 */

#define STREAM_SYNC0        0xAA
#define STREAM_SYNC1        0x55
#define STREAM_TYPE_AUDIO   0x01
#define STREAM_TYPE_TEXT    0x02
#define STREAM_TYPE_AUDIO_L 0x03
#define STREAM_TYPE_AUDIO_R 0x04
#define STREAM_HDR_SIZE     6

#define STREAM_L   0x01                    // valores de stream_canales
#define STREAM_R   0x02
#define STREAM_LR  0x03

extern volatile uint8_t  stream_on;        // 1 = mandar audio a la PC
extern volatile uint8_t  stream_canales;   // STREAM_LR (STREAM:1), STREAM_L (STREAM:L) o STREAM_R (STREAM:R)
extern volatile uint32_t stream_dropped;   // tramas descartadas por no tener lugar en el ring

// empaqueta 'frames' frames estereo I2S (4 halfwords c/u: Lhi Llo Rhi Rlo) y los encola
void stream_push_audio(const uint16_t *i2s_frames, uint16_t frames);

// encola una respuesta de texto (\r\n no hace falta)
void stream_push_text(const char *txt);

// arranca un envio USB si hay datos pendientes y el USB esta libre
void stream_kick(void);

// lo llama el callback de fin de transmision del CDC
void stream_tx_done(void);

// alineacion del dato del ADC (ver stream.c): pone en cero los contadores / responde "ALIN:corridos,directos"
// con los bloques de audio que se mandaron corregidos (<<1) y sin corregir desde el ultimo reset
void stream_alin_reset(void);
void stream_alin_informar(void);

#endif
