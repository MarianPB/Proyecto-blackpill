/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file         stm32f4xx_hal_msp.c
  * @brief        This file provides code for the MSP Initialization
  *               and de-Initialization codes.
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
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */
extern DMA_HandleTypeDef hdma_spi1_tx;

extern DMA_HandleTypeDef hdma_spi2_rx;

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN TD */

/* USER CODE END TD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN Define */

/* USER CODE END Define */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN Macro */

/* USER CODE END Macro */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* External functions --------------------------------------------------------*/
/* USER CODE BEGIN ExternalFunctions */

/* USER CODE END ExternalFunctions */

/* USER CODE BEGIN 0 */

/* USER CODE END 0 */
/**
  * Initializes the Global MSP.
  */
void HAL_MspInit(void)
{

  /* USER CODE BEGIN MspInit 0 */

  /* USER CODE END MspInit 0 */

  __HAL_RCC_SYSCFG_CLK_ENABLE();
  __HAL_RCC_PWR_CLK_ENABLE();

  /* System interrupt init*/

  /* USER CODE BEGIN MspInit 1 */

  /* USER CODE END MspInit 1 */
}

/**
  * @brief I2C3 (codec PCM3060 y pantalla OLED): PA8 = SCL, PC9 = SDA, los dos en AF4.
  */
void HAL_I2C_MspInit(I2C_HandleTypeDef* hi2c)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  if(hi2c->Instance==I2C3)
  {
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    GPIO_InitStruct.Pin = GPIO_PIN_8;                 // PA8 -> I2C3_SCL
    GPIO_InitStruct.Mode = GPIO_MODE_AF_OD;
    GPIO_InitStruct.Pull = GPIO_NOPULL;               // pull-ups externos (R5, R6)
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF4_I2C3;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = GPIO_PIN_9;                 // PC9 -> I2C3_SDA
    HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

    __HAL_RCC_I2C3_CLK_ENABLE();
  }
}

void HAL_I2C_MspDeInit(I2C_HandleTypeDef* hi2c)
{
  if(hi2c->Instance==I2C3)
  {
    __HAL_RCC_I2C3_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOA, GPIO_PIN_8);
    HAL_GPIO_DeInit(GPIOC, GPIO_PIN_9);
  }
}

/**
  * @brief Reloj de los I2S (comun a los dos): PLLI2S con el cristal de 8 MHz.
  *        8 MHz / M 8 = 1 MHz x N 344 = 344 MHz -> / R 2 = 172 MHz para el I2S1 (APB2) y el I2S2 (APB1).
  *        P y Q del PLLI2S no se usan (SPDIF y SAI), pero tienen que tener valores validos.
  */
static void I2S_ConfigurarReloj(void)
{
  static uint8_t hecho = 0;
  RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};
  if (hecho)
    return;
  PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_I2S_APB1 | RCC_PERIPHCLK_I2S_APB2;
  PeriphClkInitStruct.PLLI2S.PLLI2SM = 8;
  PeriphClkInitStruct.PLLI2S.PLLI2SN = 344;
  PeriphClkInitStruct.PLLI2S.PLLI2SP = RCC_PLLI2SP_DIV2;
  PeriphClkInitStruct.PLLI2S.PLLI2SQ = 2;
  PeriphClkInitStruct.PLLI2S.PLLI2SR = 2;
  PeriphClkInitStruct.I2sApb1ClockSelection = RCC_I2SAPB1CLKSOURCE_PLLI2S;
  PeriphClkInitStruct.I2sApb2ClockSelection = RCC_I2SAPB2CLKSOURCE_PLLI2S;
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct) != HAL_OK)
  {
    Error_Handler();
  }
  hecho = 1;
}

/**
  * @brief I2S1 (SPI1) maestro transmisor y I2S2 (SPI2) esclavo receptor: pines y DMA.
  */
void HAL_I2S_MspInit(I2S_HandleTypeDef* hi2s)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  if(hi2s->Instance==SPI1)
  {
    I2S_ConfigurarReloj();
    __HAL_RCC_SPI1_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    /* PA4 -> I2S1_WS (LRCK), PA5 -> I2S1_CK (BCK), PA7 -> I2S1_SD (DIN), PC4 -> I2S1_MCK; todos AF5 */
    GPIO_InitStruct.Pin = GPIO_PIN_4|GPIO_PIN_5|GPIO_PIN_7;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF5_SPI1;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = GPIO_PIN_4;
    HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

    /* SPI1_TX: DMA2 Stream3 Channel3, circular, de a halfword */
    hdma_spi1_tx.Instance = DMA2_Stream3;
    hdma_spi1_tx.Init.Channel = DMA_CHANNEL_3;
    hdma_spi1_tx.Init.Direction = DMA_MEMORY_TO_PERIPH;
    hdma_spi1_tx.Init.PeriphInc = DMA_PINC_DISABLE;
    hdma_spi1_tx.Init.MemInc = DMA_MINC_ENABLE;
    hdma_spi1_tx.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    hdma_spi1_tx.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
    hdma_spi1_tx.Init.Mode = DMA_CIRCULAR;
    hdma_spi1_tx.Init.Priority = DMA_PRIORITY_HIGH;
    hdma_spi1_tx.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(&hdma_spi1_tx) != HAL_OK)
    {
      Error_Handler();
    }
    __HAL_LINKDMA(hi2s,hdmatx,hdma_spi1_tx);
  }
  else if(hi2s->Instance==SPI2)
  {
    I2S_ConfigurarReloj();
    __HAL_RCC_SPI2_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    /* PB12 -> I2S2_WS (LRCK), PB13 -> I2S2_CK (BCK), PB15 -> I2S2_SD (DOUT del codec); todos AF5 */
    GPIO_InitStruct.Pin = GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_15;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF5_SPI2;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* SPI2_RX: DMA1 Stream3 Channel0, circular, de a halfword */
    hdma_spi2_rx.Instance = DMA1_Stream3;
    hdma_spi2_rx.Init.Channel = DMA_CHANNEL_0;
    hdma_spi2_rx.Init.Direction = DMA_PERIPH_TO_MEMORY;
    hdma_spi2_rx.Init.PeriphInc = DMA_PINC_DISABLE;
    hdma_spi2_rx.Init.MemInc = DMA_MINC_ENABLE;
    hdma_spi2_rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    hdma_spi2_rx.Init.MemDataAlignment = DMA_MDATAALIGN_HALFWORD;
    hdma_spi2_rx.Init.Mode = DMA_CIRCULAR;
    hdma_spi2_rx.Init.Priority = DMA_PRIORITY_HIGH;
    hdma_spi2_rx.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(&hdma_spi2_rx) != HAL_OK)
    {
      Error_Handler();
    }
    __HAL_LINKDMA(hi2s,hdmarx,hdma_spi2_rx);
  }
}

void HAL_I2S_MspDeInit(I2S_HandleTypeDef* hi2s)
{
  if(hi2s->Instance==SPI1)
  {
    __HAL_RCC_SPI1_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOA, GPIO_PIN_4|GPIO_PIN_5|GPIO_PIN_7);
    HAL_GPIO_DeInit(GPIOC, GPIO_PIN_4);
    HAL_DMA_DeInit(hi2s->hdmatx);
  }
  else if(hi2s->Instance==SPI2)
  {
    __HAL_RCC_SPI2_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOB, GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_15);
    HAL_DMA_DeInit(hi2s->hdmarx);
  }
}

/* USER CODE BEGIN 1 */

/* USER CODE END 1 */
