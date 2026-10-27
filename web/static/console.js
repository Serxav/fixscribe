(function () {
  "use strict";
  var root = document.getElementById("console");
  if (!root) return;
  var jobId = root.dataset.jobId;
  var after = 0;
  var busy = false;
  var timer = null;
  var lastStatus = "";

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function mediaUrl(rel) { return "/jobs/" + jobId + "/agent/media/" + rel; }
  function money(v) { return "$" + Number(v || 0).toFixed(2); }
  function when(a, b) { return Number(a || 0).toFixed(1) + "–" + Number(b || 0).toFixed(1) + " s"; }

  function nearBottom() {
    return window.innerHeight + window.scrollY >= document.body.scrollHeight - 160;
  }

  function shortArg(v) {
    var s = typeof v === "string" ? v : JSON.stringify(v);
    if (s === undefined) s = "";
    return s.length > 60 ? s.slice(0, 57) + "..." : s;
  }

  function renderHeader(rec) {
    var pill = $("status-pill");
    pill.textContent = rec.status;
    pill.className = "pill " + (rec.status === "running" ? "running" : rec.status === "done" ? "done" : rec.status === "failed" ? "failed" : "");
    $("turn-count").textContent = rec.turn + " / " + rec.max_turns;
    $("spend").textContent = money(rec.usd);
    var showStart = rec.status === "idle" || rec.status === "failed";
    var showResume = rec.status === "paused";
    $("btn-start").hidden = !showStart;
    $("btn-resume").hidden = !showResume;
    $("btn-start").disabled = busy;
    $("btn-resume").disabled = busy;
    var empty = rec.status === "idle" && rec.turn === 0 && after === 0;
    $("empty-state").hidden = !empty;
    var done = rec.status === "done";
    $("done-banner").hidden = !done;
  }

  function addTurn(t) {
    var card = el("article", "turn");
    var planH = el("h4", null, "PLAN");
    card.appendChild(planH);
    var planText = t.plan || "";
    if (t.tokens) planText += "  ·  " + t.tokens + " tokens";
    card.appendChild(el("p", null, planText));
    if (t.act) {
      card.appendChild(el("h4", null, "ACT"));
      var tool = el("p", "tool", t.act.tool || "");
      card.appendChild(tool);
      var keys = Object.keys(t.act.args || {});
      if (keys.length) {
        var args = keys.map(function (k) { return k + "=" + shortArg(t.act.args[k]); }).join("  ");
        card.appendChild(el("p", "args", args));
      }
    }
    if (t.observe) {
      card.appendChild(el("h4", null, "OBSERVE"));
      var obs = el("p", null, t.observe.text || "");
      obs.classList.add(t.observe.ok ? "observe-ok" : "observe-bad");
      card.appendChild(obs);
      if (t.observe.image) {
        var img = document.createElement("img");
        img.className = "thumb";
        img.alt = "Observation image for turn " + t.turn;
        img.src = mediaUrl(t.observe.image);
        img.loading = "lazy";
        img.addEventListener("click", function () {
          $("overlay-img").src = img.src;
          $("overlay").hidden = false;
        });
        card.appendChild(img);
      }
    }
    $("timeline").appendChild(card);
  }

  function renderParts(rec) {
    var box = $("parts");
    box.textContent = "";
    (rec.parts || []).forEach(function (p) {
      var card = el("div", "part" + (p.verified ? "" : " dim"));
      card.appendChild(el("div", "part-id", p.id || ""));
      card.appendChild(el("div", "part-name", p.name || ""));
      card.appendChild(el("div", "part-count", "x" + (p.count || 1)));
      if (p.crop) {
        var img = document.createElement("img");
        img.alt = "Crop of part " + (p.id || "");
        img.src = mediaUrl(p.crop);
        img.loading = "lazy";
        card.appendChild(img);
      }
      if (p.verified) card.appendChild(el("div", "check", "Verified"));
      (p.evidence || []).forEach(function (line) {
        card.appendChild(el("p", "evidence", line));
      });
      box.appendChild(card);
    });
  }

  function renderSteps(rec) {
    var list = $("steps");
    list.textContent = "";
    (rec.steps || []).forEach(function (s) {
      var item = document.createElement("li");
      var card = el("div", "step-card");
      card.appendChild(el("div", "step-num", "Step " + s.n));
      card.appendChild(el("p", null, s.text || ""));
      if ((s.parts || []).length) {
        var chips = el("div", "chips");
        s.parts.forEach(function (pid) { chips.appendChild(el("span", "chip-part", pid)); });
        card.appendChild(chips);
      }
      card.appendChild(el("div", "step-when", when(s.start_s, s.end_s)));
      if (s.quote) card.appendChild(el("blockquote", null, s.quote));
      if (s.verified) card.appendChild(el("div", "check", "Verified"));
      (s.evidence || []).forEach(function (line) {
        card.appendChild(el("p", "evidence", line));
      });
      item.appendChild(card);
      list.appendChild(item);
    });
    var notes = $("notes");
    notes.textContent = "";
    (rec.notes || []).forEach(function (line) {
      notes.appendChild(el("p", "note-line", line));
    });
  }

  function renderQuestion(rec) {
    var card = $("question-card");
    if (rec.status !== "needs_input" || !rec.question) { card.hidden = true; return; }
    card.hidden = false;
    $("question-text").textContent = rec.question.text || "";
    var wrap = $("question-frame-wrap");
    if (rec.question.frame) {
      wrap.hidden = false;
      $("question-frame").src = mediaUrl(rec.question.frame);
      var box = rec.question.box;
      var mark = $("question-box");
      if (box && box.length === 4) {
        mark.hidden = false;
        mark.style.left = (box[0] / 10) + "%";
        mark.style.top = (box[1] / 10) + "%";
        mark.style.width = ((box[2] - box[0]) / 10) + "%";
        mark.style.height = ((box[3] - box[1]) / 10) + "%";
      } else {
        mark.hidden = true;
      }
    } else {
      wrap.hidden = true;
    }
    var opts = $("question-options");
    opts.textContent = "";
    (rec.question.options || []).forEach(function (opt) {
      var b = el("button", "btn btn-glass", opt);
      b.type = "button";
      b.addEventListener("click", function () { $("answer-input").value = opt; });
      opts.appendChild(b);
    });
  }

  function renderSignoff(rec) {
    $("signoff-card").hidden = rec.status !== "awaiting_signoff";
  }

  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(poll, lastStatus === "running" ? 1500 : 5000);
  }

  function poll() {
    fetch("/api/jobs/" + jobId + "/agent?after=" + after)
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) return;
        var rec = res.d.record;
        lastStatus = rec.status;
        var stick = nearBottom();
        (res.d.turns || []).forEach(function (t) {
          addTurn(t);
          if (t.turn > after) after = t.turn;
        });
        renderHeader(rec);
        renderParts(rec);
        renderSteps(rec);
        renderQuestion(rec);
        renderSignoff(rec);
        if (stick) window.scrollTo(0, document.body.scrollHeight);
      })
      .catch(function () {})
      .finally(schedule);
  }

  function post(path, body, errEl) {
    busy = true;
    renderButtonsDisabled();
    return fetch("/api/jobs/" + jobId + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; }); })
      .then(function (res) {
        if (errEl) {
          errEl.hidden = res.ok;
          if (!res.ok) errEl.textContent = (res.d && (res.d.error || res.d.detail)) || "Request failed.";
        }
        return res;
      })
      .finally(function () { busy = false; renderButtonsDisabled(); poll(); });
  }

  function renderButtonsDisabled() {
    $("btn-start").disabled = busy;
    $("btn-resume").disabled = busy;
  }

  function launch(path) {
    busy = true;
    renderButtonsDisabled();
    fetch("/api/jobs/" + jobId + path, { method: "POST" })
      .catch(function () {})
      .finally(function () { busy = false; renderButtonsDisabled(); poll(); });
  }

  $("btn-start").addEventListener("click", function () { launch("/agent/start"); });
  $("btn-start-empty").addEventListener("click", function () { launch("/agent/start"); });
  $("btn-resume").addEventListener("click", function () { launch("/agent/resume"); });
  $("btn-send").addEventListener("click", function () {
    post("/agent/answer", { answer: $("answer-input").value }, $("answer-error"));
  });
  $("btn-approve").addEventListener("click", function () {
    post("/agent/signoff", { approved: true, notes: $("signoff-notes").value || "" }, $("signoff-error"));
  });
  $("btn-reject").addEventListener("click", function () {
    post("/agent/signoff", { approved: false, notes: $("signoff-notes").value || "" }, $("signoff-error"));
  });
  $("overlay").addEventListener("click", function () { $("overlay").hidden = true; });

  poll();
})();
