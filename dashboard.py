#!/usr/bin/env python3
# AEB-STREAM — dashboard.py
#
# Dashboard web sobre a instância AEB do HeraclitusDB. Paleta do Portal da
# Transparência. Globo 3D em primeiro plano (a Terra real + a trajetória orbital
# por cima), topo compacto, telemetria reduzida e botão de TELA CHEIA.
#
# Robusto: serve o globe.gl e as texturas LOCALMENTE (pasta assets/), sem depender
# de CDN — funciona mesmo com a rede instável/offline.
#
#   python dashboard.py            # http://127.0.0.1:7480
# Lê do banco AEB (127.0.0.1:7476); não escreve nada.

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, r"D:\DEV\HeraclitusDB\sdk\python")
import heraclitusdb  # noqa: E402

AEB_SERVER = os.environ.get("AEB_SERVER", "127.0.0.1:7476")
PORT = 7480
BASE = os.path.dirname(os.path.abspath(__file__))
CT = {".js": "application/javascript", ".jpg": "image/jpeg", ".png": "image/png", ".css": "text/css"}


def coletar() -> dict:
    c = heraclitusdb.connect(AEB_SERVER)

    def rows(kind):
        r = c.query(f'MATCH (n:{kind}) RETURN n')
        return sorted(r, key=lambda n: int(n.get("lsn", 0))) if isinstance(r, list) else []

    sats = [{"id": n.get("id"), "catnr": (n.get("attrs") or {}).get("catnr"),
             "nome": (n.get("attrs") or {}).get("nome"),
             "inclinacao": (n.get("attrs") or {}).get("inclinacao_deg"),
             "periodo": (n.get("attrs") or {}).get("periodo_min")} for n in rows("Satelite")]
    estados = []
    for n in rows("OrbitState"):
        a = n.get("attrs", {}) or {}
        estados.append({"lsn": n.get("lsn"), "catnr": a.get("catnr"), "sat": a.get("satellite_id"),
                        "ts": a.get("ts"), "lat": _f(a.get("latitude")), "lon": _f(a.get("longitude")),
                        "alt": _f(a.get("altitude_km")), "temp": _f(a.get("battery_temp")),
                        "volt": _f(a.get("solar_voltage")), "eclipse": a.get("eclipse") == "True"})
    anomalias = [{"lsn": n.get("lsn"), "sat": (n.get("attrs") or {}).get("satellite_id"),
                  "catnr": (n.get("attrs") or {}).get("catnr"), "codigo": (n.get("attrs") or {}).get("codigo"),
                  "severidade": (n.get("attrs") or {}).get("severidade"),
                  "descricao": (n.get("attrs") or {}).get("descricao"),
                  "orbitstate_lsn": (n.get("attrs") or {}).get("orbitstate_lsn")} for n in rows("Anomalia")]
    return {"satelites": sats, "estados": estados, "anomalias": anomalias,
            "head": json.loads(c.stats()["message"])["head"]}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


HTML = r"""<!doctype html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AEB-STREAM</title>
<style>
:root{--azul:#1351B4;--azul-esc:#0c326f;--amarelo:#FFCD07;--verde:#168821;
 --laranja:#F2922A;--vermelho:#E52207;--pan:#fff;--bord:#dfe3e8;--ink:#1f2933;--mut:#5f6b7a}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:#0a1020;color:var(--ink);font-family:'Segoe UI',system-ui,sans-serif;
 display:flex;flex-direction:column;overflow:hidden}
.barra{height:5px;background:var(--azul-esc);flex:none}
.top{background:var(--amarelo);padding:7px 16px;display:flex;align-items:center;gap:16px;flex:none}
.top b{color:var(--azul-esc);font-size:1rem}.top .met{display:flex;gap:16px;margin-left:auto;align-items:center}
.top .met .k{color:#6b5800;font-size:.7rem}.top .met .v{color:var(--azul-esc);font-size:1.1rem;font-weight:700}
.top .met .v.cr{color:var(--vermelho)}
.btn{background:var(--azul-esc);color:#fff;border:0;border-radius:6px;padding:6px 12px;cursor:pointer;
 font-size:.8rem;display:flex;align-items:center;gap:6px}.btn:hover{background:var(--azul)}
.chips{background:#10182b;padding:6px 14px;display:flex;gap:8px;flex-wrap:wrap;flex:none;border-bottom:1px solid #1d2840}
.chip{padding:3px 10px;border-radius:14px;border:1px solid #2a3656;background:#16203a;color:#c9d4e8;cursor:pointer;
 font-size:.76rem;display:flex;align-items:center;gap:6px}
.chip.on{border-color:var(--amarelo);color:#fff}.chip .dot{width:9px;height:9px;border-radius:50%}
.chip .a{color:#ff8a8a;font-weight:700}
.main{flex:1;position:relative;min-height:0}
#globe{position:absolute;inset:0}
.gbtn{position:absolute;top:10px;right:10px;z-index:5}
.bottom{flex:none;height:168px;display:flex;gap:1px;background:#1d2840;border-top:1px solid #1d2840}
.cell{background:#0e1729;padding:8px 12px;overflow:auto}.cell.tel{flex:1}.cell.an{flex:1.3}
.cell h3{margin:0 0 5px;font-size:.66rem;text-transform:uppercase;letter-spacing:.6px;color:#7e8aa3}
.cell h3 span{color:var(--amarelo)}
.spark{width:100%;height:52px}
.an-row{display:flex;gap:7px;align-items:flex-start;padding:5px 7px;border-left:3px solid #555;background:#121c30;
 border-radius:0 5px 5px 0;margin-bottom:5px}
.an-row.CRITICA{border-color:var(--vermelho)}.an-row.ALTA{border-color:var(--laranja)}.an-row.MEDIA{border-color:var(--amarelo)}
.an-row .sev{font-size:.6rem;font-weight:800;padding:1px 6px;border-radius:4px;white-space:nowrap}
.an-row.CRITICA .sev{background:#3a1414;color:#ff8a8a}.an-row.ALTA .sev{background:#3a2a12;color:#ffc081}
.an-row .d{font-size:.74rem;color:#dfe6f2}.an-row .m{font-size:.64rem;color:#7e8aa3}
.empty{color:#7e8aa3;font-size:.78rem;padding:6px}
svg text{fill:#7e8aa3;font-size:8px}
.head{color:#6b5800;font-size:.68rem}
</style></head><body>
<div class="barra"></div>
<div class="top"><b>🛰 AEB-STREAM</b><span class="head" id="head"></span>
  <div class="met">
    <div><div class="k">satélites</div><div class="v" id="m_sat">—</div></div>
    <div><div class="k">antenas</div><div class="v" id="m_ant">—</div></div>
    <div><div class="k">contactos</div><div class="v" id="m_hit" style="color:var(--verde)">—</div></div>
    <div><div class="k">anomalias</div><div class="v cr" id="m_an">—</div></div>
    <button class="btn" id="fs">⛶ Tela cheia</button>
  </div>
</div>
<div class="chips" id="chips"></div>
<div class="main" id="main">
  <div id="globe"></div>
  <button class="btn gbtn" id="fsg">⛶ Globo em tela cheia</button>
</div>
<div class="bottom">
  <div class="cell tel"><h3>Temperatura bateria °C — <span id="t_sat"></span></h3><svg class="spark" id="temp"></svg></div>
  <div class="cell tel"><h3>Tensão painéis V — <span id="v_sat"></span></h3><svg class="spark" id="volt"></svg></div>
  <div class="cell an"><h3>Anomalias (Cérebro · ACT-R)</h3><div id="anoms"></div></div>
</div>
<script src="/assets/globe.gl.min.js"></script>
<script>
const CORES=['#FFCD07','#39b3ff','#168821','#E52207','#F2922A','#b30059'];
const R=6371, el=id=>document.getElementById(id);
let DATA=null,SEL=null,globe=null;
// Estações terrenas (antenas) reais — INPE / programa espacial BR
const ANTENAS=[
 {nome:'Cuiabá (INPE)',lat:-15.555,lon:-56.069},
 {nome:'Cachoeira Paulista (INPE)',lat:-22.689,lon:-45.005},
 {nome:'Alcântara (CLA)',lat:-2.373,lon:-44.396},
 {nome:'Barreira do Inferno (Natal)',lat:-5.924,lon:-35.161},
];
const COR_ANT='#00e0ff';
// ângulo central (graus) entre dois pontos lat/lon na esfera
function angSep(la1,lo1,la2,lo2){const d=Math.PI/180;
 const c=Math.sin(la1*d)*Math.sin(la2*d)+Math.cos(la1*d)*Math.cos(la2*d)*Math.cos((lo1-lo2)*d);
 return Math.acos(Math.max(-1,Math.min(1,c)))/d;}
// alcance angular máximo (graus) de visibilidade para um satélite à altitude altKm
function alcance(altKm){return Math.acos(R/(R+altKm))*180/Math.PI;}

function fitGlobe(){if(!globe)return;const m=el('main');globe.width(m.clientWidth).height(m.clientHeight);}
window.addEventListener('resize',fitGlobe);
document.addEventListener('fullscreenchange',()=>setTimeout(fitGlobe,120));
el('fs').onclick=()=>{document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();};
el('fsg').onclick=()=>{document.fullscreenElement?document.exitFullscreen():el('main').requestFullscreen();};

function initGlobe(){
  globe=Globe()(el('globe'))
    .globeImageUrl('/assets/earth.jpg').bumpImageUrl('/assets/topo.png')
    .backgroundImageUrl('/assets/sky.png').backgroundColor('#0a1020')
    .atmosphereColor('#5aa0ff').atmosphereAltitude(.2)
    .pathColor(p=>p.cor).pathStroke(p=>p.hit?1.7:2.4).pathPointAlt(p=>p[2]).pathTransitionDuration(0)
    .pathDashLength(p=>p.hit?0.3:1).pathDashGap(p=>p.hit?0.12:0).pathDashAnimateTime(p=>p.hit?1600:0)
    .htmlElementsData([]).htmlLat(d=>d.lat).htmlLng(d=>d.lng).htmlAltitude(d=>d.alt)
    .htmlElement(d=>{const e=document.createElement('div');
      e.innerHTML=`<span style="font-size:${d.ant?16:19}px;filter:drop-shadow(0 0 2px #000)">${d.icon}</span><span style="font-size:11px;color:${d.cor};font-weight:700;margin-left:3px;text-shadow:0 0 4px #000,0 0 3px #000">${d.nome}</span>`;
      e.style.cssText='white-space:nowrap;pointer-events:none;transform:translate(7px,-10px)';return e;});
  globe.controls().autoRotate=true;globe.controls().autoRotateSpeed=.45;
  fitGlobe();globe.pointOfView({lat:-12,lng:-55,altitude:2.4});
}
function clampAlt(a){return Math.min(a,.62);}

async function load(){
  try{DATA=await (await fetch('/api/data')).json();}catch(e){return;}
  el('head').textContent='head LSN '+DATA.head;
  el('m_sat').textContent=DATA.satelites.length;
  el('m_ant').textContent=ANTENAS.length;
  el('m_est').textContent=DATA.estados.length;
  el('m_an').textContent=DATA.anomalias.length;
  DATA.satelites.forEach((s,i)=>s._cor=CORES[i%CORES.length]);
  if(!SEL&&DATA.satelites.length)SEL=(DATA.anomalias[0]||{}).catnr||DATA.satelites[0].catnr;
  if(typeof Globe!=='undefined'&&!globe)initGlobe();
  chips();renderGlobe();anoms();charts();
}
const estDe=c=>DATA.estados.filter(e=>e.catnr===c);
const anDe=c=>DATA.anomalias.filter(a=>a.catnr===c);
function chips(){el('chips').innerHTML=DATA.satelites.map(s=>{const na=anDe(s.catnr).length;
 return `<div class="chip ${s.catnr===SEL?'on':''}" onclick="sel('${s.catnr}')"><span class="dot" style="background:${s._cor}"></span>${s.nome||s.catnr}${na?`<span class="a">⚠${na}</span>`:''}</div>`;}).join('');}
function sel(c){SEL=c;chips();charts();const e=estDe(c).slice(-1)[0];if(globe&&e&&e.lat!=null)globe.pointOfView({lat:e.lat,lng:e.lon,altitude:1.7},800);}
function renderGlobe(){if(!globe)return;
 const paths=[],marks=[];let hits=0;
 // antenas (estações terrenas) = 📡 ; satélites = 🛰️  (distingue claramente)
 ANTENAS.forEach(a=>marks.push({lat:a.lat,lng:a.lon,alt:0,icon:'📡',nome:a.nome,cor:COR_ANT,ant:1}));
 DATA.satelites.forEach(s=>{
   const est=estDe(s.catnr).filter(e=>e.lat!=null).slice(-40); // rasto recente (live)
   if(est.length>1)paths.push({coords:est.map(e=>[e.lat,e.lon,clampAlt((e.alt||750)/R)]),cor:s._cor});
   const e=est[est.length-1];if(!e)return;
   const alt=clampAlt((e.alt||750)/R);
   marks.push({lat:e.lat,lng:e.lon,alt:alt,icon:'🛰️',nome:s.nome,cor:s._cor});
   // hit = contacto: satélite dentro do alcance de visibilidade de uma antena
   const ran=alcance(e.alt||750);
   ANTENAS.forEach(a=>{if(angSep(e.lat,e.lon,a.lat,a.lon)<=ran){
     hits++;
     paths.push({coords:[[a.lat,a.lon,.003],[e.lat,e.lon,alt]],cor:'#2ecc71',hit:true});
   }});
 });
 globe.pathsData(paths).htmlElementsData(marks);
 el('m_ant').textContent=ANTENAS.length;
 el('m_hit').textContent=hits;
}
function anoms(){el('anoms').innerHTML=DATA.anomalias.slice().reverse().map(a=>`<div class="an-row ${a.severidade}"><span class="sev">${a.severidade}</span><div><div class="d">${a.descricao}</div><div class="m">${a.sat} · ${a.codigo} · → OrbitState LSN ${a.orbitstate_lsn}</div></div></div>`).join('')||'<div class="empty">nenhuma anomalia ✓</div>';}
function charts(){const s=DATA.satelites.find(x=>x.catnr===SEL),nm=s?s.nome:'';el('t_sat').textContent=nm;el('v_sat').textContent=nm;
 const e=estDe(SEL).slice(-24);spark('temp',e.map(x=>x.temp),'#F2922A',e,'temp');spark('volt',e.map(x=>x.volt),'#39b3ff',e,'volt');}
function spark(id,vals,color,est,tipo){const s=el(id),W=s.clientWidth||300,H=52,p=14;
 const v=vals.filter(x=>x!=null).map(Number);if(!v.length){s.innerHTML='<text x="6" y="14">sem dados</text>';return;}
 const mn=Math.min(...v),mx=Math.max(...v),rg=(mx-mn)||1;s.setAttribute('viewBox',`0 0 ${W} ${H}`);
 const X=i=>p+i*(W-p-4)/Math.max(vals.length-1,1),Y=x=>H-8-(x-mn)/rg*(H-16);
 let h=`<text x="2" y="9">${mx.toFixed(0)}</text><text x="2" y="${H-2}">${mn.toFixed(0)}</text>`,d='';
 vals.forEach((x,i)=>{if(x==null)return;d+=(d?'L':'M')+X(i)+' '+Y(+x)+' ';});
 h+=`<path d="${d}" fill="none" stroke="${color}" stroke-width="1.6"/>`;
 vals.forEach((x,i)=>{if(x==null)return;const an=est[i]&&((tipo==='temp'&&(+x>45||+x<-20))||(tipo==='volt'&&!est[i].eclipse&&+x<30));h+=`<circle cx="${X(i)}" cy="${Y(+x)}" r="${an?3:1.8}" fill="${an?'#E52207':color}"/>`;});
 s.innerHTML=h;}
load();setInterval(load,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
        elif self.path.startswith("/assets/"):
            fn = os.path.normpath(self.path.split("?")[0].lstrip("/"))
            fp = os.path.join(BASE, fn)
            if fp.startswith(os.path.join(BASE, "assets")) and os.path.isfile(fp):
                with open(fp, "rb") as f:
                    self._send(200, CT.get(os.path.splitext(fp)[1], "application/octet-stream"), f.read())
            else:
                self._send(404, "text/plain", b"asset not found")
        elif self.path.startswith("/api/data"):
            try:
                self._send(200, "application/json", json.dumps(coletar()).encode("utf-8"))
            except Exception as e:
                self._send(500, "application/json", json.dumps({"erro": str(e)}).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=86400" if "/assets/" in self.path else "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"AEB-STREAM dashboard -> http://127.0.0.1:{PORT}  (le {AEB_SERVER})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
