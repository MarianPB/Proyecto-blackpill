#ifndef KEYPAD_H
#define KEYPAD_H
#include <stdint.h>

// modos de edicion (los cicla la tecla '*')
#define KP_MODE_FREQ   0
#define KP_MODE_AMP    1
#define KP_MODE_CANAL  2

void keypad_init(void);      // deja las filas en alto (llamar una vez)
void keypad_process(void);   // escanea y actua (llamar seguido en el loop)

// estado para mostrar en el OLED
uint8_t     keypad_get_mode(void);    // KP_MODE_FREQ / _AMP / _CANAL
const char* keypad_get_input(void);   // digitos tecleados sin confirmar ("" si no hay)

#endif
