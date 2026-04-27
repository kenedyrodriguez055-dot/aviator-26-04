import os
import time
import requests
import telebot

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
TOKEN = os.getenv("TELEGRAM_TOKEN", "8772666643:AAEfEnWC8dX4Nt5bRGXclvV8N4hLR09T-yE")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003906962727")
URL_API = os.getenv("API_URL", "https://aviator-round-production.up.railway.app/api/aviator/rounds/1?limit=30")

bot = telebot.TeleBot(token=TOKEN)

def enviar_telegram(texto):
    try:
        bot.send_message(chat_id=CHAT_ID, text=texto)
        print(f"📲 Mensaje enviado a Telegram: {texto}")
    except Exception as e:
        print(f"❌ Error enviando a Telegram: {e}")

def obtener_api():
    try:
        response = requests.get(URL_API, timeout=10)
        return response.json()
    except Exception as e:
        print(f"⚠️ Error de conexión API: {e}")
        return None

# =============================================================================
# FILTRO PRO AVIATOR — v2.2  GALE INTELIGENTE
# Cuota: 1.70x | Solo lógica de señales — montos los define el jugador
# =============================================================================

CUOTA = 1.70

def filtro_pro_170(results: list,
                   trades: list,
                   i: int,
                   last_trade_index: int) -> bool:
    """
    Evalúa si las condiciones del mercado aprueban una entrada.

    Parámetros
    ----------
    results           : lista de multiplicadores históricos (float)
    trades            : lista ["win"|"loss"] — un elemento por ciclo completo
    i                 : índice de la ronda que está por jugarse
    last_trade_index  : índice de la última entrada (-999 al inicio)

    Retorna True → señal aprobada | False → no entrar
    """
    if i < 6:
        return False

    last6 = results[i - 6: i]
    last5 = results[i - 5: i]
    last4 = results[i - 4: i]
    last3 = results[i - 3: i]

    # COOLDOWN
    if i - last_trade_index < 5:
        return False

    # BLOQUEOS CRÍTICOS
    if any(r < 1.30 for r in last3):
        return False
    if sum(1 for r in last4 if r < 1.50) >= 2:
        return False
    if last3[-1] < 1.50:
        return False
    if sum(1 for r in last5 if r < 1.40) >= 2:
        return False

    # CONDICIONES FUERTES
    if sum(1 for r in last3 if r >= 1.70) < 2:
        return False
    if sum(1 for r in last5 if r >= 1.80) < 3:
        return False
    if sum(1 for r in last6 if r < 1.50) > 1:
        return False

    # SCORE AVANZADO
    score = 0
    for r in last6:
        if r >= 2.0:   score += 3
        elif r >= 1.7: score += 2
        elif r >= 1.5: score += 1
        else:          score -= 3
    if score < 6:
        return False

    # CONTROL DE RACHAS
    if len(trades) >= 1 and trades[-1] == "loss":
        return False
    if len(trades) >= 2 and trades[-2:] == ["win", "win"]:
        return False

    return True


# =============================================================================
# VARIABLES DE ESTADO — inicializar al arrancar el bot
# =============================================================================

historial        = []     # multiplicadores de rondas terminadas
trades           = []     # ["win"|"loss"] por ciclo completo
last_trade_index = -999   # índice de la última entrada
gale_pendiente   = False  # True cuando E1 perdió y espera próxima señal


# =============================================================================
# FUNCIONES PRINCIPALES — implementar en el bot
# =============================================================================

def on_ronda_terminada(multiplicador: float):
    """Llamar cada vez que una ronda del juego termina."""
    historial.append(multiplicador)


def on_ronda_por_comenzar() -> str:
    """
    Llamar cuando una ronda está por comenzar.

    Retorna
    -------
    "SEÑAL"       → entrar con apuesta base (E1)
    "SEÑAL_GALE"  → entrar con apuesta base + gale (E1 + E2 juntos)
    "ESPERAR"     → no entrar
    """
    global last_trade_index

    i = len(historial)

    if filtro_pro_170(historial, trades, i, last_trade_index):
        last_trade_index = i
        if gale_pendiente:
            return "SEÑAL_GALE"
        else:
            return "SEÑAL"

    return "ESPERAR"


def on_entrada_terminada(multiplicador: float, era_gale: bool):
    """
    Llamar cuando termina la ronda donde entró el bot.

    Parámetros
    ----------
    multiplicador : crash de esa ronda
    era_gale      : True si fue una entrada SEÑAL_GALE (E1+E2 juntos)
    """
    global gale_pendiente

    if era_gale:
        # Ciclo completo con gale
        if multiplicador >= CUOTA:
            trades.append("win")
        else:
            trades.append("loss")   # ← LÍNEA CRÍTICA — no omitir
        gale_pendiente = False

    else:
        # Solo E1
        if multiplicador >= CUOTA:
            trades.append("win")
        else:
            gale_pendiente = True   # E1 perdió → esperar próxima señal
            # NO agregar a trades todavía


# =============================================================================
# BUCLE DE EJECUCIÓN
# =============================================================================

def ejecutar_bot():
    global last_trade_index, historial, trades, gale_pendiente
    
    print("🚀 Bot Aviator Gale Inteligente v2.2 Iniciado...")
    print(f"📡 API: {URL_API}")
    print(f"📲 Telegram: {CHAT_ID}")
    
    # Inicialización de historial con datos previos
    while True:
        data = obtener_api()
        if data and isinstance(data, list) and len(data) >= 6:
            historial = [float(x['max_multiplier']) for x in data][::-1]
            last_id_procesado = data[0]['id']
            print(f"📊 Historial inicial cargado con {len(historial)} rondas.")
            print(f"Último ID procesado: {last_id_procesado}")
            break
        print("⏳ Esperando datos válidos de la API...")
        time.sleep(5)
        
    apuesta_activa = None  # Puede ser "E1" o "GALE"
    
    while True:
        try:
            data = obtener_api()
            if not data or not isinstance(data, list) or len(data) < 6:
                time.sleep(2)
                continue
                
            ronda_actual = data[0]
            ronda_id = ronda_actual['id']
            ronda_val = float(ronda_actual['max_multiplier'])
            
            # Si la ronda es la misma, esperamos
            if ronda_id == last_id_procesado:
                time.sleep(1)
                continue
                
            last_id_procesado = ronda_id
            print(f"📈 Nueva Ronda Detectada: {ronda_id} -> {ronda_val}x")
            
            # 1. Procesar resultado de la apuesta anterior si existía
            if apuesta_activa == "E1":
                on_entrada_terminada(ronda_val, era_gale=False)
                if ronda_val >= CUOTA:
                    enviar_telegram(f"✅ GANADO — Crash {ronda_val:.2f}x")
                else:
                    enviar_telegram("⏳ E1 PERDIÓ — Gale en próxima señal")
                apuesta_activa = None
                
            elif apuesta_activa == "GALE":
                on_entrada_terminada(ronda_val, era_gale=True)
                if ronda_val >= CUOTA:
                    enviar_telegram(f"✅ GALE GANADO — Crash {ronda_val:.2f}x")
                else:
                    enviar_telegram(f"❌ PERDIDO — Crash {ronda_val:.2f}x")
                apuesta_activa = None
                
            # 2. Registrar la ronda terminada en el historial
            on_ronda_terminada(ronda_val)
            
            # 3. Evaluar si se debe entrar en la ronda que viene
            decision = on_ronda_por_comenzar()
            if decision == "SEÑAL":
                enviar_telegram("🟢 SEÑAL — Cashout 1.70x")
                apuesta_activa = "E1"
            elif decision == "SEÑAL_GALE":
                enviar_telegram("⚡ SEÑAL + GALE — Cashout 1.70x")
                apuesta_activa = "GALE"
                
        except Exception as e:
            print(f"💥 Error en el bucle: {e}")
            time.sleep(5)

if __name__ == "__main__":
    ejecutar_bot()
