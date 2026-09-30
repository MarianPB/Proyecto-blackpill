#include "keypad.h"
#include "main.h"          // HAL + GPIO
#include "waveforms.h"     // waveform[] y el tipo
#include <stdlib.h>        // atoi

// --- pines, segun la config de CubeMX ---
typedef struct { GPIO_TypeDef *port; uint16_t pin; } pin_t;

static const pin_t rows[4] = {                 // salidas (filas)
    {GPIOA, GPIO_PIN_0}, {GPIOA, GPIO_PIN_1},
    {GPIOB, GPIO_PIN_0}, {GPIOB, GPIO_PIN_1}
};
static const pin_t cols[4] = {                 // entradas pull-up (columnas)
    {GPIOB, GPIO_PIN_8},  {GPIOB, GPIO_PIN_9},
    {GPIOB, GPIO_PIN_13}, {GPIOA, GPIO_PIN_4}    // col 4 en PA4: PB14 es la entrada del ADC (I2S2ext_SD)
};

static const char keymap[4][4] = {             // que tecla es cada cruce
    {'1','2','3','A'},
    {'4','5','6','B'},
    {'7','8','9','C'},
    {'*','0','#','D'}
};

// --- variables que el teclado modifica (viven en otros archivos) ---
extern volatile uint8_t canal_seleccionado;    // main.c
extern float    frecuencia[2];                 // usbd_cdc_if.c (uno por canal)
extern uint32_t amplitud[2];                   // usbd_cdc_if.c (uno por canal)

// --- estado del ingreso de numeros ---
static char    numbuf[8];
static uint8_t nlen = 0;
static uint8_t mode = KP_MODE_FREQ;   // modo de edicion activo: frecuencia / amplitud / canal

void keypad_init(void)
{

    for (int r = 0; r < 4; r++)                // deja todas las filas en alto
        HAL_GPIO_WritePin(rows[r].port, rows[r].pin, GPIO_PIN_SET);
}

// escanea la matriz, devuelve la tecla RECIEN apretada (o 0 si nada nuevo)
static char keypad_scan(void)
{
    static char last = 0;
    char found = 0;

    for (int r = 0; r < 4 && !found; r++) {
        HAL_GPIO_WritePin(rows[r].port, rows[r].pin, GPIO_PIN_RESET);   // pone esta fila en bajo
        for (volatile int d = 0; d < 200; d++);                        // espera a que se asiente el nivel
        for (int c = 0; c < 4; c++) {
            if (HAL_GPIO_ReadPin(cols[c].port, cols[c].pin) == GPIO_PIN_RESET) {
                found = keymap[r][c];                                   // columna en bajo -> tecla apretada
                break;
            }
        }
        HAL_GPIO_WritePin(rows[r].port, rows[r].pin, GPIO_PIN_SET);     // vuelve la fila a alto
    }

    char result = (found && found != last) ? found : 0;   // flanco: 1 sola vez por apretada
    last = found;
    return result;
}

// escanea + aplica la accion sobre el generador
void keypad_process(void)
{
    char k = keypad_scan();
    if (!k) return;

    if (k >= '0' && k <= '9') {                        // digito
        if (mode == KP_MODE_CANAL) {                   // en modo canal: 0 = izq, 1 = der
            if (k == '0') canal_seleccionado = 0;
            else if (k == '1') canal_seleccionado = 1;
        } else if (nlen < sizeof(numbuf) - 1) {        // freq/amp: acumula el digito
            numbuf[nlen++] = k;
        }
    }
    else if (k == 'A') waveform[canal_seleccionado] = WAVE_SINE;
    else if (k == 'B') waveform[canal_seleccionado] = WAVE_SQUARE;
    else if (k == 'C') waveform[canal_seleccionado] = WAVE_TRIANGLE;
    else if (k == 'D') waveform[canal_seleccionado] = WAVE_CHIRP;
    else if (k == '*') {                               // cicla: frec -> amp -> canal
        mode = (mode + 1) % 3;
        nlen = 0;
    }
    else if (k == '#') {                               // ENTER / accion segun el modo
        if (mode == KP_MODE_CANAL) {
            canal_seleccionado ^= 1;                   // togglea izq <-> der
        } else {
            numbuf[nlen] = '\0';
            uint32_t val = atoi(numbuf);
            if (mode == KP_MODE_AMP) amplitud[canal_seleccionado] = val;
            else                     frecuencia[canal_seleccionado] = (float)val;
        }
        nlen = 0;
    }
}

// estado para mostrar en el OLED
uint8_t keypad_get_mode(void) { return mode; }

const char* keypad_get_input(void)
{
    numbuf[nlen] = '\0';   // cierra la cadena antes de devolverla
    return numbuf;
}