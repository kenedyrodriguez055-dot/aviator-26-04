import statistics
import telebot
import requests
import time
import datetime
import os
import sys

# =============================================================================
# CONFIGURACIÓN Y CREDENCIALES
# =============================================================================

TOKEN    = os.getenv("TELEGRAM_TOKEN", "8769091104:AAGlbmfJxf4BN7adCHzbrLqXFAODzyl6QCQ")
CANAL_ID = os.getenv("TELEGRAM_CHAT_ID", "-1003956115365")
URL_API  = os.getenv("API_URL", "https://aviator-round-production.up.railway.app/api/aviator/rounds/1?limit=15")

bot = telebot.TeleBot(TOKEN, parse_mode="MARKDOWN")

# ─────────────────────────────────────────────────────────────────────────────
# ESTADO GLOBAL
# ─────────────────────────────────────────────────────────────────────────────

historial        = []   # multiplicadores de rondas terminadas
last_trade_index = -999 # índice de la última entrada
esperando_e1     = False
esperando_gale   = False
cuota_activa     = None # cuota usada en la señal actual
last_round_id    = None # para evitar duplicados de la API

# --- NUEVOS CONTADORES PARA RESUMEN ---
sesion_wins      = 0
sesion_losses    = 0
historial_señales = []  # Lista de iconos ✅/❌

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 1 — Cuota dinámica
# ─────────────────────────────────────────────────────────────────────────────

def elegir_cuota(last6: list, last3: list) -> float:
    avg6  = sum(last6) / 6
    avg3  = sum(last3) / 3
    vol   = statistics.pstdev(last6)
    score = sum(3 if r >= 2.0 else 2 if r >= 1.7 else 1 if r >= 1.5 else -3
                for r in last6)
    accel = avg3 - avg6
    min3  = min(last3)

    if avg6 >= 2.5 and score >= 10 and accel >= 0 and vol < 2.0:
        return 1.70
    if avg6 >= 2.0 and score >= 8 and min3 >= 1.70:
        return 1.70

    if avg6 >= 1.9 and score >= 7:
        return 1.60

    return 1.50

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 2 — Filtro de mercado
# ─────────────────────────────────────────────────────────────────────────────

def evaluar_filtro(results: list, i: int, lti: int) -> float | None:
    if i < 15:
        return None

    last_v = results[i - 15: i]
    last6  = results[i - 6: i]
    last5  = results[i - 5: i]
    last4  = results[i - 4: i]
    last3  = results[i - 3: i]

    if sum(1 for r in last_v if r < 1.70) / 15 >= 0.30:
        return None
    if i - lti < 5:
        return None
    if any(r < 1.30 for r in last3):        return None
    if sum(1 for r in last4 if r < 1.50) >= 2: return None
    if last3[-1] < 1.50:                    return None
    if sum(1 for r in last5 if r < 1.40) >= 2: return None
    if sum(1 for r in last3 if r >= 1.70) < 2:  return None
    if sum(1 for r in last5 if r >= 1.80) < 3:  return None
    if sum(1 for r in last6 if r < 1.50) > 1:   return None

    score = sum(3 if r >= 2.0 else 2 if r >= 1.7 else 1 if r >= 1.5 else -3
                for r in last6)
    if score < 6:
        return None
    if sum(last3) / 3 <= sum(last6) / 6:
        return None
    if statistics.pstdev(last6) >= 5.0:
        return None
    if any(r > 8.0 for r in last6):
        return None
    if min(last3) < 1.60:
        return None

    return elegir_cuota(last6, last3)

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 3 — Lógica principal
# ─────────────────────────────────────────────────────────────────────────────

def enviar_telegram(msg):
    try:
        bot.send_message(chat_id=CANAL_ID, text=msg)
    except Exception as e:
        print(f"❌ Error enviando mensaje: {e}")

def enviar_resumen_sesion():
    global sesion_wins, sesion_losses, historial_señales
    total = sesion_wins + sesion_losses
    if total == 0: return
    
    wr = (sesion_wins / total) * 100
    iconos = "".join(historial_señales)
    
    msg = (
        f"📊 *RESUMEN DE SEÑALES (Últimas 10)*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Ganadas: `{sesion_wins}`\n"
        f"❌ Perdidas: `{sesion_losses}`\n"
        f"📈 Efectividad: `{wr:.1f}%`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Historial: {iconos}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Contadores reiniciados para la próxima sesión_"
    )
    enviar_telegram(msg)
    # Reiniciamos contadores para el bloque de 10 siguiente
    sesion_wins = 0
    sesion_losses = 0
    historial_señales = []

def procesar_ronda(multiplicador: float):
    global historial, last_trade_index, esperando_e1, esperando_gale, cuota_activa
    global sesion_wins, sesion_losses, historial_señales

    # ── 1. Si estábamos esperando E1 ─────────────────────────────────────────
    if esperando_e1:
        esperando_e1 = False
        if multiplicador >= cuota_activa:
            print(f"✅ E1 GANADO: {multiplicador}x")
            sesion_wins += 1
            historial_señales.append("✅")
            msg = (
                f"✅ *SEÑAL GANADA — E1*\n"
                f"Crash: `{multiplicador:.2f}x`\n"
                f"Cashout: `{cuota_activa:.2f}x`\n"
                f"Sin gale necesario ✓"
            )
            enviar_telegram(msg)
            cuota_activa = None
            if len(historial_señales) >= 10: enviar_resumen_sesion()
        else:
            print(f"⚠️ E1 PERDIDO: {multiplicador}x. Activando Gale.")
            esperando_gale = True
            msg = (
                f"⚠️ *E1 PERDIÓ — ACTIVAR GALE*\n"
                f"Crash E1: `{multiplicador:.2f}x`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💸 Gale: `$81.000`\n"
                f"🎯 Cashout: `{cuota_activa:.2f}x`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_Entra en la próxima ronda con el gale_"
            )
            enviar_telegram(msg)
        
        historial.append(multiplicador)
        return

    # ── 2. Si estábamos esperando Gale ───────────────────────────────────────
    if esperando_gale:
        esperando_gale = False
        if multiplicador >= cuota_activa:
            print(f"✅ GALE GANADO: {multiplicador}x")
            sesion_wins += 1
            historial_señales.append("✅")
            msg = (
                f"✅ *GALE GANADO*\n"
                f"Crash: `{multiplicador:.2f}x`\n"
                f"Cashout: `{cuota_activa:.2f}x`\n"
                f"Ciclo cerrado ✓"
            )
        else:
            print(f"❌ GALE PERDIDO: {multiplicador}x")
            sesion_losses += 1
            historial_señales.append("❌")
            msg = (
                f"❌ *GALE PERDIDO*\n"
                f"Crash: `{multiplicador:.2f}x`\n"
                f"Cashout objetivo: `{cuota_activa:.2f}x`\n"
                f"Ciclo perdido ✗"
            )
        enviar_telegram(msg)
        cuota_activa = None
        historial.append(multiplicador)
        if len(historial_señales) >= 10: enviar_resumen_sesion()
        return

    # ── 3. Lógica normal ─────────────────────────────────────────────────────
    historial.append(multiplicador)
    i = len(historial)
    
    cuota = evaluar_filtro(historial, i, last_trade_index)

    if cuota is not None:
        print(f"🔥 SEÑAL DETECTADA: {cuota}x")
        last_trade_index = i
        cuota_activa     = cuota
        esperando_e1     = True
        esperando_gale   = False

        emoji_cuota = "🔥" if cuota == 1.70 else "⚡" if cuota == 1.60 else "✳️"

        msg = (
            f"{emoji_cuota} *SEÑAL DETECTADA*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Cashout: `{cuota:.2f}x`\n"
            f"💰 Entrada: `$10.000`\n"
            f"🔄 Gale: $81.000 si E1 pierde\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"_Entra en la próxima ronda_"
        )
        enviar_telegram(msg)

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 4 — Ciclo de ejecución
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global last_round_id, historial
    print("🚀 Bot Aviator Pro v2.0 Dinámico Iniciado...")
    print(f"📡 API: {URL_API}")
    print(f"📲 Telegram Canal: {CANAL_ID}")
    
    while True:
        try:
            response = requests.get(URL_API, timeout=10)
            data = response.json()
            
            if not data or not isinstance(data, list):
                time.sleep(5)
                continue

            new_rounds = []
            for r in data:
                rid = r.get("id")
                if last_round_id is not None and rid <= last_round_id:
                    break
                new_rounds.append(r)
            
            if not new_rounds:
                if last_round_id is None and not historial:
                    historial = [float(x.get("max_multiplier", 1.0)) for x in data][::-1]
                    last_round_id = data[0].get("id")
                    print(f"📊 Historial inicial cargado: {len(historial)} rondas.")
                
                time.sleep(5)
                continue

            new_rounds.reverse()
            
            for r in new_rounds:
                last_round_id = r.get("id")
                mult = float(r.get("max_multiplier", 1.0))
                now = datetime.datetime.now().strftime('%H:%M:%S')
                print(f"[{now}] Nueva Ronda: {last_round_id} -> {mult}x")
                procesar_ronda(mult)

        except Exception as e:
            print(f"💥 Error en el ciclo: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()