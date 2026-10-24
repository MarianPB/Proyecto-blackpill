#include "stream.h"
#include "usbd_cdc_if.h"
#include "usb_device.h"
#include <string.h>
#include <stdio.h>

extern USBD_HandleTypeDef hUsbDeviceFS;

#define RING_SIZE  65536u              // potencia de 2 (~42 tramas de audio de 256 frames, ~112 ms)
#define RING_MASK  (RING_SIZE - 1u)
#define MAX_CHUNK  4096u               // bytes maximos por transferencia USB (con 16384 una PC perdio mas, 10 % contra 4 %)

static uint8_t  ring[RING_SIZE];
static volatile uint32_t head = 0;     // escribe el DMA/USB (ISR)
static volatile uint32_t tail = 0;     // avanza cuando el USB termina de mandar
static volatile uint32_t inflight = 0; // bytes de la transferencia USB en curso
static volatile uint8_t  usb_busy = 0;
static uint8_t seq = 0;

volatile uint8_t  stream_on = 0;
volatile uint8_t  stream_canales = STREAM_LR;
volatile uint32_t stream_dropped = 0;

// Alineacion del dato del ADC. El I2S2ext a veces recibe la palabra corrida un bit a la derecha (el bit 31
// es relleno y el signo cae en el bit 30) y a veces no, segun el armado: el 08/10 y el 20/10 a la manana
// llegaba corrida; el 20/10 a la tarde, con otra PC y otro armado, no (con el <<1 fijo el dato salia x2).
// Corrida, el bit 31 nunca vale 1; bien alineada, en audio la mitad de las muestras son negativas.
// Un bloque con algun negativo prueba que esta alineada; recien despues de ~1 s sin ningun negativo
// se pasa a corrida (asi un tono grave, con bloques enteros positivos, no confunde la deteccion).
#define BLOQUES_PARA_CORRIDA  400u     // 400 bloques de 256 frames = 1,05 s

static uint8_t  corrida = 1;           // arranca como se midio siempre
static uint32_t bloques_sin_negativos = 0;
static volatile uint32_t bloques_corridos = 0;   // desde el ultimo STREAM:1, para el comando ALIN
static volatile uint32_t bloques_directos = 0;

static inline uint32_t ring_free(void)
{
    return RING_SIZE - (head - tail);
}

static inline void ring_put(uint8_t b)
{
    ring[head & RING_MASK] = b;
    head++;
}

// escribe el encabezado; devuelve 0 si no hay lugar para la trama completa
static int begin_frame(uint8_t type, uint16_t n, uint32_t payload_bytes)
{
    if (ring_free() < STREAM_HDR_SIZE + payload_bytes)
    {
        stream_dropped++;
        seq++;                          // el salto de seq le avisa a la PC
        return 0;
    }
    ring_put(STREAM_SYNC0);
    ring_put(STREAM_SYNC1);
    ring_put(type);
    ring_put(seq++);
    ring_put(n & 0xFF);
    ring_put(n >> 8);
    return 1;
}

static void detectar_alineacion(const uint16_t *f, uint16_t frames)
{
    uint16_t hi = 0;
    for (uint32_t i = 0; i < 4u * frames; i += 2)    // halfword alta de cada muestra (L y R)
        hi |= f[i];

    if (hi & 0x8000u)
    {
        corrida = 0;
        bloques_sin_negativos = 0;
    }
    else if (++bloques_sin_negativos >= BLOQUES_PARA_CORRIDA)
    {
        corrida = 1;
    }

    if (corrida) bloques_corridos++;
    else         bloques_directos++;
}

void stream_push_audio(const uint16_t *f, uint16_t frames)
{
    if (!stream_on)
        return;

    detectar_alineacion(f, frames);
    uint8_t sh = corrida;

    uint8_t canales = stream_canales;
    uint8_t tipo = (canales == STREAM_L) ? STREAM_TYPE_AUDIO_L :
                   (canales == STREAM_R) ? STREAM_TYPE_AUDIO_R : STREAM_TYPE_AUDIO;
    uint32_t bytes_frame = (canales == STREAM_LR) ? 6u : 3u;

    if (begin_frame(tipo, frames, (uint32_t)frames * bytes_frame))
    {
        for (uint16_t i = 0; i < frames; i++)
        {
            // cada muestra: 24 bits en una palabra de 32 (hi<<16 | lo). Si llega corrida, <<1 la vuelve a
            // alinear (el LSB se pierde en el relleno); >>8 con signo deja los 24 bits.
            int32_t l = (int32_t)((((uint32_t)f[0] << 16) | f[1]) << sh) >> 8;
            int32_t r = (int32_t)((((uint32_t)f[2] << 16) | f[3]) << sh) >> 8;
            f += 4;

            if (canales & STREAM_L)
            {
                ring_put((uint8_t)l);
                ring_put((uint8_t)(l >> 8));
                ring_put((uint8_t)(l >> 16));
            }
            if (canales & STREAM_R)
            {
                ring_put((uint8_t)r);
                ring_put((uint8_t)(r >> 8));
                ring_put((uint8_t)(r >> 16));
            }
        }
    }
    stream_kick();
}

void stream_push_text(const char *txt)
{
    uint16_t n = (uint16_t)strlen(txt);
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    if (begin_frame(STREAM_TYPE_TEXT, n, n))
    {
        for (uint16_t i = 0; i < n; i++)
            ring_put((uint8_t)txt[i]);
    }
    __set_PRIMASK(primask);
    stream_kick();
}

void stream_kick(void)
{
    uint32_t primask = __get_PRIMASK();
    __disable_irq();

    if (hUsbDeviceFS.dev_state != USBD_STATE_CONFIGURED)
    {
        // cable desconectado o puerto sin enumerar: se corta el streaming y se limpia el ring
        stream_on = 0;
        tail = head;
        inflight = 0;
        usb_busy = 0;
    }
    else if (!usb_busy)
    {
        uint32_t avail = head - tail;
        if (avail)
        {
            uint32_t idx = tail & RING_MASK;
            uint32_t len = RING_SIZE - idx;          // no cruzar el final del ring
            if (len > avail)     len = avail;
            if (len > MAX_CHUNK) len = MAX_CHUNK;

            if (CDC_Transmit_FS(&ring[idx], (uint16_t)len) == USBD_OK)
            {
                usb_busy = 1;
                inflight = len;
            }
        }
    }

    __set_PRIMASK(primask);
}

void stream_alin_reset(void)
{
    bloques_corridos = 0;
    bloques_directos = 0;
}

void stream_alin_informar(void)
{
    char txt[40];
    snprintf(txt, sizeof(txt), "ALIN:%lu,%lu", (unsigned long)bloques_corridos, (unsigned long)bloques_directos);
    stream_push_text(txt);
}

void stream_tx_done(void)
{
    tail += inflight;
    inflight = 0;
    usb_busy = 0;
    stream_kick();                      // encadena el siguiente bloque
}
