#!/usr/bin/env python3
"""MES del banco (nivel 3 de ISA-95): ata el ERP (Odoo, nivel 4) con el PLC (nivel 1).

Hace tres cosas:
  1. Toma ordenes de fabricacion. Las pide a Odoo por JSON-RPC (modulo MRP); si Odoo
     no esta o aun no tiene ninguna, trabaja con una orden de demostracion para que la
     practica avance sin bloquearse en la parte de ERP.
  2. Las EJECUTA contra el PLC por Modbus TCP: arranca la linea (escribe el actuador del
     registro 4 del ESP32 PLC de la L7) y cuenta la produccion real leyendo el contador
     de transacciones (registro 3). Cada transaccion Modbus que el PLC sirve = 1 pieza.
  3. Calcula el OEE y lo expone (tablero web y /api/oee), cerrando el lazo hacia arriba.

Mapa Modbus del ESP32 PLC (holding, L6/L7):
  [0] entrada analogica   [1] realim. actuador 0   [2] entrantes   [3] salientes
  [4..7] cuatro actuadores (escribibles)   -> usamos [4] como "linea en marcha".

No necesita librerias del sistema: el contenedor instala flask, pymodbus y requests.
Variables de entorno: MES_PLC (host:puerto), MES_ODOO, MES_ODOO_DB/USER/PASS.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests
from pymodbus.client import ModbusTcpClient

PLC_HOST, PLC_PORT = (os.environ.get("MES_PLC", "192.168.1.10:502").split(":") + ["502"])[:2]
PLC_PORT = int(PLC_PORT)
ODOO = os.environ.get("MES_ODOO", "")
ODOO_DB = os.environ.get("MES_ODOO_DB", "banco")
ODOO_USER = os.environ.get("MES_ODOO_USER", "admin")
ODOO_PASS = os.environ.get("MES_ODOO_PASS", "admin")

REG_ACTUADOR = 4          # escribir 1 = linea en marcha
REG_SALIENTES = 3         # contador de transacciones servidas = piezas producidas
PERIODO_S = 1.0           # el MES sondea el PLC cada segundo (como un SCADA lento)

estado = {
    "plc": PLC_HOST + ":" + str(PLC_PORT),
    "plc_conectado": False,
    "orden": None,         # {"nombre","objetivo","producidas","origen":"odoo|demo","estado"}
    "oee": 0.0,
    "oee_a": 0.0, "oee_r": 0.0, "oee_q": 0.0,   # disponibilidad, rendimiento, calidad
    "piezas_base": None,   # lectura de [3] al arrancar la orden (para contar desde cero)
    "arranque_ts": None,
    "historico": [],       # (ts, producidas) para la grafica del tablero
}
cerrojo = threading.Lock()


# ---- Odoo (nivel 4): pedir ordenes de fabricacion por JSON-RPC ------------------------
def _odoo_rpc(servicio, metodo, args):
    r = requests.post(ODOO.rstrip("/") + "/jsonrpc", json={
        "jsonrpc": "2.0", "method": "call",
        "params": {"service": servicio, "method": metodo, "args": args},
    }, timeout=5)
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise RuntimeError(d["error"].get("data", {}).get("message", "error Odoo"))
    return d["result"]


def orden_desde_odoo():
    """Primera orden de fabricacion confirmada/en curso de Odoo, o None."""
    if not ODOO:
        return None
    try:
        uid = _odoo_rpc("common", "login", [ODOO_DB, ODOO_USER, ODOO_PASS])
        if not uid:
            return None
        ids = _odoo_rpc("object", "execute_kw", [
            ODOO_DB, uid, ODOO_PASS, "mrp.production", "search",
            [[["state", "in", ["confirmed", "progress"]]]], {"limit": 1}])
        if not ids:
            return None
        rec = _odoo_rpc("object", "execute_kw", [
            ODOO_DB, uid, ODOO_PASS, "mrp.production", "read",
            [ids, ["name", "product_qty"]]])[0]
        return {"nombre": rec["name"], "objetivo": int(rec["product_qty"] or 1), "origen": "odoo"}
    except Exception:
        return None       # ERP caido o sin modulo MRP: seguimos con la demo


def tomar_orden():
    o = orden_desde_odoo()
    if o is None:
        o = {"nombre": "MO/DEMO", "objetivo": 20, "origen": "demo"}
    o.update({"producidas": 0, "estado": "en curso"})
    return o


# ---- PLC (nivel 1): ejecutar y medir por Modbus --------------------------------------
def lazo_mes():
    """Bucle del MES: mantiene una orden activa, arranca la linea y cuenta la produccion."""
    cli = ModbusTcpClient(PLC_HOST, port=PLC_PORT, timeout=2)
    while True:
        time.sleep(PERIODO_S)
        try:
            if not cli.connected:
                cli.connect()
            with cerrojo:
                if estado["orden"] is None:
                    estado["orden"] = tomar_orden()
                    estado["piezas_base"] = None
                    estado["arranque_ts"] = time.time()
                o = estado["orden"]
            en_curso = o["estado"] == "en curso"
            # Arrancar la linea (actuador 4 = 1) SOLO con una orden en curso. Con la orden
            # terminada el MES ya no escribe en el PLC: antes lo hacia cada segundo y pisaba
            # el registro 4 a otras practicas (la L9 lo usa como rele).
            if en_curso:
                cli.write_register(REG_ACTUADOR, 1)
            rr = cli.read_holding_registers(REG_SALIENTES, count=1)
            estado["plc_conectado"] = not rr.isError()
            if rr.isError() or not en_curso:
                continue
            salientes = rr.registers[0]
            with cerrojo:
                if estado["piezas_base"] is None:
                    estado["piezas_base"] = salientes
                producidas = max(0, salientes - estado["piezas_base"])
                o["producidas"] = min(producidas, o["objetivo"])
                # OEE = disponibilidad x rendimiento x calidad. En el banco: disponibilidad = la
                # linea respondio en este ciclo; rendimiento = producidas frente a las que
                # tocaban a 1 pza/s; calidad = 1 (el banco no tiene rechazos: es el reto).
                transcurrido = max(1.0, time.time() - estado["arranque_ts"])
                esperadas = min(o["objetivo"], transcurrido)   # ritmo nominal 1 pza/s
                rendimiento = min(1.0, o["producidas"] / esperadas) if esperadas else 0.0
                estado["oee_a"], estado["oee_r"], estado["oee_q"] = 1.0, round(rendimiento, 3), 1.0
                estado["oee"] = round(rendimiento, 3)
                estado["historico"] = (estado["historico"] + [[int(time.time()), o["producidas"]]])[-120:]
                if o["producidas"] >= o["objetivo"]:
                    o["estado"] = "terminada"
                    o["fin_ts"] = time.time()
                    cli.write_register(REG_ACTUADOR, 0)    # parar la linea (una sola vez)
        except Exception as e:
            estado["plc_conectado"] = False
            estado["ult_error"] = str(e)


# ---- Tablero web (sube el estado hacia el operador) ----------------------------------
PAGINA = """<!doctype html><html lang=es><meta charset=utf-8>
<title>MES · Planta DEET</title><meta name=viewport content="width=device-width,initial-scale=1">
<style>
 /* Tablero de operador de un MES: barra de planta, orden en curso, OEE desglosado,
    curva de produccion real frente a la ideal y la cadena ERP -> MES -> PLC en vivo. */
 :root{--fondo:#eef1f5;--panel:#fff;--borde:#d7dde6;--texto:#17202b;--suave:#5d6b7c;
   --barra:#1c2b3d;--barra-t:#e8eef6;--ok:#1f9d5a;--aviso:#d08a12;--mal:#c8423b;--acento:#2563c4;
   --pista:#e3e8ef;--mono:ui-monospace,SFMono-Regular,Consolas,monospace}
 @media (prefers-color-scheme:dark){:root{--fondo:#0e141b;--panel:#16202b;--borde:#263444;--texto:#e6edf5;
   --suave:#93a3b5;--barra:#0a1017;--pista:#223040;--acento:#5b9bf0}}
 *{box-sizing:border-box}
 body{margin:0;background:var(--fondo);color:var(--texto);font:15px/1.45 system-ui,"Segoe UI",Roboto,sans-serif}
 .barra{background:var(--barra);color:var(--barra-t);display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;padding:10px 20px}
 .barra h1{font-size:17px;margin:0;font-weight:650;letter-spacing:.01em}
 .barra h1 small{font-weight:400;opacity:.7;margin-left:8px;font-size:13px}
 .esp{flex:1}
 .pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;padding:3px 10px;border-radius:999px;background:rgba(255,255,255,.08)}
 .pill i{width:8px;height:8px;border-radius:50%;background:#7b8796}
 .pill.on i{background:#3fd27c}.pill.off i{background:#f06a62}.pill.demo i{background:#f0b84a}
 .reloj{font-family:var(--mono);font-size:13px;opacity:.85}
 main{max-width:1180px;margin:0 auto;padding:18px 20px 30px;display:grid;gap:16px;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr)}
 @media (max-width:900px){main{grid-template-columns:1fr}}
 .tarjeta{background:var(--panel);border:1px solid var(--borde);border-radius:10px;padding:16px 18px;min-width:0}
 .k{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--suave);margin:0 0 6px}
 .orden{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}
 .orden b{font-size:26px;font-family:var(--mono);letter-spacing:-.01em}
 .estado{font-size:12px;font-weight:650;padding:2px 9px;border-radius:5px;background:var(--pista)}
 .estado.curso{background:#dbeafe;color:#1d4ed8}.estado.fin{background:#d7f3e3;color:#13693c}
 @media (prefers-color-scheme:dark){.estado.curso{background:#1d3357;color:#9cc2ff}.estado.fin{background:#163a28;color:#84e0aa}}
 .barrap{height:12px;border-radius:6px;background:var(--pista);overflow:hidden;margin:12px 0 6px}
 .barrap>i{display:block;height:100%;width:0;background:var(--acento);transition:width .4s}
 .cifras{display:flex;flex-wrap:wrap;gap:6px 22px;font-size:13px;color:var(--suave)}
 .cifras b{color:var(--texto);font-family:var(--mono);font-variant-numeric:tabular-nums}
 .oee{display:grid;grid-template-columns:150px 1fr;gap:16px;align-items:center}
 @media (max-width:480px){.oee{grid-template-columns:1fr}}
 .gauge{position:relative;width:150px;height:150px}
 .gauge span{position:absolute;inset:0;display:grid;place-items:center;text-align:center;font-size:30px;font-weight:700;font-family:var(--mono)}
 .gauge span small{display:block;font-size:11px;font-weight:500;color:var(--suave);font-family:system-ui;letter-spacing:.06em}
 .factor{display:grid;grid-template-columns:110px 1fr 52px;align-items:center;gap:10px;margin:8px 0;font-size:13.5px}
 .factor .p{height:8px;border-radius:4px;background:var(--pista);overflow:hidden}.factor .p i{display:block;height:100%;background:var(--ok)}
 .factor b{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums}
 .graf svg{width:100%;height:200px;display:block}
 .ley{display:flex;gap:16px;font-size:12px;color:var(--suave);margin-top:6px}
 .ley i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px}
 .cadena{display:flex;flex-direction:column;gap:8px}
 .eslabon{display:flex;align-items:center;gap:10px;border:1px solid var(--borde);border-radius:8px;padding:9px 11px}
 .eslabon .n{font-family:var(--mono);font-size:11px;color:var(--suave);width:24px}
 .eslabon div{flex:1;min-width:0}.eslabon small{display:block;color:var(--suave);font-size:12px;overflow-wrap:anywhere}
 .eslabon .pt{width:10px;height:10px;border-radius:50%;background:#9aa6b4}
 .eslabon .pt.on{background:var(--ok)}.eslabon .pt.off{background:var(--mal)}.eslabon .pt.demo{background:var(--aviso)}
 .flecha{text-align:center;color:var(--suave);font-size:12px;line-height:1}
 .eventos{list-style:none;margin:0;padding:0;font-size:13px;max-height:220px;overflow:auto}
 .eventos li{display:flex;gap:10px;padding:5px 0;border-bottom:1px solid var(--borde)}
 .eventos time{font-family:var(--mono);color:var(--suave);font-size:12px;flex:none}
 button{font:inherit;font-size:13px;border:1px solid var(--borde);background:var(--panel);color:var(--texto);border-radius:7px;padding:6px 12px;cursor:pointer}
 button:hover{border-color:var(--acento)}
 .full{grid-column:1/-1}
</style>
<div class=barra>
 <h1>MES · Planta DEET <small>ejecución de manufactura · nivel 3 ISA-95</small></h1>
 <span class=esp></span>
 <span class="pill" id=p-erp><i></i><span>ERP</span></span>
 <span class="pill" id=p-plc><i></i><span>PLC</span></span>
 <span class=reloj id=reloj></span>
</div>
<main>
 <section class=tarjeta>
  <p class=k>Orden de fabricación en ejecución</p>
  <div class=orden><b id=o-nombre>—</b><span class=estado id=o-estado>esperando</span><span class=cifras id=o-origen></span></div>
  <div class=barrap><i id=o-barra></i></div>
  <div class=cifras>
   <span>Producidas <b id=o-prod>0</b> / <b id=o-obj>0</b></span>
   <span>Ritmo <b id=o-ritmo>0</b> pza/min</span>
   <span>Transcurrido <b id=o-t>0 s</b></span>
   <span>Fin estimado <b id=o-eta>—</b></span>
  </div>
 </section>
 <section class=tarjeta>
  <p class=k>OEE de la orden</p>
  <div class=oee>
   <div class=gauge><svg viewBox="0 0 150 150" width=150 height=150>
     <circle cx=75 cy=75 r=62 fill=none stroke="var(--pista)" stroke-width=14 />
     <circle id=g-arco cx=75 cy=75 r=62 fill=none stroke="var(--ok)" stroke-width=14 stroke-linecap=round
       stroke-dasharray="0 390" transform="rotate(-90 75 75)" />
    </svg><span><div id=g-val>0 %<small>OEE</small></div></span></div>
   <div>
    <div class=factor><span>Disponibilidad</span><div class=p><i id=f-a></i></div><b id=v-a>0 %</b></div>
    <div class=factor><span>Rendimiento</span><div class=p><i id=f-r></i></div><b id=v-r>0 %</b></div>
    <div class=factor><span>Calidad</span><div class=p><i id=f-q></i></div><b id=v-q>0 %</b></div>
   </div>
  </div>
 </section>
 <section class="tarjeta graf">
  <p class=k>Producción acumulada</p>
  <svg id=graf viewBox="0 0 600 200" preserveAspectRatio=none></svg>
  <div class=ley><span><i style="background:var(--acento)"></i>real (contador del PLC)</span><span><i style="background:var(--suave)"></i>ideal (1 pza/s)</span></div>
 </section>
 <section class=tarjeta>
  <p class=k>Integración vertical</p>
  <div class=cadena>
   <div class=eslabon><span class=n>N4</span><div><b>ERP · Odoo</b><small id=c-erp>—</small></div><span class=pt id=pt-erp></span></div>
   <div class=flecha>↓ orden de fabricación &nbsp;·&nbsp; ↑ avance y OEE</div>
   <div class=eslabon><span class=n>N3</span><div><b>MES</b><small>este tablero · 192.168.1.62</small></div><span class="pt on"></span></div>
   <div class=flecha>↓ Modbus TCP: reg 4 = línea en marcha &nbsp;·&nbsp; ↑ reg 3 = piezas</div>
   <div class=eslabon><span class=n>N1</span><div><b>PLC · ESP32</b><small id=c-plc>—</small></div><span class=pt id=pt-plc></span></div>
  </div>
 </section>
 <section class="tarjeta full">
  <p class=k>Eventos</p>
  <ul class=eventos id=eventos></ul>
  <p style="margin:10px 0 0"><button onclick="nueva()">Tomar la siguiente orden</button></p>
 </section>
</main>
<script>
const $=id=>document.getElementById(id);
const pct=x=>Math.round((x||0)*100)+" %";
let ant={}, eventos=[];
function evento(t){const h=new Date().toLocaleTimeString("es-EC",{hour12:false});eventos.unshift([h,t]);eventos=eventos.slice(0,40);
 $("eventos").innerHTML=eventos.map(e=>`<li><time>${e[0]}</time><span>${e[1]}</span></li>`).join("");}
async function nueva(){await fetch("api/nueva_orden");evento("Operador: pedir la siguiente orden al ERP");}
function grafica(d){
 const h=d.historico||[], o=d.orden||{}, W=600, H=200, P=24, obj=Math.max(1,o.objetivo||1);
 if(h.length<1){$("graf").innerHTML="";return;}
 const t0=h[0][0], tn=Math.max(t0+obj, h[h.length-1][0]);
 const X=t=>P+(W-2*P)*(t-t0)/Math.max(1,tn-t0), Y=v=>H-P-(H-2*P)*Math.min(1,v/obj);
 let s=`<line x1=${P} y1=${Y(obj)} x2=${W-P} y2=${Y(obj)} stroke="var(--borde)" stroke-dasharray="4 4"/>`;
 s+=`<text x=${P} y=${Y(obj)-6} font-size=11 fill="var(--suave)">objetivo ${obj}</text>`;
 s+=`<line x1=${X(t0)} y1=${Y(0)} x2=${X(t0+obj)} y2=${Y(obj)} stroke="var(--suave)" stroke-width=1.5 stroke-dasharray="6 4"/>`;
 s+=`<polyline fill=none stroke="var(--acento)" stroke-width=2.5 points="${h.map(p=>X(p[0])+","+Y(p[1])).join(" ")}"/>`;
 const u=h[h.length-1]; s+=`<circle cx=${X(u[0])} cy=${Y(u[1])} r=4 fill="var(--acento)"/>`;
 $("graf").innerHTML=s;
}
async function tic(){
 try{
  const d=await (await fetch("api/estado")).json(), o=d.orden||{};
  const odoo=o.origen==="odoo";
  $("p-erp").className="pill "+(odoo?"on":"demo"); $("p-erp").lastElementChild.textContent=odoo?"ERP Odoo":"ERP sin orden · demo";
  $("p-plc").className="pill "+(d.plc_conectado?"on":"off"); $("p-plc").lastElementChild.textContent="PLC "+d.plc;
  $("c-erp").textContent=odoo?"orden "+o.nombre+" leída por JSON-RPC":"sin orden confirmada en Odoo: el MES usa MO/DEMO";
  $("pt-erp").className="pt "+(odoo?"on":"demo");
  $("c-plc").textContent=d.plc+(d.plc_conectado?" · responde":" · sin respuesta");
  $("pt-plc").className="pt "+(d.plc_conectado?"on":"off");
  $("o-nombre").textContent=o.nombre||"—";
  const fin=o.estado==="terminada";
  $("o-estado").textContent=o.estado||"esperando"; $("o-estado").className="estado "+(fin?"fin":(o.estado?"curso":""));
  $("o-origen").textContent=odoo?"desde Odoo (MRP)":"orden de demostración";
  const prod=o.producidas||0, obj=o.objetivo||0;
  $("o-prod").textContent=prod; $("o-obj").textContent=obj;
  $("o-barra").style.width=(obj?Math.round(100*prod/obj):0)+"%";
  const t=d.arranque_ts?Math.max(1,(fin&&o.fin_ts?o.fin_ts:Date.now()/1000)-d.arranque_ts):0;
  $("o-t").textContent=Math.round(t)+" s";
  const ritmo=t?prod/t*60:0; $("o-ritmo").textContent=ritmo.toFixed(0);
  $("o-eta").textContent=fin?"terminada":(ritmo>0?Math.round((obj-prod)/(ritmo/60))+" s":"—");
  const oee=d.oee||0; $("g-val").firstChild.textContent=Math.round(oee*100)+" %";
  $("g-arco").setAttribute("stroke-dasharray",(390*oee).toFixed(1)+" 390");
  $("g-arco").setAttribute("stroke",oee>=.85?"var(--ok)":oee>=.6?"var(--aviso)":"var(--mal)");
  for(const [k,v] of [["a",d.oee_a],["r",d.oee_r],["q",d.oee_q]]){$("f-"+k).style.width=pct(v).replace(" ","");$("v-"+k).textContent=pct(v);}
  grafica(d);
  if(o.nombre&&o.nombre!==ant.nombre) evento(`Orden ${o.nombre} recibida (${obj} piezas, ${odoo?"Odoo":"demo"}); línea en marcha`);
  if(fin&&ant.estado!=="terminada"&&o.nombre===ant.nombre) evento(`Orden ${o.nombre} terminada: ${prod}/${obj}, OEE ${pct(oee)}; línea parada`);
  if(ant.plc!==undefined&&ant.plc!==d.plc_conectado) evento(d.plc_conectado?"PLC de nuevo en línea":"PLC sin respuesta por Modbus");
  ant={nombre:o.nombre,estado:o.estado,plc:d.plc_conectado};
 }catch(e){}
 $("reloj").textContent=new Date().toLocaleTimeString("es-EC",{hour12:false});
 setTimeout(tic,1000);
}
tic();
</script></html>"""


class Mango(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _responder(self, codigo, tipo, cuerpo):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self):
        self.do_GET()

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta in ("/", "/index.html"):
            return self._responder(200, "text/html; charset=utf-8", PAGINA.encode())
        if ruta == "/api/estado":
            with cerrojo:
                cuerpo = json.dumps(estado).encode()
            return self._responder(200, "application/json", cuerpo)
        if ruta == "/api/oee":
            with cerrojo:
                cuerpo = json.dumps({"oee": estado["oee"], "orden": estado["orden"]}).encode()
            return self._responder(200, "application/json", cuerpo)
        if ruta == "/api/salud":
            return self._responder(200, "application/json",
                                   json.dumps({"ok": True, "plc": estado["plc_conectado"]}).encode())
        if ruta == "/api/nueva_orden":          # el alumno fuerza una orden nueva (demo)
            with cerrojo:
                estado["orden"] = None
            return self._responder(200, "application/json", b'{"ok": true}')
        self._responder(404, "text/plain", b"no existe")


if __name__ == "__main__":
    threading.Thread(target=lazo_mes, daemon=True).start()
    print("MES escuchando en :8095  (PLC %s:%d, Odoo %s)" % (PLC_HOST, PLC_PORT, ODOO or "-"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8095), Mango).serve_forever()
