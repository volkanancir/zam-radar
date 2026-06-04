#!/usr/bin/env python3
"""
ZAM RADAR - Mobil Uygulama Sunucusu (Play Store Hazir)
=======================================================
FastAPI + PWA + Google AdSense + reklam alani.
Bu sunucuyu ucretsiz bir hosting'e (Render/Railway) deploy et,
sonra PWABuilder.com ile 5 dakikada APK'ya cevirip
Google Play Store'a yukle.

KURULUM:
    pip install fastapi uvicorn requests

CALISTIRMA:
    python zam_radar_app.py                  # http://localhost:8080
    python zam_radar_app.py --port 3000

PLAY STORE YAYINLAMA (5 adim):
    1. Bu sunucuyu Render.com'a deploy et (ucretsiz)
    2. https://pwabuilder.com adresine sunucu URL'ini gir
    3. "Package for Stores" tikla -> APK indir
    4. Google Play Console'da uygulama olustur ($25 tek seferlik)
    5. APK'yi yukle + AdSense bagla -> yayinda
"""

import os, re, sys, json, time, random, sqlite3, requests
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
import uvicorn
import asyncio
from apscheduler.schedulers.background import BackgroundScheduler

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except: pass

# ───── AYARLAR ─────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ADSENSE_CLIENT = os.getenv("ADSENSE_CLIENT", "ca-pub-XXXXXXXXXXXXXXXX")
ADSENSE_SLOT   = os.getenv("ADSENSE_SLOT", "1234567890")

# Premium fiyat (Telegram Stars)
PREMIUM_AYLIK_STARS = 50   # 50 Stars/ay (~15 TL)
PREMIUM_YILLIK_STARS = 400 # 400 Stars/yil (~120 TL)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zam_radar_premium.db")

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q=zam+TL+fiyat+art%C4%B1%C5%9F%C4%B1&hl=tr&gl=TR&ceid=TR:tr"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

KATEGORILER = {
    "akaryakıt":  {"emoji":"⛽","renk":"#e74c3c","k":"benzin|motorin|mazot|akaryakıt|LPG|otogaz"},
    "sigara":     {"emoji":"🚬","renk":"#8e44ad","k":"sigara|tütün|alkol|içki|rakı"},
    "gıda":       {"emoji":"🍞","renk":"#e67e22","k":"gıda|ekmek|süt|yumurta|peynir|et |tavuk"},
    "elektrik":   {"emoji":"⚡","renk":"#f1c40f","k":"elektrik|doğalgaz|enerji|su "},
    "ulaşım":     {"emoji":"🚌","renk":"#3498db","k":"ulaşım|otobüs|metro|taksi|bilet|köprü|otoyol"},
    "emekli":     {"emoji":"👴","renk":"#2ecc71","k":"emekli|memur|asgari|maaş|aylık|ikramiye"},
    "vergi":      {"emoji":"📊","renk":"#95a5a6","k":"vergi|harç|MTV|KDV|tapu|noter|pasaport"},
    "konut":      {"emoji":"🏠","renk":"#e91e63","k":"kira|konut|arsa|imar|inşaat"},
    "döviz":      {"emoji":"💵","renk":"#4caf50","k":"dolar|euro|döviz|sterlin|altın"},
    "internet":   {"emoji":"📱","renk":"#2196f3","k":"internet|fatura|GSM|telefon"},
    "sağlık":     {"emoji":"💊","renk":"#00bcd4","k":"ilaç|hastane|muayene|eczane"},
}

SONUC_ONBELLEK = {"ts":0, "data":[]}

# ───── HABER MOTORU ─────
def _temizle(t): return " ".join(re.sub(r'<[^>]+>|&[a-z]+;',' ',t).split()).strip() if t else ""

def _kategori(b): 
    bl = b.lower()
    for kat,v in KATEGORILER.items():
        if any(k in bl for k in v["k"].split("|")): return kat
    return "genel"

def _fiyat(b):
    for p in [r'%(\d+)\s*zam', r'(\d+)\s*TL[\'`]', r'(\d+)\s*liraya', r'(\d+)\s*TL\s*oldu']:
        m = re.search(p, b.lower())
        if m: return m.group(0)
    return ""

def haberleri_getir():
    global SONUC_ONBELLEK
    if time.time() - SONUC_ONBELLEK["ts"] < 300 and SONUC_ONBELLEK["data"]:
        return SONUC_ONBELLEK["data"]

    s = requests.Session()
    s.headers.update({"User-Agent":random.choice(USER_AGENTS), "Accept-Language":"tr-TR"})
    esik = datetime.now() - timedelta(hours=36)
    gorulen = set()
    haberler = []

    try:
        r = s.get(GOOGLE_NEWS_RSS, timeout=15)
        for item in re.findall(r'<item>(.*?)</item>', r.text, re.DOTALL):
            t = re.search(r'<title>(.*?)</title>', item)
            l = re.search(r'<link>(.*?)</link>', item)
            src = re.search(r'<source[^>]*>(.*?)</source>', item)
            d = re.search(r'<pubDate>(.*?)</pubDate>', item)
            if not t: continue

            baslik = _temizle(t.group(1))
            url = l.group(1) if l else ""
            kaynak = _temizle(src.group(1)) if src else ""
            try:
                if datetime.strptime(d.group(1)[:25], "%a, %d %b %Y %H:%M:%S") < esik: continue
            except: continue
            if not any(k in baslik.lower() for k in "zam|arttı|artış|yükseldi|fiyat|oldu|çıktı".split("|")): continue

            key = re.sub(r'\s+','',baslik[:70]).lower()
            if key in gorulen: continue
            gorulen.add(key)
            haberler.append({"baslik":baslik,"kaynak":kaynak,"url":url,"kategori":_kategori(baslik),"fiyat":_fiyat(baslik)})
    except Exception as e:
        print(f"RSS: {e}")

    SONUC_ONBELLEK = {"ts":time.time(), "data":haberler}
    return haberler


# ───── MANIFEST.JSON ─────
MANIFEST = {
    "name": "Zam Radar - Bugun Neye Zam Geldi?",
    "short_name": "Zam Radar",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0f0f1a",
    "theme_color": "#e74c3c",
    "icons": [{"src":"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📰</text></svg>","sizes":"100x100","type":"image/svg+xml"}]
}


# ───── HTML ARAYUZ (REKLAMLI) ─────
HTML_SAYFA = """<!DOCTYPE html><html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="theme-color" content="#0f0f1a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="/manifest.json">
<title>Zam Radar</title>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={{ADSENSE_CLIENT}}" crossorigin="anonymous"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f0f1a;color:#e0e0e0;padding:16px 16px 100px;min-height:100vh;-webkit-font-smoothing:antialiased}
.header{text-align:center;padding:20px 0 16px}
.header h1{font-size:22px;background:linear-gradient(135deg,#e74c3c,#f39c12);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:800}
.header .date{color:#888;font-size:13px;margin-top:4px}

/* Premium banner */
.premium-banner{display:flex;align-items:center;justify-content:space-between;background:linear-gradient(135deg,#1a1a3e,#2a1a4e);border:1px solid #3a2a5e;border-radius:12px;padding:12px 14px;margin-bottom:16px}
.prem-left{display:flex;align-items:center;gap:10px;flex:1}
.prem-icon{font-size:28px}
.prem-title{font-size:13px;font-weight:700;color:#c084fc}
.prem-sub{font-size:11px;color:#888;margin-top:2px}
.prem-btn{background:#8b5cf6;color:#fff;padding:8px 18px;border-radius:8px;font-size:13px;font-weight:600;text-decoration:none;flex-shrink:0}
.prem-btn:active{background:#7c3aed}

.stats{display:flex;gap:8px;margin-bottom:20px}
.stat{flex:1;background:#1a1a2e;border-radius:12px;padding:14px;text-align:center;border:1px solid #252540}
.stat .num{font-size:26px;font-weight:700;color:#e74c3c}
.stat .label{font-size:11px;color:#666;margin-top:2px}

.kategori-baslik{display:flex;align-items:center;gap:12px;padding:14px;background:#1a1a2e;border-radius:12px;margin-bottom:10px;cursor:pointer;border:1px solid #252540}
.kategori-baslik:active{background:#242440}
.kat-emoji{font-size:26px;width:42px;height:42px;display:flex;align-items:center;justify-content:center;border-radius:10px;flex-shrink:0}
.kat-info{flex:1}.kat-ad{font-size:14px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px}.kat-sayi{font-size:11px;color:#666}
.kat-ok{font-size:16px;color:#444;transition:transform .2s}.kat-ok.acik{transform:rotate(180deg)}
.haber-listesi{display:none;padding:0 0 12px}.haber-listesi.acik{display:block}
.haber-kart{background:#1a1a2e;border-radius:10px;padding:14px;margin-bottom:8px;border-left:3px solid #333;cursor:pointer;transition:all .15s}
.haber-kart:active{background:#252540}.haber-kart .baslik{font-size:14px;line-height:1.4;margin-bottom:6px}.haber-kart .alt{display:flex;justify-content:space-between;font-size:11px;color:#555}
.fiyat-badge{background:#e74c3c22;color:#e74c3c;padding:2px 8px;border-radius:6px;font-weight:600;font-size:11px}

/* === REKLAM ALANI === */
.ad-container{position:fixed;bottom:0;left:0;right:0;background:#0f0f1a;padding:8px;border-top:1px solid #1a1a2e;z-index:100;text-align:center;min-height:80px;display:flex;align-items:center;justify-content:center}
.ad-container ins{display:block;width:320px;height:50px;margin:0 auto}
.ad-label{font-size:9px;color:#444;text-align:center;padding:2px 0;letter-spacing:2px;text-transform:uppercase}

.yenile-btn{position:fixed;bottom:100px;right:16px;width:44px;height:44px;border-radius:50%;background:#e74c3c;border:none;color:#fff;font-size:20px;cursor:pointer;box-shadow:0 4px 16px rgba(231,76,60,.4);display:flex;align-items:center;justify-content:center;z-index:99}
.yenile-btn:active{transform:scale(.9)}.yenile-btn.don{animation:spin .8s linear infinite}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}

.bos-durum{text-align:center;padding:60px 20px;color:#444}.bos-durum .icon{font-size:56px;margin-bottom:12px}.bos-durum p{font-size:15px}
.splash{position:fixed;inset:0;background:#0f0f1a;display:flex;align-items:center;justify-content:center;z-index:999;transition:opacity .4s}
.splash.hide{opacity:0;pointer-events:none}.splash h1{font-size:32px;background:linear-gradient(135deg,#e74c3c,#f39c12);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
</style></head>
<body>
<div class="splash" id="splash"><h1>⚡ ZAM RADAR</h1></div>

<div class="header"><h1>⚡ ZAM RADAR</h1><div class="date" id="tarih"></div></div>

<div class="premium-banner">
  <div class="prem-left">
    <div class="prem-icon">💎</div>
    <div class="prem-text">
      <div class="prem-title">Premium'a Gec</div>
      <div class="prem-sub">Reklamsiz + Her sabah Telegram bildirimi</div>
    </div>
  </div>
  <a class="prem-btn" href="https://t.me/{{BOT_USERNAME}}">Gec</a>
</div>

<div class="stats">
  <div class="stat"><div class="num" id="toplam">0</div><div class="label">Zam Haberi</div></div>
  <div class="stat"><div class="num" id="katsayi">0</div><div class="label">Kategori</div></div>
</div>

<div id="kategoriler"></div>
<div id="bos" class="bos-durum" style="display:none"><div class="icon">☕</div><p>Bugunluk zam haberi yok</p><p style="font-size:12px;color:#555;margin-top:4px">Rahat bir nefes alabilirsin</p></div>

<div class="ad-label">REKLAM</div>
<div class="ad-container">
  <ins class="adsbygoogle" style="display:inline-block;width:320px;height:50px" data-ad-client="{{ADSENSE_CLIENT}}" data-ad-slot="{{ADSENSE_SLOT}}"></ins>
</div>

<button class="yenile-btn" onclick="yenile()" id="btn">↻</button>

<script>
const KAT_BILGI={{KAT_JSON}};

function toggle(el,listId){
  const lst=document.getElementById(listId);
  const ok=el.querySelector('.kat-ok');
  const open=lst.classList.contains('acik');
  document.querySelectorAll('.haber-listesi.acik,.kat-ok.acik').forEach(x=>x.classList.remove('acik'));
  if(!open){lst.classList.add('acik');ok.classList.add('acik')}
}
function go(url){if(url)window.open(url,'_blank')}

function render(v){
  document.getElementById('splash').classList.add('hide');
  document.getElementById('tarih').textContent=v.tarih;
  document.getElementById('toplam').textContent=v.toplam;
  document.getElementById('katsayi').textContent=v.kategoriler.length;
  const katDiv=document.getElementById('kategoriler');
  const bos=document.getElementById('bos');
  if(v.toplam===0){katDiv.innerHTML='';bos.style.display='block';return}
  bos.style.display='none';
  let h='';
  v.kategoriler.forEach((kat,i)=>{
    const bilgi=KAT_BILGI[kat.kategori]||{emoji:'📌',renk:'#555'};
    const lid='l'+i;
    h+=`<div class="kategori-baslik" onclick="toggle(this,'${lid}')">
      <div class="kat-emoji" style="background:${bilgi.renk}22">${bilgi.emoji}</div>
      <div class="kat-info"><div class="kat-ad" style="color:${bilgi.renk}">${kat.kategori.toUpperCase()}</div><div class="kat-sayi">${kat.sayi} haber</div></div>
      <div class="kat-ok">▼</div></div><div class="haber-listesi" id="${lid}">`;
    kat.haberler.forEach(x=>{
      h+=`<div class="haber-kart" style="border-left-color:${bilgi.renk}" onclick="go('${x.url}')">
        <div class="baslik">${x.baslik}</div><div class="alt"><span>${x.kaynak}</span>${x.fiyat?`<span class="fiyat-badge">${x.fiyat}</span>`:''}</div></div>`;
    });
    h+='</div>'
  });
  katDiv.innerHTML=h
}

async function load(silent){
  const btn=document.getElementById('btn');
  if(!silent)btn.classList.add('don');
  try{const r=await fetch('/api/haberler');render(await r.json())}catch(e){console.error(e)}
  btn.classList.remove('don')
}
function yenile(){load(false)}
load(true);

// AdSense
try{(adsbygoogle=window.adsbygoogle||[]).push({})}catch(e){}
</script></body></html>"""

# ───── FASTAPI ─────
app = FastAPI(title="Zam Radar")

@app.get("/", response_class=HTMLResponse)
async def ana_sayfa():
    kat_json = json.dumps({k:{"emoji":v["emoji"],"renk":v["renk"]} for k,v in KATEGORILER.items()}, ensure_ascii=False)
    bot_username = os.getenv("BOT_USERNAME", "zamradarbot")
    return HTML_SAYFA.replace("{{ADSENSE_CLIENT}}",ADSENSE_CLIENT).replace("{{ADSENSE_SLOT}}",ADSENSE_SLOT).replace("{{KAT_JSON}}",kat_json).replace("{{BOT_USERNAME}}",bot_username)

@app.get("/manifest.json")
async def manifest():
    return JSONResponse(MANIFEST)

@app.get("/sw.js")
async def service_worker():
    return Response("""self.addEventListener('fetch',e=>{});self.addEventListener('install',e=>self.skipWaiting())""", media_type="application/javascript")

@app.get("/api/haberler")
async def api_haberler():
    haberler = haberleri_getir()
    kat_harita = {}
    for h in haberler: kat_harita.setdefault(h["kategori"],[]).append(h)
    kategoriler = []
    for kat in sorted(kat_harita,key=lambda k:len(kat_harita[k]),reverse=True):
        kategoriler.append({"kategori":kat,"sayi":len(kat_harita[kat]),"haberler":kat_harita[kat]})
    return JSONResponse({"tarih":datetime.now().strftime("%d %B %Y, %H:%M"),"toplam":len(haberler),"kategoriler":kategoriler})


# ─────────────────────────────────────────────
# PREMIUM ABONELIK SISTEMI
# ─────────────────────────────────────────────
def premium_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS premium (
            chat_id       TEXT PRIMARY KEY,
            username      TEXT,
            baslangic     INTEGER NOT NULL,
            bitis         INTEGER NOT NULL,
            plan          TEXT DEFAULT 'aylik',
            aktif         INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_premium_aktif ON premium(aktif, bitis);
    """)
    conn.commit()
    return conn

def premium_ekle(chat_id: str, username: str = "", gun: int = 30):
    conn = premium_db()
    now = int(time.time())
    mevcut = conn.execute("SELECT chat_id FROM premium WHERE chat_id=?", (str(chat_id),)).fetchone()
    if mevcut:
        conn.execute("UPDATE premium SET bitis=MAX(bitis,?)+?, aktif=1 WHERE chat_id=?",
                     (now, gun*86400, str(chat_id)))
    else:
        conn.execute("INSERT INTO premium (chat_id,username,baslangic,bitis,plan) VALUES (?,?,?,?,?)",
                     (str(chat_id), username, now, now+gun*86400, "aylik" if gun<=31 else "yillik"))
    conn.commit()
    conn.close()

def premium_kontrol(chat_id: str) -> bool:
    conn = premium_db()
    r = conn.execute("SELECT 1 FROM premium WHERE chat_id=? AND aktif=1 AND bitis>?", 
                     (str(chat_id), int(time.time()))).fetchone()
    conn.close()
    return r is not None

def premium_tum_kullanici_chat_id() -> list:
    conn = premium_db()
    rows = conn.execute("SELECT chat_id FROM premium WHERE aktif=1 AND bitis>?", 
                        (int(time.time()),)).fetchall()
    conn.close()
    return [r[0] for r in rows]

def premium_suresi_dolmus_temizle():
    conn = premium_db()
    conn.execute("UPDATE premium SET aktif=0 WHERE bitis<?", (int(time.time()),))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# TELEGRAM BOT KOMUTLARI
# ─────────────────────────────────────────────
def tg_mesaj_gonder(chat_id, text, markup=None):
    if not TELEGRAM_TOKEN:
        print(f"[DEBUG] TOKEN YOK! chat_id={chat_id}")
        return
    print(f"[DEBUG] Gonderiliyor: chat_id={chat_id}, token={TELEGRAM_TOKEN[:15]}...")
    pl = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
    if markup: pl["reply_markup"] = json.dumps(markup)
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=pl, timeout=10)
        print(f"[DEBUG] Sonuc: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"[DEBUG] HATA: {e}")

def tg_fatura_gonder(chat_id, baslik, aciklama, etiket, stars):
    """Telegram Stars ile odeme iste."""
    if not TELEGRAM_TOKEN: return
    pl = {
        "chat_id": chat_id,
        "title": baslik,
        "description": aciklama,
        "payload": f"premium_{etiket}_{int(time.time())}",
        "currency": "XTR",
        "prices": [{"label": etiket, "amount": stars}],
    }
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/createInvoiceLink", json=pl, timeout=10)
        data = r.json()
        if data.get("ok"):
            link = data["result"]
            tg_mesaj_gonder(chat_id,
                f"💎 *Premium Abonelik*\n\n"
                f"📦 Plan: *{etiket}*\n"
                f"⭐ Tutar: *{stars} Telegram Stars*\n\n"
                f"[👉 ODEME YAP]({link})",
                {"inline_keyboard": [[{"text": f"💳 {stars} Stars ile Ode", "url": link}]]})
    except Exception as e:
        print(f"Invoice error: {e}")

@app.get("/ping")
async def ping():
    return {"ok": True, "token_set": bool(TELEGRAM_TOKEN), "token_prefix": TELEGRAM_TOKEN[:10] if TELEGRAM_TOKEN else "NONE"}

@app.post("/tg/webhook")
async def tg_webhook(request: Request):
    """Telegram bot webhook - komutlari ve odemeleri isler."""
    try:
        data = await request.json()
    except:
        return {"ok": True}

    # PreCheckoutQuery - odeme onaylandi
    if "pre_checkout_query" in data:
        pq = data["pre_checkout_query"]
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerPreCheckoutQuery",
                     json={"pre_checkout_query_id": pq["id"], "ok": True}, timeout=10)
        return {"ok": True}

    # SuccessfulPayment - odeme tamamlandi
    if "message" in data and "successful_payment" in data["message"]:
        msg = data["message"]
        chat_id = str(msg["chat"]["id"])
        payload = msg["successful_payment"].get("invoice_payload", "")
        username = msg["chat"].get("username", msg["chat"].get("first_name", ""))

        if payload.startswith("premium_"):
            parts = payload.split("_")
            plan = parts[2] if len(parts) > 2 else "aylik"
            gun = 30 if plan == "aylik" else 365
            premium_ekle(chat_id, username, gun)
            tg_mesaj_gonder(chat_id,
                f"✅ *Premium Aktif!*\n\n"
                f"🟢 Her sabah 08:00'de zam raporu buraya gelecek.\n"
                f"📅 Plan: *{plan.upper()}*\n"
                f"⏳ Bitis: *{(datetime.now()+timedelta(days=gun)).strftime('%d.%m.%Y')}*\n\n"
                f"Tesekkurler! Reklamsiz kullanim keyfini cikar.")
        return {"ok": True}

    # Normal mesajlar
    msg = data.get("message", {})
    if "text" not in msg:
        return {"ok": True}

    chat_id = str(msg["chat"]["id"])
    text = msg["text"].strip()
    username = msg["chat"].get("username", msg["chat"].get("first_name", ""))
    is_premium = premium_kontrol(chat_id)

    if text == "/start":
        durum = "🟢 *PREMIUM AKTIF*" if is_premium else "⚪ Ucretsiz surum"
        tg_mesaj_gonder(chat_id,
            f"⚡ *ZAM RADAR'a Hos Geldin!*\n\n"
            f"Bugun neye zam geldi, aninda ogren.\n\n"
            f"📊 Durumun: {durum}\n\n"
            f"📱 *Ucretsiz:* Web uygulamasi + reklam\n"
            f"💎 *Premium:* Sabah 08:00 bildirimi + reklamsiz\n\n"
            f"Komutlar:\n"
            f"/zam - Bugunun zamlarini goster\n"
            f"/premium - Premium'a gec\n"
            f"/durum - Abonelik durumu\n"
            f"/uygulama - Mobil uygulamayi ac",
            {"inline_keyboard": [
                [{"text": "📱 Uygulamayi Ac", "url": "https://ZAM_RADAR_URL/"}],
                [{"text": "💎 Premium'a Gec", "callback_data": "premium"}]
            ]})

    elif text == "/zam":
        haberler = haberleri_getir()
        if not haberler:
            tg_mesaj_gonder(chat_id, "☕ Bugunluk zam haberi yok. Rahat bir nefes al!")
        else:
            kat_harita = {}
            for h in haberler: kat_harita.setdefault(h["kategori"],[]).append(h)
            msj = f"📰 *ZAM RADAR | {datetime.now().strftime('%d.%m.%Y')}*\n━━━━━━━━━━━━━━━━━━━\n"
            for kat in sorted(kat_harita,key=lambda k:len(kat_harita[k]),reverse=True)[:8]:
                e = KATEGORILER.get(kat,{}).get("emoji","📌")
                msj += f"\n{e} *{kat.upper()}* ({len(kat_harita[kat])} haber)\n"
                for h in kat_harita[kat][:2]:
                    fiyat = f"  *{h['fiyat']}*" if h["fiyat"] else ""
                    msj += f"  • {h['baslik'][:90]}{fiyat}\n"
            msj += f"\n🕐 {datetime.now().strftime('%H:%M')}"
            tg_mesaj_gonder(chat_id, msj)

    elif text == "/premium":
        if is_premium:
            conn = premium_db()
            r = conn.execute("SELECT bitis,plan FROM premium WHERE chat_id=?", (chat_id,)).fetchone()
            conn.close()
            bitis = datetime.fromtimestamp(r["bitis"]).strftime("%d.%m.%Y") if r else "?"
            tg_mesaj_gonder(chat_id,
                f"💎 *Premium Zaten Aktif!*\n\n"
                f"📅 Bitis: *{bitis}*\n"
                f"📦 Plan: *{r['plan'].upper() if r else '?'}*\n\n"
                f"/zam yazarak bugunun zamlarini gor.")
        else:
            tg_mesaj_gonder(chat_id,
                "💎 *Premium'a Gec, Reklamsiz Kullan!*\n\n"
                "Her sabah 08:00'de zam raporu Telegram'ina gelsin.\n\n"
                "Paketler:",
                {"inline_keyboard": [
                    [{"text": f"🟢 Aylik - {PREMIUM_AYLIK_STARS} Stars", "callback_data": "buy_aylik"}],
                    [{"text": f"🔵 Yillik - {PREMIUM_YILLIK_STARS} Stars (%33 indirim)", "callback_data": "buy_yillik"}]
                ]})

    elif text == "/durum":
        durum = "🟢 PREMIUM AKTIF" if is_premium else "⚪ Ucretsiz"
        if is_premium:
            conn = premium_db()
            r = conn.execute("SELECT bitis FROM premium WHERE chat_id=?", (chat_id,)).fetchone()
            conn.close()
            bitis = datetime.fromtimestamp(r["bitis"]).strftime("%d.%m.%Y %H:%M") if r else "?"
            durum += f"\n⏳ Bitis: {bitis}"
        tg_mesaj_gonder(chat_id, f"📊 *Abonelik Durumu*\n\n{durum}")

    elif text == "/uygulama":
        tg_mesaj_gonder(chat_id,
            "📱 *Zam Radar Mobil Uygulama*\n\n"
            "Kategorilere ayrilmis zam haberlerini gor, reklamlarla ucretsiz kullan.",
            {"inline_keyboard": [[{"text": "📱 Uygulamayi Ac", "url": "https://ZAM_RADAR_URL/"}]]})

    return {"ok": True}


@app.post("/tg/callback")
async def tg_callback(request: Request):
    """Inline button callback'lari."""
    try:
        data = await request.json()
    except:
        return {"ok": True}

    cb = data.get("callback_query", {})
    chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
    cb_data = cb.get("data", "")

    if cb_data == "premium":
        tg_mesaj_gonder(chat_id,
            "💎 *Premium Paketler*\n\n"
            f"🟢 Aylik: *{PREMIUM_AYLIK_STARS} Stars* (~15 TL)\n"
            f"🔵 Yillik: *{PREMIUM_YILLIK_STARS} Stars* (~120 TL)\n\n"
            "Telegram Stars ile guvenli odeme, abonelik hemen aktif olur.",
            {"inline_keyboard": [
                [{"text": f"🟢 Aylik - {PREMIUM_AYLIK_STARS} Stars", "callback_data": "buy_aylik"}],
                [{"text": f"🔵 Yillik - {PREMIUM_YILLIK_STARS} Stars", "callback_data": "buy_yillik"}]
            ]})

    elif cb_data == "buy_aylik":
        tg_fatura_gonder(chat_id, "Zam Radar Premium - Aylik",
                        "Her sabah 08:00 zam raporu + reklamsiz.", "Aylik Premium", PREMIUM_AYLIK_STARS)

    elif cb_data == "buy_yillik":
        tg_fatura_gonder(chat_id, "Zam Radar Premium - Yillik",
                        "Her sabah 08:00 zam raporu + reklamsiz. %33 indirimli.", "Yillik Premium", PREMIUM_YILLIK_STARS)

    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                     json={"callback_query_id": cb["id"]}, timeout=5)
    except: pass
    return {"ok": True}


# ─────────────────────────────────────────────
# GUNLUK PREMIUM BILDIRIM (APScheduler)
# ─────────────────────────────────────────────
def premium_gunluk_gonder():
    """Tum premium kullanicilara gunluk zam raporu gonder."""
    haberler = haberleri_getir()
    if not haberler:
        print("[Premium] Bugun zam haberi yok, bildirim atlanacak")
        return

    kat_harita = {}
    for h in haberler: kat_harita.setdefault(h["kategori"],[]).append(h)

    msj = f"📰 *ZAM RADAR | {datetime.now().strftime('%d.%m.%Y')}*\n━━━━━━━━━━━━━━━━━━━\n\n"
    for kat in sorted(kat_harita,key=lambda k:len(kat_harita[k]),reverse=True)[:10]:
        e = KATEGORILER.get(kat,{}).get("emoji","📌")
        msj += f"{e} *{kat.upper()}* ({len(kat_harita[kat])})\n"
        for h in kat_harita[kat][:2]:
            msj += f"  • {h['baslik'][:100]}\n"
        msj += "\n"
    msj += f"🕐 {datetime.now().strftime('%H:%M')} | Toplam {len(haberler)} zam"

    chat_ids = premium_tum_kullanici_chat_id()
    premium_suresi_dolmus_temizle()

    for cid in chat_ids:
        try:
            tg_mesaj_gonder(cid, msj)
            time.sleep(0.05)  # rate limit
        except Exception as e:
            print(f"  [!] Premium gonderim hatasi ({cid}): {e}")

    print(f"[Premium] {len(chat_ids)} kullaniciya bildirim gonderildi")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    premium_db()

    # Scheduler - her gun 08:00'de premium bildirimi
    scheduler = BackgroundScheduler()
    scheduler.add_job(premium_gunluk_gonder, "cron", hour=8, minute=0)
    scheduler.start()

    print(f"""
╔══════════════════════════════════════╗
║       ZAM RADAR v2.0 PREMIUM        ║
║  http://localhost:{args.port:<4}                   ║
║                                     ║
║  Web:     /                         ║
║  API:     /api/haberler             ║
║  Bot:     /tg/webhook               ║
║  Premium: Her sabah 08:00 bildirim  ║
╚══════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
