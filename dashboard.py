#!/usr/bin/env python3
# AEB-STREAM — dashboard.py
#
# Dashboard web (stdlib, sem frameworks) sobre a instância AEB do HeraclitusDB.
# Mostra: satélites, trajetória subsatélite num mapa-múndi, séries de telemetria
# (temperatura/tensão) e o painel de anomalias detetadas pelo Cérebro.
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


def _clean_kind(k) -> str:
    s = str(k or "")
    return s[8:-2] if s.startswith('Custom("') and s.endswith('")') else s


def coletar() -> dict:
    """Consulta o banco AEB e devolve satélites, estados e anomalias."""
    c = heraclitusdb.connect(AEB_SERVER)

    def rows(kind):
        r = c.query(f'MATCH (n:{kind}) RETURN n')
        return sorted(r, key=lambda n: int(n.get("lsn", 0))) if isinstance(r, list) else []

    sats = []
    for n in rows("Satelite"):
        a = n.get("attrs", {}) or {}
        sats.append({
            "id": n.get("id"), "catnr": a.get("catnr"), "nome": a.get("nome"),
            "inclinacao": a.get("inclinacao_deg"), "periodo": a.get("periodo_min"),
        })
    estados = []
    for n in rows("OrbitState"):
        a = n.get("attrs", {}) or {}
        estados.append({
            "lsn": n.get("lsn"), "catnr": a.get("catnr"), "sat": a.get("satellite_id"),
            "ts": a.get("ts"), "lat": _f(a.get("latitude")), "lon": _f(a.get("longitude")),
            "alt": _f(a.get("altitude_km")), "temp": _f(a.get("battery_temp")),
            "volt": _f(a.get("solar_voltage")), "eclipse": a.get("eclipse") == "True",
        })
    anomalias = []
    for n in rows("Anomalia"):
        a = n.get("attrs", {}) or {}
        anomalias.append({
            "lsn": n.get("lsn"), "sat": a.get("satellite_id"), "codigo": a.get("codigo"),
            "severidade": a.get("severidade"), "descricao": a.get("descricao"),
            "orbitstate_lsn": a.get("orbitstate_lsn"), "ts": a.get("ts"),
        })
    return {"satelites": sats, "estados": estados, "anomalias": anomalias,
            "head": json.loads(c.stats()["message"])["head"]}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


HTML = r"""<!doctype html><html lang="pt"><head><meta charset="utf-8">
<title>AEB-STREAM — Dashboard</title>
<style>
:root{--bg:#0a0e1a;--pan:#121a2e;--ink:#e6edf7;--mut:#7e8aa3;--acc:#39b3ff;--ok:#2ecc71;
 --crit:#ff4d4f;--alta:#ff9f1c;--media:#ffd23f;--grid:#1d2840}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
 font-family:'Segoe UI',system-ui,sans-serif}
.top{padding:14px 22px;background:linear-gradient(90deg,#0b1430,#142a4d);border-bottom:2px solid var(--acc);
 display:flex;align-items:center;gap:14px}
.top h1{margin:0;font-size:1.15rem;letter-spacing:.5px}.top .sub{color:var(--mut);font-size:.8rem}
.top .head{margin-left:auto;color:var(--mut);font-size:.78rem}
.wrap{display:grid;grid-template-columns:1.4fr 1fr;gap:16px;padding:16px;max-width:1400px;margin:0 auto}
.pan{background:var(--pan);border:1px solid var(--grid);border-radius:12px;padding:14px}
.pan h2{margin:0 0 10px;font-size:.82rem;text-transform:uppercase;letter-spacing:.8px;color:var(--mut)}
.full{grid-column:1/3}
.cards{display:flex;gap:10px;flex-wrap:wrap}
.card{background:#0e1729;border:1px solid var(--grid);border-radius:10px;padding:10px 12px;min-width:170px}
.card .n{font-weight:700;color:var(--acc)}.card .m{color:var(--mut);font-size:.74rem;margin-top:3px}
.chart{width:100%;height:150px}
.an{display:flex;gap:8px;align-items:flex-start;padding:8px;border-radius:8px;background:#0e1729;margin-bottom:7px;
 border-left:4px solid var(--mut)}
.an.CRITICA{border-color:var(--crit)}.an.ALTA{border-color:var(--alta)}.an.MEDIA{border-color:var(--media)}
.an .sev{font-size:.66rem;font-weight:800;padding:2px 6px;border-radius:5px;white-space:nowrap}
.an.CRITICA .sev{background:rgba(255,77,79,.18);color:var(--crit)}
.an.ALTA .sev{background:rgba(255,159,28,.18);color:var(--alta)}
.an.MEDIA .sev{background:rgba(255,210,63,.18);color:var(--media)}
.an .d{font-size:.82rem}.an .meta{color:var(--mut);font-size:.7rem;margin-top:2px}
.empty{color:var(--mut);font-size:.82rem;padding:10px}
.legend{font-size:.7rem;color:var(--mut);margin-top:6px}.legend b{color:var(--ink)}
text{fill:var(--mut);font-size:9px}
</style></head><body>
<div class="top"><h1>🛰️ AEB-STREAM</h1><span class="sub">telemetria orbital · HeraclitusDB</span>
<span class="head" id="head">—</span></div>
<div class="wrap">
  <div class="pan full"><h2>Satélites</h2><div class="cards" id="cards"></div></div>
  <div class="pan"><h2>Trajetória subsatélite</h2><svg class="chart" id="map" viewBox="0 0 360 180" style="height:200px"></svg>
    <div class="legend">● posição atual · linha = passagem · <b id="ptn">—</b> pontos</div></div>
  <div class="pan"><h2>Anomalias detetadas (o Cérebro)</h2><div id="anoms"></div></div>
  <div class="pan"><h2>Temperatura de bateria (°C)</h2><svg class="chart" id="temp"></svg></div>
  <div class="pan"><h2>Tensão dos painéis (V)</h2><svg class="chart" id="volt"></svg></div>
</div>
<script>
const SEV={CRITICA:'🔴',ALTA:'🟠',MEDIA:'🟡'};
function el(id){return document.getElementById(id)}
async function load(){
  const d=await (await fetch('/api/data')).json();
  el('head').textContent='head LSN '+d.head+' · '+d.estados.length+' leituras · '+d.anomalias.length+' anomalias';
  // cards
  el('cards').innerHTML=d.satelites.map(s=>{
    const last=d.estados.filter(e=>e.catnr===s.catnr).slice(-1)[0]||{};
    return `<div class="card"><div class="n">${s.nome||s.catnr}</div>
      <div class="m">NORAD ${s.catnr} · inc ${(+s.inclinacao).toFixed(2)}° · T ${(+s.periodo).toFixed(0)}min</div>
      <div class="m">lat ${fmt(last.lat)} lon ${fmt(last.lon)} · alt ${fmt(last.alt)}km</div>
      <div class="m">bat ${fmt(last.temp)}°C · ${fmt(last.volt)}V ${last.eclipse?'· 🌑':''}</div></div>`;
  }).join('')||'<div class="empty">sem satélites</div>';
  // map
  drawMap(d.estados);
  // charts
  line('temp', d.estados.map(e=>e.temp), '#ff9f1c', d.estados);
  line('volt', d.estados.map(e=>e.volt), '#39b3ff', d.estados);
  // anomalias
  el('anoms').innerHTML=d.anomalias.slice().reverse().map(a=>`
    <div class="an ${a.severidade}"><span class="sev">${SEV[a.severidade]||''} ${a.severidade}</span>
      <div><div class="d">${a.descricao}</div>
      <div class="meta">${a.sat} · ${a.codigo} · OrbitState LSN ${a.orbitstate_lsn} · ${(a.ts||'').slice(11,19)}</div></div></div>`
  ).join('')||'<div class="empty">nenhuma anomalia detetada ✓</div>';
  el('ptn').textContent=d.estados.length;
}
function fmt(v){return v==null?'—':(+v).toFixed(2)}
function drawMap(est){
  const s=el('map');let h='';
  // grelha
  for(let lo=-180;lo<=180;lo+=60){const x=lo+180;h+=`<line x1="${x}" y1="0" x2="${x}" y2="180" stroke="#1d2840"/>`}
  for(let la=-90;la<=90;la+=30){const y=90-la;h+=`<line x1="0" y1="${y}" x2="360" y2="${y}" stroke="#1d2840"/>`}
  // trajetória
  const pts=est.filter(e=>e.lat!=null&&e.lon!=null).map(e=>[e.lon+180,90-e.lat]);
  for(let i=1;i<pts.length;i++){const a=pts[i-1],b=pts[i];
    if(Math.abs(a[0]-b[0])<180) h+=`<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="#39b3ff" stroke-width="1" opacity=".6"/>`}
  pts.forEach((p,i)=>{const last=i===pts.length-1;
    h+=`<circle cx="${p[0]}" cy="${p[1]}" r="${last?3:1.5}" fill="${last?'#2ecc71':'#39b3ff'}"/>`});
  s.innerHTML=h;
}
function line(id,vals,color,est){
  const s=el(id),W=s.clientWidth||340,H=150,pad=22;
  const v=vals.map(x=>x==null?null:+x).filter(x=>x!=null);
  if(!v.length){s.innerHTML='<text x="10" y="20">sem dados</text>';return}
  const mn=Math.min(...v),mx=Math.max(...v),rng=(mx-mn)||1;
  s.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const X=i=>pad+i*(W-pad-6)/Math.max(vals.length-1,1);
  const Y=x=>H-pad-(x-mn)/rng*(H-2*pad);
  let h=`<line x1="${pad}" y1="${H-pad}" x2="${W}" y2="${H-pad}" stroke="#1d2840"/>
         <text x="2" y="${Y(mx)+3}">${mx.toFixed(1)}</text><text x="2" y="${Y(mn)+3}">${mn.toFixed(1)}</text>`;
  let dpath='';vals.forEach((x,i)=>{if(x==null)return;dpath+=(dpath?'L':'M')+X(i)+' '+Y(+x)+' '});
  h+=`<path d="${dpath}" fill="none" stroke="${color}" stroke-width="1.8"/>`;
  vals.forEach((x,i)=>{if(x==null)return;const an=est[i]&&((id==='temp'&&(+x>45||+x<-20))||(id==='volt'&&!est[i].eclipse&&+x<30));
    h+=`<circle cx="${X(i)}" cy="${Y(+x)}" r="${an?3.5:2}" fill="${an?'#ff4d4f':color}"/>`});
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
                body = json.dumps(coletar()).encode("utf-8")
                self._send(200, "application/json", body)
            except Exception as e:
                self._send(500, "application/json",
                           json.dumps({"erro": str(e)}).encode("utf-8"))
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
