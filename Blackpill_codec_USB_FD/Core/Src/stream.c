#include "stream.h"
#include "usbd_cdc_if.h"
#include "usb_device.h"
#include <string.h>

extern USBD_HandleTypeDef hUsbDeviceFS;

#define RING_SIZE  16384u              // potencia de 2 (~10 tramas de audio de 256 frames)
#define RING_MASK  (RING_SIZE - 1u)
#define MAX_CHUNK  4096u               // bytes maximos por transferencia USB

static uint8_t  ring[RING_SIZE];
static volatile uint32_t head = 0;     // escribe el DMA/USB (ISR)
static volatile uint32_t tail = 0;     // avanza cuando el USB termina de mandar
static volatile uint32_t inflight = 0; // bytes de la transferencia USB en curso
static volatile uint8_t  usb_busy = 0;
static uint8_t seq = 0;

volatile uint8_t  stream_on = 0;
volatile uint32_t stream_dropped = 0;

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

void stream_push_audio(const uint16_t *f, uint16_t frames)
{
    if (!stream_on)
        return;

    if (begin_frame(STREAM_TYPE_AUDIO, frames, (uint32_t)frames * 6u))
    {
        for (uint16_t i = 0; i < frames; i++)
        {
            // cada muestra: 24 bits alineados a la izquierda en 32 (hi<<16 | lo) -> >>8 con signo
            int32_t l = (int32_t)(((uint32_t)f[0] << 16) | f[1]) >> 8;
            int32_t r = (int32_t)(((uint32_t)f[2] << 16) | f[3]) >> 8;
            f += 4;

            ring_put((uint8_t)l);
            ring_put((uint8_t)(l >> 8));
            ring_put((uint8_t)(l >> 16));
            ring_put((uint8_t)r);
            ring_put((uint8_t)(r >> 8));
            ring_put((uint8_t)(r >> 16));
        }
    }
    stream_kick();
}

void stream_push_text(const char *txt)
{
    uint16_t n = (uint16_t)strlen(txt);

    if (begin_frame(STREAM_TYPE_TEXT, n, n))
    {
        for (uint16_t i = 0; i < n; i++)
            ring_put((uint8_t)txt[i]);
    }
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

void stream_tx_done(void)
{
    tail += inflight;
    inflight = 0;
    usb_busy = 0;
    stream_kick();                      // encadena el siguiente bloque
}
