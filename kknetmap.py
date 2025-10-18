#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KKNETMAP (v1.8) — Flask + D3.js

Por Otávio Augusto @oaugustopro www.oaugusto.pro


O que está incluso:
- Posição de hosts/portas salva; zoom do grafo e da timeline salvos.
- Sidebar com notas (maior, 90% transparente), edição de cor do elemento e da borda.
- Emojis fixados por host (com busca por nome).
- Eventos (nome, tag, emoji, cor, data/hora + nota) por host/porta.
  • Regras de data/hora:
    - Só HORA → hoje com essa hora.
    - Só DATA → data escolhida com 00:00:00.
    - DATA + HORA → exatamente o selecionado.
    - Vazio → agora.
  • Ao clicar na hora na lista, mini editor (date+time).
  • Salva e timeline atualiza automático.
- Timeline:
  • Eixo com ticks adaptativos (meses/dias/horas/minutos) conforme span + zoom.
  • Zoom da timeline persistente; redimensionável por handle superior.
  • Eventos não se sobrepõem (lanes); stems verticais SEMPRE atrás e “coladas” no centro do evento.
  • Arrastar evento é vertical (x ancorado no tempo); stem acompanha e volta pra âncora suavemente.
  • Card do evento exibe “último octeto” ou “octeto:porta”.
  • Clicar no evento destaca o nó no grafo (halo).
- Filtros do grafo (painel minimizável, persistente):
  • Allow/Deny por emojis fixados (chips com busca por nome).
  • Allow/Deny por REGEX (chips).
  • Allow/Deny por NOME (chips) — “nome” = host (nome/IP) ou porta (número/serviço).
  • Regras:
    - Se HOST casa (nome/regex): host e TODAS as portas ficam visíveis (salvas as outras regras).
    - Se PORTA casa: só aquela porta aparece, desde que o host esteja visível.
    - Deny em host derruba host + portas; deny em porta derruba só a porta.
- Custom links (duplo clique inicia; Esc cancela):
  • Estilos: reta/curva/tracejada, cor, rótulo no centro, notas; conectados centro a centro.
- Marca “KKNETMAP by kktools” no topo, mudando cor e fonte a cada 5min.
- Painel de instruções em Markdown (canto inferior esquerdo), com preview.
- Comentários inline explicando as partes mais importantes.
"""

import os
import json
import re
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request

# =============================================================================
# Config
# =============================================================================

SCAN_FILE = 'hosts.txt'
DATA_FILE = 'data.txt'

# Cores padrão por porta conhecida (mantido)
DEFAULT_PORT_COLORS = {
    80:   '#E52D2D', 23:   '#2D63E5', 443:  '#99E52D', 21:   '#E52DCE',
    25:   '#5B2DE5', 110:  '#35E52D', 139:  '#E52D6B', 445:  '#2DA0E5',
    143:  '#D6E52D', 53:   '#BE2DE5', 135:  '#2DE589', 8080: '#E5532D',
    1723: '#2D3DE5', 3306: '#E5D52D', 111:  '#2D80E5', 995:  '#E52D80',
    993:  '#2DE58E', 5900: '#E5A02D', 514:  '#4A2DE5', 137:  '#E52D47',
    138:  '#2DD2E5', 548:  '#CBC02D', 465:  '#AD2DE5', 587:  '#2DE595',
    631:  '#E5C02D', 1025: '#2DCDE5', 2049: '#D52DE5', 6667: '#2DE5A4',
    123:  '#E52DA9', 179:  '#2DE5B3', 636:  '#E52DA0', 1900: '#2DE5C1',
    69:   '#E5922D', 3128: '#2D43E5', 119:  '#8AE52D', 1433: '#E52DC0',
    554:  '#2DE5D5', 512:  '#E59F2D', 513:  '#6A2DE5', 10000:'#2DE534',
    8443: '#E52D5C', 20:   '#2D92E5', 161:  '#C7E52D', 162:  '#CD2DE5',
    8000: '#2DE597', 5432: '#E5622D', 1521: '#2D2FE5', 5060: '#64E52D',
    5985: '#FF0000', 3389: '#FFD580', 5040: '#FF8C00', 22:   '#FFFFFF',
}

# Catálogo de emojis para busca por nome (para pins e para eventos)
EMOJI_CATALOG = [
    {"name": "server", "emoji": "🖥️"},  {"name": "database", "emoji": "🗄️"},
    {"name": "warning", "emoji": "⚠️"}, {"name": "fire", "emoji": "🔥"},
    {"name": "check", "emoji": "✅"},   {"name": "bug", "emoji": "🐞"},
    {"name": "lock", "emoji": "🔒"},    {"name": "unlock", "emoji": "🔓"},
    {"name": "key", "emoji": "🔑"},     {"name": "lightning", "emoji": "⚡"},
    {"name": "satellite", "emoji": "🛰️"},{"name": "globe", "emoji": "🌐"},
    {"name": "gear", "emoji": "⚙️"},    {"name": "robot", "emoji": "🤖"},
    {"name": "skull", "emoji": "💀"},   {"name": "rocket", "emoji": "🚀"},
    {"name": "shield", "emoji": "🛡️"}, {"name": "clock", "emoji": "🕒"},
    {"name": "antenna", "emoji": "📡"}, {"name": "folder", "emoji": "📁"},
    {"name": "note", "emoji": "📝"},    {"name": "bell", "emoji": "🔔"},
    {"name": "plug", "emoji": "🔌"},    {"name": "wifi", "emoji": "📶"},
    {"name": "camera", "emoji": "📷"},  {"name": "chip", "emoji": "🧠"},
]

app = Flask(__name__)

# =============================================================================
# Parse + Persist
# =============================================================================

def parse_scan():
    """Lê hosts.txt (saída 'greppable' do nmap) e gera estrutura básica de hosts/portas."""
    hosts = []
    if not os.path.isfile(SCAN_FILE):
        return hosts

    with open(SCAN_FILE, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s or not s.startswith('Host:'):
                continue

            parts = s.split('\t')
            host_part = parts[0][len('Host:'):].strip()
            m = re.match(r'([\d\.]+)\s*\((.*?)\)', host_part)
            if m:
                ip = m.group(1)
                name = m.group(2) or ip
            else:
                ip = host_part.split()[0]
                name = ip

            ports = []
            if len(parts) > 1 and parts[1].startswith('Ports:'):
                entries = parts[1][len('Ports:'):].split(',')
                for entry in entries:
                    entry = entry.strip()
                    if not entry:
                        continue
                    tokens = entry.split('/')
                    try:
                        pnum = int(tokens[0])
                    except Exception:
                        continue
                    service = tokens[4] if len(tokens) > 4 else ''
                    ports.append({
                        'port': pnum,
                        'service': service,
                        'note': '',
                        'border': False,
                        'border_color': '#FFD400',
                        'color': None,
                        'fx': None, 'fy': None,
                        'events': [],
                    })

            hosts.append({
                'id': ip, 'ip': ip, 'name': name,
                'note': '',
                'border': False,
                'border_color': '#FFD400',
                'color': None,
                'fx': None, 'fy': None,
                'pinned_emojis': [],
                'events': [],
                'ports': ports
            })
    return hosts


def merge_saved_into_scan(scan_hosts, saved):
    """Mescla estado salvo (data.txt) com resultado atual do scan, preservando posições/notas/cores/eventos etc."""
    saved_hosts = saved.get('hosts', {})
    for h in scan_hosts:
        sid = h['id']
        sh = saved_hosts.get(sid, {})

        h['note'] = sh.get('note', '')
        h['border'] = sh.get('border', False)
        h['border_color'] = sh.get('border_color', h.get('border_color', '#FFD400'))
        h['color'] = sh.get('color', None)
        h['fx'] = sh.get('fx', None)
        h['fy'] = sh.get('fy', None)
        h['pinned_emojis'] = sh.get('pinned_emojis', [])
        h['events'] = sh.get('events', [])

        saved_ports = sh.get('ports', {})
        for p in h['ports']:
            sp = saved_ports.get(str(p['port']), {})
            p['note'] = sp.get('note', '')
            p['border'] = sp.get('border', False)
            p['border_color'] = sp.get('border_color', p.get('border_color', '#FFD400'))
            p['color'] = sp.get('color', None)
            p['fx'] = sp.get('fx', None)
            p['fy'] = sp.get('fy', None)
            p['events'] = sp.get('events', [])
    return scan_hosts


def load_data():
    """Carrega estado persistido (ou cria defaults)."""
    data = {
        'hosts': parse_scan(),
        'zoom': {'k': 1, 'x': 0, 'y': 0},
        'timeline_zoom': {'k': 1, 'x': 0, 'y': 0},
        'links': [],
        'instructions': ""
    }
    if not os.path.isfile(DATA_FILE):
        return data

    try:
        with open(DATA_FILE, encoding='utf-8') as f:
            saved = json.load(f)
        data['hosts'] = merge_saved_into_scan(data['hosts'], saved)
        if isinstance(saved.get('zoom'), dict):
            z = saved['zoom']; data['zoom'] = {'k': float(z.get('k', 1)), 'x': float(z.get('x', 0)), 'y': float(z.get('y', 0))}
        if isinstance(saved.get('timeline_zoom'), dict):
            tz = saved['timeline_zoom']; data['timeline_zoom'] = {'k': float(tz.get('k', 1)), 'x': float(tz.get('x', 0)), 'y': float(tz.get('y', 0))}
        if isinstance(saved.get('links'), list):
            data['links'] = saved['links']
        data['instructions'] = saved.get('instructions', "")
    except Exception:
        pass
    return data


def save_data(received):
    """Salva estado em data.txt (formato compacto)."""
    out = {
        'hosts': {},
        'zoom': {'k': 1, 'x': 0, 'y': 0},
        'timeline_zoom': {'k': 1, 'x': 0, 'y': 0},
        'links': [],
        'instructions': received.get('instructions', "")
    }

    z = received.get('zoom', {}) or {}
    out['zoom'] = {'k': float(z.get('k', 1)), 'x': float(z.get('x', 0)), 'y': float(z.get('y', 0))}
    tz = received.get('timeline_zoom', {}) or {}
    out['timeline_zoom'] = {'k': float(tz.get('k', 1)), 'x': float(tz.get('x', 0)), 'y': float(tz.get('y', 0))}

    for l in received.get('links', []):
        out['links'].append({
            'id': l.get('id'),
            'source': l.get('source'),
            'target': l.get('target'),
            'style': l.get('style', 'straight'),
            'color': l.get('color', '#555555'),
            'label': l.get('label', ''),
            'note': l.get('note', '')
        })

    for h in received.get('hosts', []):
        hid = h.get('id')
        if not hid:
            continue
        out['hosts'][hid] = {
            'note': h.get('note', ''),
            'border': bool(h.get('border', False)),
            'border_color': h.get('border_color', '#FFD400'),
            'color': h.get('color', None),
            'fx': h.get('fx', None),
            'fy': h.get('fy', None),
            'pinned_emojis': h.get('pinned_emojis', []),
            'events': h.get('events', []),
            'ports': {}
        }
        for p in h.get('ports', []):
            pid = str(p.get('port'))
            out['hosts'][hid]['ports'][pid] = {
                'note': p.get('note', ''),
                'border': bool(p.get('border', False)),
                'border_color': p.get('border_color', '#FFD400'),
                'color': p.get('color', None),
                'fx': p.get('fx', None),
                'fy': p.get('fy', None),
                'events': p.get('events', []),
            }

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


# =============================================================================
# Routes
# =============================================================================

@app.route('/data')
def data_route():
    return jsonify(load_data())


@app.route('/save', methods=['POST'])
def save_route():
    payload = request.get_json(force=True) or {}
    save_data(payload)
    return jsonify({'status': 'ok', 'ts': datetime.utcnow().isoformat() + 'Z'})


@app.route('/')
def index_route():
    """Template único (HTML/CSS/JS)."""
    HOST_EMOJIS = ['🐱', '🐶', '🦊', '🐼', '🐸', '🐵', '🐤', '🦁', '🐷', '🐯']

    html = render_template_string("""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>KKNETMAP</title>
<style>
    :root{
        --sidebar-w: 360px;
        --timeline-h: 230px;   /* altura ajustável via handle */
        --panel-bg: rgba(255,255,255,0.90); /* 90% transparente como pedido */
    }
    *{ box-sizing: border-box; }
    body{ margin:0; font-family: Inter, system-ui, Arial, sans-serif; background:#f0f0f3; }

    /* Marca grande no topo */
    #brandHeader{
        position:fixed; top:8px; width:100%; text-align:center;
        font-weight:900; font-size:clamp(22px,7vw,90px); opacity:0.12;
        pointer-events:none; user-select:none; z-index:0; transition:color 800ms ease, font-family 400ms ease;
        text-shadow: 0 2px 12px rgba(0,0,0,.18);
    }
    #brandHeader small{ font-weight:700; font-size:.42em; opacity:.85; }

    #topWrap{ position:relative; height: calc(100vh - var(--timeline-h)); }
    #canvas{ width:100%; height:100%; display:block; }

    /* Painel de filtros do grafo (com header e minimize) */
    #topFilters{
        position:absolute; left:10px; top:10px; width:520px; z-index:3;
        background: var(--panel-bg); border:1px solid #ccc; border-radius:10px; padding:10px 12px;
        box-shadow:0 2px 12px rgba(0,0,0,.2); font-size:12px;
    }
    #topFilters .header{ display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; }
    #topFilters .toggle{ cursor:pointer; border:1px solid #bbb; border-radius:6px; padding:2px 8px; background:#fff; font-size:12px; line-height:1; }
    #topFilters.collapsed{ width:auto; padding:6px 8px; }
    #topFilters.collapsed .body{ display:none; }

    .chipsRow{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }
    .chip{ display:inline-flex; gap:6px; align-items:center; padding:2px 8px; border:1px solid #ccc; border-radius:999px; background:#fff; }
    .chip .x{ cursor:pointer; font-weight:bold; }
    .emojiSearchWrap{ position:relative; margin-top:6px; }
    .emojiResults{ position:absolute; background:#fff; border:1px solid #ccc; border-radius:8px; z-index:5; max-height:140px; overflow:auto; width:100%; }
    .emojiResults div{ padding:6px 8px; cursor:pointer; }
    .emojiResults div:hover{ background:#f1f1f1; }
    #topFilters input[type="text"]{ width:100%; padding:6px 8px; border:1px solid #bbb; border-radius:8px; background:#fff; font-size:12px; }

    /* Tooltip do grafo */
    #tooltip{
        position:absolute; max-width:320px; padding:8px 10px; border:1px solid #ddd; border-radius:8px;
        background: var(--panel-bg); box-shadow:0 2px 10px rgba(0,0,0,.2); display:none; pointer-events:none; z-index:5;
        font-size:12px;
    }

    /* Sidebar (detalhes) */
    #sidebar{
        position:absolute; right:10px; top:10px; width:var(--sidebar-w); background:var(--panel-bg); z-index:3;
        border:1px solid #ccc; border-radius:10px; box-shadow:0 2px 12px rgba(0,0,0,.2); padding:12px;
        max-height: calc(100% - 20px); overflow-y:auto;
    }
    #sidebar h2{ margin:0 0 8px; font-size:1.2em; }
    #sidebar h3{ margin:14px 0 6px; font-size:1em; }
    #sidebar label{ display:block; margin:8px 0 4px; font-size:12px; }
    #sidebar textarea{
        width:100%; height:150px; padding:8px; border:1px solid #bbb; border-radius:8px; background:rgba(255,255,255,.9);
        resize:vertical;
    }
    #sidebar input, #sidebar select { width:100%; padding:6px 8px; border:1px solid #bbb; border-radius:8px; background:#fff; font-size:12px; }
    .btn{ display:inline-block; padding:6px 10px; border:1px solid #999; border-radius:8px; background:#fff; cursor:pointer; font-size:12px; margin-right:6px; }
    .btn:hover{ background:#f4f4f4; }
    .pill{ display:inline-flex; align-items:center; gap:6px; padding:2px 8px; border:1px solid #ccc; border-radius:999px; background:#fff; margin:2px; font-size:12px; }
    .pill .x{ cursor:pointer; font-weight:bold; }

    /* Halo (destaque) no grafo ao clicar evento na timeline */
    @keyframes pulseHalo{ 0%{ r:0; opacity:.9; } 100%{ r:40; opacity:0; } }
    .halo{ fill:none; stroke:#FFD54F; stroke-width:8px; opacity:.9; animation: pulseHalo 900ms ease-out forwards; pointer-events:none; }

    /* Timeline wrapper + handle de resize */
    #timelineWrap{
        position:fixed; left:0; bottom:0; width:100%; height: var(--timeline-h); background:#fff; z-index:2;
        border-top:1px solid #ddd; display:grid; grid-template-rows: 8px 52px 1fr; /* 8px = handle */
    }
    #timelineResizer{
        cursor:ns-resize; background:linear-gradient(to bottom, #e9e9e9, #f7f7f7);
        border-bottom:1px solid #ddd; position:relative;
    }
    #timelineResizer:after{
        content:''; position:absolute; left:50%; top:50%; transform:translate(-50%,-50%);
        width:36px; height:3px; border-radius:3px; background:#bbb;
        box-shadow: 0 6px 0 #bbb, 0 -6px 0 #bbb;
        opacity:.8;
    }

    /* Filtros da timeline (parte de baixo) */
    #timelineFilters{
        display:grid; grid-template-columns: 2fr 1.2fr 1.6fr 1.4fr 1.4fr 100px; gap:8px; padding:8px 12px; align-items:center;
        border-bottom:1px solid #eee; background:#fafafa;
    }
    #timelineFilters input, #timelineFilters select { padding:6px 8px; border:1px solid #bbb; border-radius:8px; background:#fff; font-size:12px; }
    #timelineSVG{ width:100%; height:100%; }
    .evtNode circle{ cursor:pointer; }
    .evtNode text{ font-size:10px; text-anchor:middle; }
    .evtStem{ stroke:#555; stroke-width:1.5px; }
    .evtSelected{ filter: drop-shadow(0 0 6px rgba(255,165,0,.9)); }
    .evtLabel{ font-size:10px; text-anchor:middle; }
    .timelineAxis text{ font-size:10px; }

    /* Notas (Markdown) — canto inferior esquerdo */
    #noteToggle{
        position:fixed; left:10px; bottom: var(--timeline-h); transform: translateY(-8px);
        width:26px; height:26px; border-radius:6px; border:1px solid #bbb; background:#fff; z-index:4;
        box-shadow:0 2px 8px rgba(0,0,0,.2); display:flex; align-items:center; justify-content:center; cursor:pointer;
        font-weight:bold;
    }
    #notePanel{
        position:fixed; left:10px; bottom: calc(var(--timeline-h) + 32px);
        width:420px; max-height:50vh; overflow:auto; z-index:4; display:none;
        background:var(--panel-bg); border:1px solid #ccc; border-radius:10px; padding:10px; box-shadow:0 2px 12px rgba(0,0,0,.25);
    }
    #notePanel h3{ margin:0 0 8px; }
    #notePanel textarea{ width:100%; height:160px; border:1px solid #bbb; border-radius:8px; padding:8px; background:#fff; }
    #notePreview{ margin-top:8px; background:#fff; border:1px solid #ddd; border-radius:8px; padding:8px; }
</style>
</head>
<body>
    <!-- Marca grande -->
    <div id="brandHeader">KKNETMAP <small>by kktools</small></div>

    <div id="topWrap">
        <!-- Painel de filtros (grafo) -->
        <div id="topFilters">
          <div class="header">
            <h3>Filtros (grafo)</h3>
            <button id="topFiltersToggle" class="toggle" title="Minimizar">–</button>
          </div>
          <div class="body">
            <!-- ALLOW emojis -->
            <div><strong>Allow emojis fixados</strong></div>
            <div id="allowChips" class="chipsRow"></div>
            <div class="emojiSearchWrap">
              <input id="allowSearch" type="text" placeholder="Digite para buscar (ex: rocket, lock...)" />
              <div id="allowResults" class="emojiResults" style="display:none"></div>
            </div>

            <!-- DENY emojis -->
            <div style="margin-top:8px"><strong>Deny emojis fixados</strong></div>
            <div id="denyChips" class="chipsRow"></div>
            <div class="emojiSearchWrap">
              <input id="denySearch" type="text" placeholder="Digite para buscar (ex: skull, bug...)" />
              <div id="denyResults" class="emojiResults" style="display:none"></div>
            </div>

            <!-- REGEX allow/deny (chips) -->
            <div style="margin-top:10px"><strong>Regex (allow)</strong></div>
            <div id="rxAllowChips" class="chipsRow"></div>
            <input id="rxAllowInput" type="text" placeholder="Regex, Enter para adicionar (ex: (scan|backup))" />

            <div style="margin-top:10px"><strong>Regex (deny)</strong></div>
            <div id="rxDenyChips" class="chipsRow"></div>
            <input id="rxDenyInput" type="text" placeholder="Regex, Enter para adicionar (ex: tmp|teste)" />

            <!-- NOME allow/deny (chips) -->
            <div style="margin-top:10px"><strong>Nome (allow)</strong> <small>(host ou porta; ex: 22, web, db)</small></div>
            <div id="nmAllowChips" class="chipsRow"></div>
            <input id="nmAllowInput" type="text" placeholder="Termo, Enter para adicionar" />

            <div style="margin-top:10px"><strong>Nome (deny)</strong> <small>(host ou porta; ex: lab, dev)</small></div>
            <div id="nmDenyChips" class="chipsRow"></div>
            <input id="nmDenyInput" type="text" placeholder="Termo, Enter para adicionar" />
          </div>
        </div>

        <!-- Grafo -->
        <svg id="canvas"></svg>

        <!-- Tooltip -->
        <div id="tooltip"></div>

        <!-- Sidebar (detalhes) -->
        <div id="sidebar">
            <h2>Detalhes</h2>
            <div id="info">Clique em um host, porta, ou link para editar. Duplo clique em um nó inicia um link; <b>Esc</b> cancela.</div>
        </div>
    </div>

    <!-- Botão/caixa de anotações (Markdown) -->
    <div id="noteToggle">✎</div>
    <div id="notePanel">
        <h3>Instruções do NetMap (Markdown)</h3>
        <textarea id="noteInput" placeholder="Escreva aqui suas instruções/legenda de organização. Markdown suportado."></textarea>
        <div id="notePreview"></div>
        <div style="margin-top:8px"><button id="noteSave" class="btn">Salvar</button> <button id="noteClose" class="btn">Fechar</button></div>
    </div>

    <!-- Timeline -->
    <div id="timelineWrap">
        <div id="timelineResizer" title="Arraste para redimensionar a timeline"></div>

        <div id="timelineFilters">
            <input id="fltText" placeholder="Regex em nome/tag/host (ex: busca|scan)" />
            <select id="fltEmoji"><option value="">Emoji</option></select>
            <select id="fltHost"><option value="">Todos os hosts</option></select>
            <input id="fltFrom" type="date" />
            <input id="fltTo"   type="date" />
            <button id="fltClear" class="btn">Limpar</button>
        </div>
        <svg id="timelineSVG"></svg>
    </div>

    <!-- Libs -->
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
    // === Dados vindos do backend ===
    const DEFAULT_PORT_COLORS = {{ default_port_colors | tojson }};
    const HOST_EMOJIS        = {{ host_emojis | tojson }};
    const EMOJI_CATALOG      = {{ emoji_catalog | tojson }};

    // === SVG principal + grupos/layers ===
    const svg   = d3.select('#canvas');
    const gRoot = svg.append('g');   // tudo que sofre zoom/pan

    const gBuiltins    = gRoot.append('g').attr('id','gBuiltins');    // links host↔porta
    const gCustomLinks = gRoot.append('g').attr('id','gCustomLinks'); // links desenhados
    const gNodes       = gRoot.append('g').attr('id','gNodes');       // nós (hosts/portas)
    const gLabels      = gRoot.append('g').attr('id','gLabels');      // labels (emoji/número)
    const gPins        = gRoot.append('g').attr('id','gPins');        // emojis fixados
    const gHalo        = gRoot.append('g').attr('id','gHalo');        // halos de destaque

    const tooltip      = d3.select('#tooltip');
    const topWrap      = document.getElementById('topWrap');

    // === Timeline ===
    const tlSVG   = d3.select('#timelineSVG');
    const tlAxisG = tlSVG.append('g').attr('class','timelineAxis');
    // stems no fundo (linhas verticais)
    const tlStemsG = tlSVG.append('g').attr('class','timelineStems');
    // eventos acima
    const tlG     = tlSVG.append('g');

    // === Estado global ===
    let state = {
        hosts: [],
        links: [],
        zoom: {k:1,x:0,y:0},
        timeline_zoom: {k:1,x:0,y:0},
        instructions: ""
    };

    // === Simulador do grafo ===
    let simulation = null;
    let simNodes = [], simLinks = [];
    let builtInLinksSel = null, nodeSel = null, labelSel = null, pinSel = null;
    let customLinkSel = null, customLinkLabelSel = null;

    // Seleção atual (para painel de detalhes e highlight na timeline)
    let selected = null;

    // Largura da borda quando ativada por clique direito
    const BORDER_WIDTH = 6;

    // ---------------- Util de cor: clarear o fill para destacar bordas/pins ----------------
    function lightenColor(c, amt=0.14){
        const col = d3.color(c) || d3.color('#9aa');
        const hsl = d3.hsl(col);
        hsl.l = Math.min(1, hsl.l + amt);
        return hsl.formatHex();
    }
    function colorForHost(host, idx){
        const base = host.color || d3.schemeCategory10[idx % 10];
        return lightenColor(base, 0.12);
    }
    function colorForPort(port){
        const base = port.color || DEFAULT_PORT_COLORS[port.port] || '#9E9E9E';
        return lightenColor(base, 0.10);
    }

    // ---------------- Persistência ----------------
    function saveAll(){
        const payload = {
            hosts: state.hosts.map(h => ({
                id:h.id, ip:h.ip, name:h.name,
                note:h.note||'', border:!!h.border, border_color:h.border_color||'#FFD400',
                color:h.color||null,
                fx: typeof h.fx==='number'?h.fx:null, fy: typeof h.fy==='number'?h.fy:null,
                pinned_emojis: Array.isArray(h.pinned_emojis)?h.pinned_emojis:[],
                events: Array.isArray(h.events)?h.events:[],
                ports: h.ports.map(p => ({
                    port:p.port, service:p.service,
                    note:p.note||'', border:!!p.border, border_color:p.border_color||'#FFD400',
                    color:p.color||null,
                    fx: typeof p.fx==='number'?p.fx:null, fy: typeof p.fy==='number'?p.fy:null,
                    events: Array.isArray(p.events)?p.events:[]
                }))
            })),
            links: state.links.map(l => ({
                id:l.id, source:l.source, target:l.target,
                style:l.style||'straight', color:l.color||'#555555',
                label:l.label||'', note:l.note||''
            })),
            zoom: state.zoom,
            timeline_zoom: state.timeline_zoom,
            instructions: state.instructions || ""
        };
        fetch('/save',{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}).catch(()=>{});
    }

    // IDs helper
    function newId(prefix='id'){ return prefix + '-' + Date.now().toString(36) + Math.random().toString(36).slice(2,7); }
    function findHost(id){ return state.hosts.find(h => h.id === id) || null; }
    function findPort(hostId, port){ const h=findHost(hostId); return h ? (h.ports.find(p=>p.port===port)||null) : null; }
    function pid(hostId, port){ return hostId + '_' + port; }

    // ---------------- Zoom/Pan do grafo (persistente) ----------------
    let currentTransform = d3.zoomIdentity;
    const zoomBehavior = d3.zoom()
        .scaleExtent([0.2, 5])
        .on('zoom', ev => {
            currentTransform = ev.transform;
            gRoot.attr('transform', currentTransform);
        })
        .on('end', () => {
            state.zoom = { k: currentTransform.k, x: currentTransform.x, y: currentTransform.y };
            saveAll();
        });
    svg.call(zoomBehavior);

    function applySavedZoom(z){
        currentTransform = d3.zoomIdentity.translate(z.x||0, z.y||0).scale(z.k||1);
        svg.call(zoomBehavior.transform, currentTransform);
    }

    function resizeSVG(){ svg.attr('width', topWrap.clientWidth).attr('height', topWrap.clientHeight); }
    window.addEventListener('resize', resizeSVG);

    // ---------------- Filtros do grafo: emojis allow/deny ----------------
    const allowChips = document.getElementById('allowChips');
    const allowSearch = document.getElementById('allowSearch');
    const allowResults = document.getElementById('allowResults');
    const denyChips = document.getElementById('denyChips');
    const denySearch = document.getElementById('denySearch');
    const denyResults = document.getElementById('denyResults');

    const allowSet = new Set();  // emojis allow
    const denySet  = new Set();  // emojis deny

    function renderChips(container, setRef){
        container.innerHTML = '';
        Array.from(setRef).forEach(emoji=>{
            const el = document.createElement('span');
            el.className = 'chip';
            el.textContent = emoji + ' ';
            const x = document.createElement('span');
            x.className = 'x'; x.textContent = '×';
            x.onclick = ()=>{ setRef.delete(emoji); renderChips(container, setRef); applyTopFiltersVisibility(); };
            el.appendChild(x);
            container.appendChild(el);
        });
    }
    function attachEmojiSearch(input, resultsBox, onPick){
        input.addEventListener('input', ()=>{
            const q = (input.value||'').trim().toLowerCase();
            if (!q){ resultsBox.style.display='none'; resultsBox.innerHTML=''; return; }
            const hits = EMOJI_CATALOG.filter(e=> e.name.includes(q)).slice(0,12);
            resultsBox.innerHTML = '';
            hits.forEach(e=>{
                const div = document.createElement('div');
                div.textContent = `${e.emoji} ${e.name}`;
                div.onclick = ()=>{ onPick(e.emoji); input.value=''; resultsBox.style.display='none'; resultsBox.innerHTML=''; };
                resultsBox.appendChild(div);
            });
            resultsBox.style.display = hits.length ? 'block' : 'none';
        });
        document.addEventListener('click', (ev)=>{
            if (!resultsBox.contains(ev.target) && ev.target!==input){ resultsBox.style.display='none'; }
        });
    }
    attachEmojiSearch(allowSearch, allowResults, (emoji)=>{ allowSet.add(emoji); renderChips(allowChips, allowSet); applyTopFiltersVisibility(); });
    attachEmojiSearch(denySearch,  denyResults,  (emoji)=>{ denySet.add(emoji);  renderChips(denyChips,  denySet);  applyTopFiltersVisibility(); });

    // ---------------- Regex + Nome (allow/deny) em chips ----------------
    const rxAllowChips = document.getElementById('rxAllowChips');
    const rxDenyChips  = document.getElementById('rxDenyChips');
    const rxAllowInput = document.getElementById('rxAllowInput');
    const rxDenyInput  = document.getElementById('rxDenyInput');

    const nmAllowChips = document.getElementById('nmAllowChips');
    const nmDenyChips  = document.getElementById('nmDenyChips');
    const nmAllowInput = document.getElementById('nmAllowInput');
    const nmDenyInput  = document.getElementById('nmDenyInput');

    const rxAllow = new Set();
    const rxDeny  = new Set();
    const nmAllow = new Set();
    const nmDeny  = new Set();

    function renderChipsGeneric(container, setRef){
      container.innerHTML='';
      Array.from(setRef).forEach(token=>{
        const el = document.createElement('span');
        el.className = 'chip';
        el.textContent = token + ' ';
        const x = document.createElement('span');
        x.className = 'x'; x.textContent = '×';
        x.onclick = ()=>{ setRef.delete(token); renderChipsGeneric(container, setRef); applyTopFiltersVisibility(); };
        el.appendChild(x);
        container.appendChild(el);
      });
    }
    function onEnter(el, cb){ el.addEventListener('keydown', e=>{ if (e.key==='Enter'){ e.preventDefault(); cb(); }}); }

    onEnter(rxAllowInput, ()=>{ const v=(rxAllowInput.value||'').trim(); if(!v) return; rxAllow.add(v); rxAllowInput.value=''; renderChipsGeneric(rxAllowChips,rxAllow); applyTopFiltersVisibility(); });
    onEnter(rxDenyInput,  ()=>{ const v=(rxDenyInput.value||'').trim();  if(!v) return; rxDeny.add(v);  rxDenyInput.value='';  renderChipsGeneric(rxDenyChips,rxDeny);   applyTopFiltersVisibility(); });
    onEnter(nmAllowInput, ()=>{ const v=(nmAllowInput.value||'').trim(); if(!v) return; nmAllow.add(v.toLowerCase()); nmAllowInput.value=''; renderChipsGeneric(nmAllowChips,nmAllow); applyTopFiltersVisibility(); });
    onEnter(nmDenyInput,  ()=>{ const v=(nmDenyInput.value||'').trim();  if(!v) return; nmDeny.add(v.toLowerCase());  nmDenyInput.value='';  renderChipsGeneric(nmDenyChips,nmDeny);   applyTopFiltersVisibility(); });

    function compileRegexSet(setRef){
      const arr=[];
      setRef.forEach(pat=>{
        try{ arr.push(new RegExp(pat,'i')); }catch(e){ /* ignora inválidos */ }
      });
      return arr;
    }

    // Texto agregados para busca (lowercase)
    function aggregateHostText(h){
        let text = (h.name||'')+' '+(h.id||'')+' '+(h.note||'');
        h.ports.forEach(p=>{
            text += ' ' + (p.service||'') + ' ' + (p.note||'');
            (p.events||[]).forEach(ev=>{
                text += ' ' + (ev.name||'') + ' ' + (ev.tag||'') + ' ' + (ev.note||'');
            });
        });
        (h.events||[]).forEach(ev=>{
            text += ' ' + (ev.name||'') + ' ' + (ev.tag||'') + ' ' + (ev.note||'');
        });
        state.links.forEach(l=>{
            if (l.source===h.id || l.target===h.id){
                text += ' ' + (l.label||'') + ' ' + (l.note||'');
            }
        });
        return text.toLowerCase();
    }
    function aggregatePortText(h, p){
        let text = (p.service||'') + ' ' + (p.note||'');
        (p.events||[]).forEach(ev=>{
            text += ' ' + (ev.name||'') + ' ' + (ev.tag||'') + ' ' + (ev.note||'');
        });
        return (aggregateHostText(h) + ' ' + text).toLowerCase();
    }
    function hostNameString(h){ return ((h.name||'')+' '+(h.id||'')).toLowerCase(); }
    function portNameString(p){ return ((String(p.port)||'')+' '+(p.service||'')).toLowerCase(); }

    // ---------------- Lógica de filtro do grafo ----------------
    function visibleByTopFilters(node){
      // Emojis (host-level)
      function pinsPass(h){
        const pins = new Set((h.pinned_emojis||[]));
        if (allowSet.size){
          let hit=false; allowSet.forEach(e=>{ if(pins.has(e)) hit=true; });
          if (!hit) return false;
        }
        if (denySet.size){
          let bad=false; denySet.forEach(e=>{ if(pins.has(e)) bad=true; });
          if (bad) return false;
        }
        return true;
      }

      const rxAllowArr = compileRegexSet(rxAllow);
      const rxDenyArr  = compileRegexSet(rxDeny);
      const hasAllowAny = rxAllow.size || nmAllow.size;

      function matchAnyRegex(arr, text){ for (const r of arr){ if (r.test(text)) return true; } return false; }
      function matchAnyTerm(setRef, text){ let ok=false; setRef.forEach(t=>{ if(t && text.includes(t)) ok=true; }); return ok; }

      if (node.type==='host'){
        const h = findHost(node.id); if (!h) return true;

        if (!pinsPass(h)) return false;

        const hostAgg = aggregateHostText(h);
        const hostName = hostNameString(h);

        // deny em host derruba host e portas
        if (matchAnyRegex(rxDenyArr, hostAgg) || matchAnyTerm(nmDeny, hostName)) return false;

        // allow: host aparece se ele mesmo ou alguma porta casa
        if (hasAllowAny){
          const hostHit = matchAnyRegex(rxAllowArr, hostAgg) || matchAnyTerm(nmAllow, hostName);
          if (hostHit) return true;
          for (const p of h.ports){
            const pAgg = aggregatePortText(h,p);
            const pName = portNameString(p);
            const pHit = matchAnyRegex(rxAllowArr, pAgg) || matchAnyTerm(nmAllow, pName);
            if (pHit) return true; // host visível se QUALQUER porta bateu allow
          }
          return false;
        }
        return true;
      }

      // Porta:
      const h = findHost(node.parent); if (!h) return true;

      // Host precisa ser visível pelos critérios de host (sem considerar esta porta específica)
      const pinsOk = (function(){
        const pins = new Set((h.pinned_emojis||[]));
        if (allowSet.size){
          let hit=false; allowSet.forEach(e=>{ if(pins.has(e)) hit=true; });
          if (!hit) return false;
        }
        if (denySet.size){
          let bad=false; denySet.forEach(e=>{ if(pins.has(e)) bad=true; });
          if (bad) return false;
        }
        return true;
      })();
      if (!pinsOk) return false;

      const hostAgg = aggregateHostText(h);
      const hostName = hostNameString(h);
      if (matchAnyRegex(rxDenyArr, hostAgg) || matchAnyTerm(nmDeny, hostName)) return false;

      const p = findPort(node.parent, node.port) || {};
      const pAgg = aggregatePortText(h,p);
      const pName = portNameString(p);

      // deny em porta derruba só a porta
      if (matchAnyRegex(rxDenyArr, pAgg) || matchAnyTerm(nmDeny, pName)) return false;

      // allow ativo?
      if (hasAllowAny){
        const hostAllowHit = matchAnyRegex(rxAllowArr, hostAgg) || matchAnyTerm(nmAllow, hostName);
        if (hostAllowHit) return true;     // host bateu allow → todas as portas aparecem
        const selfHit = matchAnyRegex(rxAllowArr, pAgg) || matchAnyTerm(nmAllow, pName);
        return !!selfHit;                   // senão, só a porta que bate allow
      }
      return true;
    }

    function applyTopFiltersVisibility(){
      const visibleIds = new Set();
      simNodes.forEach(n=>{ if (visibleByTopFilters(n)) visibleIds.add(n.id); });

      // Nós/labels/pins
      gNodes.selectAll('circle.node').style('display', d=> visibleIds.has(d.id)?null:'none');
      gLabels.selectAll('text.nodeLabel').style('display', d=> visibleIds.has(d.id)?null:'none');
      gPins.selectAll('g.pinHost').style('display', d=> visibleIds.has(d.id)?null:'none');

      // Links (built-in e custom) só se AMBOS lados estiverem visíveis
      gBuiltins.selectAll('line.builtinLink').style('display', d=>{
        const aId = (typeof d.source==='object')?d.source.id:d.source;
        const bId = (typeof d.target==='object')?d.target.id:d.target;
        return (visibleIds.has(aId) && visibleIds.has(bId))?null:'none';
      });
      gCustomLinks.selectAll('path.customLink').style('display', d=> (visibleIds.has(d.source) && visibleIds.has(d.target))?null:'none');
      gCustomLinks.selectAll('text.customLinkLabel').style('display', d=> (visibleIds.has(d.source) && visibleIds.has(d.target))?null:'none');
    }

    // ---------------- Monta dados p/ simulação ----------------
    function rebuildSimData(){
        simNodes = [];
        simLinks = [];
        state.hosts.forEach((h,i)=>{
            simNodes.push({
                id:h.id, type:'host',
                label:h.name, ip:h.id,
                note:h.note, border:h.border, border_color:h.border_color,
                color: colorForHost(h,i), r: 30 + h.ports.length * 2, // leve variação por nº de portas
                emoji: (HOST_EMOJIS[i % HOST_EMOJIS.length] || '🐾') + h.ip.split('.').pop(),
                fx:h.fx, fy:h.fy,
                pinned_emojis: Array.isArray(h.pinned_emojis)?h.pinned_emojis:[]
            });
            h.ports.forEach(p=>{
                const isHttp = /^http/.test(p.service);
                simNodes.push({
                    id: pid(h.id, p.port), type:'port',
                    port: p.port, service:p.service, parent:h.id,
                    note:p.note, border:p.border, border_color:p.border_color,
                    color: isHttp ? lightenColor('#FF9800',0.05) : colorForPort(p), r: 15,
                    fx:p.fx, fy:p.fy
                });
                simLinks.push({ source:h.id, target: pid(h.id, p.port), builtIn:true });
            });
        });
    }

    // ---------------- Criação de links custom (duplo clique inicia; Esc cancela) ----------------
    const draft = { active:false, source:null, temp:null };

    function startDraft(sourceNode){
        draft.active = true;
        draft.source = sourceNode.id;
        draft.temp = gCustomLinks.append('path')
            .attr('class','draftLink')
            .attr('stroke', '#888').attr('stroke-width', 2).attr('fill','none')
            .attr('pointer-events','none');
        svg.on('mousemove.draft', e=>{
            if (!draft.active) return;
            const p = d3.pointer(e, gRoot.node());
            const src = nodeById(draft.source);
            draft.temp.attr('d', `M ${src.x},${src.y} L ${p[0]},${p[1]}`);
        });
        window.addEventListener('keydown', escCancelDraft);
    }
    function escCancelDraft(e){ if (e.key === 'Escape'){ stopDraft(); } }
    function maybeFinishDraft(targetNode){
        if (!draft.active) return false;
        if (targetNode.id === draft.source){ stopDraft(); return true; }
        const link = { id:newId('link'), source:draft.source, target:targetNode.id, style:'straight', color:'#555555', label:'', note:'' };
        state.links.push(link);
        stopDraft(); saveAll(); renderGraph(); selectLink(link);
        return true;
    }
    function stopDraft(){
        draft.active = false; draft.source = null;
        if (draft.temp){ draft.temp.remove(); draft.temp=null; }
        svg.on('mousemove.draft', null);
        window.removeEventListener('keydown', escCancelDraft);
    }

    // ---------------- Render do grafo ----------------
    function renderGraph(){
        rebuildSimData();

        // Links host↔porta (built-in)
        builtInLinksSel = gBuiltins.selectAll('line.builtinLink').data(simLinks, d => d.source+'->'+d.target);
        builtInLinksSel.exit().remove();
        builtInLinksSel = builtInLinksSel.enter().append('line')
            .attr('class', 'builtinLink').attr('stroke', '#aaa')
            .merge(builtInLinksSel);

        // Links custom
        customLinkSel = gCustomLinks.selectAll('path.customLink').data(state.links, d=>d.id);
        customLinkSel.exit().remove();
        customLinkSel = customLinkSel.enter().append('path')
            .attr('class','customLink').attr('fill','none').attr('stroke-width', 2)
            .on('click', (ev,l)=>{ ev.stopPropagation(); selectLink(l); })
            .merge(customLinkSel);

        customLinkLabelSel = gCustomLinks.selectAll('text.customLinkLabel').data(state.links, d=>d.id);
        customLinkLabelSel.exit().remove();
        customLinkLabelSel = customLinkLabelSel.enter().append('text')
            .attr('class','customLinkLabel').attr('font-size','12px').attr('text-anchor','middle').attr('dy', -6)
            .on('click', (ev,l)=>{ ev.stopPropagation(); selectLink(l); })
            .merge(customLinkLabelSel);

        // Nós
        nodeSel = gNodes.selectAll('circle.node').data(simNodes, d => d.id);
        nodeSel.exit().remove();
        nodeSel = nodeSel.enter().append('circle')
            .attr('class','node')
            .attr('r', d=>d.r)
            .attr('fill', d=>d.color)
            .attr('stroke', d=> d.border ? (d.border_color||'#FFD400') : 'none')
            .attr('stroke-width', d=> d.border ? BORDER_WIDTH : 0)
            .on('dblclick', (ev,d)=> { ev.stopPropagation(); startDraft(d); }) // duplo clique inicia criação de link
            .on('click', (ev,d)=> {                                     // clique apenas seleciona
                ev.stopPropagation();
                if (draft.active){ maybeFinishDraft(d); return; }
                selectNode(d);
            })
            .on('contextmenu', (ev,d)=>{
                // botão direito alterna borda e salva
                ev.preventDefault();
                d.border = !d.border;
                d3.select(ev.currentTarget)
                    .attr('stroke', d.border ? (d.border_color||'#FFD400') : 'none')
                    .attr('stroke-width', d.border ? BORDER_WIDTH : 0);
                if (d.type==='host'){ const h=findHost(d.id); if (h) h.border=d.border; }
                else { const p=findPort(d.parent,d.port); if (p) p.border=d.border; }
                saveAll();
            })
            .call(d3.drag().on('start', dragStarted).on('drag', dragged).on('end', dragEnded))
            .on('mousemove', (ev,d)=> showTooltip(ev,d))
            .on('mouseout',  ()=> hideTooltip())
            .merge(nodeSel);

        // Labels dos nós (emoji do host / número da porta)
        labelSel = gLabels.selectAll('text.nodeLabel').data(simNodes, d => 'label-'+d.id);
        labelSel.exit().remove();
        labelSel = labelSel.enter().append('text')
            .attr('class','nodeLabel').attr('dy','.35em').attr('text-anchor','middle')
            .attr('font-size', d=> d.type==='host' ? '24px' : '12px')
            .text(d=> d.type==='port' ? d.port : d.emoji)
            .merge(labelSel);

        // Emojis fixados (no topo direito do host)
        pinSel = gPins.selectAll('g.pinHost').data(simNodes.filter(n=>n.type==='host'), d=>'pin-'+d.id);
        pinSel.exit().remove();
        const pinEnter = pinSel.enter().append('g').attr('class','pinHost');
        pinEnter.merge(pinSel).each(function(h){
            const g = d3.select(this);
            const items = g.selectAll('text.pinEmoji').data(h.pinned_emojis || []);
            items.exit().remove();
            items.enter().append('text').attr('class','pinEmoji').attr('font-size','14px').text(d=>d).merge(items);
        });

        // Simulador físico (forces)
        if (!simulation){
            simulation = d3.forceSimulation(simNodes)
                .force('link', d3.forceLink(simLinks).id(d=>d.id).distance(100))
                .force('collision', d3.forceCollide().radius(d=>d.r+10))
                .on('tick', ticked);
        } else {
            simulation.nodes(simNodes).on('tick', ticked);
            simulation.force('link').links(simLinks);
            simulation.alpha(0.7).restart();
        }

        // Posições iniciais (respeita fx/fy salvos)
        simNodes.forEach(d=>{
            if (typeof d.fx !== 'number' || typeof d.fy !== 'number'){
                const W = topWrap.clientWidth, H = topWrap.clientHeight;
                d.x = Math.random()*(W-2*d.r)+d.r;
                d.y = Math.random()*(H-2*d.r)+d.r;
            } else { d.x = d.fx; d.y = d.fy; }
        });

        function ticked(){
            // Atualiza links built-in
            builtInLinksSel
                .attr('x1', d=> nodeById(d.source).x)
                .attr('y1', d=> nodeById(d.source).y)
                .attr('x2', d=> nodeById(d.target).x)
                .attr('y2', d=> nodeById(d.target).y);

            // Nós + labels
            nodeSel.attr('cx', d=> d.x).attr('cy', d=> d.y);
            labelSel.attr('x', d=> d.x).attr('y', d=> d.y);

            // Posição dos emojis fixados (empilhados no topo direito)
            gPins.selectAll('g.pinHost').each(function(h){
                const g = d3.select(this);
                g.selectAll('text.pinEmoji')
                  .attr('x', h.x + h.r - 8)
                  .attr('y', (d,i)=> (h.y - h.r) + 14 + i*16);
            });

            // Links custom renderizados (reta/curva/tracejada)
            customLinkSel
                .attr('stroke', d=> d.color || '#555')
                .attr('stroke-dasharray', d=> d.style==='dashed' ? '6,6' : null)
                .attr('d', d=> customLinkPath(d));

            // Label do link no ponto médio
            customLinkLabelSel
                .attr('x', d=> midPoint(d).x)
                .attr('y', d=> midPoint(d).y)
                .text(d=> d.label || '');
        }

        applyTopFiltersVisibility();
    }

    function nodeById(idOrNode){ return (typeof idOrNode==='string') ? simNodes.find(n=>n.id===idOrNode) : idOrNode; }

    function dragStarted(ev,d){
        if (!ev.active) simulation.alphaTarget(0.3).restart();
        d.fx = (typeof d.fx==='number')?d.fx:d.x;
        d.fy = (typeof d.fy==='number')?d.fy:d.y;
    }
    function dragged(ev,d){ d.fx = ev.x; d.fy = ev.y; }
    function dragEnded(ev,d){
        if (!ev.active) simulation.alphaTarget(0);
        d.fx = ev.x; d.fy = ev.y;
        if (d.type==='host'){ const h=findHost(d.id); if (h){ h.fx=d.fx; h.fy=d.fy; } }
        else { const p=findPort(d.parent,d.port); if (p){ p.fx=d.fx; p.fy=d.fy; } }
        saveAll();
    }

    function customLinkPath(l){
        const a = nodeById(l.source), b = nodeById(l.target);
        if (!a || !b) return '';
        if (l.style === 'curve'){
            const mx=(a.x+b.x)/2, my=(a.y+b.y)/2;
            const dx=b.x-a.x, dy=b.y-a.y, nx=-dy, ny=dx;
            const cx=mx+nx*0.2, cy=my+ny*0.2; // leve curvatura
            return `M ${a.x},${a.y} Q ${cx},${cy} ${b.x},${b.y}`;
        }
        return `M ${a.x},${a.y} L ${b.x},${b.y}`;
    }
    function midPoint(l){
        const a = nodeById(l.source), b = nodeById(l.target);
        if (!a || !b) return {x:0,y:0};
        if (l.style==='curve'){
            const mx=(a.x+b.x)/2, my=(a.y+b.y)/2;
            const dx=b.x-a.x, dy=b.y-a.y, nx=-dy, ny=dx;
            const cx=mx+nx*0.2, cy=my+ny*0.2;
            return { x:(a.x+2*cx+b.x)/4, y:(a.y+2*cy+b.y)/4 };
        }
        return { x:(a.x+b.x)/2, y:(a.y+b.y)/2 };
    }

    // ---------------- Seleção + painel de detalhes ----------------
    function selectNode(d){
        selected = { kind:'node', data:d };
        renderDetails();
        highlightTimelineForSelection(d);
    }
    function selectLink(l){
        selected = { kind:'link', data:l };
        renderDetails();
        highlightTimelineForSelection(null);
    }

    // Helpers de data/hora
    function formatLocalDate(d){
        const pad=n=>String(n).padStart(2,'0');
        return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());
    }
    function orNowLocalString(){ return formatLocalDate(new Date()); }

    // Parser flexível: aceita datetime-local, só date, só time
    function parseLocalDateTimeFlexible({dtLocal, onlyDate, onlyTime}){
        if (onlyDate || onlyTime){
            let d = new Date();
            if (onlyDate){
                const m = String(onlyDate).match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
                if (m){ d = new Date(+m[1], +m[2]-1, +m[3], 0,0,0); }
            } else {
                // sem date → hoje 00:00
                d = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0,0,0);
            }
            if (onlyTime){
                const t = String(onlyTime).match(/^(\\d{2}):(\\d{2})(?::(\\d{2}))?$/);
                if (t){ d.setHours(+t[1], +t[2], +(t[3]||0), 0); }
            }
            return d;
        }
        if (dtLocal){
            const m = String(dtLocal).match(/^(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2})(?::(\\d{2}))?$/);
            if (m) return new Date(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +(m[6]||0));
        }
        return new Date();
    }

    function toHex(c){
        if (!c) return '#999999';
        if (c[0]==='#') return c;
        const ctx = document.createElement('canvas').getContext('2d');
        ctx.fillStyle = c;
        const s = ctx.fillStyle;
        const m = s.match(/^rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)$/);
        if (!m) return '#999999';
        const r = (+m[1]).toString(16).padStart(2,'0');
        const g = (+m[2]).toString(16).padStart(2,'0');
        const b = (+m[3]).toString(16).padStart(2,'0');
        return '#'+r+g+b;
    }

    function renderPinnedEmojis(container, node){
        container.html('');
        const row = container.append('div');
        (node.pinned_emojis||[]).forEach((em,idx)=>{
            const pill = row.append('span').attr('class','pill').text(em + ' ');
            pill.append('span').attr('class','x').text('×').on('click', ()=>{
                const h = findHost(node.id); if (!h) return;
                h.pinned_emojis.splice(idx,1);
                node.pinned_emojis = h.pinned_emojis.slice();
                saveAll(); renderGraph(); renderPinnedEmojis(container, node);
            });
        });
    }

    function showEmojiSearch(q, container, onPick){
        container.html('');
        q = (q||'').trim().toLowerCase();
        if (!q) return;
        const hits = EMOJI_CATALOG.filter(e=> e.name.includes(q)).slice(0,10);
        hits.forEach(e=>{
            const opt = container.append('div').attr('class','pill').style('cursor','pointer');
            opt.text(`${e.emoji} ${e.name}`);
            opt.on('click', ()=>{ onPick(e.emoji); container.html(''); });
        });
    }

    // ---------------- Eventos ----------------
    let editingEventId = null;

    function getNodeEvents(d){
        if (d.type==='host'){ const h=findHost(d.id); return (h && h.events) ? h.events : []; }
        const p=findPort(d.parent,d.port); return (p && p.events) ? p.events : [];
    }
    function setNodeEvents(d, evts){
        if (d.type==='host'){ const h=findHost(d.id); if (h) h.events = evts; }
        else { const p=findPort(d.parent,d.port); if (p) p.events = evts; }
    }

    function renderEventEditor(info, node){
        const form = info.append('div').attr('id','eventForm');

        form.append('label').text('Nome do evento:');
        const inName = form.append('input').attr('type','text');

        form.append('label').text('Tag:');
        const inTag = form.append('input').attr('type','text');

        form.append('label').text('Emoji (pesquise pelo nome):');
        const inEmoji = form.append('input').attr('type','text').attr('placeholder','ex: rocket, shield...');
        const results = form.append('div');
        inEmoji.on('input', ()=> showEmojiSearch(inEmoji.node().value, results, (emoji)=>{ inEmoji.node().value = emoji; results.html(''); }));

        form.append('label').text('Cor do evento:');
        const inColor = form.append('input').attr('type','color').attr('value','#0077ff');

        // Campo datetime-local (opcional completo)
        form.append('label').text('Data e hora (opcional, completo):');
        const inDt = form.append('input').attr('type','datetime-local').attr('step','1');

        // OU: campos separados
        form.append('label').text('OU informe separadamente:');
        const rowDT = form.append('div').style('display','grid').style('grid-template-columns','1fr 1fr').style('gap','8px');
        const inDate = rowDT.append('input').attr('type','date');
        const inTime = rowDT.append('input').attr('type','time').attr('step','1');

        // Nota do evento
        form.append('label').text('Nota do evento:');
        const inNote = form.append('textarea').attr('placeholder','Detalhes adicionais do evento...');

        const btns = form.append('div').style('margin-top','8px');
        const btnSave = btns.append('button').attr('class','btn').text('Salvar evento');
        const btnCancel = btns.append('button').attr('class','btn').text('Cancelar edição').style('display','none');

        // Se estiver editando, pré-carrega
        if (editingEventId){
            const arr = getNodeEvents(node);
            const idx = arr.findIndex(e=>e.id===editingEventId);
            if (idx>=0){
                const ev = arr[idx];
                inName.node().value  = ev.name || '';
                inTag.node().value   = ev.tag  || '';
                inEmoji.node().value = ev.icon || '';
                inColor.node().value = ev.color|| '#0077ff';
                inDt.node().value    = ev.datetime || '';
                inNote.node().value  = ev.note || '';
                if (ev.datetime){
                    const dd = new Date(ev.datetime.replace(' ', 'T'));
                    inDate.node().value = dd.toISOString().slice(0,10);
                    inTime.node().value = dd.toTimeString().slice(0,8);
                }
                btnCancel.style('display','inline-block');
            } else editingEventId=null;
        }

        btnCancel.on('click', ()=>{ editingEventId=null; renderDetails(); });

        btnSave.on('click', ()=>{
            // Regras de data/hora conforme solicitado
            const rawDtLocal = (inDt.node().value || '').trim();
            const rawDate    = (inDate.node().value || '').trim();
            const rawTime    = (inTime.node().value || '').trim();

            const finalDate = parseLocalDateTimeFlexible({ dtLocal:rawDtLocal, onlyDate: rawDate || null, onlyTime: rawTime || null });
            const finalStr  = formatLocalDate(finalDate);

            const ev = {
                id: editingEventId || newId('evt'),
                name: (inName.node().value || '').trim(),
                tag:  (inTag.node().value || '').trim(),
                icon: (inEmoji.node().value || '').trim() || '📌',
                color: inColor.node().value || '#0077ff',
                datetime: finalStr,
                note: (inNote.node().value || '').trim()
            };
            const arr = getNodeEvents(node).slice();
            const i = arr.findIndex(x=>x.id===ev.id);
            if (i>=0) arr[i]=ev; else arr.push(ev);
            setNodeEvents(node, arr);
            editingEventId=null;
            saveAll();
            buildTimeline(); redrawTimelineAxis();
            highlightTimelineForSelection(node);
            renderDetails();
        });
    }

    function renderEventList(info, node){
        const arr = getNodeEvents(node).slice().sort((a,b)=> (a.datetime||'').localeCompare(b.datetime||''));
        if (!arr.length){ info.append('p').style('opacity','.7').text('Sem eventos ainda.'); return; }

        arr.forEach(ev=>{
            const row = info.append('div')
                .style('display','flex').style('align-items','center').style('gap','8px')
                .style('margin','4px 0').style('padding','6px 8px')
                .style('border','1px solid #ddd').style('border-radius','8px').style('background','#fff');
            row.append('span').text(ev.icon||'📝').style('font-size','18px');
            row.append('span').text(ev.name||'(sem nome)');
            row.append('small').text(ev.tag?('#'+ev.tag):'').style('opacity','.7');

            // Click na hora abre mini editor (date+time)
            const timeBtn = row.append('span').text(' ' + (ev.datetime||'(definir)')).style('color','#0077ff').style('cursor','pointer');
            timeBtn.on('click', ()=>{
                const mini = row.append('span').style('margin-left','8px').style('display','inline-flex').style('gap','6px').style('align-items','center');
                const dIn = mini.append('input').attr('type','date');
                const tIn = mini.append('input').attr('type','time').attr('step','1');
                const ok  = mini.append('button').attr('class','btn').text('OK');

                if (ev.datetime){
                    const dd = new Date(ev.datetime.replace(' ', 'T'));
                    dIn.node().value = dd.toISOString().slice(0,10);
                    tIn.node().value = dd.toTimeString().slice(0,8);
                }

                ok.on('click', ()=>{
                    const finalD = parseLocalDateTimeFlexible({ dtLocal:null, onlyDate: dIn.node().value||null, onlyTime: tIn.node().value||null });
                    ev.datetime = formatLocalDate(finalD);
                    const arr2 = getNodeEvents(node).slice();
                    const idx = arr2.findIndex(e=>e.id===ev.id); if (idx>=0) arr2[idx]=ev;
                    setNodeEvents(node, arr2);
                    saveAll(); buildTimeline(); redrawTimelineAxis(); highlightTimelineForSelection(node); renderDetails();
                });
            });

            if (ev.note){
                row.append('small').style('opacity','.7').text(' — '+(ev.note.slice(0,60))+(ev.note.length>60?'...':''));
            }

            row.append('button').attr('class','btn').text('Editar').on('click', ()=>{ editingEventId=ev.id; renderDetails(); });
            row.append('button').attr('class','btn').text('Remover').on('click', ()=>{
                const arr2 = getNodeEvents(node).filter(e=>e.id!==ev.id);
                setNodeEvents(node, arr2);
                saveAll(); buildTimeline(); redrawTimelineAxis(); highlightTimelineForSelection(node); renderDetails();
            });
        });
    }

    // ---------------- Tooltip ----------------
    function showTooltip(ev, node){
        let html='';
        if (node.type==='host'){
            html += '<b>Host:</b> ' + (node.label||node.ip) + '<br/>';
            const h = findHost(node.id);
            const hostEv = (h && h.events)||[];
            if (hostEv.length){
                html += '<div><b>Eventos do host:</b><ul style="margin:4px 0 0 16px">';
                hostEv.forEach(e=> html += `<li>${e.icon||''} ${e.name||''} <small>(${e.tag||''})</small></li>`);
                html += '</ul></div>';
            }
            const portEv = [];
            if (h){ h.ports.forEach(p=> (p.events||[]).forEach(e=> portEv.push({port:p.port, ...e}))); }
            if (portEv.length){
                html += '<div style="margin-top:4px"><b>Eventos de portas:</b><ul style="margin:4px 0 0 16px">';
                portEv.slice(0,6).forEach(e=> html += `<li>[${e.port}] ${e.icon||''} ${e.name||''}</li>`);
                if (portEv.length>6) html += '<li>...</li>';
                html += '</ul></div>';
            }
        } else {
            html += `<b>Porta:</b> ${node.port} <small>(${node.service||''})</small><br/>`;
            const p = findPort(node.parent,node.port);
            const evs = (p && p.events)||[];
            if (evs.length){
                html += '<div><b>Eventos:</b><ul style="margin:4px 0 0 16px">';
                evs.forEach(e=> html += `<li>${e.icon||''} ${e.name||''} <small>(${e.tag||''})</small></li>`);
                html += '</ul></div>';
            }
        }
        tooltip.style('display','block')
               .style('left', (ev.clientX+12)+'px')
               .style('top',  (ev.clientY+12)+'px')
               .html(html);
    }
    function hideTooltip(){ tooltip.style('display','none'); }

    // ---------------- Timeline ----------------
    let tlTransform = d3.zoomIdentity;
    let tlX = null;
    const AXIS_BOTTOM_PAD = 24;

    // Zoom da timeline (persistente)
    const tlZoom = d3.zoom()
        .scaleExtent([0.5, 20])
        .on('zoom', ev=>{
            tlTransform = ev.transform;
            tlG.attr('transform', tlTransform);
            tlStemsG.attr('transform', tlTransform); // stems seguem o zoom
            redrawTimelineAxis();
        })
        .on('end', ()=>{
            state.timeline_zoom = {k:tlTransform.k, x:tlTransform.x, y:tlTransform.y};
            saveAll();
        });
    tlSVG.call(tlZoom);

    // Filtros da timeline (combos)
    function populateFilters(){
        const emSel = document.getElementById('fltEmoji');
        if (emSel.childElementCount<=1){
            EMOJI_CATALOG.forEach(e=>{
                const opt = document.createElement('option');
                opt.value = e.emoji; opt.textContent = `${e.emoji} ${e.name}`;
                emSel.appendChild(opt);
            });
        }
        const hostSel = document.getElementById('fltHost');
        hostSel.innerHTML = '<option value="">Todos os hosts</option>';
        state.hosts.forEach(h=>{
            const opt = document.createElement('option');
            opt.value = h.id;
            opt.textContent = `${h.name||h.id} (${h.id})`;
            hostSel.appendChild(opt);
        });
    }

    function parseLocalDateTime(s){
        if (!s) return new Date();
        const m = s.match(/^(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2})(?::(\\d{2}))?$/);
        if (m){ return new Date(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +(m[6]||0)); }
        return new Date(s);
    }

    function allEvents(){
        const out=[];
        state.hosts.forEach(h=>{
            (h.events||[]).forEach(e=> out.push({ type:'host', hostId:h.id, hostName:h.name||h.id, ev:e }));
            h.ports.forEach(p=> (p.events||[]).forEach(e=> out.push({ type:'port', hostId:h.id, port:p.port, hostName:h.name||h.id, ev:e })));
        });
        return out;
    }

    function filteredEvents(){
        const txt = document.getElementById('fltText').value;
        const r = (txt||'').trim() ? new RegExp(txt, 'i') : null;
        const emoji = document.getElementById('fltEmoji').value;
        const hostId = document.getElementById('fltHost').value;
        const from = document.getElementById('fltFrom').value;
        const to   = document.getElementById('fltTo').value;

        let rows = allEvents();

        if (r){
            rows = rows.filter(x=>{
                const name=(x.ev.name||''), tag=(x.ev.tag||''), host=(x.hostName||''), note=(x.ev.note||'');
                return r.test(name) || r.test(tag) || r.test(host) || r.test(note);
            });
        }
        if (emoji) rows = rows.filter(x=> (x.ev.icon||'')===emoji);
        if (hostId) rows = rows.filter(x=> x.hostId===hostId);

        const tFrom = from ? +parseLocalDateTime(from+'T00:00:00') : null;
        const tTo   = to   ? +parseLocalDateTime(to  +'T23:59:59') : null;
        rows = rows.filter(x=>{
            const t = x.ev.datetime ? +parseLocalDateTime(x.ev.datetime) : null;
            if (tFrom && (t == null || t < tFrom)) return false;
            if (tTo   && (t == null || t > tTo))   return false;
            return true;
        });

        rows.sort((a,b)=> (a.ev.datetime||'').localeCompare(b.ev.datetime||''));
        return rows;
    }

    // Evita sobreposição na timeline atribuindo "lanes" (linhas) com distâncias mínimas
    function assignLanes(events, xScale, minDX=60, laneGap=48){
        const lanes = [];
        const placed = events.map(e=>{
            const x = xScale(parseLocalDateTime(e.ev.datetime||orNowLocalString()));
            let lane = 0;
            while (lane<lanes.length && (x - lanes[lane]) < minDX){ lane++; }
            if (lane===lanes.length) lanes.push(-Infinity);
            lanes[lane] = x;
            return { e, x, lane, yOffset: lane*laneGap };
        });
        return { placed, laneCount: lanes.length };
    }

    function buildTimeline(){
        tlG.selectAll('*').remove();
        tlAxisG.selectAll('*').remove();
        tlStemsG.selectAll('*').remove();

        const rows = filteredEvents();
        const W = +tlSVG.node().clientWidth, H = +tlSVG.node().clientHeight;

        if (!rows.length){
            tlX = d3.scaleTime().domain([new Date(), new Date()]).range([40, W-20]);
            const axis = d3.axisBottom(tlX);
            tlAxisG.attr('transform', `translate(0, ${H-AXIS_BOTTOM_PAD})`).call(axis);
            return;
        }

        const times = rows.map(r=> parseLocalDateTime(r.ev.datetime||orNowLocalString()));
        const tMin = d3.min(times), tMax = d3.max(times);
        const pad = (tMax - tMin) * 0.08 + 60*1000; // margem lateral + 1min
        tlX = d3.scaleTime().domain([new Date(+tMin - pad), new Date(+tMax + pad)]).range([40, W-20]);

        drawTimelineAxis(); // primeiro eixo

        const baseY = H - AXIS_BOTTOM_PAD - 2;
        const { placed } = assignLanes(rows, tlX, 60, 48);

        // Stems no fundo, conectadas ao centro dos eventos
        tlStemsG.selectAll('line.evtStem').data(placed, d=>d.e.ev.id||newId('anon'))
          .join(
            enter => enter.append('line')
              .attr('class','evtStem')
              .attr('x1', d=>d.x).attr('x2', d=>d.x)
              .attr('y1', d=> baseY - (d.yOffset+12))
              .attr('y2', baseY)
              .attr('pointer-events','none'),
            update => update
              .attr('x1', d=>d.x).attr('x2', d=>d.x)
              .attr('y1', d=> baseY - (d.yOffset+12))
              .attr('y2', baseY)
          );

        // Nós da timeline (círculo + emoji + label)
        const gEvt = tlG.selectAll('g.evtNode').data(placed, d=>d.e.ev.id||newId('anon'))
            .enter().append('g')
            .attr('class','evtNode')
            .each(function(d){ d.anchor = { x:d.x, y: baseY - (d.yOffset+12) }; })
            .attr('transform', d=> `translate(${d.anchor.x}, ${d.anchor.y})`)
            .call(d3.drag()
              .on('drag', function(ev,d){
                // Arrasto vertical (x fixo); stem acompanha
                const y = ev.y;
                d3.select(this).attr('transform', `translate(${d.anchor.x}, ${y})`);
                tlStemsG.selectAll('line.evtStem')
                  .filter(s=> (s.e.ev.id === d.e.ev.id))
                  .attr('y1', y);
              })
              .on('end',  function(ev,d){
                // Volta à âncora
                d3.select(this).transition().duration(250)
                  .attr('transform', `translate(${d.anchor.x}, ${d.anchor.y})`);
                tlStemsG.selectAll('line.evtStem')
                  .filter(s=> (s.e.ev.id === d.e.ev.id))
                  .transition().duration(250)
                  .attr('y1', d.anchor.y);
              })
            )
            .on('click', (ev,d)=>{
                if (d.e.type==='host'){
                    const H = findHost(d.e.hostId);
                    selectNode({ type:'host', id:d.e.hostId, label:H?.name, ip:d.e.hostId,
                                 note:H?.note, color: H?.color, border: H?.border, border_color: H?.border_color });
                    flashNodeHalo(d.e.hostId);
                } else {
                    const P = findPort(d.e.hostId, d.e.port);
                    selectNode({ type:'port', parent:d.e.hostId, port:d.e.port, service: P?.service,
                                 note:P?.note, color:P?.color, border:P?.border, border_color:P?.border_color });
                    flashNodeHalo(pid(d.e.hostId, d.e.port));
                }
            });

        gEvt.append('circle').attr('r', 11).attr('fill', d=> d.e.ev.color || '#2196F3').attr('stroke','#333').attr('stroke-width',1);
        gEvt.append('text').attr('y', 4).text(d=> d.e.ev.icon || '📌');

        // Label: host:porta (host = último octeto)
        gEvt.append('text').attr('class','evtLabel').attr('y', 28)
            .text(d=> {
                const oct = d.e.hostId.split('.').pop();
                return d.e.type==='host' ? oct : `${oct}:${d.e.port}`;
            });
    }

    // Ticks adaptativos conforme span e zoom
    function drawTimelineAxis(){
        const W = +tlSVG.node().clientWidth, H = +tlSVG.node().clientHeight;
        const xNew = tlTransform.rescaleX(tlX);
        const [d0,d1] = xNew.domain();
        const ms = +d1 - +d0;
        const days = ms / 86400000;
        const hours = ms / 3600000;
        const months = (d1.getFullYear()-d0.getFullYear())*12 + (d1.getMonth()-d0.getMonth());
        const approxTicks = Math.max(2, Math.floor(W / 90));  // ~90px por tick

        let interval;
        if (days > 180){
            const step = Math.max(1, Math.round(Math.max(months, days/30) / approxTicks));
            interval = d3.timeMonth.every(step);
        } else if (days > 3){
            const step = Math.max(1, Math.round(days / approxTicks));
            interval = d3.timeDay.every(step);
        } else {
            // Horas por padrão; se zoom forte, cai para minutos (até 30)
            if (hours < 6 && (W / Math.max(hours,0.001)) > 150){
                const mins = Math.max(1, Math.round((hours*60) / approxTicks));
                interval = d3.timeMinute.every(Math.min(mins, 30));
            } else {
                const step = Math.max(1, Math.round(hours / approxTicks));
                interval = d3.timeHour.every(step);
            }
        }

        const axis = d3.axisBottom(xNew).ticks(interval);
        tlAxisG.attr('transform', `translate(0, ${H-AXIS_BOTTOM_PAD})`).call(axis);
    }
    function redrawTimelineAxis(){ if (!tlX) return; drawTimelineAxis(); }

    // Destaca eventos relacionados ao nó selecionado
    function highlightTimelineForSelection(sel){
        tlG.selectAll('g.evtNode').classed('evtSelected', false);
        if (!sel) return;
        const rows = allEvents();
        const ids = new Set();
        rows.forEach(r=>{
            if (sel.type==='host' && r.hostId===sel.id) ids.add(r.ev.id);
            if (sel.type==='port' && r.type==='port' && r.hostId===sel.parent && r.port===sel.port) ids.add(r.ev.id);
        });
        tlG.selectAll('g.evtNode').filter(function(d){ return ids.has(d.e.ev.id); }).classed('evtSelected', true);
    }

    // Halo no grafo para achar o nó a partir da timeline
    function flashNodeHalo(nodeId){
        const n = simNodes.find(n=> n.id===nodeId);
        if (!n) return;
        gHalo.append('circle').attr('class','halo').attr('cx', n.x).attr('cy', n.y).attr('r', 0)
            .on('animationend', function(){ d3.select(this).remove(); });
    }

    // ---------------- Handlers filtros timeline ----------------
    document.getElementById('fltText').addEventListener('input', ()=>{ buildTimeline(); redrawTimelineAxis(); highlightTimelineForSelection(selected ? selected.data : null); });
    document.getElementById('fltEmoji').addEventListener('change', ()=>{ buildTimeline(); redrawTimelineAxis(); highlightTimelineForSelection(selected ? selected.data : null); });
    document.getElementById('fltHost').addEventListener('change', ()=>{ buildTimeline(); redrawTimelineAxis(); highlightTimelineForSelection(selected ? selected.data : null); });
    document.getElementById('fltFrom').addEventListener('change', ()=>{ buildTimeline(); redrawTimelineAxis(); highlightTimelineForSelection(selected ? selected.data : null); });
    document.getElementById('fltTo').addEventListener('change',   ()=>{ buildTimeline(); redrawTimelineAxis(); highlightTimelineForSelection(selected ? selected.data : null); });
    document.getElementById('fltClear').addEventListener('click', ()=>{
        document.getElementById('fltText').value='';
        document.getElementById('fltEmoji').value='';
        document.getElementById('fltHost').value='';
        document.getElementById('fltFrom').value='';
        document.getElementById('fltTo').value='';
        buildTimeline(); redrawTimelineAxis(); highlightTimelineForSelection(selected ? selected.data : null);
    });

    // ---------------- Marca “KKNETMAP by kktools” muda a cada 5 minutos ----------------
    const header = document.getElementById('brandHeader');
    const fonts = ['Impact, Charcoal, sans-serif','Trebuchet MS, sans-serif','Courier New, monospace','Georgia, serif','Verdana, sans-serif'];
    function randColor(){ const h = Math.floor(Math.random()*360); return `hsl(${h}deg,75%,45%)`; }
    function refreshBrand(){ header.style.color = randColor(); header.style.fontFamily = fonts[Math.floor(Math.random()*fonts.length)]; }
    refreshBrand(); setInterval(refreshBrand, 5*60*1000);

    // ---------------- Painel de instruções (Markdown) ----------------
    const noteToggle = document.getElementById('noteToggle');
    const notePanel  = document.getElementById('notePanel');
    const noteInput  = document.getElementById('noteInput');
    const notePrev   = document.getElementById('notePreview');
    const noteSave   = document.getElementById('noteSave');
    const noteClose  = document.getElementById('noteClose');

    function renderMarkdownPreview(){
        try{ notePrev.innerHTML = marked.parse(noteInput.value || ''); }
        catch(e){ notePrev.textContent = noteInput.value || ''; }
    }
    noteToggle.addEventListener('click', ()=>{ notePanel.style.display = (notePanel.style.display==='none'||!notePanel.style.display)?'block':'none'; });
    noteClose.addEventListener('click', ()=>{ notePanel.style.display='none'; });
    noteInput.addEventListener('input', ()=>{ renderMarkdownPreview(); });
    noteSave.addEventListener('click', ()=>{ state.instructions = noteInput.value || ''; saveAll(); });
    renderMarkdownPreview();

    // ---------------- Resize da timeline (handle superior) ----------------
    const resizer = document.getElementById('timelineResizer');
    const rootStyle = document.documentElement.style;
    const HKEY = 'kknetmap_timeline_h';
    const savedH = localStorage.getItem(HKEY);
    if (savedH){ rootStyle.setProperty('--timeline-h', savedH+'px'); }

    let rDrag=false, rStartY=0, rStartH=0;
    resizer.addEventListener('mousedown', e=>{
        rDrag=true; rStartY=e.clientY;
        const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--timeline-h')) || 230;
        rStartH = cur;
        document.body.style.userSelect='none';
    });
    window.addEventListener('mousemove', e=>{
        if (!rDrag) return;
        const dy = -(e.clientY - rStartY); // arrastar pra cima aumenta timeline
        const newH = Math.max(150, Math.min(window.innerHeight*0.75, rStartH + dy));
        rootStyle.setProperty('--timeline-h', newH+'px');
        // Reajusta canvas de cima imediatamente
        resizeSVG();
        // Eixo precisa redesenhar com novo tamanho
        redrawTimelineAxis();
        localStorage.setItem(HKEY, String(newH));
    });
    window.addEventListener('mouseup', ()=>{ if (rDrag){ rDrag=false; document.body.style.userSelect=''; } });

    // ---------------- Minimizar/expandir painel de filtros do grafo ----------------
    const topFiltersEl = document.getElementById('topFilters');
    const topFiltersToggle = document.getElementById('topFiltersToggle');
    const TOPFILT_KEY = 'kknetmap_topFiltersCollapsed';
    function applyTopFiltersCollapsed(collapsed){
      if (collapsed){ topFiltersEl.classList.add('collapsed'); topFiltersToggle.textContent='+'; topFiltersToggle.title='Expandir'; }
      else { topFiltersEl.classList.remove('collapsed'); topFiltersToggle.textContent='–'; topFiltersToggle.title='Minimizar'; }
    }
    applyTopFiltersCollapsed(localStorage.getItem(TOPFILT_KEY) === '1');
    topFiltersToggle.addEventListener('click', ()=>{
      const willCollapse = !topFiltersEl.classList.contains('collapsed');
      applyTopFiltersCollapsed(willCollapse);
      localStorage.setItem(TOPFILT_KEY, willCollapse ? '1' : '0');
    });
    topFiltersEl.querySelector('.header h3').addEventListener('dblclick', ()=> topFiltersToggle.click());

    // ---------------- Bootstrap ----------------
    function applySavedMainZoom(){ applySavedZoom(state.zoom || {k:1,x:0,y:0}); }
    function applySavedTimelineZoom(){
        tlTransform = d3.zoomIdentity.translate(state.timeline_zoom?.x||0, state.timeline_zoom?.y||0).scale(state.timeline_zoom?.k||1);
        tlSVG.call(tlZoom.transform, tlTransform);
    }

    async function init(){
        resizeSVG();
        const res = await fetch('/data'); const json = await res.json();
        state.hosts = json.hosts || [];
        state.links = json.links || [];
        state.zoom  = json.zoom || {k:1,x:0,y:0};
        state.timeline_zoom = json.timeline_zoom || {k:1,x:0,y:0};
        state.instructions = json.instructions || "";

        // Preenche Markdown salvo (se houver)
        noteInput.value = state.instructions || '';
        renderMarkdownPreview();

        populateFilters();
        applySavedMainZoom();
        applySavedTimelineZoom();

        buildTimeline();
        redrawTimelineAxis();
        renderGraph();

        // Limpa seleção ao clicar em vazio (exceto se desenhando link)
        svg.on('click', ()=> { if (draft.active) return; selected=null; renderDetails(); highlightTimelineForSelection(null); });
    }

    // Render do painel de detalhes (host/porta/link) — incluído no init
    function renderDetails(){
        const info = d3.select('#info').html('');
        if (!selected){ info.text('Clique em um host, porta, ou link para editar.'); return; }

        if (selected.kind === 'node'){
            const d = selected.data;
            if (d.type==='host'){
                info.append('h3').text(`Host: ${d.label || d.ip}`);
                info.append('p').text(`IP: ${d.ip}`);
            } else {
                const h = findHost(d.parent);
                info.append('h3').text(`Porta: ${d.port}`);
                if (/^http/.test(d.service)){
                    const url = `${h.ip}:${d.port}`;
                    info.append('p').html(`<a href="http://${url}" target="_blank">Abrir em http://${url}</a>`);
                } else {
                    info.append('p').text(`Serviço: ${d.service || ''}`);
                }
            }

            // Nota
            info.append('label').text('Nota:');
            const ta = info.append('textarea').text(d.note || '');
            ta.on('blur', ()=>{
                if (d.type==='host'){ const h=findHost(d.id); if (h){ h.note = ta.node().value; d.note=h.note; } }
                else { const p=findPort(d.parent,d.port); if (p){ p.note = ta.node().value; d.note=p.note; } }
                saveAll();
            });

            // Cor do elemento
            info.append('label').text('Cor do elemento:');
            const col = info.append('input').attr('type','color').attr('value', toHex(d.color||'#9aa'));
            col.on('input', ()=>{
                const v = col.node().value; d.color=v;
                gNodes.selectAll('circle.node').filter(n=>n.id===d.id)
                     .attr('fill', lightenColor(v, d.type==='host'?0.12:0.10));
            });
            col.on('change', ()=>{
                if (d.type==='host'){ const h=findHost(d.id); if (h) h.color=d.color; }
                else { const p=findPort(d.parent,d.port); if (p) p.color=d.color; }
                saveAll();
            });

            // Cor da borda
            info.append('label').text('Cor da borda:');
            const bcol = info.append('input').attr('type','color').attr('value', toHex(d.border_color || '#FFD400'));
            bcol.on('input', ()=>{
                const v = bcol.node().value; d.border_color=v;
                gNodes.selectAll('circle.node').filter(n=>n.id===d.id)
                     .attr('stroke', d.border ? v : 'none')
                     .attr('stroke-width', d.border ? BORDER_WIDTH : 0);
            });
            bcol.on('change', ()=>{
                if (d.type==='host'){ const h=findHost(d.id); if (h) h.border_color=d.border_color; }
                else { const p=findPort(d.parent,d.port); if (p) p.border_color=d.border_color; }
                saveAll();
            });

            // Emojis fixados (hosts)
            if (d.type==='host'){
                info.append('h3').text('Emojis Fixados (tags):');
                const pinWrap = info.append('div');
                renderPinnedEmojis(pinWrap, d);

                info.append('label').text('Adicionar emoji fixado:');
                const input = info.append('input').attr('placeholder','Pesquisar por nome (ex: rocket, shield...)');
                const results = info.append('div');
                input.on('input', ()=> showEmojiSearch(input.node().value, results, (emoji)=>{
                    const h = findHost(d.id); if (!h) return;
                    h.pinned_emojis = h.pinned_emojis || [];
                    h.pinned_emojis.push(emoji);
                    d.pinned_emojis = h.pinned_emojis.slice();
                    saveAll(); renderGraph(); renderPinnedEmojis(pinWrap, d);
                }));
            }

            // Eventos do objeto
            info.append('h3').text('Eventos do objeto');
            renderEventEditor(info, d);
            renderEventList(info, d);
        }

        if (selected.kind === 'link'){
            const l = selected.data;
            info.append('h3').text('Link personalizado');
            info.append('p').text(`${l.source} ➜ ${l.target}`);

            info.append('label').text('Nome do link (aparece no centro):');
            const inLabel = info.append('input').attr('type','text').attr('value', l.label || '');
            inLabel.on('input', ()=>{ l.label = inLabel.node().value; saveAll(); renderGraph(); });

            info.append('label').text('Notas:');
            const inNote = info.append('textarea').text(l.note || '');
            inNote.on('blur', ()=>{ l.note = inNote.node().value; saveAll(); });

            info.append('label').text('Estilo do link:');
            const sel = info.append('select');
            ['straight','curve','dashed'].forEach(s=> sel.append('option').attr('value',s).property('selected', l.style===s).text(s));
            sel.on('change', ()=>{ l.style = sel.node().value; saveAll(); renderGraph(); });

            info.append('label').text('Cor:');
            const inColor = info.append('input').attr('type','color').attr('value', toHex(l.color || '#555555'));
            inColor.on('input', ()=>{ l.color = inColor.node().value; saveAll(); renderGraph(); });

            info.append('div').style('margin-top','8px').append('button').attr('class','btn').text('Remover link')
                .on('click', ()=>{
                    state.links = state.links.filter(x=>x.id!==l.id);
                    saveAll(); renderGraph(); selected=null; renderDetails();
                });
        }
    }

    // ---------------- Inicialização ----------------
    init();
    </script>
</body>
</html>
""",
    default_port_colors=DEFAULT_PORT_COLORS,
    host_emojis=HOST_EMOJIS,
    emoji_catalog=EMOJI_CATALOG)
    return html


# =============================================================================
# Main
# =============================================================================
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000, help='Porta para o servidor Flask')
    args = parser.parse_args()
    app.run(debug=True, threaded=True, port=args.port)
