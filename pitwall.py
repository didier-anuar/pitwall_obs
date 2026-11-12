"""PITWALL - todo en un solo archivo (overlays + servidor + app del juego).

  python pitwall.py          -> datos reales de Assetto Corsa
  python pitwall.py --demo   -> coches simulados, sin juego
  python pitwall.py --zip    -> crea PitwallBridge.zip para Content Manager

Tabla:     http://localhost:9100
Sectores:  http://localhost:9100/sectors?car=NUMERO
"""
import json, math, os, random, socket, struct, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 9100
HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = False
SEL = {"car": 0}   # piloto elegido a mano en /control (0 = automático)
CMD = {"seq": 0, "focus": -1}   # órdenes para el juego: las recoge la app Pitwall Bridge
AC_WINDOW = "Assetto Corsa"     # título de la ventana del juego
CAMERAS = {                     # teclas de cámara del juego: revísalas en Opciones > Controles
    "Cockpit": "F1",
    "Chase": "F2",
    "TV / Pista": "F6",
}

def press_key(combo):
    """Envía una tecla (ej: "F6" o "CTRL+F1") a la ventana de Assetto Corsa. Solo Windows."""
    if not combo: return "Cámara no configurada"
    if DEMO: return "Modo demo: no se envía la tecla"
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, AC_WINDOW)
        if not hwnd: return "No encuentro la ventana de Assetto Corsa"
        mods, vks = {"CTRL": 0x11, "SHIFT": 0x10, "ALT": 0x12}, []
        for p in combo.upper().split("+"):
            p = p.strip()
            vks.append(mods[p] if p in mods else 0x6F + int(p[1:]) if p[0] == "F" and p[1:].isdigit() else ord(p[0]))
        prev = u.GetForegroundWindow()
        u.SwitchToThisWindow(hwnd, True); time.sleep(0.15)
        for v in vks: u.keybd_event(0, u.MapVirtualKeyW(v, 0), 8, 0)          # tecla abajo
        time.sleep(0.05)
        for v in reversed(vks): u.keybd_event(0, u.MapVirtualKeyW(v, 0), 8 | 2, 0)   # tecla arriba
        time.sleep(0.1)
        if prev: u.SwitchToThisWindow(prev, True)                               # devuelve el foco a OBS
        return "OK: " + combo
    except Exception as e:
        return "No se pudo enviar la tecla: " + str(e)

OVERLAY = r'''<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pitwall - Torre de tiempos</title>
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@600;700&display=swap" rel="stylesheet">
<style>
:root{--blue:#1e7bff;--ink:#f4f7fb;--dim:#9db4d6;--hot:#ffb020;--pit:#4ad8ff;--rh:38px;
  --row:rgba(7,11,20,.93);--font:"Rajdhani","Barlow Condensed","Arial Narrow",Arial,sans-serif}
html,body{margin:0;background:transparent;font-family:var(--font);color:var(--ink);font-style:italic;font-weight:700}
#tower{width:560px;margin:12px;filter:drop-shadow(0 0 10px rgba(30,123,255,.35))}
.hdr{height:86px;display:flex;flex-direction:column;justify-content:center;padding-left:64px;position:relative;
  background:linear-gradient(100deg,#0c2c6e,#06122b 60%,#050a16);clip-path:polygon(0 0,96% 0,88% 100%,0 100%)}
.hdr::before{content:"";position:absolute;inset:0 auto 0 0;width:46px;
  background:repeating-linear-gradient(115deg,var(--blue) 0 9px,transparent 9px 16px)}
.logo{display:flex;align-items:center;gap:10px}
.g1{font-size:46px;line-height:46px;letter-spacing:.02em;text-transform:uppercase}
.flag{width:56px;height:28px;transform:skewX(-18deg);background:repeating-conic-gradient(#e9eef8 0 25%,#1a2236 0 50%) 0 0/14px 14px}
.g2{font-size:17px;letter-spacing:.5em;color:var(--dim);text-transform:uppercase}
.state{height:40px;display:flex;align-items:center;gap:14px;padding-left:30px;font-size:30px;margin-top:4px;
  background:linear-gradient(100deg,#0b2a66,#050b18 75%);clip-path:polygon(0 0,86% 0,80% 100%,0 100%)}
.state i{color:var(--blue);font-weight:400}
.th,.r{display:grid;grid-template-columns:18px 58px 1fr 54px 104px 120px;align-items:center}
.th{height:34px;margin-top:6px;font-size:18px;color:var(--ink);text-transform:uppercase;letter-spacing:.06em;
  background:linear-gradient(90deg,#0f4bb8,#0a2a66 55%,rgba(5,10,22,.9))}
.th span,.r div{text-align:center}
.th .crown{color:#ffc928;font-size:18px;font-style:normal}
.th .drv,.r .nm{text-align:left}
.th .gap,.r .iv,.r .t{text-align:right;padding-right:14px}
#rows{position:relative;margin-top:2px;background:rgba(3,6,12,.4)}
.r{position:absolute;left:0;right:0;height:var(--rh);font-size:25px;font-variant-numeric:tabular-nums;
  background:var(--row);transition:transform .8s cubic-bezier(.3,.7,.2,1);border-bottom:1px solid rgba(255,255,255,.07)}
.r .tab{height:100%;width:7px;background:var(--tc)}
.r .nm{padding-left:16px;text-transform:uppercase;white-space:nowrap;overflow:hidden}
.r .iv,.r .t{font-size:23px}
.r .t{color:var(--dim)}
.ty span{display:inline-block;box-sizing:border-box;min-width:28px;height:28px;line-height:22px;padding:0 3px;border:3px solid var(--tyc,#9db4d6);border-radius:50%;font-size:15px;font-style:normal}
.r.lead{background:linear-gradient(90deg,#1559d9,#0d3b8f 55%,rgba(7,11,20,.93))}
.r.fight .iv{color:var(--hot)}
.r.pit .t{color:var(--pit)}
</style></head><body>
<div id="tower">
  <div class="hdr"><div class="logo"><span class="g1" id="g1"></span><span class="flag"></span></div><div class="g2" id="g2"></div></div>
  <div class="state"><b id="mode">RACE</b><i>/</i><b id="lap">LAP --</b></div>
  <div class="th"><span class="crown">♛</span><span>Pos</span><span class="drv">Driver</span><span>Tyre</span><span class="gap">Int</span><span class="gap">Gap</span></div>
  <div id="rows"></div>
</div>
<script>
const LEAGUE = ['GRID', 'RACING LEAGUE'];   // <- nombre de la liga
const COLORS = {};                          // <- colores por número de coche. Ej: {23:'#f5c400', 77:'#ff3030'}
const RH = 38, rows = document.getElementById('rows'), els = {}, $ = id => document.getElementById(id);
$('g1').textContent = LEAGUE[0]; $('g2').textContent = LEAGUE[1];
const fmt = s => {
  const ms = Math.round(s * 1000), m = Math.floor(ms / 60000), r = ((ms % 60000) / 1000).toFixed(3);
  return m ? m + ':' + r.padStart(6, '0') : r;
};
const TY = {S:'#ff3b3b', M:'#ffd21f', H:'#f4f7fb', W:'#3aa0ff', I:'#3ac86a'};   // color por neumático
function render(d){
  $('mode').textContent = d.race === false ? 'SESIÓN' : 'RACE';
  $('lap').textContent = 'LAP ' + d.lap + (d.total ? ' / ' + d.total : '');
  rows.style.height = d.cars.length * RH + 'px';
  d.cars.forEach(c => {
    let e = els[c.num];
    if(!e){
      e = els[c.num] = document.createElement('div');
      e.className = 'r';
      e.style.setProperty('--tc', COLORS[c.num] || 'hsl(' + (c.num * 47 % 360) + ',75%,55%)');
      e.innerHTML = '<div><div class="tab"></div></div><div class="p"></div><div class="nm"></div><div class="ty"></div><div class="iv"></div><div class="t"></div>';
      e.style.transform = 'translateY(' + (c.pos - 1) * RH + 'px)';
      rows.appendChild(e);
    }
    e.style.transform = 'translateY(' + (c.pos - 1) * RH + 'px)';
    e.children[1].textContent = c.pos;
    e.children[2].textContent = c.name;
    const ty = (c.tyre || '').toUpperCase();
    if(e.dataset.ty !== ty){
      e.dataset.ty = ty; e.children[3].replaceChildren();
      if(ty){ const s = document.createElement('span'); s.textContent = ty; s.style.setProperty('--tyc', TY[ty[0]] || '#9db4d6'); e.children[3].append(s); }
    }
    e.children[4].textContent = c.pos === 1 ? '--' : '+' + fmt(c.interval);
    e.children[5].textContent = c.pit ? 'PIT' : c.pos === 1 ? '--:--.--' : '+' + fmt(c.gap);
    e.classList.toggle('lead', c.pos === 1);
    e.classList.toggle('pit', c.pit);
    e.classList.toggle('fight', !c.pit && c.pos > 1 && c.interval < 1.0);
  });
}
async function tick(){
  try{ render(await (await fetch('/data.json', {cache:'no-store'})).json()); }
  catch(e){ $('lap').textContent = 'SIN CONEXIÓN'; }
}
tick(); setInterval(tick, 500);
</script></body></html>
'''

SECTORS = r'''<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pitwall - Sectores</title>
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@600;700&display=swap" rel="stylesheet">
<style>
:root{--blue:#1e7bff;--ink:#f4f7fb;--dim:#9db4d6;--tc:#1e7bff;--font:"Rajdhani","Barlow Condensed","Arial Narrow",Arial,sans-serif}
html,body{margin:0;background:transparent;font-family:var(--font);color:var(--ink);font-style:italic;font-weight:700}
#wrap{width:460px;margin:12px;filter:drop-shadow(0 0 10px rgba(30,123,255,.35))}
#card{background:linear-gradient(100deg,#0b2a66,#060e1f 45%,#050a16);
  clip-path:polygon(0 0,100% 0,100% calc(100% - 16px),calc(100% - 16px) 100%,0 100%);border-bottom:4px solid var(--blue)}
.head{display:flex;align-items:center;gap:14px;padding:8px 14px 8px 0;border-bottom:2px solid rgba(30,123,255,.6)}
#num{min-width:44px;padding:4px 10px 4px 16px;text-align:center;background:var(--tc);color:#07101f;font-size:28px;
  clip-path:polygon(0 0,100% 0,88% 100%,0 100%)}
#name{font-size:34px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;overflow:hidden}
.body{display:grid;grid-template-columns:1.15fr 1fr;align-items:center;padding:10px 0}
#cur{font-size:56px;text-align:center;font-variant-numeric:tabular-nums}
.int{text-align:center;border-left:2px solid rgba(255,255,255,.14);font-variant-numeric:tabular-nums}
#gap{display:block;font-size:32px}
#ahead{display:block;font-size:19px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
.sec{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:0 16px 14px}
.s span{display:block;text-align:center;font-size:17px;color:var(--dim)}
.s.cur span{color:var(--ink)}
.s u{display:block;height:5px;background:rgba(255,255,255,.16);transform:skewX(-18deg)}
.s em{display:block;height:100%;width:0;background:var(--blue)}
</style></head><body>
<div id="wrap"><div id="card">
  <div class="head"><span id="num">--</span><b id="name">Esperando datos</b></div>
  <div class="body">
    <div id="cur">0.000</div>
    <div class="int"><span id="gap">—</span><span id="ahead"></span></div>
  </div>
  <div class="sec">
    <div class="s"><span>S1</span><u><em></em></u></div>
    <div class="s"><span>S2</span><u><em></em></u></div>
    <div class="s"><span>S3</span><u><em></em></u></div>
  </div>
</div></div>
<script>
// Prioridad: ?car=NUMERO en la URL > piloto elegido en /control > coche que sigue la cámara del juego > líder.
const COLORS = {};                          // <- colores por número de coche. Ej: {23:'#f5c400'}
const want = +new URLSearchParams(location.search).get('car') || 0;
const $ = id => document.getElementById(id), secs = [...document.querySelectorAll('.s')];
const fmt = s => {
  const ms = Math.round(s * 1000), m = Math.floor(ms / 60000), r = ((ms % 60000) / 1000).toFixed(3);
  return m ? m + ':' + r.padStart(6, '0') : r;
};
let base = 0, t0 = performance.now();
function show(d){
  if(!d.cars.length) return;
  const i = Math.max(0, d.cars.findIndex(c => c.num === (want || d.selected || d.focus)));
  const c = d.cars[i], ahead = d.cars[i - 1];
  document.documentElement.style.setProperty('--tc', COLORS[c.num] || 'hsl(' + (c.num * 47 % 360) + ',75%,55%)');
  $('num').textContent = c.pos;
  $('name').textContent = c.name;
  $('gap').textContent = c.pit ? 'PIT' : ahead ? '+' + c.interval.toFixed(3) : '—';
  $('ahead').textContent = ahead ? ahead.name : 'Líder';
  const p = (c.spline || 0) * 3, k = Math.min(2, Math.floor(p));
  secs.forEach((s, n) => {
    s.classList.toggle('cur', n === k);
    s.querySelector('em').style.width = (n < k ? 100 : n === k ? (p - k) * 100 : 0) + '%';
  });
  base = c.cur || 0; t0 = performance.now();
}
async function tick(){
  try{ show(await (await fetch('/data.json', {cache:'no-store'})).json()); }catch(e){}
}
function loop(){ $('cur').textContent = fmt(base + Math.min(1, (performance.now() - t0) / 1000)); requestAnimationFrame(loop); }
tick(); setInterval(tick, 300); loop();
</script></body></html>
'''

CONTROL = r'''<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Pitwall - Control</title>
<style>
*{box-sizing:border-box}
body{margin:0;padding:10px;background:#0b1220;color:#f4f7fb;font:600 15px "Segoe UI",Arial,sans-serif}
h2{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#7f95b8;margin:14px 0 6px}
h2:first-child{margin-top:0}
.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px}
button{padding:9px 10px;font:inherit;color:inherit;background:#16233b;border:2px solid #24385c;border-radius:6px;
  text-align:left;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
button:hover{border-color:#3b5a92}
button.on{border-color:#1e7bff;background:#123a82}
#msg{margin-top:12px;font-size:13px;color:#7f95b8;min-height:16px}
</style></head><body>
<h2>Cámaras</h2><div class="g" id="cams"></div>
<h2>Pilotos</h2><div class="g" id="drv"></div>
<div id="msg"></div>
<script>
const $ = id => document.getElementById(id);
let D = {cars: [], cams: [], selected: 0};
const btn = (txt, on, fn) => { const b = document.createElement('button'); b.textContent = txt; if(on) b.className = 'on'; b.onclick = fn; return b; };
async function call(url, ok){
  try{ const t = await (await fetch(url)).text(); $('msg').textContent = ok || t; }
  catch(e){ $('msg').textContent = 'Sin conexión con Pitwall'; }
}
async function pick(n){
  D.selected = n; draw();
  await call('/select?car=' + n, n ? 'Siguiendo al piloto seleccionado' : 'Modo automático');
}
function draw(){
  $('cams').replaceChildren(...(D.cams || []).map(n => btn(n, false, () => call('/cam?name=' + encodeURIComponent(n)))));
  $('drv').replaceChildren(btn('AUTO (cámara del juego)', D.selected === 0, () => pick(0)),
    ...D.cars.map(c => btn(c.pos + '. ' + c.name, D.selected === c.num, () => pick(c.num))));
}
async function poll(){ try{ D = await (await fetch('/data.json', {cache:'no-store'})).json(); draw(); }catch(e){} }
poll(); setInterval(poll, 2000);
</script></body></html>
'''

MANIFEST = r'''[ABOUT]
NAME = Pitwall Bridge
AUTHOR = Pitwall
VERSION = 1.0
DESCRIPTION = Envia la clasificacion en vivo a Pitwall (localhost:9100).

[CORE]
LAZY = NONE

[WINDOW_1]
ID = main
NAME = Pitwall Bridge
FUNCTION_MAIN = windowMain
SIZE = 260, 90
'''

LUA = r'''-- Pitwall Bridge: envia la clasificacion en vivo a Pitwall.
local URL = "http://127.0.0.1:9100/push"
local HEADERS = { ["Content-Type"] = "application/json" }
local INTERVAL = 0.25                      -- segundos entre envios
local HIDE = { }                           -- nombres a ocultar. Ej: { "Mi Nombre" }

local timer, status, sent = 0, "iniciando", 0
local lastSeq, lastCmd = nil, "-"

local function try(f, default)
  local ok, v = pcall(f)
  if ok and v ~= nil then return v end
  return default
end

local function esc(s)
  return (tostring(s):gsub('[%c"\\]', function(c) return string.format("\\u%04x", c:byte()) end))
end

local function seconds(v)
  v = tonumber(v) or 0
  if v <= 0 or v > 3600000 then return 0 end
  return v / 1000
end

local function hidden(name)
  for _, h in ipairs(HIDE) do if h:lower() == name:lower() then return true end end
  return false
end

local function collect()
  local sim = ac.getSim()
  local session = try(function() return ac.getSession(sim.currentSessionIndex) end, nil)
  local isRace = session ~= nil and session.type == ac.SessionType.Race
  local total = session and tonumber(session.laps) or 0
  local track = try(function() return ac.getTrackName() end, "")
  local cars = {}
  for i = 0, sim.carsCount - 1 do
    local c = ac.getCar(i)
    if c and c.isConnected then
      local name = try(function() return ac.getDriverName(i) end, "")
      if name ~= "" and not hidden(name) then
        cars[#cars + 1] = string.format(
          '{"id":%d,"name":"%s","pos":%d,"laps":%d,"spline":%.5f,"last":%.3f,"best":%.3f,"cur":%.3f,"pit":%s,"tyre":"%s"}',
          i, esc(name), c.racePosition or 0, c.lapCount or 0, c.splinePosition or 0,
          seconds(c.previousLapTimeMs), seconds(c.bestLapTimeMs), seconds(c.lapTimeMs), tostring(c.isInPitlane == true),
          esc(try(function() return ac.getTyresName(i) end, "")))
      end
    end
  end
  return string.format('{"track":"%s","total":%d,"race":%s,"focus":%d,"cars":[%s]}',
    esc(track), total or 0, tostring(isRace), sim.focusedCar or 0, table.concat(cars, ","))
end

function script.update(dt)
  timer = timer + dt
  if timer < INTERVAL then return end
  timer = 0
  local ok, body = pcall(collect)
  if not ok then status = "error: " .. tostring(body) return end
  web.post(URL, HEADERS, body, function(err, response)
    if err then status = "sin conexion con Pitwall" return end
    sent = sent + 1; status = "enviando"
    -- Pitwall responde con "numero_de_orden,coche_a_seguir" (lo elegido en el panel de OBS)
    local text = try(function() return response.body end, "")
    local seq, focus = string.match(text, "(%d+),(%-?%d+)")
    seq, focus = tonumber(seq), tonumber(focus)
    if seq then
      if lastSeq ~= nil and seq ~= lastSeq and focus and focus >= 0 then
        pcall(ac.focusCar, focus); lastCmd = "seguir al coche " .. (focus + 1)
      end
      lastSeq = seq
    end
  end)
end

function script.windowMain(dt)
  ui.text("Estado: " .. status)
  ui.text("Envios: " .. sent)
  ui.text("Ultimo comando: " .. lastCmd)
end
'''

LISTEN = ("0.0.0.0", 11000)        # donde escuchamos al servidor de AC
AC_SERVER = ("127.0.0.1", 12000)   # donde escucha el servidor de AC (misma PC)
PUSH = {"t": 0, "args": None, "focus": 0}   # datos enviados desde el juego (modo espectador)
S = {"track": "", "laps": 0, "type": 0, "cars": {}}
LOCK = threading.Lock()

class Reader:
    def __init__(s, b): s.b, s.i = b, 1          # salta el byte de tipo
    def u(s, f):
        v = struct.unpack_from("<" + f, s.b, s.i); s.i += struct.calcsize("<" + f)
        return v if len(v) > 1 else v[0]
    def a(s):                                    # texto ASCII/UTF-8
        n = s.u("B"); t = s.b[s.i:s.i + n].decode("utf-8", "ignore"); s.i += n; return t
    def w(s):                                    # texto UTF-32
        n = s.u("B"); t = s.b[s.i:s.i + n * 4].decode("utf-32-le", "ignore"); s.i += n * 4; return t

def car(i):
    return S["cars"].setdefault(i, {"id": i, "name": "", "on": False, "laps": 0,
                                    "spline": 0.0, "last": 0.0, "best": 0.0})

def handle(d):
    t, r = d[0], Reader(d)
    with LOCK:
        if t in (50, 59):                        # sesión nueva / info de sesión
            r.u("BBBB"); r.w()
            S["track"] = r.a(); r.a(); r.a()
            S["type"] = r.u("B"); r.u("H"); S["laps"] = r.u("H")
            if t == 50:
                for c in S["cars"].values(): c.update(laps=0, last=0.0, best=0.0)
        elif t == 54:                            # info de un coche
            i, on = r.u("BB"); r.w(); r.w()
            c = car(i); c["on"] = bool(on); c["name"] = r.w()
        elif t == 51:                            # nueva conexión
            name = r.w(); r.w(); car(r.u("B")).update(name=name, on=True)
        elif t == 52:                            # desconexión
            r.w(); r.w(); car(r.u("B"))["on"] = False
        elif t == 53:                            # posición en tiempo real
            v = r.u("B3f3fHHf"); c = car(v[0]); c["spline"] = v[-1]; c["on"] = True
        elif t == 73:                            # vuelta completada
            i, ms, cuts, n = r.u("BIBB"); c = car(i); c["last"] = ms / 1000
            if cuts == 0 and (not c["best"] or c["last"] < c["best"]): c["best"] = c["last"]
            for _ in range(n):
                rid, _t, laps, _f = r.u("BIHB"); car(rid)["laps"] = laps

def setup(sock):
    sock.sendto(struct.pack("<BH", 200, 250), AC_SERVER)    # posiciones cada 250 ms
    sock.sendto(struct.pack("<Bh", 204, -1), AC_SERVER)     # info de la sesión actual
    for i in range(32):
        if not S["cars"].get(i, {}).get("name"):
            sock.sendto(struct.pack("<BB", 201, i), AC_SERVER)  # nombres de pilotos

def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: sock.ioctl(socket.SIO_UDP_CONNRESET, False)   # evita el error 10054 en Windows
    except (AttributeError, OSError): pass
    sock.bind(LISTEN); sock.settimeout(1); last = 0
    while True:
        if time.time() - last > 10:
            try: setup(sock)
            except OSError: pass
            last = time.time()
        try: handle(sock.recvfrom(2048)[0])
        except (socket.timeout, ConnectionResetError): pass
        except Exception as e: print("paquete ignorado:", e)

def standings():
    if DEMO: return demo_standings()
    if time.time() - PUSH["t"] < 3:
        d = build(*PUSH["args"]); d["focus"] = PUSH["focus"]; return d
    with LOCK:
        cs = [dict(c) for c in S["cars"].values() if c["on"] and c["name"]]
        track, total, race = S["track"] or "Pitwall", S["laps"], S["type"] == 3
    return build(cs, track, total, race)

def build(cs, track, total, race):
    prog = lambda c: c["laps"] + c["spline"]
    cs.sort(key=(lambda c: (c.get("pos") or 999, -prog(c))) if race else (lambda c: c["best"] or 1e9))
    out, acc = [], 0
    for i, c in enumerate(cs):
        ref = c["last"] or c["best"] or 90          # segundos por vuelta aprox.
        if i == 0: gap = 0
        elif race: gap = max(0, prog(cs[i - 1]) - prog(c)) * ref
        else: gap = max(0, c["best"] - cs[i - 1]["best"]) if c["best"] else 0
        acc += gap
        out.append({"pos": i + 1, "num": c["id"] + 1, "name": c["name"], "gap": acc,
                    "interval": gap, "last": c["last"], "best": c["best"],
                    "spline": c["spline"], "cur": c.get("cur") or c["spline"] * ref,
                    "lap": c["laps"] + 1, "pit": c.get("pit", False), "tyre": c.get("tyre", "")})
    lap = out[0]["lap"] if out else 0
    return {"track": track, "lap": min(lap, total) if total else lap, "total": total, "cars": out, "race": race}

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if self.path.startswith("/select"):
            try: SEL["car"] = int(q["car"][0])
            except (KeyError, ValueError): SEL["car"] = 0
            if SEL["car"] > 0: CMD["focus"] = SEL["car"] - 1; CMD["seq"] += 1   # el juego sigue a ese piloto
            body, ctype = b"ok", "text/plain"
        elif self.path.startswith("/cam"):
            body, ctype = press_key(CAMERAS.get(q.get("name", [""])[0], "")).encode("utf-8"), "text/plain; charset=utf-8"
        elif self.path.startswith("/data.json"):
            d = standings(); d["selected"] = SEL["car"]; d["cams"] = list(CAMERAS)
            body, ctype = json.dumps(d).encode(), "application/json"
        else:
            page = SECTORS if self.path.startswith("/sectors") else CONTROL if self.path.startswith("/control") else OVERLAY
            body, ctype = page.encode(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            PUSH["args"] = (d["cars"], d.get("track") or "Pitwall", d.get("total", 0), bool(d.get("race")))
            PUSH["focus"] = d.get("focus", -1) + 1; PUSH["t"] = time.time()
        except Exception as e: print("POST invalido:", e)
        out = f"{CMD['seq']},{CMD['focus']}".encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass


# ---- modo demo ----
NAMES = [f"Driver {i}" for i in range(1, 13)]
LAP_LEN, TOTAL_LAPS, T0 = 5000.0, 13, time.time()
rng = random.Random(7)
CARS = [{"name": n, "num": i + 1, "speed": 52 + rng.uniform(-2.5, 2.5),
         "phase": rng.uniform(0, 6), "start": -i * 12.0} for i, n in enumerate(NAMES)]

def dist(c, t):   # metros recorridos; el ritmo oscila para generar adelantamientos
    return max(0.0, c["start"] + c["speed"] * t + 25 * math.sin(t / 18 + c["phase"]))

def demo_standings():
    t = time.time() - T0 + 60
    rows = sorted(({**c, "d": dist(c, t)} for c in CARS), key=lambda c: -c["d"])
    out = []
    for i, c in enumerate(rows):
        lap_t = LAP_LEN / c["speed"]
        gap = 0 if i == 0 else (rows[i - 1]["d"] - c["d"]) / c["speed"]
        out.append({"pos": i + 1, "num": c["num"], "name": c["name"], "gap": 0 if i == 0 else (rows[0]["d"] - c["d"]) / c["speed"], "interval": gap,
                    "last": lap_t + 0.3 * math.sin(t + c["num"]), "best": lap_t - 0.4 * (c["num"] % 3),
                    "spline": (c["d"] % LAP_LEN) / LAP_LEN, "cur": (c["d"] % LAP_LEN) / c["speed"],
                    "lap": int(c["d"] // LAP_LEN) + 1, "pit": (int(t / 40) + c["num"]) % 29 == 0, "tyre": ["S", "M", "H"][c["num"] % 3]})
    return {"track": "Imola", "lap": min(out[0]["lap"], TOTAL_LAPS), "total": TOTAL_LAPS, "cars": out, "focus": 5, "race": True}


def make_zip():
    import zipfile
    with zipfile.ZipFile(os.path.join(HERE, "PitwallBridge.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("apps/lua/PitwallBridge/manifest.ini", MANIFEST)
        z.writestr("apps/lua/PitwallBridge/PitwallBridge.lua", LUA)

if __name__ == "__main__":
    if "--zip" in sys.argv:
        make_zip(); print("Creado PitwallBridge.zip: arrastralo a Content Manager."); sys.exit()
    DEMO = "--demo" in sys.argv
    if not DEMO: threading.Thread(target=listener, daemon=True).start()
    print(f"Pitwall {'DEMO' if DEMO else '(AC real)'} en http://localhost:{PORT}  (Ctrl+C para salir)")
    print(f"  Tabla:    http://localhost:{PORT}\n  Sectores: http://localhost:{PORT}/sectors?car=1\n  Panel OBS: http://localhost:{PORT}/control")
    HTTPServer(("0.0.0.0", PORT), H).serve_forever()
