#ifndef WAVEFORMS_H
#define WAVEFORMS_H
#include <stdint.h>

typedef enum {
    WAVE_SINE = 0,
    WAVE_SQUARE,
    WAVE_TRIANGLE,
    WAVE_CHIRP,
    WAVE_SINE_TAB,   // 4: seno 1 kHz EXACTO por tabla (sin acumulador, sin truncacion de fase)
    WAVE_MULTI,      // 5: multitono 60 Hz + 7 kHz (el de 7 kHz a 1/4 de amplitud)
    WAVE_TAB_FEA,    // 6: ~995.4 Hz por TABLA (limpia) -> referencia para THD
    WAVE_ACC_FEA     // 7: ~995.4 Hz por ACUMULADOR con FTW peor caso (truncacion maxima)
} waveform_t;

extern volatile waveform_t waveform[2];   // forma de onda de cada canal

int32_t wave_next(uint8_t c);             // da la muestra del canal c y avanza su fase
void chirp_config(uint8_t c, float f0, float f1, float dur_s);  // configura el barrido

#endif