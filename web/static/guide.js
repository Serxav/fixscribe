(function () {
  "use strict";
  var root = document.getElementById("guide");
  if (!root) return;
  var jobId = root.dataset.jobId;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var crumb = document.getElementById("crumb");
  window.addEventListener("scroll", function () {
    if (crumb) crumb.classList.toggle("show", window.scrollY > 260);
  }, { passive: true });

  // Tap the step photo: a missing fastener is added (SAM follows the point), a wrong one removed.
  // each photo and film sets the shape of its own frame, so no black bands around it
  document.querySelectorAll(".stage").forEach(function (stage) {
    var media = stage.querySelector("img.fit, video.fit");
    if (!media) return;
    var fit = function () {
      var w = media.naturalWidth || media.videoWidth, h = media.naturalHeight || media.videoHeight;
      if (w && h) stage.style.aspectRatio = w + " / " + h;
    };
    fit();
    media.addEventListener("load", fit);
    media.addEventListener("loadedmetadata", fit);
  });
  document.querySelectorAll("img[data-tap-step]").forEach(function (img) {
    var markers = JSON.parse(img.getAttribute("data-markers") || "[]");
    var hint = img.parentNode.querySelector("[data-tap-hint]");
    var busy = false;
    img.addEventListener("click", function (event) {
      if (busy || !img.naturalWidth) return;
      var rect = img.getBoundingClientRect();
      var scale = Math.min(rect.width / img.naturalWidth, rect.height / img.naturalHeight);
      var shownW = img.naturalWidth * scale, shownH = img.naturalHeight * scale;
      var x = (event.clientX - rect.left - (rect.width - shownW) / 2) / shownW;
      var y = (event.clientY - rect.top - (rect.height - shownH) / 2) / shownH;
      if (x < 0 || x > 1 || y < 0 || y > 1) return;
      var hit = markers.filter(function (m) {
        return x >= m.x - 0.02 && x <= m.x + m.w + 0.02 && y >= m.y - 0.02 && y <= m.y + m.h + 0.02;
      })[0];
      var base = "/guides/" + jobId + "/steps/" + img.dataset.tapStep + "/fasteners";
      var ask = hit ? "Remove marker " + hit.number + "?" : "Add a fastener here? SAM will follow it through the step.";
      if (!window.confirm(ask)) return;
      busy = true;
      if (hint) hint.textContent = hit ? "Removing…" : "SAM is following it…";
      fetch(hit ? base + "/" + hit.number + "/remove" : base, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: hit ? null : JSON.stringify({ x: x, y: y })
      }).then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      }).then(function (answer) {
        if (answer.ok) { window.location.reload(); return; }
        busy = false;
        if (hint) hint.textContent = answer.data.error || "Could not change the map — try again";
      }).catch(function () {
        busy = false;
        if (hint) hint.textContent = "Could not change the map — try again";
      });
    });
  });

  function showView(stage, name) {
    stage.querySelectorAll("[data-view]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.view === name));
    });
    stage.querySelectorAll("[data-view-panel]").forEach(function (panel) {
      var on = panel.dataset.viewPanel === name;
      panel.classList.toggle("on", on);
      var video = panel.querySelector("video");
      if (video) { if (on) { video.play().catch(function () {}); } else { video.pause(); } }
    });
  }
  document.querySelectorAll("[data-stage]").forEach(function (stage) {
    stage.querySelectorAll("[data-view]").forEach(function (button) {
      button.addEventListener("click", function () { showView(stage, button.dataset.view); });
    });
    var first = stage.querySelector("[data-view-panel].on video");
    if (first) first.play().catch(function () {});
  });

  var mainVideo = document.getElementById("main-video");
  document.querySelectorAll("[data-seek]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (!mainVideo) return;
      mainVideo.currentTime = parseFloat(button.dataset.seek) || 0;
      mainVideo.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
      mainVideo.play().catch(function () {});
    });
  });

  var toast = document.getElementById("toast");
  var hideTimer = null;
  function showToast(kind, title, text, badge) {
    toast.className = "toast glass show " + kind;
    document.getElementById("toast-title").textContent = title;
    document.getElementById("toast-text").textContent = text || "";
    document.getElementById("toast-badge").textContent = badge;
    clearTimeout(hideTimer);
    if (kind !== "busy") hideTimer = setTimeout(function () { toast.classList.remove("show"); }, 6000);
  }
  document.querySelectorAll("[data-check]").forEach(function (input) {
    input.addEventListener("change", function () {
      if (!input.files.length) return;
      var form = new FormData();
      form.append("photo", input.files[0]);
      showToast("busy", "Checking your photo…", "SAM is counting what is left.", "…");
      fetch("/guides/" + jobId + "/steps/" + input.dataset.check + "/check", { method: "POST", body: form })
        .then(function (response) { return response.json().then(function (data) { return { ok: response.ok, data: data }; }); })
        .then(function (result) {
          if (!result.ok) { showToast("error", "Could not check this photo", result.data.error || "Please try again.", "!"); return; }
          var titles = { done: "Step done", not_yet: "Not yet", unclear: "Not sure" };
          var badges = { done: "✓", not_yet: "!", unclear: "?" };
          showToast(result.data.verdict, titles[result.data.verdict] || "Result", result.data.message, badges[result.data.verdict] || "?");
        })
        .catch(function () { showToast("error", "No connection", "Please try again.", "!"); })
        .finally(function () { input.value = ""; });
    });
  });

  var repair = document.getElementById("repair");
  var steps = Array.prototype.map.call(document.querySelectorAll("article.step"), function (article) {
    var photo = article.querySelector("[data-view-panel='photo'] img");
    var clip = article.querySelector("[data-view-panel='clip'] video");
    return {
      title: article.querySelector(".h3").textContent,
      text: article.querySelector(".instruction").textContent,
      warnings: Array.prototype.map.call(article.querySelectorAll(".step-body .warn"), function (w) { return w.textContent; }),
      photo: photo ? photo.getAttribute("src") : null,
      clip: clip ? clip.getAttribute("src") : null,
    };
  });
  var current = 0;
  function renderRepair() {
    var step = steps[current];
    document.getElementById("repair-count").textContent = (current + 1) + " / " + steps.length;
    document.getElementById("repair-bars").innerHTML = steps.map(function (_, i) { return '<i class="' + (i <= current ? "on" : "") + '"></i>'; }).join("");
    var media = document.getElementById("repair-media");
    media.innerHTML = "";
    if (step.clip || step.photo) {
      var stage = document.createElement("div");
      stage.className = "stage";
      var el = document.createElement(step.clip ? "video" : "img");
      el.className = "fit";
      el.src = step.clip || step.photo;
      if (step.clip) { el.muted = true; el.loop = true; el.playsInline = true; el.autoplay = true; }
      else { el.alt = step.title; }
      stage.appendChild(el);
      media.appendChild(stage);
    }
    document.getElementById("repair-text").textContent = (current + 1) + ". " + step.text;
    document.getElementById("repair-warn").innerHTML = "";
    step.warnings.forEach(function (w) {
      var div = document.createElement("div"); div.className = "warn"; div.textContent = w;
      document.getElementById("repair-warn").appendChild(div);
    });
    repair.querySelector("[data-repair-prev]").disabled = current === 0;
    repair.querySelector("[data-repair-next]").textContent = current === steps.length - 1 ? "Done" : "Next step";
  }
  function openRepair(index) {
    if (!steps.length) return;
    current = Math.max(0, Math.min(steps.length - 1, index));
    repair.classList.add("open");
    document.body.style.overflow = "hidden";
    renderRepair();
  }
  function closeRepair() { repair.classList.remove("open"); document.body.style.overflow = ""; }
  function go(delta) {
    if (current + delta >= steps.length) { closeRepair(); return; }
    current = Math.max(0, current + delta);
    renderRepair();
  }
  document.querySelectorAll("[data-repair-open]").forEach(function (b) {
    b.addEventListener("click", function () { openRepair(parseInt(b.dataset.repairOpen, 10) || 0); });
  });
  repair.querySelector("[data-repair-close]").addEventListener("click", closeRepair);
  repair.querySelector("[data-repair-prev]").addEventListener("click", function () { go(-1); });
  repair.querySelector("[data-repair-next]").addEventListener("click", function () { go(1); });
  document.addEventListener("keydown", function (e) {
    if (!repair.classList.contains("open")) return;
    if (e.key === "Escape") closeRepair();
    if (e.key === "ArrowRight") go(1);
    if (e.key === "ArrowLeft") go(-1);
  });
  var touchX = null;
  repair.addEventListener("touchstart", function (e) { touchX = e.touches[0].clientX; }, { passive: true });
  repair.addEventListener("touchend", function (e) {
    if (touchX === null) return;
    var dx = e.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 60) go(dx < 0 ? 1 : -1);
    touchX = null;
  });
})();
