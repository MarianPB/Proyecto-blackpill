/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "usb_device.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "sine_table.h"
#include "waveforms.h"
#include "oled.h"
#include "keypad.h"
#include "stream.h"
#include <math.h>
#include <stdio.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

typedef enum {

	LEFT,
	RIGHT

}canal_e;

typedef enum {

	OFF,
	ON

}estado_e;
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define FS           97656.25          // frecuencia de muestreo real (I2SCLK 100MHz / 1024)

#define FRAMES_HALF  256               // frames estereo por media vuelta del DMA
#define FRAMES_TOTAL (2 * FRAMES_HALF) // frames en todo el buffer (512)
#define BUF_HW       (FRAMES_TOTAL * 4)// halfwords totales: 2 canales x 2 halfwords c/u (2048)
#define I2S_SIZE     (FRAMES_TOTAL * 2)// tamaño que espera la HAL del I2S (1024)

#define PCM_ADDR     (0x46 << 1)       // direccion I2C del codec (7 bits corridos a 8)

#define I2C_QSIZE    8                 // cola de pedidos I2C que llegan por USB
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
I2C_HandleTypeDef hi2c1;

I2S_HandleTypeDef hi2s2;
DMA_HandleTypeDef hdma_spi2_tx;
DMA_HandleTypeDef hdma_i2s2_ext_rx;

/* USER CODE BEGIN PV */
uint32_t          acc[2] = {0, 0};              // acumuladores de fase (uno por canal)
volatile uint32_t ftw[2] = {0, 0};              // FTW de cada canal
volatile uint8_t  canal_seleccionado = LEFT;    // canal que edita el teclado
uint16_t          audio_buf[BUF_HW];            // buffer circular del DMA (DAC, salida)
uint16_t          rx_buf[BUF_HW];               // buffer circular del DMA (ADC, entrada)

// estado del codec (registro 64: bit5 = ADC apagado, bit4 = DAC apagado, bit0 = single-ended)
volatile uint8_t  adc_activo = 1;
volatile uint8_t  dac_activo = 1;

// pedidos de acceso I2C generados desde USB (no se puede bloquear en la interrupcion)
typedef struct { uint8_t op; uint8_t reg; uint8_t val; } i2c_req_t;   // op: 1 = escribir, 2 = leer
static volatile i2c_req_t i2c_q[I2C_QSIZE];
static volatile uint8_t   i2c_q_head = 0, i2c_q_tail = 0;
volatile uint8_t  modo_diferencial = 1;         // 1 = salida diferencial, 0 = single-ended

// parametros de cada canal (los escribe el USB o el teclado)
extern float frecuencia[2];
extern uint32_t amplitud[2];
extern volatile uint8_t salida_activa[2];
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
static void MX_I2C1_Init(void);
static void MX_I2S2_Init(void);
/* USER CODE BEGIN PFP */
static void fill(uint16_t *dst);
static void pcm_write(uint8_t reg, uint8_t val);
static void pcm_update_sys(void);
void codec_i2c_request(uint8_t op, uint8_t reg, uint8_t val);
static void codec_i2c_process(void);
void PCM3060_SetAmplitude(uint8_t canal, uint32_t amplitud);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_I2C1_Init();
  MX_I2S2_Init();
  MX_USB_DEVICE_Init();
  /* USER CODE BEGIN 2 */
  // FTW inicial de cada canal
  ftw[0] = (uint32_t)(frecuencia[0] * 4294967296.0 / FS);
  ftw[1] = (uint32_t)(frecuencia[1] * 4294967296.0 / FS);

  // cargo las dos mitades del buffer antes de largar el DMA
  fill(&audio_buf[0]);
  fill(&audio_buf[BUF_HW / 2]);

  // I2S full duplex por DMA en modo circular: DAC sale por audio_buf, ADC entra por rx_buf
  HAL_I2SEx_TransmitReceive_DMA(&hi2s2, audio_buf, rx_buf, I2S_SIZE);

  // margen para que el codec estabilice sus relojes internos
  HAL_Delay(50);

  // configuracion del codec por I2C
  pcm_write(72, 0x00);   // reg 72: ADC esclavo, I2S 24 bits (el STM32 es el maestro del bus)
  pcm_update_sys();      // reg 64: ADC y DAC encendidos, modo diferencial
  pcm_write(65, 0xFF);   // reg 65: volumen DAC L = 0 dB
  pcm_write(66, 0xFF);   // reg 66: volumen DAC R = 0 dB
  pcm_write(68, 0x40);   // reg 68: sobremuestreo doble (64x a 96 kHz)

  oled_init();
  chirp_config(0, 200.0f, 2000.0f, 1.0f);   // barrido inicial: 200 Hz -> 2 kHz en 1 s
  chirp_config(1, 200.0f, 2000.0f, 1.0f);
  keypad_init();
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */

   // recalculo el FTW de cada canal a partir de su frecuencia
   ftw[0] = (uint32_t)(frecuencia[0] * 4294967296.0 / FS);
   ftw[1] = (uint32_t)(frecuencia[1] * 4294967296.0 / FS);

   // amplitud: se escribe al codec por I2C solo cuando cambia, para no saturar el bus
   static uint32_t last_amp[2] = { 0xFFFFFFFF, 0xFFFFFFFF };
   for (int c = 0; c < 2; c++) {
       if (amplitud[c] != last_amp[c]) {
           last_amp[c] = amplitud[c];
           PCM3060_SetAmplitude(c, amplitud[c]);   // volumen de ese canal (registro del codec)
       }
   }

   // estado del codec (diferencial / single-ended, ADC y DAC on/off): se aplica solo cuando cambia
   static uint8_t last_modo = 0xFF, last_adc = 0xFF, last_dac = 0xFF;
   if (modo_diferencial != last_modo || adc_activo != last_adc || dac_activo != last_dac) {
       last_modo = modo_diferencial;
       last_adc  = adc_activo;
       last_dac  = dac_activo;
       pcm_update_sys();
   }

   // accesos I2C pedidos por la PC (escritura / lectura de registros del codec)
   codec_i2c_process();

   // teclado: escaneo cada 20 ms
   static uint32_t last_key = 0;
   if (HAL_GetTick() - last_key >= 20) {
       last_key = HAL_GetTick();
       keypad_process();
   }

   // refresco del OLED cada 200 ms
   static uint32_t last_oled = 0;
   if (HAL_GetTick() - last_oled >= 200) {
       last_oled = HAL_GetTick();
       oled_show(canal_seleccionado, waveform[canal_seleccionado],
                 (uint32_t)frecuencia[canal_seleccionado], (uint8_t)amplitud[canal_seleccionado],
                 keypad_get_mode(), keypad_get_input());
   }
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 25;
  RCC_OscInitStruct.PLL.PLLN = 192;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 4;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief I2C1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_I2C1_Init(void)
{

  /* USER CODE BEGIN I2C1_Init 0 */

  /* USER CODE END I2C1_Init 0 */

  /* USER CODE BEGIN I2C1_Init 1 */

  /* USER CODE END I2C1_Init 1 */
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 100000;
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2C1_Init 2 */

  /* USER CODE END I2C1_Init 2 */

}

/**
  * @brief I2S2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_I2S2_Init(void)
{

  /* USER CODE BEGIN I2S2_Init 0 */

  /* USER CODE END I2S2_Init 0 */

  /* USER CODE BEGIN I2S2_Init 1 */

  /* USER CODE END I2S2_Init 1 */
  hi2s2.Instance = SPI2;
  hi2s2.Init.Mode = I2S_MODE_MASTER_TX;
  hi2s2.Init.Standard = I2S_STANDARD_PHILIPS;
  hi2s2.Init.DataFormat = I2S_DATAFORMAT_24B;
  hi2s2.Init.MCLKOutput = I2S_MCLKOUTPUT_ENABLE;
  hi2s2.Init.AudioFreq = I2S_AUDIOFREQ_96K;
  hi2s2.Init.CPOL = I2S_CPOL_LOW;
  hi2s2.Init.ClockSource = I2S_CLOCK_PLL;
  hi2s2.Init.FullDuplexMode = I2S_FULLDUPLEXMODE_ENABLE;
  if (HAL_I2S_Init(&hi2s2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2S2_Init 2 */

  /* USER CODE END I2S2_Init 2 */

}

/**
  * Enable DMA controller clock
  */
static void MX_DMA_Init(void)
{

  /* DMA controller clock enable */
  __HAL_RCC_DMA1_CLK_ENABLE();

  /* DMA interrupt init */
  /* DMA1_Stream3_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Stream3_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream3_IRQn);
  /* DMA1_Stream4_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Stream4_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Stream4_IRQn);

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_0|GPIO_PIN_1, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_0|GPIO_PIN_1, GPIO_PIN_SET);

  /*Configure GPIO pins : PA0 PA1 */
  GPIO_InitStruct.Pin = GPIO_PIN_0|GPIO_PIN_1;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pin : PA4 */
  GPIO_InitStruct.Pin = GPIO_PIN_4;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pins : PB0 PB1 */
  GPIO_InitStruct.Pin = GPIO_PIN_0|GPIO_PIN_1;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : PB13 PB8 PB9 */
  GPIO_InitStruct.Pin = GPIO_PIN_13|GPIO_PIN_8|GPIO_PIN_9;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
// Llena una mitad del buffer: FRAMES_HALF frames estereo
static void fill(uint16_t *dst)
{
    for (int i = 0; i < FRAMES_HALF; i++)
    {
        int32_t s[2];                 // una muestra de 24 bits por canal (L y R)

        for (int c = 0; c < 2; c++)
        {
            int32_t v = wave_next(c);                  // muestra segun la forma de onda del canal
            if (!salida_activa[c]) v = 0;              // canal apagado -> silencio
            s[c] = v;
        }

        // cada muestra de 24 bits se parte en 2 halfwords, MSB primero
        *dst++ = (uint16_t)(s[0] >> 8);   // L: bits altos
        *dst++ = (uint16_t)(s[0] << 8);   // L: bits bajos
        *dst++ = (uint16_t)(s[1] >> 8);   // R: bits altos
        *dst++ = (uint16_t)(s[1] << 8);   // R: bits bajos
    }
}

// full duplex: RX y TX circulan sincronizados, asi que con el evento del RX
// se re-llena la mitad de TX que se acaba de vaciar y se procesa la mitad de RX que se acaba de llenar

// 1a mitad lista
void HAL_I2SEx_TxRxHalfCpltCallback(I2S_HandleTypeDef *hi2s)
{
    fill(&audio_buf[0]);
    stream_push_audio(&rx_buf[0], FRAMES_HALF);
}

// 2a mitad lista
void HAL_I2SEx_TxRxCpltCallback(I2S_HandleTypeDef *hi2s)
{
    fill(&audio_buf[BUF_HW / 2]);
    stream_push_audio(&rx_buf[BUF_HW / 2], FRAMES_HALF);
}

// escribe un byte en un registro del codec por I2C
static void pcm_write(uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = { reg, val };
    HAL_I2C_Master_Transmit(&hi2c1, PCM_ADDR, buf, 2, 100);
}

// registro 64 del codec: MRST|SRST siempre en 1, ADPSV (bit5) apaga el ADC, DAPSV (bit4) apaga el DAC,
// S/E (bit0) = 0 diferencial / 1 single-ended
static void pcm_update_sys(void)
{
    uint8_t v = 0xC0;
    if (!adc_activo)      v |= 0x20;
    if (!dac_activo)      v |= 0x10;
    if (!modo_diferencial) v |= 0x01;
    pcm_write(64, v);
}

// encola un pedido de acceso I2C (lo llama el parser USB, en interrupcion)
void codec_i2c_request(uint8_t op, uint8_t reg, uint8_t val)
{
    uint8_t next = (i2c_q_head + 1) % I2C_QSIZE;
    if (next == i2c_q_tail)
        return;                                 // cola llena: se descarta
    i2c_q[i2c_q_head].op  = op;
    i2c_q[i2c_q_head].reg = reg;
    i2c_q[i2c_q_head].val = val;
    i2c_q_head = next;
}

// atiende la cola desde el lazo principal
static void codec_i2c_process(void)
{
    while (i2c_q_tail != i2c_q_head)
    {
        i2c_req_t r = { i2c_q[i2c_q_tail].op, i2c_q[i2c_q_tail].reg, i2c_q[i2c_q_tail].val };
        i2c_q_tail = (i2c_q_tail + 1) % I2C_QSIZE;

        char msg[40];
        if (r.op == 1)
        {
            pcm_write(r.reg, r.val);
            snprintf(msg, sizeof(msg), "I2CW %u=0x%02X", r.reg, r.val);
        }
        else
        {
            uint8_t v = 0;
            if (HAL_I2C_Mem_Read(&hi2c1, PCM_ADDR, r.reg, I2C_MEMADD_SIZE_8BIT, &v, 1, 100) == HAL_OK)
                snprintf(msg, sizeof(msg), "I2CR %u=0x%02X", r.reg, v);
            else
                snprintf(msg, sizeof(msg), "I2CR %u=ERR", r.reg);
        }
        stream_push_text(msg);
    }
}

// convierte la amplitud en % a la atenuacion del codec y la escribe
void PCM3060_SetAmplitude(uint8_t canal, uint32_t amplitud)
{
    uint8_t reg = (canal == 0) ? 0x41 : 0x42;   // 0x41 = DAC L, 0x42 = DAC R

    if (amplitud == 0)
    {
        pcm_write(reg, 0x00);   // mute de ese canal
        return;
    }

    if (amplitud > 100)
        amplitud = 100;

    float A = amplitud / 100.0f;
    float db = 20.0f * log10f(A);          // % -> dB
    int pasos = (int)roundf(-db / 0.5f);   // cada paso del registro son 0.5 dB
    uint8_t valor = 255 - pasos;           // 0xFF = 0 dB, baja de a 0.5 dB

    pcm_write(reg, valor);
}
/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
