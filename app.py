#!/usr/bin/env python3
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import yfinance as yf
import ta
import pandas as pd
from datetime import datetime
import threading
import time
import json
import os
from collections import deque
import traceback

app = Flask(__name__)
CORS(app)

CAPITALE_INIZIALE = 10000.0
TICKERS = [
    "AAPL", "NVDA", "MSFT", "TSLA", "AMD", "GOOGL", "META",
    "MP", "UUUU", "CRML", "NB", "AREC",
    "SOFI", "ACHR", "GRAB", "PLTR", "RIVN"
]
RISCHIO_PER_TRADE = 0.10
PROB_ENTRATA = 75
PROB_USCITA = 45
STOP_LOSS = 0.95
SCAN_INTERVAL = 45
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "portfolio.json")

class Portafoglio:
    def __init__(self):
        self.cash = CAPITALE_INIZIALE
        self.posizioni = {}
        self.storico = []
        self.equity_curve = deque(maxlen=500)
        self.capitalizzazione = CAPITALE_INIZIALE
        self.robot_running = True
        self.last_scan = None
        self.scan_results = {}
        self.load()

    def save(self):
        data = {
            "cash": self.cash,
            "posizioni": self.posizioni,
            "storico": self.storico[-200:],
            "equity_curve": list(self.equity_curve),
            "capitalizzazione": self.capitalizzazione
        }
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, default=str)

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    data = json.load(f)
                self.cash = data.get("cash", CAPITALE_INIZIALE)
                self.posizioni = data.get("posizioni", {})
                self.storico = data.get("storico", [])
                self.equity_curve = deque(data.get("equity_curve", []), maxlen=500)
                self.capitalizzazione = data.get("capitalizzazione", CAPITALE_INIZIALE)
            except Exception:
                pass

    def valore_totale(self, prezzi_attuali):
        val_pos = 0.0
        for t, p in self.posizioni.items():
            if t in prezzi_attuali and prezzi_attuali[t] > 0:
                val_pos += p["qty"] * prezzi_attuali[t]
        self.capitalizzazione = self.cash + val_pos
        return self.capitalizzazione

    def reset(self):
        self.cash = CAPITALE_INIZIALE
        self.posizioni = {}
        self.storico = []
        self.equity_curve = deque(maxlen=500)
        self.capitalizzazione = CAPITALE_INIZIALE
        self.scan_results = {}
        self.save()

portafoglio = Portafoglio()
_lock = threading.Lock()

def calcola_probabilita_vincita(ticker):
    try:
        df = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 55:
            return 0, 0.0
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        if len(close) < 55:
            return 0, 0.0
        prezzo = float(close.iloc[-1])
        rsi = ta.momentum.RSIIndicator(close).rsi()
        macd_ind = ta.trend.MACD(close)
        macd = macd_ind.macd()
        ema50 = ta.trend.EMAIndicator(close, window=50).ema_indicator()
        score = 50.0
        rsi_val = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50
        macd_curr = float(macd.iloc[-1]) if not pd.isna(macd.iloc[-1]) else 0
        macd_prev = float(macd.iloc[-2]) if len(macd) > 1 and not pd.isna(macd.iloc[-2]) else 0
        ema_val = float(ema50.iloc[-1]) if not pd.isna(ema50.iloc[-1]) else prezzo
        if rsi_val < 30: score += 20
        elif rsi_val > 70: score -= 20
        if macd_curr > macd_prev: score += 15
        if prezzo > ema_val: score += 15
        if len(rsi) > 2:
            rsi_prev = float(rsi.iloc[-2])
            if rsi_val > rsi_prev and rsi_val < 40: score += 5
        prob = max(5.0, min(95.0, score))
        return prob, prezzo
    except Exception:
        return 0, 0.0

def esegui_trade(ticker, azione, qty, prezzo, motivo=""):
    with _lock:
        now = datetime.now().isoformat(timespec="seconds")
        if azione == "COMPRA":
            costo = qty * prezzo
            if costo > portafoglio.cash:
                qty = int(portafoglio.cash / prezzo)
                if qty <= 0: return False
                costo = qty * prezzo
            portafoglio.cash -= costo
            if ticker in portafoglio.posizioni:
                p = portafoglio.posizioni[ticker]
                old_qty = p["qty"]
                old_cost = p["prezzo_medio"] * old_qty
                new_qty = old_qty + qty
                p["qty"] = new_qty
                p["prezzo_medio"] = (old_cost + costo) / new_qty
            else:
                portafoglio.posizioni[ticker] = {"qty": qty, "prezzo_medio": prezzo, "entry_time": now}
            portafoglio.storico.append({
                "time": now, "ticker": ticker, "azione": "COMPRA", "qty": qty,
                "prezzo": round(prezzo, 4), "valore": round(costo, 2),
                "motivo": motivo or "Segnale ingresso", "cash_dopo": round(portafoglio.cash, 2)
            })
            return True
        elif azione == "VENDI":
            if ticker not in portafoglio.posizioni: return False
            p = portafoglio.posizioni[ticker]
            qty = min(qty, p["qty"])
            if qty <= 0: return False
            ricavo = qty * prezzo
            costo_medio = p["prezzo_medio"] * qty
            pnl = ricavo - costo_medio
            pnl_pct = (prezzo / p["prezzo_medio"] - 1) * 100 if p["prezzo_medio"] else 0
            portafoglio.cash += ricavo
            p["qty"] -= qty
            if p["qty"] <= 0: del portafoglio.posizioni[ticker]
            portafoglio.storico.append({
                "time": now, "ticker": ticker, "azione": "VENDI", "qty": qty,
                "prezzo": round(prezzo, 4), "valore": round(ricavo, 2),
                "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                "motivo": motivo or "Segnale uscita", "cash_dopo": round(portafoglio.cash, 2)
            })
            return True
    return False

def job_robot():
    prezzi = {}
    scan_data = {}
    for ticker in TICKERS:
        try:
            hist = yf.Ticker(ticker).history(period="1d")
            prezzi[ticker] = float(hist["Close"].iloc[-1]) if not hist.empty else 0.0
        except Exception:
            prezzi[ticker] = 0.0
    for ticker in TICKERS:
        try:
            prob, prezzo = calcola_probabilita_vincita(ticker)
            if prezzo <= 0: continue
            prezzi[ticker] = prezzo
            action = None
            note = ""
            if ticker in portafoglio.posizioni:
                p_medio = portafoglio.posizioni[ticker]["prezzo_medio"]
                if prezzo < p_medio * STOP_LOSS:
                    qty = portafoglio.posizioni[ticker]["qty"]
                    esegui_trade(ticker, "VENDI", qty, prezzo, "STOP LOSS")
                    action = "STOP LOSS"
                    note = f"Venduto a -{((1 - prezzo/p_medio)*100):.1f}%"
            if (prob > PROB_ENTRATA and ticker not in portafoglio.posizioni and portafoglio.cash > 50):
                importo = portafoglio.cash * RISCHIO_PER_TRADE
                qty = int(importo / prezzo)
                if qty > 0:
                    ok = esegui_trade(ticker, "COMPRA", qty, prezzo, f"Prob {prob:.0f}%")
                    if ok:
                        action = "COMPRA"
                        note = f"Entrata Prob {prob:.0f}%"
            if (prob < PROB_USCITA and ticker in portafoglio.posizioni):
                qty = portafoglio.posizioni[ticker]["qty"]
                esegui_trade(ticker, "VENDI", qty, prezzo, f"Prob bassa {prob:.0f}%")
                action = "VENDI"
                note = f"Uscita Prob {prob:.0f}%"
            pos_info = None
            if ticker in portafoglio.posizioni:
                p = portafoglio.posizioni[ticker]
                pnl = (prezzo - p["prezzo_medio"]) * p["qty"]
                pnl_pct = (prezzo / p["prezzo_medio"] - 1) * 100
                pos_info = {"qty": p["qty"], "prezzo_medio": round(p["prezzo_medio"], 4),
                            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2)}
            scan_data[ticker] = {"prob": round(prob, 1), "prezzo": round(prezzo, 4),
                                 "action": action, "note": note, "posizione": pos_info}
        except Exception:
            traceback.print_exc()
    with _lock:
        portafoglio.scan_results = scan_data
        portafoglio.last_scan = datetime.now().isoformat(timespec="seconds")
        val = portafoglio.valore_totale(prezzi)
        portafoglio.equity_curve.append({"time": portafoglio.last_scan, "value": round(val, 2)})
        portafoglio.save()

def robot_loop():
    while True:
        if portafoglio.robot_running:
            try: job_robot()
            except Exception as e: print(f"Robot error: {e}")
        time.sleep(SCAN_INTERVAL)

_thread = threading.Thread(target=robot_loop, daemon=True)
_thread.start()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    with _lock:
        prezzi = {}
        for t in list(portafoglio.posizioni.keys()) + TICKERS:
            if t not in prezzi:
                try:
                    h = yf.Ticker(t).history(period="1d")
                    prezzi[t] = float(h["Close"].iloc[-1]) if not h.empty else 0
                except Exception:
                    prezzi[t] = 0
        val = portafoglio.valore_totale(prezzi)
        guadagno = val - CAPITALE_INIZIALE
        guadagno_pct = ((val / CAPITALE_INIZIALE) - 1) * 100
        positions = []
        for t, p in portafoglio.posizioni.items():
            px = prezzi.get(t, p["prezzo_medio"])
            pnl = (px - p["prezzo_medio"]) * p["qty"]
            positions.append({
                "ticker": t, "qty": p["qty"], "prezzo_medio": round(p["prezzo_medio"], 4),
                "prezzo_attuale": round(px, 4), "valore": round(p["qty"] * px, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round((px / p["prezzo_medio"] - 1) * 100, 2) if p["prezzo_medio"] else 0,
                "entry_time": p.get("entry_time", "")
            })
        realized = sum(t.get("pnl", 0) for t in portafoglio.storico if t.get("azione") == "VENDI")
        return jsonify({
            "cash": round(portafoglio.cash, 2),
            "capitalizzazione": round(val, 2),
            "guadagno": round(guadagno, 2),
            "guadagno_pct": round(guadagno_pct, 2),
            "realized_pnl": round(realized, 2),
            "posizioni": positions,
            "num_posizioni": len(positions),
            "robot_running": portafoglio.robot_running,
            "last_scan": portafoglio.last_scan,
            "scan_results": portafoglio.scan_results,
            "storico": list(reversed(portafoglio.storico[-50:])),
            "equity_curve": list(portafoglio.equity_curve),
            "config": {
                "capitale_iniziale": CAPITALE_INIZIALE,
                "rischio": RISCHIO_PER_TRADE * 100,
                "prob_entrata": PROB_ENTRATA,
                "prob_uscita": PROB_USCITA,
                "stop_loss": round((1 - STOP_LOSS) * 100, 1),
                "tickers": TICKERS
            }
        })

@app.route("/api/scan", methods=["POST"])
def api_scan():
    try:
        job_robot()
        return jsonify({"ok": True, "message": "Scansione completata"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/start", methods=["POST"])
def api_start():
    portafoglio.robot_running = True
    return jsonify({"ok": True, "running": True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    portafoglio.robot_running = False
    return jsonify({"ok": True, "running": False})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    with _lock:
        portafoglio.reset()
    return jsonify({"ok": True})

if __name__ == "__main__":
    if not portafoglio.equity_curve:
        portafoglio.equity_curve.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "value": CAPITALE_INIZIALE
        })
        portafoglio.save()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
