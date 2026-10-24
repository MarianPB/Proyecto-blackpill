#include "waveforms.h"
#include "sine_table.h"
#include "tabla_1khz.h"            // tabla de 1 kHz EXACTO (32 periodos, sin truncacion)
#include "tabla_fea.h"             // tabla de ~995.4 Hz (peor caso) + FTW_FEA, para comparar THD

// acumulador de fase y FTW de cada canal (definidos en main.c)
extern uint32_t acc[2];
extern volatile uint32_t ftw[2];

#define FS  97656.25               // frecuencia de muestreo (debe coincidir con la de main.c)

// --- estado de la forma de onda "seno por tabla" (1 kHz, sin acumulador) ---
static uint16_t idx1k[2] = { 0, 0 };          // indice de lectura de la tabla, por canal

// --- estado del multitono (60 Hz + 7 kHz) ---
// Frecuencias FIJAS: la FTW se calcula una vez (constante de compilacion).
static const uint32_t ftw60 = (uint32_t)(  60.0 * 4294967296.0 / FS);
static const uint32_t ftw7k = (uint32_t)(7000.0 * 4294967296.0 / FS);
static uint32_t acc60[2] = { 0, 0 };          // acumulador del tono de 60 Hz, por canal
static uint32_t acc7k[2] = { 0, 0 };          // acumulador del tono de 7 kHz, por canal

// --- estado de las formas "fea" (~995.4 Hz), para el experimento de THD ---
static uint16_t idxfea[2] = { 0, 0 };         // indice de lectura de la tabla fea (limpia), por canal
static uint32_t accfea[2] = { 0, 0 };         // acumulador de la version fea (con truncacion), por canal

volatile waveform_t waveform[2] = { WAVE_SINE, WAVE_SINE };  // forma de onda de cada canal

// estado del chirp, uno por canal
static uint32_t chirp_ftw[2];      // FTW instantanea del barrido
static uint32_t chirp_start[2];    // FTW correspondiente a f0
static uint32_t chirp_end[2];      // FTW correspondiente a f1
static uint32_t chirp_step[2];     // incremento de FTW por muestra

// Configura un barrido de f0 a f1 en dur_s segundos para el canal c
void chirp_config(uint8_t c, float f0, float f1, float dur_s)
{
    chirp_start[c] = (uint32_t)(f0 * 4294967296.0 / FS);
    chirp_end[c]   = (uint32_t)(f1 * 4294967296.0 / FS);
    uint32_t nsamp = (uint32_t)(dur_s * FS);               // muestras que dura el barrido
    if (nsamp == 0) nsamp = 1;
    chirp_step[c]  = (chirp_end[c] - chirp_start[c]) / nsamp;
    chirp_ftw[c]   = chirp_start[c];
}

int32_t wave_next(uint8_t c)
{
    int32_t v;

    switch (waveform[c])
    {
    case WAVE_SINE:                              // seno: valor directo de la tabla
        acc[c] += ftw[c];                        // avanza la fase
        v = sine_table[acc[c] >> 19];            // los 13 bits altos indexan la tabla de 8192
        break;

    case WAVE_SQUARE:                                       // cuadrada: signo segun la mitad del acumulador
        acc[c] += ftw[c];
        v = (acc[c] < 0x80000000u) ? 8388607 : -8388608;    // 1a mitad -> maximo (+), 2a mitad -> minimo (-)
        break;

    case WAVE_TRIANGLE:                                             // triangular: rampa que sube y baja
        acc[c] += ftw[c];
        if (acc[c] < 0x80000000u)                                   // 1a mitad: sube de -max a +max
            v = -8388608 + (int32_t)(acc[c] >> 7);                  // >>7 lleva los 2^31 valores de la media fase al rango +-2^23
        else                                                        // 2a mitad: baja de +max a -max
            v = 8388608 - (int32_t)((acc[c] - 0x80000000u) >> 7);
        if (v > 8388607) v = 8388607;                               // recorte por si el pico se pasa 1 unidad
        break;

     case WAVE_CHIRP:                             // chirp: seno con la FTW subiendo hasta f1 y volviendo a f0
        chirp_ftw[c] += chirp_step[c];
        if (chirp_ftw[c] >= chirp_end[c])
            chirp_ftw[c] = chirp_start[c];
        acc[c] += chirp_ftw[c];
        v = sine_table[acc[c] >> 19];
        break;

     case WAVE_SINE_TAB:                         // seno 1 kHz EXACTO: se lee la tabla con indice (sin acumulador)
        v = tabla_1khz[idx1k[c]];                // sin truncacion de fase -> sin espurios por el salto del indice
        if (++idx1k[c] >= TABLA_1KHZ_LEN)        // avanza 1 y da la vuelta justo al cerrar los 32 periodos
            idx1k[c] = 0;
        break;

     case WAVE_MULTI:                            // multitono: 60 Hz + 7 kHz (el de 7 kHz a 1/4 de amplitud)
        acc60[c] += ftw60;
        acc7k[c] += ftw7k;
        // pesos 4:1 y /5 -> 60 Hz = 4/5 del fondo, 7 kHz = 1/5 (justo 1/4 del de 60 Hz); pico <= +-2^23
        v = (4 * sine_table[acc60[c] >> 19] + sine_table[acc7k[c] >> 19]) / 5;
        break;

     case WAVE_TAB_FEA:                          // ~995.4 Hz por TABLA (LIMPIA, sin truncacion)
        v = tabla_fea[idxfea[c]];
        if (++idxfea[c] >= TABLA_FEA_LEN)
            idxfea[c] = 0;
        break;

     case WAVE_ACC_FEA:                          // ~995.4 Hz por ACUMULADOR con FTW peor caso (TRUNCA)
        accfea[c] += FTW_FEA;                    // misma frecuencia que la tabla, pero con truncacion maxima
        v = sine_table[accfea[c] >> 19];         // los 13 bits altos -> espurio de truncacion ~ -78 dBc
        break;

     default:
        v = 0;
    }
    return v;
}