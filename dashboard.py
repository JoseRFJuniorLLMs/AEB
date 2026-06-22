#!/usr/bin/env python3
# AEB-STREAM — dashboard.py
#
# Dashboard web sobre a instância AEB do HeraclitusDB. Paleta do Portal da
# Transparência (gov.br). Mostra: satélites, GLOBO 3D com a trajetória orbital
# por cima do planeta, séries de telemetria e o painel de anomalias.
#
#   python dashboard.py            # http://127.0.0.1:7480
#
# Lê do banco AEB (127.0.0.1:7476); não escreve nada (só consulta).

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, r"D:\DEV\HeraclitusDB\sdk\python")
import heraclitusdb  # noqa: E402

AEB_SERVER = os.environ.get("AEB_SERVER", "127.0.0.1:7476")
PORT = 7480


def coletar() -> dict:
    """Consulta o banco AEB e devolve satélites, estados e anomalias."""
    c = heraclitusdb.connect(AEB_SERVER)

    def rows(kind):
        r = c.query(f'MATCH (n:{kind}) RETURN n')
        return sorted(r, key=lambda n: int(n.get("lsn", 0))) if isinstance(r, list) else []

    sats = []
    for n in rows("Satelite"):
        a = n.get("attrs", {}) or {}
        sats.append({"id": n.get("id"), "catnr": a.get("catnr"), "nome": a.get("nome"),
                     "inclinacao": a.get("inclinacao_deg"), "periodo": a.get("periodo_min")})
    estados = []
    for n in rows("OrbitState"):
        a = n.get("attrs", {}) or {}
        estados.append({"lsn": n.get("lsn"), "catnr": a.get("catnr"), "sat": a.get("satellite_id"),
                        "ts": a.get("ts"), "lat": _f(a.get("latitude")), "lon": _f(a.get("longitude")),
                        "alt": _f(a.get("altitude_km")), "temp": _f(a.get("battery_temp")),
                        "volt": _f(a.get("solar_voltage")), "eclipse": a.get("eclipse") == "True"})
    anomalias = []
    for n in rows("Anomalia"):
        a = n.get("attrs", {}) or {}
        anomalias.append({"lsn": n.get("lsn"), "sat": a.get("satellite_id"), "catnr": a.get("catnr"),
                          "codigo": a.get("codigo"), "severidade": a.get("severidade"),
                          "descricao": a.get("descricao"), "orbitstate_lsn": a.get("orbitstate_lsn"),
                          "ts": a.get("ts")})
    return {"satelites": sats, "estados": estados, "anomalias": anomalias,
            "head": json.loads(c.stats()["message"])["head"]}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


HTML = r"""<!doctype html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AEB-STREAM</title>
<style>
:root{--azul:#1351B4;--azul-esc:#0c326f;--amarelo:#FFCD07;--verde:#168821;
 --laranja:#F2922A;--vermelho:#E52207;--bg:#eef1f5;--pan:#fff;--bord:#dfe3e8;
 --ink:#1f2933;--mut:#5f6b7a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
 font-family:'Rawline','Segoe UI',system-ui,sans-serif}
.barra{height:6px;background:var(--azul-esc)}
.top{background:var(--amarelo);padding:12px 22px;display:flex;align-items:center;gap:14px;
 border-bottom:3px solid var(--azul-esc)}
.top h1{margin:0;font-size:1.15rem;color:var(--azul-esc);letter-spacing:.3px}
.top .sub{color:#6b5800;font-size:.8rem}.top .head{margin-left:auto;color:#6b5800;font-size:.78rem}
.wrap{max-width:1400px;margin:0 auto;padding:16px;display:grid;grid-template-columns:1.5fr 1fr;gap:16px}
.pan{background:var(--pan);border:1px solid var(--bord);border-radius:10px;padding:14px}
.pan h2{margin:0 0 10px;font-size:.78rem;text-transform:uppercase;letter-spacing:.7px;color:var(--mut)}
.full{grid-column:1/3}
.metrics{display:flex;gap:12px}
.metric{flex:1;background:#f5f7fa;border-radius:8px;padding:12px 14px}
.metric .l{font-size:.74rem;color:var(--mut)}.metric .v{font-size:1.7rem;font-weight:700;color:var(--azul)}
.metric.crit .v{color:var(--vermelho)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.chip{padding:5px 11px;border-radius:16px;border:1px solid var(--bord);background:#fff;cursor:pointer;
 font-size:.78rem;display:flex;align-items:center;gap:6px}
.chip.on{border-color:var(--azul);background:#eaf1fb;color:var(--azul);font-weight:600}
.chip .dot{width:9px;height:9px;border-radius:50%}.chip .a{color:var(--vermelho);font-weight:700}
#globe{width:100%;height:440px;border-radius:10px;overflow:hidden;background:#0a1020}
.glh{font-size:.72rem;color:var(--mut);margin-top:6px}
.chart{width:100%;height:140px}
.an{display:flex;gap:8px;align-items:flex-start;padding:9px 10px;border-radius:0 8px 8px 0;background:#f7f9fc;
 margin-bottom:7px;border-left:4px solid var(--mut)}
.an.CRITICA{border-color:var(--vermelho)}.an.ALTA{border-color:var(--laranja)}.an.MEDIA{border-color:var(--amarelo)}
.an .sev{font-size:.64rem;font-weight:800;padding:2px 7px;border-radius:5px;white-space:nowrap}
.an.CRITICA .sev{background:#fde7e3;color:var(--vermelho)}
.an.ALTA .sev{background:#fdefdd;color:#9a5a09}.an.MEDIA .sev{background:#fff6cc;color:#6b5800}
.an .d{font-size:.82rem}.an .meta{color:var(--mut);font-size:.7rem;margin-top:2px}
.empty{color:var(--mut);font-size:.82rem;padding:8px}
svg text{fill:var(--mut);font-size:9px}
@media(max-width:900px){.wrap{grid-template-columns:1fr}.full{grid-column:1}}
</style></head><body>
<div class="barra"></div>
<div class="top"><h1>🛰 AEB-STREAM</h1><span class="sub">Telemetria orbital · HeraclitusDB</span>
 <span class="head" id="head">—</span></div>
<div class="wrap">
  <div class="pan full"><h2>Painel da constelação</h2>
    <div class="metrics">
      <div class="metric"><div class="l">Satélites</div><div class="v" id="m_sat">—</div></div>
      <div class="metric"><div class="l">Leituras orbitais</div><div class="v" id="m_est">—</div></div>
      <div class="metric crit"><div class="l">Anomalias detetadas</div><div class="v" id="m_an">—</div></div>
    </div>
    <div class="chips" id="chips"></div>
  </div>

  <div class="pan"><h2>Planeta &amp; trajetória orbital (3D)</h2>
    <div id="globe"></div>
    <div class="glh">Arrasta para rodar · roda do rato para zoom · linha = passagem do satélite · ● posição atual</div>
  </div>

  <div class="pan"><h2>Anomalias detetadas (o Cérebro · ACT-R)</h2><div id="anoms"></div></div>

  <div class="pan"><h2>Temperatura de bateria (°C) — <span id="t_sat"></span></h2><svg class="chart" id="temp"></svg></div>
  <div class="pan"><h2>Tensão dos painéis (V) — <span id="v_sat"></span></h2><svg class="chart" id="volt"></svg></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/globe.gl"></script>
<script>
const SEV={CRITICA:'🔴',ALTA:'🟠',MEDIA:'🟡'};
const CORES=['#1351B4','#168821','#E52207','#F2922A','#5f259f','#00a0a0','#b30059'];
const R_TERRA=6371;
let DATA=null, SEL=null, globe=null;
const el=id=>document.getElementById(id);

async function load(){
  DATA=await (await fetch('/api/data')).json();
  el('head').textContent='head LSN '+DATA.head+' · '+DATA.estados.length+' leituras · '+DATA.anomalias.length+' anomalias';
  el('m_sat').textContent=DATA.satelites.length;
  el('m_est').textContent=DATA.estados.length;
  el('m_an').textContent=DATA.anomalias.length;
  // cor por satélite
  DATA.satelites.forEach((s,i)=>s._cor=CORES[i%CORES.length]);
  if(!SEL && DATA.satelites.length){
    const comAnom=DATA.anomalias[0]?DATA.anomalias[0].catnr:null;
    SEL=comAnom||DATA.satelites[0].catnr;
  }
  renderChips(); renderGlobe(); renderAnoms(); renderCharts();
}
function estadosDe(catnr){return DATA.estados.filter(e=>e.catnr===catnr)}
function anomDe(catnr){return DATA.anomalias.filter(a=>a.catnr===catnr)}

function renderChips(){
  el('chips').innerHTML=DATA.satelites.map(s=>{
    const na=anomDe(s.catnr).length;
    return `<div class="chip ${s.catnr===SEL?'on':''}" onclick="sel('${s.catnr}')">
      <span class="dot" style="background:${s._cor}"></span>${s.nome||s.catnr}
      ${na?`<span class="a">⚠${na}</span>`:''}</div>`;
  }).join('')||'<div class="empty">sem satélites — corre o pipeline/seed</div>';
}
function sel(c){SEL=c;renderChips();renderCharts();if(globe)focar(c)}

function renderGlobe(){
  const paths=DATA.satelites.map(s=>{
    const pts=estadosDe(s.catnr).filter(e=>e.lat!=null).map(e=>[e.lat,e.lon,(e.alt||750)/R_TERRA]);
    return {coords:pts,cor:s._cor,nome:s.nome};
  }).filter(p=>p.coords.length>1);
  const pontos=DATA.satelites.map(s=>{
    const e=estadosDe(s.catnr).slice(-1)[0]; if(!e||e.lat==null)return null;
    return {lat:e.lat,lng:e.lon,alt:(e.alt||750)/R_TERRA,cor:s._cor,nome:s.nome};
  }).filter(Boolean);
  if(!globe){
    globe=Globe()(el('globe'))
      .globeImageUrl('https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-blue-marble.jpg')
      .bumpImageUrl('https://cdn.jsdelivr.net/npm/three-globe/example/img/earth-topology.png')
      .backgroundColor('#0a1020').atmosphereColor('#1351B4').atmosphereAltitude(0.18)
      .pathColor(p=>p.cor).pathStroke(2.2).pathPointAlt(p=>p[2])
      .pathTransitionDuration(0)
      .pointColor(p=>p.cor).pointAltitude(p=>p.alt).pointRadius(0.55)
      .pointLabel(p=>p.nome);
    globe.controls().autoRotate=true; globe.controls().autoRotateSpeed=0.5;
    globe.controls().enableZoom=true;
    const w=el('globe').clientWidth; globe.width(w).height(440);
    window.addEventListener('resize',()=>{const w=el('globe').clientWidth;globe.width(w).height(440)});
  }
  globe.pathsData(paths).pointsData(pontos);
}
function focar(catnr){
  const e=estadosDe(catnr).slice(-1)[0]; if(e&&e.lat!=null) globe.pointOfView({lat:e.lat,lng:e.lon,altitude:1.8},800);
}

function renderAnoms(){
  el('anoms').innerHTML=DATA.anomalias.slice().reverse().map(a=>`
    <div class="an ${a.severidade}"><span class="sev">${SEV[a.severidade]||''} ${a.severidade}</span>
      <div><div class="d">${a.descricao}</div>
      <div class="meta">${a.sat} · ${a.codigo} · proveniência → OrbitState LSN ${a.orbitstate_lsn}</div></div></div>`
  ).join('')||'<div class="empty">nenhuma anomalia detetada ✓</div>';
}
function renderCharts(){
  const s=DATA.satelites.find(x=>x.catnr===SEL); const nm=s?s.nome:'';
  el('t_sat').textContent=nm; el('v_sat').textContent=nm;
  const e=estadosDe(SEL);
  line('temp', e.map(x=>x.temp), '#F2922A', e, 'temp');
  line('volt', e.map(x=>x.volt), '#1351B4', e, 'volt');
}
function line(id,vals,color,est,tipo){
  const s=el(id),W=s.clientWidth||340,H=140,pad=22;
  const v=vals.filter(x=>x!=null).map(Number);
  if(!v.length){s.innerHTML='<text x="10" y="20">sem dados</text>';return}
  const mn=Math.min(...v),mx=Math.max(...v),rng=(mx-mn)||1;
  s.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const X=i=>pad+i*(W-pad-6)/Math.max(vals.length-1,1), Y=x=>H-pad-(x-mn)/rng*(H-2*pad);
  let h=`<line x1="${pad}" y1="${H-pad}" x2="${W}" y2="${H-pad}" stroke="#dfe3e8"/>
        <text x="2" y="${Y(mx)+3}">${mx.toFixed(1)}</text><text x="2" y="${Y(mn)+3}">${mn.toFixed(1)}</text>`;
  let dp='';vals.forEach((x,i)=>{if(x==null)return;dp+=(dp?'L':'M')+X(i)+' '+Y(+x)+' '});
  h+=`<path d="${dp}" fill="none" stroke="${color}" stroke-width="1.8"/>`;
  vals.forEach((x,i)=>{if(x==null)return;
    const an=est[i]&&((tipo==='temp'&&(+x>45||+x<-20))||(tipo==='volt'&&!est[i].eclipse&&+x<30));
    h+=`<circle cx="${X(i)}" cy="${Y(+x)}" r="${an?3.6:2}" fill="${an?'#E52207':color}"/>`});
  s.innerHTML=h;
}
load();setInterval(load,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
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
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(f"AEB-STREAM dashboard -> http://127.0.0.1:{PORT}  (le {AEB_SERVER})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
