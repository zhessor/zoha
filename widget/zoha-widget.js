/* Zoha chat widget: one <script> tag on any website.
   <script src="https://YOUR-SERVER/widget.js" data-server="https://YOUR-SERVER" defer></script> */
(function () {
  var s = document.currentScript || document.querySelector("script[data-server]");
  var server = ((s && s.getAttribute("data-server")) || "").replace(/\/$/, "");
  if (!server) return;
  var title = (s && s.getAttribute("data-title")) || "Chat with us";
  var accent = (s && s.getAttribute("data-color")) || "#1f9d8f";
  var el = function (tag, css, text) { var e = document.createElement(tag); if (css) e.style.cssText = css; if (text) e.textContent = text; return e; };
  var btn = el("button", "position:fixed;right:20px;bottom:20px;width:56px;height:56px;border-radius:50%;border:0;background:" + accent + ";color:#fff;font-size:24px;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);z-index:2147483000", "💬");
  btn.setAttribute("aria-label", title);
  var box = el("div", "position:fixed;right:20px;bottom:88px;width:340px;max-width:calc(100vw - 40px);height:440px;max-height:70vh;background:#fff;color:#1b1f1e;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.3);display:none;flex-direction:column;overflow:hidden;font:14px/1.45 system-ui,Segoe UI,Arial,sans-serif;z-index:2147483000");
  var head = el("div", "padding:12px 14px;background:" + accent + ";color:#fff;font-weight:600", title);
  var log = el("div", "flex:1;overflow:auto;padding:12px;background:#f6f8f7");
  var form = el("form", "display:flex;gap:6px;padding:8px;border-top:1px solid #e3e7e5");
  var input = el("input", "flex:1;padding:9px;border:1px solid #cfd6d3;border-radius:8px;font:inherit");
  input.placeholder = "Type your question"; input.maxLength = 500;
  var send = el("button", "padding:0 14px;border:0;border-radius:8px;background:" + accent + ";color:#fff;cursor:pointer", "Send");
  form.appendChild(input); form.appendChild(send);
  box.appendChild(head); box.appendChild(log); box.appendChild(form);
  var history = [];
  function add(who, text) {
    var b = el("div", "margin:6px 0;padding:8px 11px;border-radius:12px;max-width:85%;white-space:pre-wrap;" +
      (who === "me" ? "margin-left:auto;background:" + accent + ";color:#fff" : "background:#fff;border:1px solid #e3e7e5"), text);
    log.appendChild(b); log.scrollTop = log.scrollHeight; return b;
  }
  add("bot", "Hi! Ask me anything about us, or leave your number and we'll call you back.");
  function post(path, body) {
    return fetch(server + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); });
  }
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim(); if (!text) return;
    input.value = ""; add("me", text);
    var wait = add("bot", "…");
    post("/chat", { message: text, history: history.slice(-6) }).then(function (d) {
      wait.textContent = d.reply || d.error || "Sorry, something went wrong.";
      history.push({ role: "user", text: text }, { role: "bot", text: wait.textContent });
      if (d.offer_lead && !box.querySelector("[data-lead]")) leadForm();
    }).catch(function () { wait.textContent = "Sorry, I can't connect right now."; });
  });
  function leadForm() {
    var f = el("form", "margin:8px 0;padding:10px;background:#fff;border:1px solid #e3e7e5;border-radius:10px"); f.setAttribute("data-lead", "1");
    var n = el("input", "width:100%;box-sizing:border-box;margin:3px 0;padding:7px;border:1px solid #cfd6d3;border-radius:6px"); n.placeholder = "Your name";
    var p = el("input", "width:100%;box-sizing:border-box;margin:3px 0;padding:7px;border:1px solid #cfd6d3;border-radius:6px"); p.placeholder = "Phone number";
    var g = el("button", "margin-top:4px;padding:7px 12px;border:0;border-radius:6px;background:" + accent + ";color:#fff;cursor:pointer", "Call me back");
    f.appendChild(n); f.appendChild(p); f.appendChild(g); log.appendChild(f); log.scrollTop = log.scrollHeight;
    f.addEventListener("submit", function (ev) {
      ev.preventDefault();
      post("/lead", { name: n.value, phone: p.value, message: (history.filter(function (h) { return h.role === "user"; }).pop() || {}).text || "" })
        .then(function (d) { f.textContent = d.ok ? "Thanks! We'll call you soon." : (d.error || "Please check your number."); });
    });
  }
  btn.addEventListener("click", function () { box.style.display = box.style.display === "flex" ? "none" : "flex"; if (box.style.display === "flex") input.focus(); });
  document.body.appendChild(box); document.body.appendChild(btn);
})();
