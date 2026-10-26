/*
 * PGT client chat: drop-in for a client business's own website (Brick 4b, 2026-10-25).
 * Ported from the pgt-demos live chat (a020999), pointed at the engine's /t/<slug>/chat.
 *
 *   <script src="https://pgt-site-assistant.onrender.com/client-widget.js"
 *           data-tenant="terry-allen" data-name="Terry Allen Plumbing"
 *           data-greeting="Hi! What can we help you with?" data-accent="#0b5cab"
 *           data-ink="#10233f" data-paper="#ffffff" data-font="system-ui, sans-serif"></script>
 *
 * A floating "Text us" button opens a chat panel. When the assistant captures a lead, the
 * engine stores it under this business and emails the owner; the customer sees a short
 * "sent" card. One lead per conversation (lead_captured). No cookies, no tracking.
 */
(function () {
  var me = document.currentScript;
  var API = new URL(me.src).origin;
  function attr(n, d) { return me.getAttribute(n) || d; }
  var cfg = {
    tenant: attr("data-tenant", ""),
    name: attr("data-name", "us"),
    greeting: attr("data-greeting", "Hi! How can we help?"),
    accent: attr("data-accent", "#222"),
    ink: attr("data-ink", "#111"),
    paper: attr("data-paper", "#fff"),
    font: attr("data-font", "system-ui, sans-serif"),
  };
  if (!cfg.tenant) return;

  var css = [
    ".pgtc-launch{position:fixed;right:18px;bottom:18px;z-index:2147483000;display:flex;align-items:center;gap:10px;border:0;border-radius:999px;padding:14px 20px;font:600 16px/1 var(--pgtc-font);background:var(--pgtc-accent);color:#fff;box-shadow:0 10px 30px rgba(0,0,0,.25);cursor:pointer}",
    ".pgtc-dot{width:9px;height:9px;border-radius:50%;background:#3ddc84;flex:0 0 auto}",
    ".pgtc-panel{position:fixed;right:18px;bottom:18px;z-index:2147483001;width:380px;max-width:calc(100vw - 24px);height:560px;max-height:calc(100dvh - 36px);display:flex;flex-direction:column;background:var(--pgtc-paper);color:var(--pgtc-ink);border-radius:20px;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.35);font:15px/1.45 var(--pgtc-font)}",
    ".pgtc-head{display:flex;align-items:center;gap:10px;padding:14px 16px;background:var(--pgtc-ink);color:#fff}",
    ".pgtc-head b{font-size:16px}.pgtc-head small{display:block;opacity:.75;font-size:12px}",
    ".pgtc-x{margin-left:auto;background:none;border:0;color:#fff;font-size:24px;line-height:1;cursor:pointer;padding:4px 8px}",
    ".pgtc-log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:8px}",
    ".pgtc-m{max-width:85%;padding:9px 13px;border-radius:16px;white-space:pre-wrap;word-wrap:break-word}",
    ".pgtc-bot{align-self:flex-start;background:#fff;border:1px solid rgba(0,0,0,.08);color:#111}",
    ".pgtc-usr{align-self:flex-end;background:var(--pgtc-accent);color:#fff}",
    ".pgtc-note{align-self:center;font-size:12px;opacity:.7;text-align:center;padding:2px 8px}",
    ".pgtc-lead{align-self:stretch;background:#fff;color:#111;border:2px solid var(--pgtc-accent);border-radius:14px;padding:12px 14px;font-size:14px}",
    ".pgtc-lead strong{display:block;margin-bottom:6px;color:var(--pgtc-accent)}",
    ".pgtc-form{display:flex;gap:8px;padding:10px;border-top:1px solid rgba(0,0,0,.08);background:#fff}",
    ".pgtc-form input{flex:1;min-width:0;border:1px solid rgba(0,0,0,.15);border-radius:12px;padding:11px 12px;font:16px var(--pgtc-font);color:#111;background:#fff}",
    ".pgtc-form button{border:0;border-radius:12px;padding:0 16px;font:600 15px var(--pgtc-font);background:var(--pgtc-accent);color:#fff;cursor:pointer}",
    ".pgtc-form button:disabled{opacity:.5;cursor:default}",
    ".pgtc-by{font-size:11px;text-align:center;opacity:.55;padding:0 0 8px;background:#fff;color:#111}",
    "@media (max-width:480px){.pgtc-panel{right:0;bottom:0;width:100vw;max-width:100vw;height:100dvh;max-height:100dvh;border-radius:0}}",
  ].join("\n");

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function mount() {
    var root = document.documentElement.style;
    root.setProperty("--pgtc-accent", cfg.accent);
    root.setProperty("--pgtc-ink", cfg.ink);
    root.setProperty("--pgtc-paper", cfg.paper);
    root.setProperty("--pgtc-font", cfg.font);
    var style = el("style"); style.textContent = css; document.head.appendChild(style);

    var launch = el("button", "pgtc-launch"); launch.type = "button";
    launch.appendChild(el("span", "pgtc-dot"));
    launch.appendChild(el("span", null, "Text " + cfg.name));
    document.body.appendChild(launch);

    var panel = el("div", "pgtc-panel"); panel.style.display = "none";
    panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Chat with " + cfg.name);
    var head = el("div", "pgtc-head");
    var title = el("div"); title.appendChild(el("b", null, cfg.name));
    title.appendChild(el("small", null, "We answer right away, day or night"));
    var x = el("button", "pgtc-x", "×"); x.type = "button"; x.setAttribute("aria-label", "Close chat");
    head.appendChild(title); head.appendChild(x);
    var log = el("div", "pgtc-log");
    var form = el("form", "pgtc-form");
    var input = el("input"); input.placeholder = "Type a message"; input.setAttribute("aria-label", "Message");
    input.maxLength = 1000; input.enterKeyHint = "send";
    var send = el("button", null, "Send"); send.type = "submit";
    form.appendChild(input); form.appendChild(send);
    var by = el("div", "pgtc-by", "AI assistant. It never makes up prices or times.");
    panel.appendChild(head); panel.appendChild(log); panel.appendChild(form); panel.appendChild(by);
    document.body.appendChild(panel);

    var history = [{ role: "assistant", content: cfg.greeting }];
    var opened = false, busy = false, leadShown = false, booked = false;

    function add(cls, text) { var m = el("div", "pgtc-m " + cls, text); log.appendChild(m); log.scrollTop = log.scrollHeight; return m; }
    function note(text) { var n = el("div", "pgtc-note", text); log.appendChild(n); log.scrollTop = log.scrollHeight; }
    function showLead(lead) {
      if (leadShown) return; leadShown = true;
      var card = el("div", "pgtc-lead");
      card.appendChild(el("strong", null, lead.urgent ? "Sent as urgent" : "Sent to " + cfg.name));
      [["Name", lead.name], ["Phone", lead.phone], ["Email", lead.email], ["About", lead.summary]].forEach(function (r) {
        if (r[1]) card.appendChild(el("div", null, r[0] + ": " + r[1]));
      });
      card.appendChild(el("div", "pgtc-note", "They'll get back to you as soon as they can."));
      log.appendChild(card); log.scrollTop = log.scrollHeight;
    }

    function open() {
      panel.style.display = "flex"; launch.style.display = "none";
      if (!opened) { opened = true; add("pgtc-bot", cfg.greeting); }
      input.focus();
    }
    function close() { panel.style.display = "none"; launch.style.display = "flex"; }
    launch.addEventListener("click", open);
    x.addEventListener("click", close);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = input.value.trim();
      if (!text || busy) return;
      input.value = ""; add("pgtc-usr", text);
      history.push({ role: "user", content: text });
      busy = true; send.disabled = true;
      var typing = add("pgtc-bot", "…");
      fetch(API + "/t/" + encodeURIComponent(cfg.tenant) + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ history: history, lead_captured: leadShown, booked: booked }),
      })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          typing.remove();
          if (!res.ok || !res.j.reply) { history.pop(); note((res.j && res.j.reply) || "Something went wrong. Try again."); return; }
          add("pgtc-bot", res.j.reply);
          history.push({ role: "assistant", content: res.j.reply });
          // A booking's confirmation IS the reply (written by the server from the store).
          if (res.j.booking) { booked = true; leadShown = true; }
          else if (res.j.lead) showLead(res.j.lead);
        })
        .catch(function () { typing.remove(); history.pop(); note("Couldn't connect. Check your connection and try again."); })
        .then(function () { busy = false; send.disabled = false; input.focus(); });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
