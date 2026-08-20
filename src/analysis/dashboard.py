"""Dashboard visualization — generates a standalone HTML dashboard.

Reads analysis output files and renders an interactive dashboard using Chart.js.
"""
from __future__ import annotations

import html
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from web3 import Web3

from ..data.artifacts import (
    ArtifactError,
    combine_event_tables,
    inflate_volume_timeline,
    read_holdings_document,
    read_table,
)
from ..models import VerifiedPool
from .metrics import calculate_withdrawal_severity

_HTML_TEMPLATE: str | None = None
_JS_TEMPLATE: str | None = None

# Pool series need to remain distinguishable on the dark dashboard even when a
# token has substantially more than the six pools covered by the old palette.
_CHART_SERIES_COLORS = [
    "#f59e0b", "#22c55e", "#f43f5e", "#8b5cf6", "#14b8a6",
    "#60a5fa", "#f97316", "#a3e635", "#ec4899", "#06b6d4",
    "#fb7185", "#c084fc", "#2dd4bf", "#eab308", "#84cc16",
    "#38bdf8", "#e879f9", "#a78bfa", "#34d399", "#fbbf24",
]
_CHART_LINE_DASHES = [[], [9, 4], [3, 3], [12, 4, 3, 4]]


def _load_templates():
    global _HTML_TEMPLATE, _JS_TEMPLATE
    if _HTML_TEMPLATE is not None:
        return

    _JS_TEMPLATE = """const topH = {top_h_json};
const poolReserveRows = {pool_reserve_json};
const addressLabels = {address_labels_json};
const tvlD = {tvl_json};
const portfolioData = {portfolio_json};
const tokenSymbol = "{symbol}";
const chainId = {chain_id};
const tvlPointDetails = {tvl_detail_json};
const chartSeriesColors = {chart_colors_json};
const topChartHolders = topH.slice(0, 10);

function fmtNum(v, digits){
  if (v === null || v === undefined || isNaN(v)) return '<span class="muted">-</span>';
  return Number(v).toLocaleString(undefined,{maximumFractionDigits:digits});
}
function fmtUsd(v, digits){
  if (v === null || v === undefined || isNaN(v)) return '<span class="muted">-</span>';
  return '$' + Number(v).toLocaleString(undefined,{maximumFractionDigits:digits});
}
function escTxt(s){
  return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function shortIdentifier(value){
  var text = String(value == null ? '' : value);
  return text.length > 14 ? text.slice(0, 8) + '...' + text.slice(-4) : (text || '-');
}
function displayLabelFor(value){
  var full = String(value == null ? '' : value);
  if (!full) return '-';
  var mapped = addressLabels && addressLabels[full.toLowerCase()];
  if (mapped) return String(mapped);
  return shortIdentifier(full);
}
function isEthereumAddress(value){
  return /^0x[0-9a-fA-F]{40}$/.test(String(value || ''));
}
function identifierHtml(value){
  var full = String(value == null ? '' : value);
  if (!full) return '<span class="muted">-</span>';
  var safe = escTxt(full);
  var result = '<span class="identifier-wrap">'
    + '<button type="button" class="identifier-copy addr" data-identifier="' + safe + '"'
    + ' aria-label="Copy full identifier ' + safe + '"'
    + ' onmouseenter="showIdentifierTooltip(this)" onmouseleave="hideIdentifierTooltip()"'
    + ' onfocus="showIdentifierTooltip(this)" onblur="hideIdentifierTooltip()"'
    + ' onclick="copyIdentifier(event,this)">' + escTxt(displayLabelFor(full)) + '</button>';
  if (chainId === 1 && isEthereumAddress(full)) {
    result += '<a class="identifier-link" href="https://etherscan.io/address/' + safe + '"'
      + ' target="_blank" rel="noopener noreferrer" title="Open in Etherscan"'
      + ' aria-label="Open ' + safe + ' in Etherscan" onclick="event.stopPropagation()">&#8599;</a>';
  }
  return result + '</span>';
}
function showIdentifierTooltip(button){
  var tooltip = document.getElementById('identifier-tooltip');
  if (!tooltip || !button) return;
  tooltip.textContent = button.getAttribute('data-identifier') || '';
  tooltip.hidden = false;
  var rect = button.getBoundingClientRect();
  var left = Math.max(12, Math.min(rect.left, window.innerWidth - tooltip.offsetWidth - 12));
  var top = rect.top - tooltip.offsetHeight - 8;
  if (top < 8) top = rect.bottom + 8;
  tooltip.style.left = left + 'px';
  tooltip.style.top = top + 'px';
}
function hideIdentifierTooltip(){
  var tooltip = document.getElementById('identifier-tooltip');
  if (tooltip) tooltip.hidden = true;
}
function fallbackCopyIdentifier(value){
  var textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  var copied = document.execCommand('copy');
  document.body.removeChild(textarea);
  return copied;
}
var copyToastTimer = null;
function showCopyToast(message, failed){
  var toast = document.getElementById('copy-toast');
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle('copy-toast-error', !!failed);
  toast.classList.add('copy-toast-visible');
  if (copyToastTimer) window.clearTimeout(copyToastTimer);
  copyToastTimer = window.setTimeout(function(){
    toast.classList.remove('copy-toast-visible');
  }, 1800);
}
async function copyIdentifierValue(event, value){
  if (event && typeof event.preventDefault === 'function') {
    event.preventDefault();
  }
  if (event && typeof event.stopPropagation === 'function') {
    event.stopPropagation();
  }
  value = String(value || '');
  if (!value) return;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
    } else if (!fallbackCopyIdentifier(value)) {
      throw new Error('copy unavailable');
    }
    showCopyToast('Copied: ' + shortIdentifier(value), false);
  } catch (err) {
    showCopyToast('Copy failed — full value is shown on hover', true);
  }
}
async function copyIdentifier(event, button){
  var value = button ? (button.getAttribute('data-identifier') || '') : '';
  return copyIdentifierValue(event, value);
}
function renderTvlDetails(index){
  var panel = document.getElementById('tvl-details');
  var detail = (tvlPointDetails || [])[index];
  if (!panel || !detail) return;
  var blockLabel = (typeof detail.block === 'number')
    ? ('Block ' + fmtNum(detail.block, 0))
    : escTxt(detail.block);
  document.getElementById('tvl-detail-title').innerHTML =
    blockLabel + (detail.time_label ? (' &middot; ' + escTxt(detail.time_label)) : '');
  var meta = '<div class="detail-summary">Total TVL <strong>' + fmtNum(detail.total_tvl, 4) + ' ' + escTxt(tokenSymbol) + '</strong></div>';
  if (detail.volume_bucket_label) {
    meta += '<span style="opacity:.85">Volume bucket: ' + escTxt(detail.volume_bucket_label) + '</span>';
  }
  document.getElementById('tvl-detail-meta').innerHTML = meta;
  var rows = '';
  for (var i = 0; i < detail.pools.length; i++) {
    var p = detail.pools[i];
    var share = (p.share_pct == null) ? '-' : Number(p.share_pct).toFixed(2) + '%';
    rows += '<tr>'
      + '<td>' + identifierHtml(p.address) + '</td>'
      + '<td>' + escTxt(p.protocol) + '</td>'
      + '<td>' + fmtNum(p.tvl, 4) + '</td>'
      + '<td>' + share + '</td>'
      + '<td>' + fmtUsd(p.price_usd, 4) + '</td>'
      + '<td>' + fmtNum(p.volume_token, 4) + '</td>'
      + '<td>' + fmtUsd(p.volume_usd, 2) + '</td>'
      + '</tr>';
  }
  document.getElementById('tvl-detail-body').innerHTML = rows;
  panel.style.display = '';
  panel.scrollIntoView({behavior:'smooth', block:'nearest'});
}
function closeTvlDetails(){
  var panel = document.getElementById('tvl-details');
  if (panel) panel.style.display = 'none';
}

(function(){
  function tc(id,cfg){ new Chart(document.getElementById(id),cfg); }

  tc('c1',{
    type:'doughnut',
    data:{
      labels:['Pools with positive balance','Non-pool positive holders'],
      datasets:[{data:[{pool_count},{holder_count}],backgroundColor:['#3b82f6','#64748b'],borderWidth:0}]
    },
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{color:'#94a3b8',padding:12,font:{size:12}}}}}
  });

  tc('c2',{
    type:'doughnut',
    data:{
      labels:['Main measured pool','Other measured pools'],
      datasets:[{data:[{pool_share},{pool_other}],backgroundColor:['#f59e0b','#64748b'],borderColor:'#1e293b',borderWidth:2}]
    },
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{color:'#94a3b8',padding:12,font:{size:12}}}}}
  });

  tc('c3',{
    type:'bar',
    data:{
      labels:topChartHolders.map(function(d){return displayLabelFor(d.address);}),
      datasets:[{label:'Balance',data:topChartHolders.map(function(d){return d.balance_decimal;}),backgroundColor:'#3b82f6',borderRadius:4}]
    },
    options:{
      responsive:true,
      maintainAspectRatio:false,
      plugins:{
        legend:{display:false},
        tooltip:{callbacks:{
          title:function(items){
            var row = items && items.length ? topChartHolders[items[0].dataIndex] : null;
            return row && row.address ? row.address : '-';
          },
          label:function(ctx){
            var row = topChartHolders[ctx.dataIndex] || {};
            var balance = Number(row.balance_decimal || 0).toLocaleString(undefined,{maximumFractionDigits:6});
            return 'Balance: ' + balance + ' ' + tokenSymbol;
          },
          footer:function(){return 'Click bar to copy full address';}
        }}
      },
      onHover:function(event,elements){
        if (event && event.native && event.native.target) {
          event.native.target.style.cursor = elements && elements.length ? 'pointer' : 'default';
        }
      },
      onClick:function(event,elements){
        if (!elements || !elements.length) return;
        var row = topChartHolders[elements[0].index];
        if (row && row.address) copyIdentifierValue(event.native || event, row.address);
      },
      scales:{y:{beginAtZero:true,ticks:{color:'#64748b'},grid:{color:'#1e293b'}},x:{ticks:{color:'#64748b'},grid:{display:false}}}
    }
  });
  if (document.getElementById('c7') && poolReserveRows && poolReserveRows.length) {
    tc('c7',{
      type:'pie',
      data:{
        labels:poolReserveRows.map(function(d){
          return d.pool_label || shortIdentifier(d.address);
        }),
        datasets:[{
          label:'Observed token reserve',
          data:poolReserveRows.map(function(d){return Number(d.balance_decimal || 0);}),
          backgroundColor:poolReserveRows.map(function(_,i){return chartSeriesColors[i % chartSeriesColors.length];}),
          borderColor:'#1e293b',
          borderWidth:1,
          hoverOffset:6
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{
          legend:{
            position:'bottom',
            labels:{color:'#94a3b8',padding:8,boxWidth:10,font:{size:10}}
          },
          tooltip:{callbacks:{
            title:function(items){
              var row = items && items.length ? poolReserveRows[items[0].dataIndex] : null;
              return row && row.address ? row.address : '-';
            },
            label:function(ctx){
              var row = poolReserveRows[ctx.dataIndex] || {};
              var total = poolReserveRows.reduce(function(sum,d){return sum + Number(d.balance_decimal || 0);},0);
              var value = Number(row.balance_decimal || 0);
              var share = total > 0 ? value / total * 100 : 0;
              return (row.pool_label || 'Reserve') + ': '
                + value.toLocaleString(undefined,{maximumFractionDigits:4}) + ' ' + tokenSymbol
                + ' (' + share.toFixed(2) + '%)';
            },
            footer:function(){return 'Click slice to copy address';}
          }}
        },
        onHover:function(event,elements){
          if (event && event.native && event.native.target) {
            event.native.target.style.cursor = elements && elements.length ? 'pointer' : 'default';
          }
        },
        onClick:function(event,elements){
          if (!elements || !elements.length) return;
          var row = poolReserveRows[elements[0].index];
          if (row && row.address) copyIdentifierValue(event.native || event, row.address);
        }
      }
    });
  }
  {price_chart}
  {volume_chart}
  {tvl_chart}
})();

function togglePortfolio(addr) {
  var row = document.getElementById('portfolio-' + addr);
  if (!row) return;
  var holderRow = row.previousElementSibling;
  var icon = holderRow ? holderRow.querySelector('.expand-icon') : null;
  var open = row.style.display !== 'none';
  if (open) {
    row.style.display = 'none';
    if (icon) icon.textContent = '+';
    return;
  }
  row.style.display = '';
  if (icon) icon.textContent = '-';
  var inner = row.querySelector('.portfolio-inner');
  if (!inner) return;
  var key = (addr || '').toLowerCase();
  var positions = (portfolioData && portfolioData[key]) || [];
  if (!positions.length) {
    inner.innerHTML = '<div style="color:#64748b;padding:8px 0">No LP positions with share &gt; 0 for this address in the analysis window.</div>';
    return;
  }
  var html = '<table class="portfolio-table"><thead><tr>'
    + '<th>Protocol</th><th>Pool</th><th>Share %</th><th>Liquidity</th><th>Token0</th><th>Token1</th><th>Ticks</th>'
    + '</tr></thead><tbody>';
  for (var i = 0; i < positions.length; i++) {
    var p = positions[i];
    var pool = (p.pool || '');
    var ticks = (p.tick_lower != null && p.tick_upper != null)
      ? (p.tick_lower + ' / ' + p.tick_upper) : '-';
    var proto = ((p.protocol || '') + ' ' + (p.version || '')).trim() || '-';
    html += '<tr>'
      + '<td>' + proto + '</td>'
      + '<td>' + identifierHtml(pool) + '</td>'
      + '<td>' + (p.share_pct != null ? p.share_pct : '-') + '</td>'
      + '<td>' + (p.liquidity || '-') + '</td>'
      + '<td>' + (p.token0_amount || '-') + '</td>'
      + '<td>' + (p.token1_amount || '-') + '</td>'
      + '<td>' + ticks + '</td>'
      + '</tr>';
  }
  html += '</tbody></table>';
  inner.innerHTML = html;
}
"""

    _HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{symbol} Token Dashboard</title>
<meta name="description" content="On-chain liquidity and holdings analysis for {symbol} on Ethereum mainnet.">
<meta property="og:title" content="{symbol} Token Dashboard">
<meta property="og:description" content="On-chain liquidity and holdings analysis for {symbol}.">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0f172a;--card:#1e293b;--border:#334155;--text:#f1f5f9;--text-muted:#94a3b8;--text-dim:#64748b;--accent:#3b82f6;--accent-light:#60a5fa;--green:#4ade80;--yellow:#facc15;--red:#f87171;--radius:10px;--shadow:0 4px 24px rgba(0,0,0,0.25)}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);padding:20px;min-height:100vh}
.container{max-width:1400px;margin:0 auto}
h1{font-size:24px;font-weight:700;letter-spacing:-0.3px}
.symbol-muted{color:var(--text-muted);font-weight:400}
.subtitle{color:var(--text-muted);font-size:13px;margin-bottom:20px}
.nav-bar{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.brand{font-size:18px;font-weight:700}
.brand a{color:inherit;text-decoration:none}
.brand a:hover{color:var(--accent-light)}
.brand-accent{color:var(--accent)}
.nav-links a{color:var(--text-dim);text-decoration:none;font-size:13px;margin-left:20px;transition:color 0.2s}
.nav-links a:hover,.nav-links a.active{color:var(--accent-light)}
.nav-links a.active{font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px;box-shadow:var(--shadow)}
.card h2{font-size:12px;color:var(--text-muted);margin-bottom:14px;text-transform:uppercase;letter-spacing:0.6px;font-weight:600}
.stat-value{font-size:30px;font-weight:700;color:var(--text)}
.stat-label{font-size:12px;color:var(--text-dim);margin-top:2px}
.stat-note{font-size:10px;color:var(--text-dim);margin-top:4px;opacity:.85}
.badge{display:inline-block;padding:3px 16px;border-radius:20px;font-weight:600;font-size:13px}
.method-badge{display:inline-block;margin-left:8px;padding:2px 7px;border-radius:999px;font-size:10px;font-weight:600;vertical-align:2px;text-transform:uppercase;letter-spacing:.35px}
.method-snapshot{background:rgba(34,197,94,.13);color:var(--green)}
.method-reconstructed{background:rgba(250,204,21,.13);color:var(--yellow)}
.method-unavailable{background:rgba(100,116,139,.13);color:var(--text-muted)}
.bg-low{background:rgba(34,197,94,0.12);color:var(--green)}
.bg-medium{background:rgba(250,204,21,0.12);color:var(--yellow)}
.bg-high{background:rgba(239,68,68,0.12);color:var(--red)}
.bg-n-a{background:rgba(100,116,139,0.12);color:var(--text-muted)}
.fw{grid-column:1/-1}
.chart-box{position:relative;height:260px;width:100%}
.chart-box-sm{position:relative;height:200px;width:100%}
.pools-layout{display:grid;grid-template-columns:minmax(0,1fr) 230px;gap:14px;align-items:start}
@media (max-width:980px){.pools-layout{grid-template-columns:1fr}}
.pool-reserve-side{border:1px solid var(--border);border-radius:8px;padding:12px;background:rgba(15,23,42,0.35)}
.pool-reserve-side-title{font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;font-weight:600;margin-bottom:8px}
.pool-reserve-side-note{font-size:10px;color:var(--text-dim);line-height:1.4;margin-top:8px}
.pool-reserve-mini{position:relative;height:190px;width:100%}
.token-pair{display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap}
.token-pair .pair-sep{color:var(--text-dim);font-weight:600}
.point-details{margin-top:14px;padding:14px;background:rgba(15,23,42,0.65);border:1px solid var(--border);border-radius:8px}
.point-details-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.point-details-title{font-size:13px;font-weight:600;color:var(--text)}
.point-details-meta{font-size:12px;color:var(--text-dim);margin-bottom:10px}
.detail-summary{font-size:12px;color:var(--text-muted);margin-bottom:4px}
.detail-summary strong{color:var(--text)}
.close-btn{border:1px solid var(--border);background:transparent;color:var(--text-muted);width:26px;height:26px;border-radius:6px;font-size:16px;line-height:1;cursor:pointer;flex:0 0 auto}
.close-btn:hover{color:var(--text);border-color:var(--accent)}
.muted{color:var(--text-dim)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:8px 6px;border-bottom:1px solid var(--border);color:var(--text-dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.5px}
td{padding:6px;border-bottom:1px solid #1e293b;color:#cbd5e1}
tr:hover td{background:rgba(59,130,246,0.04)}
.addr{font-family:'SF Mono','Fira Code','Cascadia Code','Courier New',monospace;font-size:11px;color:var(--accent-light);word-break:break-all}
.identifier-wrap{display:inline-flex;align-items:center;gap:4px;max-width:100%}
.identifier-copy{appearance:none;border:0;background:transparent;padding:2px 3px;border-radius:4px;cursor:pointer;white-space:nowrap;line-height:1.35}
.identifier-copy:hover,.identifier-copy:focus-visible{background:rgba(96,165,250,.12);outline:none;color:#93c5fd}
.identifier-copy:focus-visible{box-shadow:0 0 0 2px rgba(96,165,250,.45)}
.identifier-link{display:inline-flex;align-items:center;justify-content:center;color:var(--text-dim);text-decoration:none;font-size:12px;width:18px;height:18px;border-radius:4px}
.identifier-link:hover,.identifier-link:focus-visible{color:var(--accent-light);background:rgba(96,165,250,.12);outline:none}
.identifier-tooltip{position:fixed;z-index:1000;max-width:min(620px,calc(100vw - 24px));padding:7px 9px;border:1px solid var(--border);border-radius:6px;background:#020617;color:var(--text);box-shadow:var(--shadow);font:11px/1.4 'SF Mono','Fira Code','Cascadia Code','Courier New',monospace;overflow-wrap:anywhere;pointer-events:none}
.copy-toast{position:fixed;right:20px;bottom:20px;z-index:1100;padding:10px 14px;border:1px solid rgba(74,222,128,.35);border-radius:8px;background:#052e16;color:#bbf7d0;box-shadow:var(--shadow);font-size:12px;opacity:0;transform:translateY(8px);pointer-events:none;transition:opacity .16s,transform .16s}
.copy-toast.copy-toast-visible{opacity:1;transform:translateY(0)}
.copy-toast.copy-toast-error{border-color:rgba(248,113,113,.35);background:#450a0a;color:#fecaca}
.plabel{display:inline-block;padding:1px 8px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(96,165,250,0.12);color:var(--accent-light)}
.scroll{max-height:360px;overflow-y:auto}
.scroll::-webkit-scrollbar{width:5px}
.scroll::-webkit-scrollbar-track{background:transparent}
.scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.glow{box-shadow:0 0 30px rgba(59,130,246,0.06)}
.info-bar{display:flex;flex-wrap:wrap;gap:12px 24px;margin-bottom:20px;padding:12px 16px;background:var(--card);border:1px solid var(--border);border-radius:8px}
.info-item{font-size:12px;color:var(--text-muted)}
.info-item span{color:var(--text);font-weight:500}
.coverage-note{margin:-4px 0 14px;padding:10px 12px;border:1px solid rgba(250,204,21,.24);border-radius:7px;background:rgba(250,204,21,.07);font-size:12px;line-height:1.55;color:var(--text-muted)}
.coverage-note strong{display:block;color:var(--yellow);margin-bottom:2px}
.coverage-inline{color:var(--yellow);font-weight:600}
.not-measured{color:var(--text-dim);font-style:italic;white-space:nowrap}
.amount-missing{display:inline-block;padding:3px 7px;border-radius:5px;background:rgba(250,204,21,.10);color:var(--yellow);font-size:11px;font-weight:600;font-style:normal;white-space:nowrap}
.cannot-calculate{color:var(--text-dim);font-size:11px;white-space:nowrap}
.measured-share{white-space:nowrap;color:var(--text)}
.measured-share small{color:var(--text-dim);font-size:10px}
.empty-note{padding:12px 16px;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:8px;color:var(--red);font-size:13px;margin-bottom:16px}
.footer{margin-top:32px;padding:16px;border-top:1px solid var(--border);text-align:center;font-size:12px;color:var(--text-dim)}
.footer a{color:var(--accent-light);text-decoration:none}
.holder-row{cursor:pointer;transition:background .15s}
.holder-row:hover{background:var(--bg-card-hover,#1e293b)}
.expand-icon{display:inline-block;width:20px;height:20px;line-height:18px;text-align:center;border-radius:4px;background:var(--bg-card,#0f172a);color:var(--accent);font-weight:700;font-size:14px;transition:transform .2s}
.badge-eoa{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600;background:rgba(34,197,94,.15);color:#22c55e}
.badge-contract{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600;background:rgba(234,179,8,.15);color:#eab308}
.badge-pool{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:600;background:rgba(59,130,246,.15);color:#3b82f6}
.badge-uniswap{display:inline-block;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(255,0,122,.15);color:#ff007a;margin:1px}
.badge-curve{display:inline-block;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(0,0,0,.35);color:#a0aec0;margin:1px;border:1px solid #4a5568}
.badge-balancer{display:inline-block;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(30,144,255,.15);color:#1e90ff;margin:1px}
.badge-dex-other{display:inline-block;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(148,163,184,.15);color:#94a3b8;margin:1px}
.dex-muted{color:var(--text-dim);font-size:11px}
.portfolio-row>td{padding:0!important;background:var(--bg-card,#0f172a)}
.portfolio-inner{padding:12px 16px 16px}
.portfolio-table{width:100%;border-collapse:collapse;font-size:12px}
.portfolio-table th{padding:6px 8px;text-align:left;color:var(--text-dim);border-bottom:1px solid var(--border);font-weight:600}
.portfolio-table td{padding:5px 8px;border-bottom:1px solid rgba(255,255,255,.04);color:var(--text)}
.portfolio-table tr:last-child td{border-bottom:none}
.no-positions{padding:16px;text-align:center;color:var(--text-dim);font-size:13px}
@media(max-width:640px){.grid{grid-template-columns:1fr}.nav-bar{flex-direction:column;gap:10px;align-items:flex-start}.nav-links a{margin-left:0;margin-right:14px}.stat-value{font-size:24px}}
</style>
</head>
<body>
<div class="container">
  <nav class="nav-bar">
    <div class="brand"><a id="nav-home-brand" href="../"><span class="brand-accent">On-Chain</span> Token Crash</a></div>
    <div class="nav-links">
      <a id="nav-home" href="../">Home</a>
      <a href="#" class="active">Dashboard</a>
      <a href="https://github.com/Cooler-tu/On-Chain-Token-Crash-Liquidity-Analysis" target="_blank">GitHub</a>
    </div>
  </nav>
  <script>
  (function(){{
    var path = location.pathname || "";
    var home = (path.indexOf("/run/") !== -1 || path === "/" || path === "/index.html") ? "/" : "../";
    ["nav-home", "nav-home-brand"].forEach(function(id){{
      var el = document.getElementById(id);
      if (el) el.href = home;
    }});
  }})();
  </script>

  <h1>{symbol} <span class="symbol-muted">Holdings &amp; Liquidity</span></h1>
  <p class="subtitle">Chain ID: {chain_id} &middot; Token: {token_identifier}</p>
  {empty_note}

  <div class="info-bar">
    <div class="info-item">Blocks &middot; <span>{block_window}</span></div>
    <div class="info-item">Balance query &middot; <span>{query_time}</span></div>
    <div class="info-item">Balance coverage &middot; <span>{balance_coverage}</span></div>
    <div class="info-item">Balance source &middot; <span>{balance_source_label}</span></div>
    <div class="info-item">Token &middot; <span>{token_name}</span></div>
    <div class="info-item">Decimals &middot; <span>{decimals}</span> <span style="opacity:.6">({decimals_source})</span></div>
    {supply_info}
  </div>

  <div class="grid">
    <div class="card glow">
      <div class="stat-value">{total_addresses}</div>
      <div class="stat-label">Unique Transfer Addresses</div>
    </div>
    <div class="card glow">
      <div class="stat-value">{positive_holder_count}</div>
      <div class="stat-label">Positive-Balance Holders</div>
      <div class="stat-note">Non-pool addresses in covered rows</div>
    </div>
    <div class="card glow">
      <div class="stat-value">{num_pools}</div>
      <div class="stat-label">Verified Liquidity Pools</div>
    </div>
    <div class="card glow">
      <div class="stat-value"><span class="badge bg-{risk_lvl_class}">{risk_level}</span></div>
      <div class="stat-label">Risk Index &middot; Score <span style="color:{risk_color}">{risk_score}</span></div>
      <div class="stat-note">raw = 0.15·pool + 0.15·lp + 0.20·withdrawal + 0.15·temporal + 0.15·role + 0.15·impact + 0.05·activity</div>
      <div class="stat-note">final = clamp(raw − migration, 0, 1) × confidence · not a crash probability · LOW &lt; 0.40 · MEDIUM 0.40–0.70 · HIGH ≥ 0.70</div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Positive Holder Distribution</h2>
      <div class="chart-box-sm"><canvas id="c1"></canvas></div>
    </div>
    <div class="card">
      <h2>Measured Pool Concentration</h2>
      <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 8px;line-height:1.5">{pool_conc_summary}</p>
      <div class="chart-box-sm"><canvas id="c2"></canvas></div>
    </div>
    <div class="card">
      <h2>Top {top_chart_holder_count} Non-Pool Holders</h2>
      <p style="font-size:11px;color:var(--text-dim);margin:-8px 0 8px">Positive end balances, ranked highest to lowest &middot; Hover for the full address and balance &middot; Click a bar to copy.</p>
      <div class="chart-box-sm"><canvas id="c3"></canvas></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Price Timeline (USD)</h2>
      <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 10px">Swap-derived USD price per pool. Bucket from analysis window: ~month→daily 00:00 UTC; ~week/day→hourly.</p>
      <div class="chart-box"><canvas id="c5"></canvas></div>
    </div>
    <div class="card">
      <h2>Trading Volume by Pool</h2>
      <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 10px">Volume in {symbol}; stacked by pool. Same time bucket as price &amp; TVL ({chart_bucket_label}).</p>
      <div class="chart-box"><canvas id="c6"></canvas></div>
    </div>
  </div>

  <div class="grid">
    <div class="card fw">
      <h2>Top {top_table_holder_count} Non-Pool Holders by End Balance</h2>
      <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 6px">Pool and DEX custody addresses are excluded. Positive end balances are ranked from highest to lowest among addresses covered by the balance query. EOA and contract addresses may both appear; this is not a complete holder census when coverage is partial.</p>
      <p style="font-size:11px;color:var(--text-dim);margin:0 0 12px">DEX = touched that venue in this window (LP, swap, pool transfer, or same tx as a pool trade). “—” = only P2P / no DEX link found here.{balance_note}</p>
      <div class="scroll"><table><thead><tr><th>#</th><th>Address</th><th>Type</th><th>DEX</th><th>End Balance ({symbol})</th><th>Start Balance</th><th>Net Change</th><th>Peak</th><th>Tx Count</th><th></th></tr></thead><tbody>{table_top}</tbody></table></div>
    </div>
  </div>

  {pool_section}

  <div class="grid">
    <div class="card fw">
      <h2>Pool TVL Timeline (Total + Per Pool) {tvl_method_badge}</h2>
      <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 10px">{tvl_method_note} Bucket configuration: {chart_bucket_label}.</p>
      <div class="chart-box"><canvas id="c4"></canvas></div>
      <div id="tvl-details" class="point-details" style="display:none">
        <div class="point-details-head">
          <div id="tvl-detail-title" class="point-details-title"></div>
          <button type="button" class="close-btn" onclick="closeTvlDetails()" aria-label="Close details">&times;</button>
        </div>
        <div id="tvl-detail-meta" class="point-details-meta"></div>
        <div class="scroll">
          <table>
            <thead><tr><th>Pool</th><th>Protocol / Version</th><th>TVL ({symbol})</th><th>TVL Share</th><th>Price (USD)</th><th>Volume ({symbol})</th><th>Volume (USD)</th></tr></thead>
            <tbody id="tvl-detail-body"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <div class="grid">
    <div class="card fw">
      <h2>Liquidity Withdrawals</h2>
      <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 12px">Read this table in two layers: a negative raw liquidity change confirms a removal action; calculating removed {symbol}, USD value, and TVL share additionally requires token amounts. Missing token amounts are never converted to zero.</p>
{withdrawal_quantification_note}
{table_withdrawal_summary}
      <div class="scroll"><table><thead><tr><th>Block</th><th>Pool</th><th>Events</th><th>Actor / Scope</th><th>Raw Liquidity Change</th><th>Removed ({symbol})</th><th>Est. USD</th><th>% Pool TVL</th><th>Protocol</th></tr></thead><tbody>{table_withdrawals}</tbody></table></div>
    </div>
  </div>

  <div class="footer">
    Generated by <a href="https://github.com/Cooler-tu/On-Chain-Token-Crash-Liquidity-Analysis">On-Chain Token Crash &amp; Liquidity Analysis</a>
    &middot; Data sourced from Ethereum mainnet
  </div>
</div>
<div id="identifier-tooltip" class="identifier-tooltip" role="tooltip" hidden></div>
<div id="copy-toast" class="copy-toast" role="status" aria-live="polite"></div>
<script>
{js_script}
</script>
</body>
</html>"""


def generate_dashboard(
    output_dir: str | Path = "output",
) -> str:
    out = Path(output_dir)
    _load_templates()

    inputs = _load_dashboard_inputs(out)
    holdings = inputs["holdings"]
    token_profile = inputs["token_profile"]
    verified_pools = inputs["verified_pools"]
    metrics = inputs["metrics"]
    risk = inputs["risk"]
    positions_data = inputs["positions"]
    swaps_data = inputs["swaps"]
    liq_data = inputs["liquidity_events"]
    transfers_data = inputs["transfers"]
    events_all = inputs["events_all"]

    holdings_data = holdings.get("holdings", [])
    pool_ident = holdings.get("pool_identification", [])

    if not pool_ident and verified_pools:
        pool_ident = [
            {
                "pool_address": p.get("pool_address", ""),
                "protocol": p.get("protocol", ""),
                "version": p.get("version", ""),
                "token0": p.get("token0", ""),
                "token1": p.get("token1", ""),
                "in_holders_list": False,
            }
            for p in verified_pools if p.get("verified", True)
        ]

    pool_meta = _pool_meta_lookup(verified_pools)
    dex_by_addr = _build_address_dex_map(
        pool_meta, positions_data, events_all
    )
    _write_json(out / "address_dex.json", dex_by_addr)

    # Enrich holdings rows for table/CSV convenience
    for h in holdings_data:
        info = dex_by_addr.get((h.get("address") or "").lower(), {})
        h["dex_protocols"] = info.get("protocols", [])
        h["dex_roles"] = info.get("roles", {})

    # Portfolio: all LP positions (incl. share=0 out-of-range), with real protocol
    portfolio_map: dict[str, list] = {}
    for pos in positions_data:
        owner = (pos.get("owner") or "").strip()
        if not owner:
            continue
        pool_key = (pos.get("pool_address") or "").lower()
        meta = pool_meta.get(pool_key, {})
        protocol = meta.get("protocol") or _guess_protocol_from_method(
            pos.get("resolution_method")
        )
        version = meta.get("version") or _guess_version_from_method(
            pos.get("resolution_method")
        )
        portfolio_map.setdefault(owner.lower(), []).append({
            "pool": pos.get("pool_address", ""),
            "owner": owner,
            "protocol": protocol,
            "version": version,
            "share_pct": round(float(pos.get("share_pct") or 0), 4),
            "liquidity": pos.get("liquidity", "0"),
            "token0_amount": pos.get("token0_amount", ""),
            "token1_amount": pos.get("token1_amount", ""),
            "tick_lower": pos.get("tick_lower"),
            "tick_upper": pos.get("tick_upper"),
            "resolution_method": pos.get("resolution_method", ""),
        })
    portfolio_json = json.dumps(portfolio_map, indent=2)
    _write_json(out / "portfolios.json", portfolio_map)

    top_holders = _rank_non_pool_holders(holdings_data, limit=20)
    pool_holders = [h for h in holdings_data if h.get("is_pool")]
    tvl_data = metrics.get("tvl_timeline", [])
    pool_conc = metrics.get("pool_concentration", {})
    volume_metrics = metrics.get("volume", {})

    # Month windows should chart ~daily ticks even when TVL fell back to
    # per-swap event points (event_accumulate_fallback).
    from .metrics import chart_bucket_seconds, resample_tvl_timeline

    chart_span_resolved = str(
        metrics.get("chart_span") or volume_metrics.get("chart_span") or "month"
    )
    bucket_seconds = int(
        volume_metrics.get("bucket_seconds")
        or chart_bucket_seconds(chart_span_resolved)
        or 0
    )
    if tvl_data and bucket_seconds > 0:
        tvl_data = resample_tvl_timeline(
            tvl_data,
            bucket_seconds,
            chart_span=chart_span_resolved,
            chart_bucket=str(metrics.get("chart_bucket") or ""),
        )

    risk_score = risk.get("final_score", 0)
    risk_level = risk.get("risk_level", "N/A")
    symbol = token_profile.get("symbol", "TOKEN")
    chain_id = token_profile.get("chain_id", 1)
    token_addr = token_profile.get("address", "")
    token_name = token_profile.get("name", symbol)
    decimals = token_profile.get("decimals", 18)
    decimals_source = token_profile.get("decimals_source", "unknown")
    total_supply = token_profile.get("total_supply_decimal", 0) or 0
    metrics = _refresh_withdrawal_metrics(
        metrics,
        liq_data,
        verified_pools,
        token_addr,
        decimals,
        pool_conc,
        tvl_data,
    )
    holdings_count = holdings.get("holdings_count", 0)
    total_addresses = holdings.get("total_unique_addresses", 0)
    holder_semantics = _holder_semantics(holdings_data)
    positive_holder_count = holder_semantics["positive_non_pool_count"]
    positive_pool_count = holder_semantics["positive_pool_count"]
    balance_covered_count = holder_semantics["covered_count"]
    zero_fill_count = holder_semantics["zero_fill_count"]
    coverage_denominator = holder_semantics["total_count"]
    if coverage_denominator:
        coverage_pct = balance_covered_count / coverage_denominator * 100
        balance_coverage = "{:,} / {:,} addresses ({:.1f}%)".format(
            balance_covered_count, coverage_denominator, coverage_pct
        )
    else:
        balance_coverage = "N/A"
    balance_source_label = _humanize_source(holdings.get("balance_source") or "unknown")
    query_time = holdings.get("query_time_human", "")
    from_block = holdings.get("from_block") or 0
    to_block = holdings.get("to_block") or holdings.get("balance_block") or 0
    if not from_block or not to_block:
        timeline_meta = _load_json(out / "incident_timeline.json", {})
        from_block = from_block or timeline_meta.get("from_block") or 0
        to_block = to_block or timeline_meta.get("to_block") or 0
    if from_block and to_block:
        block_window = "{:,} → {:,}".format(int(from_block), int(to_block))
    elif to_block:
        block_window = "… → {:,}".format(int(to_block))
    else:
        block_window = "N/A"
    pool_liquidity = _pool_liquidity_presentation(pool_ident, metrics)
    main_pool_share = pool_conc.get("main_pool_share", 0) * 100
    main_pool_addr = pool_conc.get("main_pool", "")
    main_volume_addr = volume_metrics.get("main_volume_pool", "")
    main_volume_share = volume_metrics.get("main_volume_share", 0) * 100
    token_symbols = _resolve_token_symbol_map(
        pool_ident,
        target_address=token_addr,
        target_symbol=symbol,
    )
    # Also pull tokens from verified_pools in case pool_ident is incomplete.
    more_symbols = _resolve_token_symbol_map(
        [
            {
                "token0": (p.get("token0") if isinstance(p, dict) else getattr(p, "token0", "")),
                "token1": (p.get("token1") if isinstance(p, dict) else getattr(p, "token1", "")),
            }
            for p in (verified_pools or [])
        ],
        target_address=token_addr,
        target_symbol=symbol,
    )
    token_symbols.update(more_symbols)
    address_labels = _build_address_display_labels(
        pool_ident or verified_pools,
        token_symbols=token_symbols,
        verified_pools=verified_pools,
    )
    main_pool_label = _identifier_html(
        main_pool_addr,
        chain_id=chain_id,
        label=address_labels.get((main_pool_addr or "").lower()),
    )
    main_volume_label = _identifier_html(
        main_volume_addr,
        chain_id=chain_id,
        label=address_labels.get((main_volume_addr or "").lower()),
    )
    if main_pool_addr and main_volume_addr:
        pool_conc_summary = (
            "Main measured liquidity pool: {} ({:.2f}%) · Main volume pool: {} ({:.2f}%)".format(
                main_pool_label, main_pool_share, main_volume_label, main_volume_share
            )
        )
    elif main_pool_addr:
        pool_conc_summary = "Main measured liquidity pool: {} ({:.2f}%)".format(
            main_pool_label, main_pool_share
        )
    else:
        pool_conc_summary = "No active pool concentration data."
    pool_conc_summary = (
        '<span class="coverage-inline">{}</span><br>{}'.format(
            pool_liquidity["coverage_title"], pool_conc_summary
        )
    )

    risk_lvl_class = risk_level.lower() if risk_level != "N/A" else "n-a"
    risk_color = _risk_color(risk_score)

    empty_note = ""
    if holdings_count == 0 and total_addresses == 0:
        empty_note = (
            '<div class="empty-note">'
            "No transfer/holdings data in this block window — "
            "pool list and risk score below still reflect discovery results."
            "</div>"
        )

    supply_info = (
        f'<div class="info-item">Total Supply · <span>{_fmt_supply(total_supply, symbol)}</span></div>'
        if total_supply else ''
    )

    # Build tables
    table_top = _table_top_holders(
        top_holders, symbol, chain_id=chain_id, address_labels=address_labels
    )
    table_ident, reserve_pie_rows = _table_pool_ident(
        pool_ident,
        metrics,
        decimals,
        symbol,
        chain_id=chain_id,
        pool_holders=pool_holders,
        verified_pools=verified_pools,
        token_symbols=token_symbols,
        address_labels=address_labels,
    )
    table_movers = _table_wallet_movers(
        swaps_data,
        holdings_data,
        token_addr,
        decimals,
        symbol,
        chain_id=chain_id,
        address_labels=address_labels,
    )
    table_withdrawals = _table_withdrawals(
        metrics,
        decimals,
        symbol,
        chain_id=chain_id,
        address_labels=address_labels,
    )
    table_withdrawal_summary = _table_withdrawal_summary(
        metrics, symbol, chain_id=chain_id, address_labels=address_labels
    )
    table_large = _table_large_wallets(
        metrics, symbol, chain_id=chain_id, address_labels=address_labels
    )
    withdrawal_quantification_note = _withdrawal_quantification_note(metrics)

    balance_note_parts = []
    balance_start_block = holdings.get("balance_start_block") or from_block
    balance_end_block = holdings.get("balance_end_block") or to_block
    if balance_start_block and balance_end_block:
        balance_note_parts.append(
            "Snapshot blocks: start {:,} → end {:,}".format(
                int(balance_start_block), int(balance_end_block)
            )
        )
    dune_count = holdings.get("dune_historical_balance_count")
    rebuild_count = holdings.get("event_rebuild_count")
    if dune_count is not None:
        balance_note_parts.append(
            "{} addresses via Dune historical snapshot".format(dune_count)
        )
    if rebuild_count is not None:
        balance_note_parts.append(
            "{} addresses with event-flow peak/trajectory".format(rebuild_count)
        )
    if holdings.get("balance_source"):
        balance_note_parts.append("source: {}".format(holdings["balance_source"]))
    if coverage_denominator:
        balance_note_parts.append(
            "{} balance-covered; {} unqueried/zero-filled".format(
                balance_covered_count, zero_fill_count
            )
        )
        balance_note_parts.append(
            "positive-holder count excludes pools and zero-filled rows"
        )
    balance_note = " · ".join(balance_note_parts)
    if balance_note:
        balance_note = '<br><span style="opacity:.85">' + balance_note + "</span>"

    # Build pool section
    pool_section_parts = []
    activity = metrics.get("wallet_activity") or {}
    large_wallet_note = (
        "Flags are independent: Trade = largest single swap; Mover = |net USD|; "
        "Activity = swap count; Volume = cumulative wallet volume."
    )
    if activity:
        note_parts = []
        modes = activity.get("threshold_modes") or {}
        percentile_label = activity.get("adaptive_percentile_label") or "P99"
        adaptive_note = activity.get("selection_mode") in (
            "adaptive_percentile", "hybrid"
        )
        if adaptive_note:
            note_parts.append(
                "{} within {} wallets".format(
                    percentile_label,
                    int(activity.get("wallets_considered") or 0),
                )
            )
        trade_th = activity.get("large_trade_threshold_usd")
        mover_th = activity.get("mover_net_usd_threshold")
        activity_th = activity.get("activity_trade_threshold")
        if trade_th:
            note_parts.append(
                "Trade ≥ ${:,.0f} single swap{}".format(
                    trade_th,
                    " (adaptive)" if modes.get("trade") == "percentile" else "",
                )
            )
        if mover_th:
            note_parts.append(
                "Mover ≥ ${:,.0f} |net USD|{}".format(
                    mover_th,
                    " (adaptive)" if modes.get("mover") == "percentile" else "",
                )
            )
        if activity_th:
            note_parts.append(
                "Activity ≥ {} swaps{}".format(
                    int(activity_th),
                    " (adaptive)" if modes.get("activity") == "percentile" else "",
                )
            )
        volume_th = activity.get("ratio_threshold_usd")
        if volume_th:
            if modes.get("volume") == "fixed_ratio":
                note_parts.append(
                    "Share ≥ {:.2%} of total volume".format(
                        float(activity.get("volume_ratio") or 0)
                    )
                )
            else:
                note_parts.append(
                    "Volume ≥ ${:,.0f} (adaptive)".format(volume_th)
                )
        if note_parts:
            prefix = (
                "Independent adaptive signals: "
                if adaptive_note else "Independent signals: "
            )
            large_wallet_note = prefix + " · ".join(note_parts) + "."

    if table_ident:
        reserve_pie_block = ""
        if reserve_pie_rows:
            reserve_pie_block = """<aside class="pool-reserve-side">
        <div class="pool-reserve-side-title">Reserve share</div>
        <div class="pool-reserve-mini"><canvas id="c7"></canvas></div>
        <p class="pool-reserve-side-note">Observed target-token reserve mix across verified pools (same values as the Reserve column).</p>
      </aside>"""
        pool_section_parts.append(f"""<div class="grid">
    <div class="card fw">
      <h2>All Verified Pools</h2>
      <div class="coverage-note"><strong>{pool_liquidity['coverage_title']}</strong>{pool_liquidity['comparison_note']}<br>{pool_liquidity['method_note']}</div>
      <div class="pools-layout">
        <div class="scroll"><table><thead><tr><th>Pool Address</th><th>Protocol / Version</th><th>Token Pair</th><th>Observed Token Reserve</th><th>Estimated Pool Liquidity (in {html.escape(str(symbol))})</th><th>Volume ({symbol})</th><th>{pool_liquidity['share_header']}</th><th>Vol Share</th><th>In Holders</th></tr></thead><tbody>{table_ident}</tbody></table></div>
        {reserve_pie_block}
      </div>
    </div>
  </div>""")

    if table_movers:
        pool_section_parts.append(f"""<div class="grid">
    <div class="card fw">
      <h2>Top Movers (Holder Net Change)</h2>
      <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 12px">Net (Holdings) = end-block balance − start-block balance when a Dune/RPC snapshot exists. Bought/Sold/Swap Net are swap-only context; transfer-only moves can differ.</p>
      <div class="scroll"><table><thead><tr><th>#</th><th>Address</th><th>Bought ({symbol})</th><th>Sold ({symbol})</th><th>Swap Net ({symbol})</th><th>Holdings Net ({symbol})</th><th>Peak ({symbol})</th><th>Source</th><th>Swap Tx</th></tr></thead><tbody>{table_movers}</tbody></table></div>
    </div>
  </div>""")
    if table_large:
        pool_section_parts.append(f"""<div class="grid">
    <div class="card fw">
      <h2>Notable Wallets (USD)</h2>
      <p style="font-size:12px;color:var(--text-dim);margin:-8px 0 12px">{large_wallet_note}</p>
      <div class="scroll"><table><thead><tr><th>#</th><th>Address</th><th>Max Single USD</th><th>Bought USD</th><th>Sold USD</th><th>Net USD</th><th>Total USD</th><th>Volume Share</th><th>Swap Tx</th><th>Flags</th></tr></thead><tbody>{table_large}</tbody></table></div>
    </div>
  </div>""")
    pool_section = "\n".join(pool_section_parts)

    # Charts use the full analysis window; bucket size was chosen at metrics time
    # (~month→daily, ~week/day→hourly) — no UI range toggle.
    chart_span = str(metrics.get("chart_span") or volume_metrics.get("chart_span") or "")
    chart_bucket = str(metrics.get("chart_bucket") or volume_metrics.get("bucket") or "")
    if chart_bucket == "day":
        chart_bucket_label = "daily buckets"
    elif chart_bucket == "hour" or int(volume_metrics.get("bucket_seconds") or 0) == 3600:
        chart_bucket_label = "hourly buckets"
    else:
        chart_bucket_label = chart_bucket or "auto buckets"
    if chart_span:
        chart_bucket_label = "{} ({})".format(chart_bucket_label, chart_span)

    tvl_method = _tvl_method_presentation(
        metrics.get("tvl_timeline_source"), tvl_data
    )

    tvl_chart = _build_tvl_chart_js(
        tvl_data,
        token_decimals=decimals,
        symbol=symbol,
        address_labels=address_labels,
        bucket_seconds=bucket_seconds,
    )
    tvl_details = _build_tvl_details_data(
        tvl_data,
        volume_metrics,
        token_decimals=decimals,
        address_labels=address_labels,
    )
    price_rows = _price_series_for_chart(
        tvl_data,
        swaps=swaps_data,
        verified_pools=verified_pools,
        target_token=token_addr,
        token_decimals=decimals,
        bucket_seconds=bucket_seconds,
    )
    price_chart = _build_price_chart_js(
        price_rows,
        symbol=symbol,
        address_labels=address_labels,
        bucket_seconds=bucket_seconds,
    )
    volume_chart = _build_volume_chart_js(
        volume_metrics, symbol=symbol, address_labels=address_labels
    )

    # Build JS
    js_vars = {
        "top_h_json": json.dumps(top_holders, indent=2),
        "pool_reserve_json": json.dumps(reserve_pie_rows, indent=2),
        "address_labels_json": json.dumps(address_labels, indent=2),
        "tvl_json": json.dumps(tvl_data, indent=2),
        "portfolio_json": portfolio_json,
        "symbol": symbol.replace("\\", "\\\\").replace('"', '\\"'),
        "chain_id": int(chain_id or 0),
        "tvl_detail_json": json.dumps(tvl_details, default=str),
        "chart_colors_json": json.dumps(_CHART_SERIES_COLORS),
        "pool_count": positive_pool_count,
        "holder_count": positive_holder_count,
        "pool_share": main_pool_share,
        "pool_other": max(0, 100 - main_pool_share),
        "price_chart": price_chart,
        "volume_chart": volume_chart,
        "tvl_chart": tvl_chart,
    }
    
    js_script = _JS_TEMPLATE
    for k, v in js_vars.items():
        js_script = js_script.replace("{" + k + "}", str(v))


    # Build HTML
    html_vars = {
        "symbol": symbol,
        "token_name": token_name,
        "chain_id": chain_id,
        "token_identifier": _identifier_html(
            token_addr,
            chain_id=chain_id,
            label=address_labels.get((token_addr or "").lower()) or symbol,
        ),
        "query_time": query_time or "N/A",
        "block_window": block_window,
        "decimals": decimals,
        "decimals_source": decimals_source,
        "supply_info": supply_info,
        "empty_note": empty_note,
        "total_addresses": total_addresses,
        "positive_holder_count": positive_holder_count,
        "top_chart_holder_count": min(10, len(top_holders)),
        "top_table_holder_count": len(top_holders),
        "balance_coverage": balance_coverage,
        "balance_source_label": balance_source_label,
        "num_pools": len(verified_pools),
        "risk_lvl_class": risk_lvl_class,
        "risk_level": risk_level if risk_level != "N/A" else "N/A",
        "risk_color": risk_color,
        "risk_score": risk_score,
        "pool_conc_summary": pool_conc_summary,
        "balance_note": balance_note,
        "chart_bucket_label": chart_bucket_label,
        "tvl_method_badge": tvl_method["badge_html"],
        "tvl_method_note": tvl_method["note"],
        "table_top": table_top,
        "table_movers": table_movers or "",
        "table_withdrawals": table_withdrawals or "",
        "table_withdrawal_summary": table_withdrawal_summary or "",
        "withdrawal_quantification_note": withdrawal_quantification_note,
        "pool_section": pool_section,
        "js_script": js_script,
    }
    dashboard_html = _HTML_TEMPLATE
    for k, v in html_vars.items():
        dashboard_html = dashboard_html.replace("{" + k + "}", str(v))

    dashboard_path = out / "dashboard.html"
    with open(dashboard_path, "w") as f:
        f.write(dashboard_html)

    return str(dashboard_path.resolve())


def _config_to_chart_js(canvas_id: str, cfg: dict, *, with_tvl_click: bool = False) -> str:
    """Serialize a Chart.js config dict into ``tc('id', {...})`` JS."""
    options = dict(cfg.get("options") or {})
    # onClick cannot JSON-serialize; splice after dumps when needed.
    options.pop("onClick", None)
    payload = {
        "type": cfg.get("type", "line"),
        "data": cfg.get("data") or {},
        "options": options,
    }
    raw = json.dumps(payload, default=str)
    if with_tvl_click:
        # Insert onClick into options object.
        raw = raw.replace(
            '"options": {',
            (
                '"options": {'
                '"onClick":function(evt,els,chart){'
                "var active=chart.getElementsAtEventForMode("
                "evt,'index',{intersect:false},true);"
                "if(active&&active.length){renderTvlDetails(active[0].index);}},"
            ),
            1,
        )
    return "tc('%s',%s);" % (canvas_id, raw)


def _build_tvl_chart_js(
    tvl_data: list,
    token_decimals: int = 18,
    symbol: str = "TOKEN",
    address_labels: Optional[dict[str, str]] = None,
    bucket_seconds: int = 0,
) -> str:
    return _config_to_chart_js(
        "c4",
        _build_tvl_chart_config(
            tvl_data,
            token_decimals=token_decimals,
            symbol=symbol,
            address_labels=address_labels,
            bucket_seconds=bucket_seconds,
        ),
        with_tvl_click=True,
    )


def _build_price_chart_js(
    tvl_data: list,
    symbol: str = "TOKEN",
    address_labels: Optional[dict[str, str]] = None,
    bucket_seconds: int = 0,
) -> str:
    return _config_to_chart_js(
        "c5",
        _build_price_chart_config(
            tvl_data,
            symbol=symbol,
            address_labels=address_labels,
            bucket_seconds=bucket_seconds,
        ),
    )


def _build_volume_chart_js(
    volume_metrics: dict,
    symbol: str = "TOKEN",
    address_labels: Optional[dict[str, str]] = None,
) -> str:
    return _config_to_chart_js(
        "c6",
        _build_volume_chart_config(
            volume_metrics, symbol=symbol, address_labels=address_labels
        ),
    )


def _entry_ts(entry: dict) -> int:
    """Unix timestamp for a timeline row (snapshot or event)."""
    for key in ("block_timestamp", "bucket_ts", "block_number"):
        try:
            v = int(entry.get(key) or 0)
        except (TypeError, ValueError):
            continue
        # Heuristic: real unix vs block height
        if v > 1_000_000_000:
            return v
        if key == "block_timestamp" and v > 0:
            return v
    return 0


def _window_bounds(timestamps: list[int], span: str) -> tuple[int, int]:
    from .metrics import _SPAN_WINDOW_SECONDS

    if not timestamps:
        return 0, 0
    hi = max(timestamps)
    lo = hi - int(_SPAN_WINDOW_SECONDS.get(span, 86_400))
    return lo, hi


def _rebucket_ts(ts: int, bucket_seconds: int) -> int:
    if ts <= 0 or bucket_seconds <= 0:
        return ts
    return (ts // bucket_seconds) * bucket_seconds


def _filter_tvl_for_span(tvl_data: list, span: str) -> list:
    """Keep last month/week/day of points; rebucket month→daily, week/day→hourly."""
    from .metrics import chart_bucket_seconds

    if not tvl_data:
        return []
    stamps = [_entry_ts(t) for t in tvl_data]
    stamps = [t for t in stamps if t > 0]
    lo, hi = _window_bounds(stamps, span)
    bucket = chart_bucket_seconds(span)
    # (bucket_ts, pool) → last entry
    last: dict[tuple[int, str], dict] = {}
    for t in tvl_data:
        ts = _entry_ts(t)
        if ts <= 0 or ts < lo or ts > hi:
            continue
        bts = _rebucket_ts(ts, bucket)
        pa = str(t.get("pool_address") or "unknown")
        key = (bts, pa.lower())
        row = dict(t)
        row["block_number"] = bts
        row["block_timestamp"] = bts
        last[key] = row
    return sorted(
        last.values(),
        key=lambda e: (int(e.get("block_number") or 0), str(e.get("pool_address") or "")),
    )


def _filter_volume_for_span(volume_metrics: dict, span: str) -> dict:
    """Slice + re-aggregate volume_timeline for the selected chart span."""
    from .metrics import chart_bucket_seconds

    src = volume_metrics or {}
    timeline = list(src.get("volume_timeline") or [])
    if not timeline:
        out = dict(src)
        out["volume_timeline"] = []
        out["bucket_seconds"] = chart_bucket_seconds(span)
        out["chart_span"] = span
        return out

    stamps = []
    for bucket in timeline:
        try:
            stamps.append(int(bucket.get("bucket_ts") or 0))
        except (TypeError, ValueError):
            continue
    stamps = [t for t in stamps if t > 0]
    lo, hi = _window_bounds(stamps, span)
    bucket_seconds = chart_bucket_seconds(span)

    merged: dict[int, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"volume_in_token": 0.0, "volume_usd": 0.0})
    )
    for bucket in timeline:
        try:
            ts = int(bucket.get("bucket_ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0 or ts < lo or ts > hi:
            continue
        bts = _rebucket_ts(ts, bucket_seconds)
        for pa, pdata in (bucket.get("pools") or {}).items():
            merged[bts][pa]["volume_in_token"] += float(
                pdata.get("volume_in_token") or 0
            )
            usd = pdata.get("volume_usd")
            if usd is not None:
                merged[bts][pa]["volume_usd"] += float(usd or 0)

    volume_timeline = []
    for bts in sorted(merged):
        pools = {
            pa: {
                "volume_in_token": round(vals["volume_in_token"], 6),
                "volume_usd": round(vals["volume_usd"], 2)
                if vals["volume_usd"]
                else None,
            }
            for pa, vals in sorted(
                merged[bts].items(), key=lambda x: -x[1]["volume_in_token"]
            )
        }
        volume_timeline.append({
            "bucket_ts": bts,
            "total_volume_in_token": round(
                sum(p["volume_in_token"] for p in pools.values()), 6
            ),
            "pools": pools,
        })

    out = dict(src)
    out["volume_timeline"] = volume_timeline
    out["bucket_seconds"] = bucket_seconds
    out["chart_span"] = span
    return out


def _build_chart_span_views(
    tvl_data: list,
    volume_metrics: dict,
    token_decimals: int = 18,
    symbol: str = "TOKEN",
) -> dict[str, dict]:
    """Precompute Chart.js configs for month / week / day toggles."""
    views: dict[str, dict] = {}
    for span in ("month", "week", "day"):
        tvl_span = _filter_tvl_for_span(tvl_data, span)
        vol_span = _filter_volume_for_span(volume_metrics, span)
        views[span] = {
            "price": _build_price_chart_config(tvl_span, symbol=symbol),
            "volume": _build_volume_chart_config(vol_span, symbol=symbol),
            "tvl": _build_tvl_chart_config(
                tvl_span, token_decimals=token_decimals, symbol=symbol
            ),
            "tvl_details": _build_tvl_details_data(
                tvl_span, vol_span, token_decimals=token_decimals
            ),
        }
    return views


def _price_series_for_chart(
    tvl_data: list,
    *,
    swaps: Optional[list] = None,
    verified_pools: Optional[list] = None,
    target_token: str = "",
    token_decimals: int = 18,
    bucket_seconds: int = 0,
) -> list[dict]:
    """Prefer swap-derived USD prices so V2 event-TVL rows without price_usd still chart."""
    from .metrics import calculate_price_timeline_from_swaps

    seconds = int(bucket_seconds or 0) or 3_600
    pool_models = []
    for row in verified_pools or []:
        if isinstance(row, VerifiedPool):
            if row.verified:
                pool_models.append(row)
            continue
        if not isinstance(row, dict) or not row.get("verified", True):
            continue
        allowed = set(VerifiedPool.__dataclass_fields__)
        try:
            pool_models.append(
                VerifiedPool(**{k: v for k, v in row.items() if k in allowed})
            )
        except TypeError:
            continue

    if swaps and pool_models and target_token:
        local = calculate_price_timeline_from_swaps(
            swaps,
            pool_models,
            target_token,
            token_decimals,
            bucket_seconds=seconds,
        )
        if local:
            return [
                {
                    "block_number": int(row["bucket_ts"]),
                    "block_timestamp": int(row["bucket_ts"]),
                    "pool_address": row.get("pool_address") or "",
                    "price_usd": float(row.get("price_usd") or 0),
                    "protocol": row.get("protocol") or "",
                    "version": row.get("version") or "",
                }
                for row in local
                if float(row.get("price_usd") or 0) > 0
            ]

    return [
        row
        for row in (tvl_data or [])
        if float(row.get("price_usd") or 0) > 0
    ]


def _chart_axis_label(value: Any, bucket_seconds: int = 0) -> str:
    """Format TVL/price chart x ticks: unix buckets as dates, else block numbers."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return str(value or "")
    if v > 1_000_000_000:
        dt = datetime.fromtimestamp(v, tz=timezone.utc)
        if int(bucket_seconds or 0) >= 86_400:
            return dt.strftime("%m-%d")
        return dt.strftime("%m-%d %H:%M")
    return "{:,}".format(v)


def _tvl_series(
    tvl_data: list,
    token_decimals: int = 18,
):
    """Return per-block TVL series with one representative value per pool."""
    scale = 10 ** max(0, int(token_decimals or 18))
    by_pool: dict[str, list[dict]] = defaultdict(list)
    for t in tvl_data:
        by_pool[t.get("pool_address") or "unknown"].append(t)

    use_usd = any(t.get("tvl_usd") is not None for t in tvl_data)
    labels = sorted({t["block_number"] for entries in by_pool.values() for t in entries})
    total_values = []
    block_pools: dict[int, dict[str, dict]] = {}
    for block in labels:
        total = 0.0
        per_pool: dict[str, dict] = {}
        for pa, entries in by_pool.items():
            last = None
            for t in entries:
                if t["block_number"] == block:
                    last = t
            if last is None:
                continue
            try:
                if use_usd and last.get("tvl_usd") is not None:
                    value = float(last.get("tvl_usd") or 0)
                else:
                    raw = last.get("tvl_in_token", last.get("tvl", 0))
                    value = float(raw) / scale if raw is not None else 0.0
            except (TypeError, ValueError):
                value = 0.0
            per_pool[pa] = {"value": value, "entry": last}
            total += value
        block_pools[block] = per_pool
        total_values.append(total)
    return labels, total_values, block_pools, use_usd


def _empty_line_config(canvas_hint: str = "No Data") -> dict:
    return {
        "type": "line",
        "data": {
            "labels": [canvas_hint],
            "datasets": [{
                "data": [0],
                "borderColor": "#3b82f6",
                "backgroundColor": "#3b82f6",
            }],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"legend": {"display": False}},
            "scales": {
                "y": {"ticks": {"color": "#64748b"}, "grid": {"color": "#1e293b"}},
                "x": {"ticks": {"color": "#64748b"}, "grid": {"display": False}},
            },
        },
    }


def _build_tvl_chart_config(
    tvl_data: list,
    token_decimals: int = 18,
    symbol: str = "TOKEN",
    address_labels: Optional[dict[str, str]] = None,
    bucket_seconds: int = 0,
) -> dict:
    if not tvl_data:
        return _empty_line_config()

    labels, total_values, block_pools, use_usd = _tvl_series(tvl_data, token_decimals)
    display_labels = [
        _chart_axis_label(block, bucket_seconds) for block in labels
    ]
    unit = "USD" if use_usd else (symbol or "token")
    datasets = [{
        "label": "Total ({})".format(unit),
        "data": total_values,
        "borderColor": "#3b82f6",
        "backgroundColor": "rgba(59,130,246,0.08)",
        "fill": True,
        "tension": 0.25,
        "pointRadius": 0,
    }]
    pool_addresses = sorted({pa for per_pool in block_pools.values() for pa in per_pool})
    for i, pa in enumerate(pool_addresses):
        color = _CHART_SERIES_COLORS[i % len(_CHART_SERIES_COLORS)]
        datasets.append({
            "label": _address_display_label(pa, address_labels),
            "data": [
                block_pools.get(block, {}).get(pa, {}).get("value", 0.0)
                for block in labels
            ],
            "borderColor": color,
            "backgroundColor": color + "33",
            "borderWidth": 1.5,
            "borderDash": _CHART_LINE_DASHES[i % len(_CHART_LINE_DASHES)],
            "fill": False,
            "tension": 0.2,
            "pointRadius": 0,
            "spanGaps": True,
        })

    return {
        "type": "line",
        "data": {"labels": display_labels, "datasets": datasets},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "interaction": {"intersect": False, "mode": "index"},
            "plugins": {
                "legend": {"labels": {"color": "#94a3b8"}, "position": "top"}
            },
            "scales": {
                "y": {
                    "beginAtZero": True,
                    "ticks": {"color": "#64748b"},
                    "grid": {"color": "#1e293b"},
                },
                "x": {
                    "ticks": {"color": "#64748b", "maxRotation": 45},
                    "grid": {"display": False},
                },
            },
        },
    }


def _find_volume_bucket(
    timeline: list,
    bucket_seconds: int,
    ts: int,
) -> Optional[dict]:
    """Return the volume bucket covering ts, or the nearest earlier bucket."""
    if not timeline or ts <= 0:
        return None
    best = None
    best_ts = -1
    for bucket in timeline:
        try:
            bts = int(bucket.get("bucket_ts") or 0)
        except (TypeError, ValueError):
            continue
        if bts <= ts and bts >= best_ts:
            # Prefer covering bucket when bucket_seconds known
            if bucket_seconds > 0 and ts < bts + bucket_seconds:
                return bucket
            best = bucket
            best_ts = bts
    return best


def _build_tvl_details_data(
    tvl_data: list,
    volume_metrics: Optional[dict],
    token_decimals: int = 18,
    address_labels: Optional[dict[str, str]] = None,
) -> list:
    """Build per-time-point pool details for the TVL chart click handler."""
    if not tvl_data:
        return []
    labels, total_values, block_pools, use_usd = _tvl_series(tvl_data, token_decimals)
    timeline = (volume_metrics or {}).get("volume_timeline") or []
    bucket_seconds = int((volume_metrics or {}).get("bucket_seconds") or 3600)
    details = []
    scale = 10 ** max(0, int(token_decimals or 18))

    for idx, block in enumerate(labels):
        per_pool = block_pools.get(block) or {}
        total = total_values[idx] if idx < len(total_values) else 0.0
        entry_timestamps = [
            _entry_ts(info.get("entry") or {}) for info in per_pool.values()
        ]
        ts = max((value for value in entry_timestamps if value > 0), default=0)
        if not ts:
            try:
                ts = int(block) if int(block) > 1_000_000_000 else 0
            except (TypeError, ValueError):
                ts = 0
        bucket = _find_volume_bucket(timeline, bucket_seconds, ts) if ts else None
        bucket_pools = (bucket or {}).get("pools") or {}

        pools = []
        for pa, info in sorted(
            per_pool.items(), key=lambda x: -float(x[1].get("value") or 0)
        ):
            entry = info.get("entry") or {}
            value = float(info.get("value") or 0)
            pool_vol = bucket_pools.get(pa.lower()) or {}
            price_usd = entry.get("price_usd")
            tvl_token = value
            if use_usd:
                try:
                    bal = float(entry.get("balance_raw") or entry.get("tvl_in_token") or 0)
                    tvl_token = bal / scale
                except (TypeError, ValueError):
                    tvl_token = value
            pools.append({
                "address": pa,
                "label": _address_display_label(pa, address_labels),
                "protocol": "{} {}".format(
                    entry.get("protocol") or "", entry.get("version") or ""
                ).strip(),
                "tvl": tvl_token if use_usd else value,
                "share_pct": (value / total * 100) if total else None,
                "price_usd": price_usd if price_usd is not None else None,
                "volume_token": pool_vol.get("volume_in_token"),
                "volume_usd": pool_vol.get("volume_usd"),
            })

        volume_bucket_label = ""
        if bucket and bucket.get("bucket_ts"):
            volume_bucket_label = datetime.fromtimestamp(
                int(bucket["bucket_ts"]), tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")

        time_label = ""
        if ts:
            time_label = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )

        details.append({
            "block": block if not ts else time_label or block,
            "time_label": time_label,
            "total_tvl": total if not use_usd else total,
            "volume_bucket_label": volume_bucket_label,
            "pools": pools,
        })
    return details


def _build_price_chart_config(
    tvl_data: list,
    symbol: str = "TOKEN",
    address_labels: Optional[dict[str, str]] = None,
    bucket_seconds: int = 0,
) -> dict:
    by_pool: dict[str, list[dict]] = defaultdict(list)
    for t in tvl_data:
        price_usd = t.get("price_usd") or 0
        if price_usd > 0:
            by_pool[t.get("pool_address") or "unknown"].append(t)

    if not by_pool:
        return _empty_line_config()

    labels = sorted({t["block_number"] for entries in by_pool.values() for t in entries})
    display_labels = [
        _chart_axis_label(block, bucket_seconds) for block in labels
    ]
    datasets = []
    for i, (pa, entries) in enumerate(sorted(by_pool.items())):
        vals_by_block = {t["block_number"]: t["price_usd"] for t in entries}
        color = _CHART_SERIES_COLORS[i % len(_CHART_SERIES_COLORS)]
        datasets.append({
            "label": _address_display_label(pa, address_labels),
            "data": [vals_by_block.get(b) for b in labels],
            "borderColor": color,
            "backgroundColor": color + "33",
            "borderWidth": 1.5,
            "borderDash": _CHART_LINE_DASHES[i % len(_CHART_LINE_DASHES)],
            "pointRadius": 0,
            "fill": False,
            "spanGaps": True,
            "tension": 0.2,
        })

    return {
        "type": "line",
        "data": {"labels": display_labels, "datasets": datasets},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "interaction": {"intersect": False, "mode": "index"},
            "plugins": {
                "legend": {"labels": {"color": "#94a3b8"}, "position": "top"}
            },
            "scales": {
                "y": {
                    "beginAtZero": True,
                    "ticks": {"color": "#64748b"},
                    "grid": {"color": "#1e293b"},
                },
                "x": {
                    "ticks": {"color": "#64748b", "maxRotation": 45},
                    "grid": {"display": False},
                },
            },
        },
    }


def _build_volume_chart_config(
    volume_metrics: dict,
    symbol: str = "TOKEN",
    address_labels: Optional[dict[str, str]] = None,
) -> dict:
    timeline = (volume_metrics or {}).get("volume_timeline", [])
    pool_ids = sorted((volume_metrics or {}).get("volume_by_pool", {}).keys())
    if not timeline or not pool_ids:
        return {
            "type": "bar",
            "data": {
                "labels": ["No Data"],
                "datasets": [{
                    "data": [0],
                    "backgroundColor": "#3b82f6",
                }],
            },
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "plugins": {"legend": {"display": False}},
                "scales": {
                    "y": {"ticks": {"color": "#64748b"}, "grid": {"color": "#1e293b"}},
                    "x": {"ticks": {"color": "#64748b"}, "grid": {"display": False}},
                },
            },
        }

    labels = []
    for bucket in timeline:
        ts = int(bucket.get("bucket_ts") or 0)
        if ts:
            labels.append(
                datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")
            )
        else:
            labels.append("0")

    datasets = []
    for i, pa in enumerate(pool_ids):
        color = _CHART_SERIES_COLORS[i % len(_CHART_SERIES_COLORS)]
        data = []
        for bucket in timeline:
            data.append(
                bucket.get("pools", {}).get(pa, {}).get("volume_in_token", 0)
            )
        datasets.append({
            "label": _address_display_label(pa, address_labels),
            "data": data,
            "backgroundColor": color,
            "borderColor": color,
            "borderWidth": 1,
            "stack": "volume",
        })

    return {
        "type": "bar",
        "data": {"labels": labels, "datasets": datasets},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "legend": {"labels": {"color": "#94a3b8"}, "position": "top"}
            },
            "scales": {
                "x": {
                    "stacked": True,
                    "ticks": {"color": "#64748b", "maxRotation": 45},
                    "grid": {"display": False},
                },
                "y": {
                    "stacked": True,
                    "beginAtZero": True,
                    "ticks": {"color": "#64748b"},
                    "grid": {"color": "#1e293b"},
                },
            },
        },
    }


def _short_pool_label(addr: str) -> str:
    if not addr:
        return "N/A"
    if len(addr) <= 14:
        return addr
    return addr[:8] + "..." + addr[-4:]


def _address_display_label(
    addr: Any, address_labels: Optional[dict[str, str]] = None
) -> str:
    full = str(addr or "")
    if not full:
        return "N/A"
    mapped = (address_labels or {}).get(full.lower())
    if mapped:
        return str(mapped)
    return _short_pool_label(full)


def _labeled_identifier_html(
    value: Any,
    *,
    chain_id: int = 1,
    address_labels: Optional[dict[str, str]] = None,
) -> str:
    full = str(value or "")
    label = (address_labels or {}).get(full.lower()) if full else None
    return _identifier_html(full, chain_id=chain_id, label=label)


def _short_addr(addr: str) -> str:
    if not addr:
        return "-"
    if len(addr) <= 12:
        return addr
    return addr[:8] + "..." + addr[-4:]


def _is_positive_balance(row: dict[str, Any]) -> bool:
    raw = row.get("balance_raw")
    if raw not in (None, ""):
        try:
            return int(raw) > 0
        except (TypeError, ValueError):
            pass
    try:
        return float(row.get("balance_decimal") or 0) > 0
    except (TypeError, ValueError):
        return False


def _rank_non_pool_holders(
    rows: list[dict[str, Any]], limit: int = 20
) -> list[dict[str, Any]]:
    """Return positive non-pool rows ranked by end balance, largest first."""
    candidates = [
        row
        for row in rows
        if not row.get("is_pool")
        and row.get("balance_source") != "zero_fill"
        and _is_positive_balance(row)
    ]

    def _end_balance(row: dict[str, Any]) -> float | int:
        raw = row.get("balance_raw")
        if raw not in (None, ""):
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
        try:
            return float(row.get("balance_decimal") or 0)
        except (TypeError, ValueError):
            return 0

    ranked = sorted(candidates, key=_end_balance, reverse=True)
    return ranked[:max(0, int(limit))]


def _holder_semantics(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Return explicit holder and balance-coverage counts for dashboard labels."""
    total_count = len(rows or [])
    zero_fill_count = sum(
        1 for row in rows or [] if row.get("balance_source") == "zero_fill"
    )
    positive_non_pool_count = sum(
        1
        for row in rows or []
        if not row.get("is_pool")
        and row.get("balance_source") != "zero_fill"
        and _is_positive_balance(row)
    )
    positive_pool_count = sum(
        1
        for row in rows or []
        if row.get("is_pool")
        and row.get("balance_source") != "zero_fill"
        and _is_positive_balance(row)
    )
    return {
        "total_count": total_count,
        "covered_count": max(0, total_count - zero_fill_count),
        "zero_fill_count": zero_fill_count,
        "positive_non_pool_count": positive_non_pool_count,
        "positive_pool_count": positive_pool_count,
    }


def _humanize_source(value: Any) -> str:
    text = str(value or "unknown").strip().replace("_", " ")
    if not text:
        return "Unknown"
    words = []
    for word in text.split():
        upper = word.upper()
        words.append(upper if upper in {"RPC", "DUNE"} else word.capitalize())
    return " ".join(words)


def _tvl_method_presentation(
    source: Any,
    rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Describe TVL according to its real lineage instead of a fixed caption."""
    normalized = str(source or "").strip().lower()
    if not normalized:
        row_sources = {
            str(row.get("source_event") or "").lower() for row in rows or []
        }
        if "balance_x_price" in row_sources:
            normalized = "dune_snapshot"
        elif rows:
            normalized = "event_accumulate"

    if normalized in {"dune_balance_local_price", "dune_snapshot"}:
        price_note = (
            "local swap-derived prices"
            if normalized == "dune_balance_local_price"
            else "available price observations"
        )
        return {
            "kind": "snapshot",
            "badge_html": (
                '<span class="method-badge method-snapshot">Balance snapshot</span>'
            ),
            "note": (
                "Balance-Snapshot TVL uses pool token balance snapshots × {}. "
                "Hourly views may carry a daily balance across intraday price buckets."
            ).format(price_note),
        }
    if normalized in {"event_accumulate", "event_accumulate_fallback"}:
        reason = (
            "The snapshot query failed, so "
            if normalized == "event_accumulate_fallback"
            else ""
        )
        return {
            "kind": "reconstructed",
            "badge_html": (
                '<span class="method-badge method-reconstructed">Event reconstructed</span>'
            ),
            "note": (
                "{}TVL is reconstructed by accumulating indexed liquidity events. "
                "Treat it as an activity-based proxy, not an on-chain balance snapshot."
            ).format(reason),
        }
    return {
        "kind": "unavailable",
        "badge_html": (
            '<span class="method-badge method-unavailable">Source unavailable</span>'
        ),
        "note": "No reliable TVL lineage is available for this output.",
    }


def _identifier_html(
    value: Any, *, chain_id: int = 1, label: Optional[str] = None
) -> str:
    """Render a compact, copyable identifier with an optional Etherscan link."""
    full = str(value or "")
    if not full:
        return _fmt_missing()
    safe_full = html.escape(full, quote=True)
    display = str(label).strip() if label not in (None, "") else _short_pool_label(full)
    safe_short = html.escape(display, quote=False)
    button = (
        '<button type="button" class="identifier-copy addr" '
        'data-identifier="{full}" aria-label="Copy full identifier {full}" '
        'onmouseenter="showIdentifierTooltip(this)" '
        'onmouseleave="hideIdentifierTooltip()" '
        'onfocus="showIdentifierTooltip(this)" '
        'onblur="hideIdentifierTooltip()" '
        'onclick="copyIdentifier(event,this)">{short}</button>'
    ).format(full=safe_full, short=safe_short)
    link = ""
    if int(chain_id or 0) == 1 and Web3.is_address(full):
        link = (
            '<a class="identifier-link" href="https://etherscan.io/address/{full}" '
            'target="_blank" rel="noopener noreferrer" title="Open in Etherscan" '
            'aria-label="Open {full} in Etherscan" '
            'onclick="event.stopPropagation()">&#8599;</a>'
        ).format(full=safe_full)
    return '<span class="identifier-wrap">{}{}</span>'.format(button, link)


def _fmt_missing() -> str:
    return '<span style="color:#64748b">—</span>'


def _fmt_usd(value) -> str:
    if value is None or value == "":
        return _fmt_missing()
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _fmt_missing()
    if abs(v) >= 1_000_000:
        return "$" + format(v / 1_000_000, ".2f") + "M"
    if abs(v) >= 1_000:
        return "$" + format(v / 1_000, ".1f") + "k"
    return "$" + format(v, ",.2f")


def _fmt_pct(value) -> str:
    if value is None or value == "":
        return _fmt_missing()
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _fmt_missing()
    return "{:.2f}%".format(v * 100)


def _fmt_net_bal(bal, symbol: str) -> str:
    if bal is None:
        return _fmt_missing()
    color = "#4ade80" if bal >= 0 else "#f87171"
    return '<span style="color:{}">{}</span>'.format(
        color, _fmt_bal(bal, symbol)
    )


def _has_snapshot(h: dict) -> bool:
    return (h.get("balance_source") or "") in ("dune_historical", "rpc")


def _table_wallet_movers(
    swaps: list,
    holdings: list,
    target_token: str,
    token_decimals: int,
    symbol: str,
    top_n: int = 20,
    chain_id: int = 1,
    address_labels: Optional[dict[str, str]] = None,
) -> str:
    target = (target_token or "").lower()
    if not target:
        return ""
    scale = 10 ** max(0, int(token_decimals or 18))
    stats: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"bought": 0.0, "sold": 0.0, "net": 0.0, "tx": 0}
    )

    for e in swaps:
        if (e.get("event_type") or "").upper() != "SWAP":
            continue
        t0 = (e.get("token0_address") or "").lower()
        t1 = (e.get("token1_address") or "").lower()
        try:
            a0 = abs(int(e.get("token0_amount", "0") or "0"))
            a1 = abs(int(e.get("token1_amount", "0") or "0"))
        except (TypeError, ValueError):
            continue
        if target == t0:
            amount = a0 / scale
            net_delta = -amount
        elif target == t1:
            amount = a1 / scale
            net_delta = amount
        else:
            continue
        addr = (e.get("actor") or e.get("recipient") or "").lower()
        if not addr:
            continue
        s = stats[addr]
        s["bought"] = float(s["bought"]) + max(net_delta, 0.0)
        s["sold"] = float(s["sold"]) + max(-net_delta, 0.0)
        s["net"] = float(s["net"]) + net_delta
        s["tx"] = int(s["tx"]) + 1

    holdings_by_addr: dict[str, dict] = {}
    for h in holdings or []:
        addr = (h.get("address") or "").lower()
        if addr:
            holdings_by_addr[addr] = h

    # Seed snapshot-backed holders so transfer-only movers also appear.
    for addr, h in holdings_by_addr.items():
        if _has_snapshot(h) and not h.get("is_pool"):
            stats.setdefault(addr, {"bought": 0.0, "sold": 0.0, "net": 0.0, "tx": 0})

    # Wallet-level view: drop pool addresses that slipped in via swap actors.
    stats = {
        addr: s for addr, s in stats.items()
        if not (holdings_by_addr.get(addr) or {}).get("is_pool")
    }

    def _num(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _sort_key(item):
        addr, s = item
        h = holdings_by_addr.get(addr) or {}
        h_net = _num(h.get("net_change_decimal"))
        activity = float(s["bought"]) + float(s["sold"])
        if h_net is not None:
            return (-abs(h_net), -activity)
        return (-activity, -int(s["tx"]))

    rows = []
    for i, (addr, s) in enumerate(
        sorted(stats.items(), key=_sort_key)[:top_n],
        1,
    ):
        h = holdings_by_addr.get(addr) or {}
        h_net = _num(h.get("net_change_decimal"))
        peak = (
            _num(h.get("peak_balance_decimal"))
            if _has_snapshot(h) else None
        )
        source_html = (
            '<span class="badge-dex-other">snapshot</span>'
            if h_net is not None
            else '<span class="dex-muted">swap</span>'
        )
        rows.append(
            "<tr>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "</tr>".format(
                i,
                _labeled_identifier_html(
                    addr, chain_id=chain_id, address_labels=address_labels
                ),
                _fmt_bal(float(s["bought"]), symbol),
                _fmt_bal(float(s["sold"]), symbol),
                _fmt_bal(float(s["net"]), symbol),
                _fmt_net_bal(h_net, symbol),
                _fmt_bal(peak, symbol) if peak is not None else _fmt_missing(),
                source_html,
                int(s["tx"]),
            )
        )
    return "\n".join(rows)


def _table_large_wallets(
    metrics: dict,
    symbol: str,
    top_n: int = 25,
    chain_id: int = 1,
    address_labels: Optional[dict[str, str]] = None,
) -> str:
    """Render notable-wallet rows from metrics.wallet_activity."""
    activity = metrics.get("wallet_activity") or {}
    wallets = [w for w in activity.get("wallets") or [] if w.get("notable")][:top_n]
    if not wallets:
        return ""
    rows = []
    modes = activity.get("threshold_modes") or {}
    percentile_label = activity.get("adaptive_percentile_label") or "P99"
    for i, w in enumerate(wallets, 1):
        flags = []
        trade_th = activity.get("large_trade_threshold_usd")
        mover_th = activity.get("mover_net_usd_threshold")
        activity_th = activity.get("activity_trade_threshold")
        if w.get("large_trade"):
            flags.append(
                "Trade {}".format(percentile_label)
                if modes.get("trade") == "percentile"
                else (
                    "Trade ${}k+".format(int(trade_th) // 1000)
                    if trade_th else "Trade"
                )
            )
        if w.get("large_mover"):
            flags.append(
                "Mover {}".format(percentile_label)
                if modes.get("mover") == "percentile"
                else (
                    "Mover ${}k+".format(int(mover_th) // 1000)
                    if mover_th else "Mover"
                )
            )
        if w.get("high_activity"):
            flags.append(
                "Activity {}".format(percentile_label)
                if modes.get("activity") == "percentile"
                else (
                    "Frequent {}tx+".format(int(activity_th))
                    if activity_th else "Frequent"
                )
            )
        if w.get("market_share"):
            flags.append(
                "Volume {}".format(percentile_label)
                if modes.get("volume") == "percentile"
                else "Share"
            )
        flag_html = '<span class="badge-dex-other">{}</span>'.format(
            " / ".join(flags)
        )
        rows.append(
            "<tr>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "</tr>".format(
                i,
                _labeled_identifier_html(
                    w.get("address", ""),
                    chain_id=chain_id,
                    address_labels=address_labels,
                ),
                _fmt_usd(w.get("max_single_usd")),
                _fmt_usd(w.get("bought_usd")),
                _fmt_usd(w.get("sold_usd")),
                _fmt_usd(w.get("net_usd")),
                _fmt_usd(w.get("total_usd")),
                "{:.3%}".format(float(w.get("volume_share_pct") or 0) / 100.0),
                int(w.get("swap_count") or 0),
                flag_html,
            )
        )
    return "\n".join(rows)


def _refresh_withdrawal_metrics(
    metrics: dict,
    liquidity_events: list[dict],
    verified_pools: list[dict],
    target_token: str,
    token_decimals: int,
    pool_concentration: dict,
    timeline: list[dict],
) -> dict:
    """Reapply current withdrawal semantics to old Parquet/JSON output locally."""
    removals = [
        row for row in liquidity_events
        if str(row.get("event_type") or "").upper() == "LIQUIDITY_REMOVE"
    ]
    if not removals or not verified_pools or not target_token:
        return metrics

    # Preserve the incident/window scope recorded in the existing metrics.  Old
    # output can otherwise contain canonical rows beyond the selected incident.
    old_events = (
        metrics.get("withdrawal_severity", {}).get("withdrawal_events", []) or []
    )
    scope_keys = {
        (
            int(row.get("block_number", row.get("block", 0)) or 0),
            str(row.get("pool", row.get("pool_address", "")) or "").lower(),
        )
        for row in old_events
    }
    if scope_keys:
        scoped = [
            row for row in removals
            if (
                int(row.get("block_number") or 0),
                str(row.get("pool_address") or "").lower(),
            ) in scope_keys
        ]
        if scoped:
            removals = scoped

    allowed = set(VerifiedPool.__dataclass_fields__)
    pool_models = [
        VerifiedPool(**{key: value for key, value in row.items() if key in allowed})
        for row in verified_pools
        if row.get("verified", True)
    ]
    refreshed = calculate_withdrawal_severity(
        removals,
        pre_event_tvl=int(pool_concentration.get("total_tvl") or 0),
        incident_block=0,
        verified_pools=pool_models,
        target_token=target_token,
        token_decimals=token_decimals,
        tvl_by_pool=pool_concentration.get("per_pool_tvl") or {},
        timeline=timeline,
    )
    result = dict(metrics)
    result["withdrawal_severity"] = refreshed
    return result


def _withdrawal_quantification_note(metrics: dict) -> str:
    severity = metrics.get("withdrawal_severity", {}) or {}
    total = int(severity.get("num_withdrawals") or 0)
    quantified = int(severity.get("quantified_withdrawals") or 0)
    delta_only = int(severity.get("liquidity_delta_only_withdrawals") or 0)
    unmapped = int(severity.get("unmapped_withdrawals") or 0)
    if total <= 0:
        return ""
    detail = (
        "Amount known: {:,} · Amount missing: {:,} · Pool mapping failed: {:,}."
    ).format(quantified, delta_only, unmapped)
    explanation = (
        "For the {:,} missing-amount actions, the V4 query returned a negative "
        "raw liquidity change but no token0/token1 amounts. Removed token, USD, "
        "and TVL share therefore cannot be calculated. This is missing data—not "
        "a zero withdrawal.".format(delta_only)
        if delta_only else
        "Every detected action in this window includes token amounts."
    )
    return (
        '<div class="coverage-note"><strong>{:,} removal actions detected</strong>'
        "{} {}</div>"
    ).format(total, detail, explanation)


def _table_withdrawal_summary(
    metrics: dict,
    symbol: str,
    chain_id: int = 1,
    address_labels: Optional[dict[str, str]] = None,
) -> str:
    """Render a per-pool withdrawal summary table."""
    rows = metrics.get("withdrawal_severity", {}).get("per_pool_removals", []) or []
    if not rows:
        return ""
    table_rows = []
    for r in rows:
        table_rows.append(
            "<tr>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "</tr>".format(
                _labeled_identifier_html(
                    r.get("pool_address", ""),
                    chain_id=chain_id,
                    address_labels=address_labels,
                ),
                int(r.get("num_withdrawals") or 0),
                _fmt_bal(float(r.get("removed_target_decimal") or 0), symbol),
                _fmt_usd(r.get("removed_usd")),
                _fmt_pct(r.get("pool_tvl_share")),
                ("{} {}".format(r.get("protocol", ""), r.get("version", ""))).strip() or "-",
            )
        )
    return (
        '<div class="scroll"><table><thead><tr><th>Pool</th><th>Events</th>'
        "<th>Removed ({})</th><th>Est. USD</th><th>% Pool TVL</th>"
        "<th>Protocol</th></tr></thead><tbody>{}</tbody></table></div>"
    ).format(symbol, "\n".join(table_rows))


def _table_withdrawals(
    metrics: dict,
    token_decimals: int,
    symbol: str,
    top_n: int = 20,
    chain_id: int = 1,
    address_labels: Optional[dict[str, str]] = None,
) -> str:
    events = metrics.get("withdrawal_severity", {}).get("withdrawal_events", []) or []
    if not events:
        return (
            '<tr><td colspan="9" style="text-align:center;padding:24px;color:#64748b">'
            "No liquidity removal events in this window.</td></tr>"
        )
    events = events[:top_n]
    rows = []
    for e in events:
        status = str(e.get("quantification_status") or "").lower()
        removed_decimal = e.get("removed_target_decimal")
        if status not in {"quantified", "liquidity_delta_only", "unmapped"}:
            status = "quantified" if removed_decimal is not None else "unmapped"
        if status == "quantified" and removed_decimal is not None:
            removed_html = _fmt_bal(float(removed_decimal), symbol)
        elif status == "liquidity_delta_only":
            removed_html = (
                '<span class="amount-missing" title="Removal detected; this query did not return token0/token1 amounts">'
                "Token amount not returned</span>"
            )
        else:
            removed_html = (
                '<span class="amount-missing" title="The event could not be mapped to the target-token side">'
                "Pool/token mapping failed</span>"
            )
        if status == "quantified":
            usd_html = _fmt_usd(e.get("removed_usd"))
            share_html = _fmt_pct(e.get("pool_tvl_share"))
        else:
            unavailable = (
                '<span class="cannot-calculate" '
                'title="A token amount is required for this calculation">'
                "Cannot calculate</span>"
            )
            usd_html = unavailable
            share_html = unavailable
        actor = e.get("actor", "")
        actor_or_scope = (
            "Pool/block aggregate"
            if e.get("aggregation_scope") == "pool_block"
            else _labeled_identifier_html(
                actor, chain_id=chain_id, address_labels=address_labels
            )
        )
        delta_raw = str(e.get("liquidity_delta") or "0")
        try:
            delta_display = "{:,}".format(int(delta_raw))
        except (TypeError, ValueError):
            delta_display = html.escape(delta_raw) or "-"
        delta_html = '<span title="{}">{}</span>'.format(
            html.escape(delta_raw, quote=True), delta_display
        )
        rows.append(
            "<tr>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "<td>{}</td>"
            "</tr>".format(
                int(e.get("block_number") or 0),
                _labeled_identifier_html(
                    e.get("pool", e.get("pool_address", "")),
                    chain_id=chain_id,
                    address_labels=address_labels,
                ),
                int(e.get("event_count") or 1),
                actor_or_scope,
                delta_html,
                removed_html,
                usd_html,
                share_html,
                ("{} {}".format(e.get("protocol", ""), e.get("version", ""))).strip() or "-",
            )
        )
    return "\n".join(rows)


def _table_top_holders(
    holders: list,
    symbol: str,
    chain_id: int = 1,
    address_labels: Optional[dict[str, str]] = None,
) -> str:
    if not holders:
        return (
            '<tr><td colspan="10" style="text-align:center;padding:24px;color:#64748b">'
            "No holder data available</td></tr>"
        )
    rows = []
    for i, h in enumerate(holders[:20], 1):
        addr = h.get("address", "")
        banner = (
            h.get("address_type", "eoa")
            if h.get("address_type")
            else ("pool" if h.get("is_pool") else "eoa")
        )
        dex_html = _dex_badges_html(
            h.get("dex_protocols") or [], h.get("dex_roles") or {}
        )
        start = h.get("balance_start_decimal")
        net = h.get("net_change_decimal")
        peak = h.get("peak_balance_decimal")
        has_snapshot = _has_snapshot(h)
        rows.append(
            f'<tr class="holder-row" onclick="togglePortfolio(\'{addr}\')" data-owner="{addr}">'
            f"<td>{i}</td>"
            f'<td>{_labeled_identifier_html(addr, chain_id=chain_id, address_labels=address_labels)}</td>'
            f'<td><span class="badge-{banner}">{banner}</span></td>'
            f"<td>{dex_html}</td>"
            f"<td>{_fmt_bal(h.get('balance_decimal', 0), symbol)}</td>"
            f"<td>{_fmt_bal(start, symbol) if has_snapshot and start is not None else _fmt_missing()}</td>"
            f"<td>{_fmt_net_bal(net if has_snapshot else None, symbol)}</td>"
            f"<td>{_fmt_bal(peak, symbol) if has_snapshot and peak is not None else _fmt_missing()}</td>"
            f"<td>{h.get('tx_count', 0)}</td>"
            f'<td><span class="expand-icon">+</span></td></tr>'
            f'<tr class="portfolio-row" id="portfolio-{addr}" style="display:none">'
            f'<td colspan="10"><div class="portfolio-inner">Loading...</div></td></tr>'
        )
    return "\n".join(rows)


def _dex_badges_html(protocols: list, roles: dict) -> str:
    if not protocols:
        return '<span class="dex-muted">—</span>'
    parts = []
    for p in protocols:
        key = (p or "").lower()
        css = "badge-dex-other"
        if key == "uniswap":
            css = "badge-uniswap"
        elif key == "curve":
            css = "badge-curve"
        elif key == "balancer":
            css = "badge-balancer"
        role_bits = []
        r = roles.get(key) or {}
        if r.get("lp"):
            role_bits.append("LP")
        if r.get("swap"):
            role_bits.append("Swap")
        label = p.title() if p else "DEX"
        title = "+".join(role_bits) if role_bits else "related"
        parts.append(
            f'<span class="{css}" title="{title}">{label}</span>'
        )
    return "".join(parts)


def _pool_meta_lookup(verified_pools: list) -> dict[str, dict[str, str]]:
    """Map pool_address / custody / pool_id → protocol+version."""
    out: dict[str, dict[str, str]] = {}
    for p in verified_pools or []:
        if isinstance(p, dict):
            protocol = (p.get("protocol") or "").lower()
            version = (p.get("version") or "").lower()
            keys = [
                p.get("pool_address"),
                p.get("custody_address"),
                p.get("pool_id"),
            ]
        else:
            protocol = (getattr(p, "protocol", "") or "").lower()
            version = (getattr(p, "version", "") or "").lower()
            keys = [
                getattr(p, "pool_address", None),
                getattr(p, "custody_address", None),
                getattr(p, "pool_id", None),
            ]
        meta = {"protocol": _canon_protocol(protocol), "version": version}
        for k in keys:
            if k:
                out[str(k).lower()] = meta
    return out


def _canon_protocol(name: str) -> str:
    n = (name or "").lower().strip()
    if n.startswith("uni"):
        return "uniswap"
    if n.startswith("curve"):
        return "curve"
    if n.startswith("bal"):
        return "balancer"
    return n


def _guess_protocol_from_method(method: Optional[str]) -> str:
    m = (method or "").lower()
    if "v4" in m or "v3" in m or "v2" in m or "v1" in m:
        return "uniswap"
    return ""


def _guess_version_from_method(method: Optional[str]) -> str:
    m = (method or "").lower()
    for v in ("v4", "v3", "v2", "v1"):
        if v in m:
            return v
    return ""


def _build_address_dex_map(
    pool_meta: dict[str, dict[str, str]],
    positions: list,
    events: list,
) -> dict[str, dict[str, Any]]:
    """Infer which DEX venues an address touched in the indexed window.

    Signals (strong → weaker):
      1. LP position owners
      2. Swap / liquidity event actor|recipient
      3. TOKEN_TRANSFER directly to/from a known pool or custody address
      4. TOKEN_TRANSFER counterparties in the same tx as a DEX pool event
         (catches router-mediated swaps where the user is not the Swap actor)
    """
    lp: dict[str, set[str]] = defaultdict(set)
    swap: dict[str, set[str]] = defaultdict(set)
    venue_addrs = {
        a for a, meta in (pool_meta or {}).items()
        if a.startswith("0x") and len(a) == 42 and meta.get("protocol")
    }

    for pos in positions or []:
        owner = (pos.get("owner") or "").lower()
        if not owner:
            continue
        meta = pool_meta.get((pos.get("pool_address") or "").lower(), {})
        proto = meta.get("protocol") or _guess_protocol_from_method(
            pos.get("resolution_method")
        )
        if proto:
            lp[owner].add(proto)

    by_tx: dict[str, list] = defaultdict(list)
    for evt in events or []:
        txh = evt.get("transaction_hash") or ""
        if txh:
            by_tx[txh].append(evt)

        et = (evt.get("event_type") or "").upper()
        proto = _canon_protocol(evt.get("protocol") or "")
        if not proto:
            meta = pool_meta.get((evt.get("pool_address") or "").lower(), {})
            proto = meta.get("protocol") or ""

        if et in ("SWAP", "LIQUIDITY_ADD", "LIQUIDITY_REMOVE", "MINT", "BURN", "COLLECT_FEES"):
            if not proto:
                continue
            for key in ("actor", "recipient", "owner"):
                addr = (evt.get(key) or "").lower()
                if addr and addr.startswith("0x") and len(addr) == 42:
                    if et in ("LIQUIDITY_ADD", "LIQUIDITY_REMOVE", "MINT", "BURN"):
                        lp[addr].add(proto)
                    else:
                        swap[addr].add(proto)

        elif et == "TOKEN_TRANSFER":
            fr = (evt.get("actor") or "").lower()
            to = (evt.get("recipient") or "").lower()
            if fr in venue_addrs:
                p = pool_meta[fr].get("protocol") or ""
                if p and to.startswith("0x") and len(to) == 42 and to not in venue_addrs:
                    swap[to].add(p)
            if to in venue_addrs:
                p = pool_meta[to].get("protocol") or ""
                if p and fr.startswith("0x") and len(fr) == 42 and fr not in venue_addrs:
                    swap[fr].add(p)

    # Same-tx linkage: user Transfer in a tx that also hits a DEX pool event
    for evs in by_tx.values():
        dex_protos: set[str] = set()
        for e in evs:
            et = (e.get("event_type") or "").upper()
            if et not in (
                "SWAP",
                "LIQUIDITY_ADD",
                "LIQUIDITY_REMOVE",
                "MINT",
                "BURN",
                "COLLECT_FEES",
            ):
                continue
            proto = _canon_protocol(e.get("protocol") or "")
            if not proto:
                meta = pool_meta.get((e.get("pool_address") or "").lower(), {})
                proto = meta.get("protocol") or ""
            if proto:
                dex_protos.add(proto)
        if not dex_protos:
            continue
        for e in evs:
            if (e.get("event_type") or "").upper() != "TOKEN_TRANSFER":
                continue
            for key in ("actor", "recipient"):
                addr = (e.get(key) or "").lower()
                if (
                    addr
                    and addr.startswith("0x")
                    and len(addr) == 42
                    and addr not in venue_addrs
                ):
                    for p in dex_protos:
                        swap[addr].add(p)

    out: dict[str, dict[str, Any]] = {}
    addrs = set(lp) | set(swap)
    for addr in addrs:
        protocols = sorted(lp.get(addr, set()) | swap.get(addr, set()))
        roles = {}
        for p in protocols:
            roles[p] = {
                "lp": p in lp.get(addr, set()),
                "swap": p in swap.get(addr, set()),
            }
        out[addr] = {"protocols": protocols, "roles": roles}
    return out


def _table_pool_holders(holders: list, symbol: str, chain_id: int = 1) -> str:
    rows = []
    for h in holders:
        rows.append(
            f"<tr><td>{_identifier_html(h.get('address', ''), chain_id=chain_id)}</td>"
            f"<td>{h.get('pool_label','')}</td>"
            f"<td>{_fmt_bal(h.get('balance_decimal',0),symbol)}</td>"
            f"<td><span class=\"plabel\">POOL</span></td></tr>"
        )
    return "\n".join(rows)


def _pool_custody_map(verified_pools: Optional[list] = None) -> dict[str, str]:
    """Map pool_address / poolId → custody address used for token reserves."""
    out: dict[str, str] = {}
    for pool in verified_pools or []:
        if isinstance(pool, dict):
            pool_addr = (pool.get("pool_address") or "").lower()
            custody = (pool.get("custody_address") or pool_addr).lower()
        else:
            pool_addr = (getattr(pool, "pool_address", None) or "").lower()
            custody = (getattr(pool, "custody_address", None) or pool_addr).lower()
        if pool_addr:
            out[pool_addr] = custody or pool_addr
    return out


def _observed_token_reserves(
    pools: list,
    pool_holders: Optional[list] = None,
    verified_pools: Optional[list] = None,
) -> tuple[dict[str, float], dict[str, str], float]:
    """Resolve per-pool observed target-token reserves and unique-custody total.

    Returns (reserve_by_pool, custody_by_pool, total_unique_custody_reserve).
    Share uses unique custody addresses so V4 PoolManager balances are not
    double-counted across multiple poolIds.
    """
    holder_bal = {
        (row.get("address") or "").lower(): float(row.get("balance_decimal") or 0)
        for row in (pool_holders or [])
        if (row.get("address") or "")
    }
    custody_by_pool = _pool_custody_map(verified_pools)
    reserve_by_pool: dict[str, float] = {}
    custody_reserve: dict[str, float] = {}

    for pool in pools:
        pool_addr = (pool.get("pool_address") or "").lower()
        if not pool_addr:
            continue
        custody = custody_by_pool.get(pool_addr, pool_addr)
        custody_by_pool[pool_addr] = custody
        from_ident = float(pool.get("balance_decimal") or 0)
        reserve = from_ident
        if reserve <= 0:
            reserve = float(holder_bal.get(pool_addr) or 0)
        if reserve <= 0:
            reserve = float(holder_bal.get(custody) or 0)
        reserve_by_pool[pool_addr] = reserve
        if custody not in custody_reserve or reserve > custody_reserve[custody]:
            preferred = float(holder_bal.get(custody) or 0)
            custody_reserve[custody] = preferred if preferred > 0 else reserve

    total = sum(value for value in custody_reserve.values() if value > 0)
    return reserve_by_pool, custody_by_pool, total


def _pool_liquidity_presentation(pools: list, metrics: dict) -> dict[str, str]:
    """Describe the denominator and coverage behind per-pool TVL shares."""
    pool_conc = metrics.get("pool_concentration", {}) or {}
    measured_ids = {
        str(pool_id).lower()
        for pool_id, value in (pool_conc.get("per_pool_tvl") or {}).items()
        if int(value or 0) > 0
    }
    verified_count = len(pools)
    measured_count = sum(
        1
        for pool in pools
        if str(pool.get("pool_address") or "").lower() in measured_ids
    )
    coverage_pct = (
        measured_count / verified_count * 100 if verified_count else 0.0
    )
    partial = measured_count < verified_count
    prefix = "Partial coverage" if partial else "Coverage"
    coverage_title = (
        "{} · {} of {} verified pools measured ({:.1f}%)".format(
            prefix, measured_count, verified_count, coverage_pct
        )
        if verified_count
        else "Coverage unavailable · no verified pools"
    )

    missing_v4 = sum(
        1
        for pool in pools
        if str(pool.get("version") or "").lower() == "v4"
        and str(pool.get("pool_address") or "").lower() not in measured_ids
    )
    comparison_note = (
        "The percentages below compare only the {} measured pool{}; "
        "they do not represent all {} verified pools.".format(
            measured_count, "" if measured_count == 1 else "s", verified_count
        )
        if partial
        else "The percentages below compare all verified pools."
    )
    if missing_v4:
        comparison_note += (
            " The {} V4 pool{} {} not included because V4 Pool IDs share a "
            "PoolManager and currently have no reliable per-pool liquidity measurement."
        ).format(
            missing_v4,
            "" if missing_v4 == 1 else "s",
            "is" if missing_v4 == 1 else "are",
        )

    source = str(pool_conc.get("source") or "none")
    if source == "onchain":
        method = "End-block on-chain estimate"
    elif source == "timeline":
        method = "Timeline-derived estimate"
    else:
        method = "No comparable per-pool liquidity estimate"
    snapshot_block = pool_conc.get("snapshot_block")
    if snapshot_block not in (None, ""):
        try:
            method += " · Block {:,}".format(int(snapshot_block))
        except (TypeError, ValueError):
            method += " · Block {}".format(snapshot_block)
    method_note = (
        method
        + ". Estimated pool liquidity is expressed in target-token units, not USD. "
        + "“Not measured” does not mean zero liquidity. "
        + "Observed Token Reserve is the target-token balance at the pool or "
        + "custody address (not LP count or full USD TVL); V4 may use a shared "
        + "PoolManager balance."
    )
    return {
        "coverage_title": coverage_title,
        "comparison_note": comparison_note,
        "method_note": method_note,
        "share_header": "Share Among Measured Pools ({}/{})".format(
            measured_count, verified_count
        ),
    }


def _known_token_symbols() -> dict[str, str]:
    return {
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
        "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
        "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
        "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",
        "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee": "ETH",
    }


def _decode_maybe_bytes32_symbol(raw: Any) -> str:
    if isinstance(raw, (bytes, bytearray)):
        text = bytes(raw).split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        return text.strip()
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _fetch_erc20_symbol(w3: Any, address: str) -> str:
    checksum = Web3.to_checksum_address(address)
    string_abi = [
        {
            "constant": True,
            "inputs": [],
            "name": "symbol",
            "outputs": [{"name": "", "type": "string"}],
            "type": "function",
        }
    ]
    bytes_abi = [
        {
            "constant": True,
            "inputs": [],
            "name": "symbol",
            "outputs": [{"name": "", "type": "bytes32"}],
            "type": "function",
        }
    ]
    try:
        contract = w3.eth.contract(address=checksum, abi=string_abi)
        return _decode_maybe_bytes32_symbol(contract.functions.symbol().call())
    except Exception:
        pass
    try:
        contract = w3.eth.contract(address=checksum, abi=bytes_abi)
        return _decode_maybe_bytes32_symbol(contract.functions.symbol().call())
    except Exception:
        return ""


def _resolve_token_symbol_map(
    pools: list,
    *,
    target_address: str = "",
    target_symbol: str = "",
    rpc_url: str = "",
) -> dict[str, str]:
    """Map token addresses → symbols for pool pair labels."""
    symbols = dict(_known_token_symbols())
    target = (target_address or "").lower()
    if target and target_symbol:
        symbols[target] = str(target_symbol)

    addresses: list[str] = []
    seen: set[str] = set()
    for pool in pools or []:
        for key in ("token0", "token1"):
            addr = (pool.get(key) or "").lower()
            if addr.startswith("0x") and addr not in seen:
                seen.add(addr)
                addresses.append(addr)

    missing = [addr for addr in addresses if addr not in symbols]
    if not missing:
        return symbols

    url = (rpc_url or os.environ.get("ETH_RPC_URL") or os.environ.get("RPC_URL") or "").strip()
    if not url:
        return symbols
    try:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
        for addr in missing:
            if not Web3.is_address(addr):
                continue
            sym = _fetch_erc20_symbol(w3, addr)
            if sym:
                symbols[addr] = sym
    except Exception:
        return symbols
    return symbols


def _token_pair_text(
    token0: str,
    token1: str,
    token_symbols: Optional[dict[str, str]] = None,
) -> str:
    symbols = token_symbols or {}
    t0 = (token0 or "").lower()
    t1 = (token1 or "").lower()
    sym0 = symbols.get(t0) or _short_pool_label(token0)
    sym1 = symbols.get(t1) or _short_pool_label(token1)
    return "{}/{}".format(sym0, sym1)


def _build_address_display_labels(
    pools: list,
    *,
    token_symbols: Optional[dict[str, str]] = None,
    verified_pools: Optional[list] = None,
) -> dict[str, str]:
    """Map token + pool addresses to human labels (symbols / pair names)."""
    labels: dict[str, str] = {}
    symbols = dict(token_symbols or {})
    for addr, sym in symbols.items():
        if addr and sym:
            labels[str(addr).lower()] = str(sym)

    rows = list(pools or [])
    for pool in verified_pools or []:
        if isinstance(pool, dict):
            rows.append(pool)
        else:
            rows.append(
                {
                    "pool_address": getattr(pool, "pool_address", ""),
                    "protocol": getattr(pool, "protocol", ""),
                    "version": getattr(pool, "version", ""),
                    "token0": getattr(pool, "token0", ""),
                    "token1": getattr(pool, "token1", ""),
                    "custody_address": getattr(pool, "custody_address", ""),
                }
            )

    for pool in rows:
        if not isinstance(pool, dict):
            continue
        pool_addr = (pool.get("pool_address") or "").lower()
        if not pool_addr:
            continue
        pair = _token_pair_text(
            pool.get("token0", ""), pool.get("token1", ""), symbols
        )
        proto = "{} {}".format(
            pool.get("protocol", "") or "", pool.get("version", "") or ""
        ).strip()
        label = "{} · {}".format(proto, pair) if proto else pair
        # Prefer the first non-empty label; keep existing if already set.
        labels.setdefault(pool_addr, label)
        custody = (pool.get("custody_address") or "").lower()
        # Only label shared custody when it equals the pool address (V2/V3).
        # V4 PoolManager stays unlabeled as a pair to avoid multi-pool ambiguity.
        if custody and custody == pool_addr:
            labels.setdefault(custody, label)
    return labels


def _token_pair_html(
    token0: str,
    token1: str,
    token_symbols: Optional[dict[str, str]] = None,
    chain_id: int = 1,
) -> str:
    symbols = token_symbols or {}
    t0 = (token0 or "").lower()
    t1 = (token1 or "").lower()
    label0 = symbols.get(t0) or None
    label1 = symbols.get(t1) or None
    left = _identifier_html(token0, chain_id=chain_id, label=label0)
    right = _identifier_html(token1, chain_id=chain_id, label=label1)
    return (
        '<span class="token-pair">'
        f"{left}<span class=\"pair-sep\">/</span>{right}"
        "</span>"
    )


def _table_pool_ident(
    pools: list,
    metrics: dict,
    token_decimals: int = 18,
    symbol: str = "TOKEN",
    chain_id: int = 1,
    pool_holders: Optional[list] = None,
    verified_pools: Optional[list] = None,
    token_symbols: Optional[dict[str, str]] = None,
    address_labels: Optional[dict[str, str]] = None,
) -> tuple[str, list[dict[str, Any]]]:
    pool_conc = metrics.get("pool_concentration", {})
    per_pool_tvl = pool_conc.get("per_pool_tvl", {}) or {}
    volume_by_pool = metrics.get("volume", {}).get("volume_by_pool", {}) or {}
    total_tvl = float(pool_conc.get("total_tvl", 0) or 0)
    total_volume = float(metrics.get("volume", {}).get("total_volume_in_token", 0) or 0)
    tvl_lookup = {str(k).lower(): v for k, v in per_pool_tvl.items()}
    vol_lookup = {str(k).lower(): v for k, v in volume_by_pool.items()}
    scale = 10 ** max(0, int(token_decimals or 18))
    reserve_by_pool, custody_by_pool, total_reserve = _observed_token_reserves(
        pools, pool_holders=pool_holders, verified_pools=verified_pools
    )
    custody_counts: dict[str, int] = defaultdict(int)
    for pool in pools:
        pool_addr = (pool.get("pool_address") or "").lower()
        if pool_addr:
            custody_counts[custody_by_pool.get(pool_addr, pool_addr)] += 1
    symbols = token_symbols or {}

    rows = []
    pie_rows: list[dict[str, Any]] = []
    for p in pools:
        pa = (p.get("pool_address") or "").lower()
        t0 = p.get("token0", "")
        t1 = p.get("token1", "")
        pair_cell = _token_pair_html(t0, t1, symbols, chain_id=chain_id)
        sym0 = symbols.get((t0 or "").lower()) or _short_pool_label(t0)
        sym1 = symbols.get((t1 or "").lower()) or _short_pool_label(t1)
        pair_label = "{}/{}".format(sym0, sym1)
        proto = "{} {}".format(p.get("protocol", "") or "", p.get("version", "") or "").strip()
        in_list = "Yes" if p.get("in_holders_list") else "No"
        measured = pa in tvl_lookup and int(tvl_lookup.get(pa, 0) or 0) > 0
        raw_tvl = int(tvl_lookup.get(pa, 0) or 0) if measured else 0
        vol_info = vol_lookup.get(pa, {}) or {}
        tvl_decimal = raw_tvl / scale if raw_tvl else 0.0
        vol_decimal = float(vol_info.get("volume_in_token", 0) or 0)
        tvl_share = raw_tvl / total_tvl * 100 if total_tvl > 0 and measured else 0.0
        vol_share = vol_decimal / total_volume * 100 if total_volume > 0 else 0.0
        custody = custody_by_pool.get(pa, pa)
        reserve = float(reserve_by_pool.get(pa, 0) or 0)
        reserve_share = reserve / total_reserve * 100 if total_reserve > 0 and reserve > 0 else 0.0
        if reserve > 0:
            share_label = (
                "&lt;0.1%" if 0 < reserve_share < 0.1 else "{:.2f}%".format(reserve_share)
            )
            reserve_cell = "{} ({})".format(_fmt_bal(reserve, symbol), share_label)
            if custody_counts.get(custody, 0) > 1:
                reserve_cell += ' <small class="muted">shared custody</small>'
            pie_rows.append(
                {
                    "address": p.get("pool_address") or custody,
                    "pool_label": "{} · {}".format(proto or "pool", pair_label),
                    "balance_decimal": reserve,
                }
            )
        else:
            reserve_cell = '<span class="muted">0</span>'
        if measured:
            tvl_cell = _fmt_bal(tvl_decimal, symbol)
            share_label = (
                "&lt;0.1%" if 0 < tvl_share < 0.1 else "{:.1f}%".format(tvl_share)
            )
            share_cell = (
                '<span class="measured-share">{} '
                '<small>of measured liquidity</small></span>'.format(share_label)
            )
        else:
            unavailable_note = (
                "Not measured: per-pool V4 liquidity is unavailable because V4 "
                "Pool IDs share the PoolManager custody contract."
                if str(p.get("version") or "").lower() == "v4"
                else "Not measured in the current pool-liquidity snapshot."
            )
            safe_note = html.escape(unavailable_note, quote=True)
            tvl_cell = '<span class="not-measured" title="{}">Not measured</span>'.format(
                safe_note
            )
            share_cell = '<span class="not-measured" title="{}">Not measured</span>'.format(
                safe_note
            )
        rows.append(
            f"<tr><td>{_labeled_identifier_html(p.get('pool_address', ''), chain_id=chain_id, address_labels=address_labels)}</td>"
            f"<td>{html.escape(proto)}</td>"
            f"<td>{pair_cell}</td>"
            f"<td>{reserve_cell}</td>"
            f"<td>{tvl_cell}</td>"
            f"<td>{_fmt_bal(vol_decimal, symbol)}</td>"
            f"<td>{share_cell}</td>"
            f"<td>{vol_share:.2f}%</td>"
            f"<td>{in_list}</td></tr>"
        )
    return "\n".join(rows), pie_rows


def _fmt_bal(bal: float, symbol: str) -> str:
    if bal >= 1_000_000:
        return f"{bal/1_000_000:.2f}M {symbol}"
    if bal >= 1_000:
        return f"{bal/1_000:.2f}K {symbol}"
    return f"{bal:.4f} {symbol}"


def _fmt_supply(val: float, symbol: str) -> str:
    if val >= 1_000_000_000:
        return f"{val/1_000_000_000:.2f}B {symbol}"
    if val >= 1_000_000:
        return f"{val/1_000_000:.2f}M {symbol}"
    if val >= 1_000:
        return f"{val/1_000:.2f}K {symbol}"
    return f"{val:.4f} {symbol}"


def _risk_color(score: float) -> str:
    if score < 0.25:
        return "#4ade80"
    if score < 0.55:
        return "#facc15"
    return "#f87171"


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default
    return default


def _read_artifact_rows(
    out: Path,
    name: str,
    fallback: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Read a large table Parquet-first and tolerate legacy JSON-only outputs."""
    if not (out / "tables" / "{}.parquet".format(name)).exists():
        return list(fallback or [])
    try:
        return read_table(name, out, prefer="parquet", legacy_rows=True)
    except (ArtifactError, FileNotFoundError, ImportError, OSError, ValueError):
        return list(fallback or [])


def _load_dashboard_inputs(out: Path) -> dict[str, Any]:
    """Load summaries plus Parquet-first row tables for dashboard rendering."""
    holdings = read_holdings_document(out, prefer="parquet", legacy_rows=True)
    token_profile = _load_json(out / "token_profile.json", {})
    verified_pools = _load_json(out / "verified_pools.json", [])
    metrics = _load_json(out / "metrics.json", {})
    risk = _load_json(out / "risk_assessment.json", {})

    holdings = dict(holdings or {})
    _restore_display_addresses(
        holdings["holdings"], ("address", "resolved_owner")
    )
    positions = _read_artifact_rows(
        out, "positions", _load_json(out / "positions.json", [])
    )
    _restore_display_addresses(
        positions,
        ("pool_address", "owner", "lp_token_address", "beneficial_owner"),
    )
    swaps = _read_artifact_rows(
        out, "swaps", _load_json(out / "swaps.json", [])
    )
    liquidity = _read_artifact_rows(
        out,
        "liquidity_events",
        _load_json(out / "liquidity_events.json", []),
    )
    transfers = _read_artifact_rows(
        out, "transfers", _load_json(out / "transfers.json", [])
    )
    legacy_events_all = _load_json(out / "events_all.json", [])
    position_artifact_exists = (
        (out / "tables" / "position_events.parquet").exists()
        or (out / "position_events.json").exists()
    )
    position_fallback = _load_json(out / "position_events.json", [])
    if not position_artifact_exists:
        position_fallback = [
            row
            for row in legacy_events_all
            if (row.get("event_type") or "").upper() == "POSITION_TRANSFER"
        ]
    position_events = _read_artifact_rows(
        out,
        "position_events",
        position_fallback,
    )

    metrics = dict(metrics or {})
    tvl_fallback = metrics.get("tvl_timeline") or _load_json(
        out / "tvl_timeline.json", []
    )
    metrics["tvl_timeline"] = _read_artifact_rows(
        out, "tvl_timeline", tvl_fallback
    )

    volume_summary = dict(metrics.get("volume") or {})
    volume_document = _load_json(out / "volume_timeline.json", {})
    if not volume_summary:
        volume_summary = dict(volume_document or {})
    volume_fallback = (
        volume_summary
        if volume_summary.get("volume_timeline")
        else volume_document
    )
    volume_rows = _read_artifact_rows(
        out,
        "volume_timeline",
        [],
    )
    if volume_rows:
        volume_summary = inflate_volume_timeline(volume_rows, volume_summary)
    elif volume_fallback.get("volume_timeline"):
        volume_summary["volume_timeline"] = volume_fallback["volume_timeline"]
    else:
        volume_summary["volume_timeline"] = []
    metrics["volume"] = volume_summary

    combined_events = combine_event_tables(
        swaps, liquidity, transfers, position_events
    )
    events_all = combined_events or legacy_events_all
    return {
        "holdings": holdings,
        "token_profile": token_profile,
        "verified_pools": verified_pools,
        "metrics": metrics,
        "risk": risk,
        "positions": positions,
        "swaps": swaps,
        "liquidity_events": liquidity,
        "transfers": transfers,
        "position_events": position_events,
        "events_all": events_all,
    }


def _restore_display_addresses(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> None:
    """Restore EIP-55 display casing after normalized Parquet reads."""
    for row in rows:
        for field in fields:
            value = row.get(field)
            if not isinstance(value, str) or len(value) != 42:
                continue
            try:
                row[field] = Web3.to_checksum_address(value)
            except ValueError:
                continue



def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
