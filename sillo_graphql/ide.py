"""The in-browser explorer served on ``GET``.

Two versions, chosen by :attr:`~sillo_graphql.policy.IDE.assets`.

``"bundled"`` is the default and is written out below: one HTML document with
its CSS and JavaScript inline, no network requests, no build step. It works
offline, inside a private network, and under a Content-Security-Policy that
forbids third-party script — none of which is true of an explorer that fetches
two megabytes of editor from a CDN at load time. It is deliberately small: an
editor, variables, headers, a response pane and a schema browser.

``"cdn"`` serves GraphiQL proper from unpkg with subresource integrity, for
when the full editor is worth the dependency.

Neither is served unless it is switched on, and the page only offers a
subscriptions socket when one is actually mounted — the previous integration
advertised a WebSocket endpoint that did not exist, which is a worse failure
than having no explorer at all.
"""

from __future__ import annotations

import html as html_module
import json

from sillo_graphql.policy import IDE

__all__ = ["render"]

_CDN = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/graphiql@3.8.3/graphiql.min.css"
  integrity="sha384-Mq3vbRBY71jfjQAt/DcjxUIYY33ksal4cgdRt9U/hNPvHBCaT2JfJ/PTRiPKf0aM"
  crossorigin />
<style>body{margin:0;height:100vh}#app{height:100vh}</style>
</head>
<body>
<div id="app">Loading…</div>
<script src="https://unpkg.com/react@18.2.0/umd/react.production.min.js"
  integrity="sha384-tMH8h3BGESGckSAVGZ82T9n90ztNXxvdwvdM6UoR56cYcf+0iGXBliJ29D+wZ/x8"
  crossorigin></script>
<script src="https://unpkg.com/react-dom@18.2.0/umd/react-dom.production.min.js"
  integrity="sha384-bm7MnzvK++ykSwVJ2tynSE5TRdN+xL418osEVF2DE/L/gfWHj91J2Sphe582B1Bh"
  crossorigin></script>
<script src="https://unpkg.com/graphiql@3.8.3/graphiql.min.js"
  integrity="sha384-HbRVEFG0JGJZeAHCJ9Xm2+tpknBQ7QZmNlO/DgZtkZ0aJSypT96YYGRNod99l9Ie"
  crossorigin></script>
<script>
  var config = __CONFIG__;
  var fetcher = GraphiQL.createFetcher(
    config.subscriptions
      ? { url: config.endpoint, subscriptionUrl: config.socket }
      : { url: config.endpoint }
  );
  ReactDOM.createRoot(document.getElementById('app')).render(
    React.createElement(GraphiQL, {
      fetcher: fetcher, defaultQuery: config.defaultQuery
    })
  );
</script>
</body>
</html>
"""

_BUNDLED = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>__TITLE__</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #fbfbfa; --panel: #fff; --ink: #16181d; --dim: #6b7280;
    --line: #e4e4e7; --accent: #16181d; --mono: ui-monospace, SFMono-Regular,
      "SF Mono", Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#101114; --panel:#17181c; --ink:#e8e8ea; --dim:#9095a1;
            --line:#26282e; --accent:#e8e8ea; }
  }
  * { box-sizing: border-box; }
  body { margin:0; height:100vh; display:flex; flex-direction:column;
         background:var(--bg); color:var(--ink);
         font:13px/1.5 ui-sans-serif, system-ui, -apple-system, sans-serif; }
  header { display:flex; align-items:center; gap:12px; padding:10px 16px;
           border-bottom:1px solid var(--line); flex-shrink:0; }
  header h1 { font-size:13px; font-weight:600; margin:0; letter-spacing:-0.01em; }
  header .path { color:var(--dim); font-family:var(--mono); font-size:11px; }
  header .grow { margin-left:auto; }
  button { font:inherit; font-weight:600; padding:6px 14px; border-radius:7px;
           border:1px solid var(--line); background:var(--panel);
           color:var(--ink); cursor:pointer; }
  button.run { background:var(--accent); color:var(--bg); border-color:var(--accent); }
  button:disabled { opacity:.5; cursor:default; }
  main { flex:1; display:grid; grid-template-columns:1fr 1fr; min-height:0; }
  @media (max-width: 800px) { main { grid-template-columns:1fr; } }
  .col { display:flex; flex-direction:column; min-width:0; min-height:0; }
  .col + .col { border-left:1px solid var(--line); }
  .pane { display:flex; flex-direction:column; min-height:0; flex:1; }
  .pane + .pane { border-top:1px solid var(--line); }
  .pane.small { flex:0 0 22%; }
  .label { padding:6px 12px; font-size:10px; letter-spacing:.08em;
           text-transform:uppercase; color:var(--dim);
           border-bottom:1px solid var(--line); display:flex; gap:8px; }
  .label .tab { cursor:pointer; }
  .label .tab[aria-selected="true"] { color:var(--ink); }
  textarea, pre { flex:1; margin:0; padding:12px; border:0; resize:none;
                  background:var(--panel); color:var(--ink);
                  font-family:var(--mono); font-size:12.5px; line-height:1.65;
                  overflow:auto; white-space:pre; tab-size:2; }
  textarea:focus { outline:none; }
  pre { color:var(--ink); }
  .status { padding:4px 12px; font-size:11px; color:var(--dim);
            border-top:1px solid var(--line); font-family:var(--mono); }
  .schema { flex:1; overflow:auto; padding:10px 12px; font-family:var(--mono);
            font-size:12px; }
  .schema .t { font-weight:700; margin-top:10px; }
  .schema .f { color:var(--dim); padding-left:12px; }
  .err { color:#c0392b; }
  @media (prefers-color-scheme: dark) { .err { color:#ff8a80; } }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span class="path">__ENDPOINT__</span>
  <span class="grow"></span>
  <button id="schema-btn" type="button">Schema</button>
  <button id="run" class="run" type="button">Run &#9654;</button>
</header>
<main>
  <div class="col">
    <div class="pane">
      <div class="label"><span>Operation</span><span style="margin-left:auto"
        >&#8984;/Ctrl + Enter</span></div>
      <textarea id="query" spellcheck="false"></textarea>
    </div>
    <div class="pane small">
      <div class="label">
        <span class="tab" id="tab-vars" aria-selected="true">Variables</span>
        <span class="tab" id="tab-headers" aria-selected="false">Headers</span>
      </div>
      <textarea id="vars" spellcheck="false"></textarea>
      <textarea id="headers" spellcheck="false" hidden></textarea>
    </div>
  </div>
  <div class="col">
    <div class="pane" id="response-pane">
      <div class="label">Response</div>
      <pre id="out"></pre>
      <div class="status" id="status">ready</div>
    </div>
    <div class="pane" id="schema-pane" hidden>
      <div class="label">Schema</div>
      <div class="schema" id="schema"></div>
    </div>
  </div>
</main>
<script>
(function () {
  var config = __CONFIG__;
  var $ = function (id) { return document.getElementById(id); };
  var query = $('query'), vars = $('vars'), headers = $('headers');
  var out = $('out'), status = $('status');

  query.value = config.defaultQuery || '{\\n  __typename\\n}\\n';
  vars.value = '{}';
  headers.value = '{}';

  function parse(text, what) {
    var trimmed = (text || '').trim();
    if (!trimmed) return {};
    try { return JSON.parse(trimmed); }
    catch (e) { throw new Error(what + ' is not valid JSON: ' + e.message); }
  }

  function show(value, isError) {
    out.textContent =
      typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    out.className = isError ? 'err' : '';
  }

  var running = false;
  async function run() {
    if (running) return;
    running = true;
    $('run').disabled = true;
    var started = performance.now();
    status.textContent = 'running…';
    try {
      var body = { query: query.value, variables: parse(vars.value, 'Variables') };
      var extra = parse(headers.value, 'Headers');
      var init = {
        'content-type': 'application/json', 'accept': 'application/json'
      };
      for (var k in extra) init[k] = extra[k];
      var res = await fetch(config.endpoint, {
        method: 'POST', headers: init, credentials: 'same-origin',
        body: JSON.stringify(body)
      });
      var text = await res.text();
      var payload;
      try { payload = JSON.parse(text); } catch (e) { payload = text; }
      show(payload, false);
      status.textContent = res.status + ' ' + res.statusText + ' · ' +
        Math.round(performance.now() - started) + 'ms';
    } catch (e) {
      show(String(e.message || e), true);
      status.textContent = 'failed';
    } finally {
      running = false;
      $('run').disabled = false;
    }
  }

  $('run').addEventListener('click', run);
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); run(); }
  });

  function selectTab(which) {
    var isVars = which === 'vars';
    vars.hidden = !isVars; headers.hidden = isVars;
    $('tab-vars').setAttribute('aria-selected', String(isVars));
    $('tab-headers').setAttribute('aria-selected', String(!isVars));
  }
  $('tab-vars').addEventListener('click', function () { selectTab('vars'); });
  $('tab-headers').addEventListener('click', function () { selectTab('headers'); });

  var schemaLoaded = false;
  $('schema-btn').addEventListener('click', async function () {
    var pane = $('schema-pane');
    pane.hidden = !pane.hidden;
    if (pane.hidden || schemaLoaded) return;
    schemaLoaded = true;
    var target = $('schema');
    target.textContent = 'loading…';
    try {
      var res = await fetch(config.endpoint, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          query: '{ __schema { types { name kind fields { name } } } }'
        })
      });
      var payload = await res.json();
      if (!payload.data) {
        target.textContent = 'Introspection is disabled on this endpoint.';
        return;
      }
      target.innerHTML = '';
      payload.data.__schema.types
        .filter(function (t) { return t.fields && t.name.indexOf('__') !== 0; })
        .forEach(function (t) {
          var head = document.createElement('div');
          head.className = 't'; head.textContent = t.name;
          target.appendChild(head);
          t.fields.forEach(function (f) {
            var row = document.createElement('div');
            row.className = 'f'; row.textContent = f.name;
            target.appendChild(row);
          });
        });
    } catch (e) {
      target.textContent = String(e.message || e);
    }
  });
})();
</script>
</body>
</html>
"""
