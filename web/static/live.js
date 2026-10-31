(function () {
  "use strict";
  var root = document.getElementById("live");
  var $ = function (id) { return document.getElementById(id); };
  var jobId = root.dataset.jobId;
  var lang = (root.dataset.lang || "en").toLowerCase();
  var steps = JSON.parse($("live-steps").textContent);
  var SVG = "http://www.w3.org/2000/svg";
  var CHECK_MS = 500;
  var MIN_GAP_MS = 2500; // never faster than this
  var STILL_REFRESH_MS = 15000; // an unchanged view is looked at again this often
  var STILL_PAUSE_MS = 120000; // nothing moved for this long: stop spending until it does
  var MOVED = 14; // mean grey difference that means the camera shows something else
  var STATUS = { on_track: "On track", done_step: "Step done", wrong: "Check this", unclear: "Looking…" };

  var current = 0;
  var pending = 0;
  var lastStatus = "";
  var voiceOn = true;
  var busy = false;
  var sentAt = 0;
  var sentSample = null;
  var marksSample = null;
  var askedSample = null;
  var askedStep = 0;
  var marksBusy = false;
  var stillSample = null;
  var stillSince = Date.now();
  var synth = window.speechSynthesis || null;

  function bestVoice() {
    if (!synth) return null;
    var voices = synth.getVoices().filter(function (v) { return v.lang.toLowerCase().indexOf(lang.split("-")[0]) === 0; });
    var good = /premium|enhanced|mejorada|natural|neural|siri|google/i, bad = /compact|espeak/i;
    voices.sort(function (a, b) { return (good.test(b.name) - bad.test(b.name)) - (good.test(a.name) - bad.test(a.name)); });
    return voices[0] || null;
  }

  function say(text, first) {
    if (!synth || !voiceOn || !text) return;
    if (first) synth.cancel();
    var u = new SpeechSynthesisUtterance(text);
    var v = bestVoice();
    if (v) u.voice = v;
    u.lang = v ? v.lang : lang;
    u.rate = 0.95;
    synth.speak(u);
  }

  function byIndex(n) {
    return steps.filter(function (s) { return s.index === n; })[0] || null;
  }

  function drawRail() {
    $("live-rail").innerHTML = "";
    steps.forEach(function (s) {
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("aria-label", "Step " + s.index);
      b.className = s.index < current ? "done" : s.index === current ? "now" : "";
      b.appendChild(document.createElement("i"));
      b.addEventListener("click", function () { enterStep(s.index, true); });
      $("live-rail").appendChild(b);
    });
  }

  // A new step: show the manual's own words and read them out, with the first warning.
  function enterStep(n, byHand) {
    var step = byIndex(n);
    if (!step) return;
    current = n;
    if (byHand) { pending = 0; clearMarks(); }
    lastStatus = "";
    $("live-step").textContent = "Step " + n + " of " + steps.length;
    $("live-title").textContent = step.title;
    $("live-instruction").textContent = step.instruction;
    var warn = step.warnings && step.warnings.length ? step.warnings[0] : "";
    $("live-warn").textContent = warn ? "⚠︎ " + warn : "";
    $("live-warn").classList.toggle("hidden", !warn);
    $("live-photo").classList.toggle("hidden", !step.photo);
    if (step.photo) $("live-photo").src = step.photo;
    $("live-say").textContent = "";
    $("live-next").textContent = "";
    drawRail();
    say(step.title + ". " + step.instruction + (warn ? " " + warn : ""), true);
  }

  function clearMarks() {
    $("live-marks").innerHTML = "";
    marksSample = null;
  }

  function node(name, attrs, parent) {
    var el = document.createElementNS(SVG, name);
    Object.keys(attrs).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    parent.appendChild(el);
    return el;
  }

  // Drawn like the landing photos: outline, dot on the part, a line up to its name.
  function drawMarks(parts, sample) {
    var svg = $("live-marks");
    var video = $("live-camera");
    var w = video.videoWidth, h = video.videoHeight;
    svg.innerHTML = "";
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    var unit = Math.max(w, h) / 1000;
    parts.forEach(function (part, i) {
      var points = part.outline.map(function (p) { return [p[0] * w / 1000, p[1] * h / 1000]; });
      var cx = points.reduce(function (a, p) { return a + p[0]; }, 0) / points.length;
      var cy = points.reduce(function (a, p) { return a + p[1]; }, 0) / points.length;
      var top = Math.min.apply(null, points.map(function (p) { return p[1]; }));
      var g = node("g", { "class": "live-part" + (part.target ? " target" : ""), style: "--i:" + i }, svg);
      node("polygon", { points: points.map(function (p) { return p.join(","); }).join(" ") }, g);
      node("path", { d: "M" + cx + " " + cy + "L" + cx + " " + top, "class": "live-lead" }, g);
      node("circle", { cx: cx, cy: cy, r: 5 * unit }, g);
      var size = 15 * unit, high = 28 * unit;
      var width = (part.label.length * 0.62 * size) + 24 * unit;
      var left = Math.max(0, Math.min(w - width, cx - width / 2));
      var y = Math.max(0, top - high);
      node("rect", { x: left, y: y, width: width, height: high, rx: 14 * unit }, g);
      var text = node("text", { x: left + 12 * unit, y: y + 19 * unit, "font-size": size }, g);
      text.textContent = part.label;
    });
    marksSample = parts.length ? sample : null;
    svg.classList.remove("stale");
  }

  // The parts take longer than the step: asked once per still view, drawn only if it stayed.
  function askMarks(answer, sample, blob) {
    var video = $("live-camera");
    var step = answer.step || current;
    if (marksBusy || !answer.object_box || !answer.object_box.length) return;
    if (apart(grey(video), sample) > MOVED) return;
    if (step === askedStep && apart(sample, askedSample) <= MOVED) return;
    marksBusy = true;
    askedSample = sample;
    askedStep = step;
    var form = new FormData();
    form.append("frame", blob, "frame.jpg");
    form.append("step", String(step));
    form.append("region", answer.object_box.join(","));
    fetch("/api/live/" + jobId + "/marks", { method: "POST", body: form })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && apart(grey(video), sample) <= MOVED) drawMarks(res.d.parts || [], sample);
      })
      .catch(function () {})
      .finally(function () { marksBusy = false; });
  }

  function show(answer, sample, blob) {
    pending = answer.pending || 0;
    if (answer.step && answer.step !== current) enterStep(answer.step, false);
    var status = $("live-status");
    status.className = "live-status " + answer.status;
    status.textContent = STATUS[answer.status] || "";
    if (answer.say) $("live-say").textContent = answer.say;
    if (answer.next) $("live-next").textContent = "Next: " + answer.next;
    askMarks(answer, sample, blob);
    // Only news is spoken: a coach that keeps talking is not listened to.
    if (answer.status !== lastStatus && (answer.status === "wrong" || answer.status === "done_step")) say(answer.say, false);
    if (answer.status !== "unclear") lastStatus = answer.status;
  }

  // A tiny grey copy of the view, to know whether the camera shows something new.
  function grey(video) {
    var small = $("live-small");
    var ctx = small.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, 0, 0, small.width, small.height);
    var rgba = ctx.getImageData(0, 0, small.width, small.height).data;
    var out = new Uint8Array(small.width * small.height);
    for (var i = 0; i < out.length; i++) out[i] = (rgba[i * 4] + rgba[i * 4 + 1] + rgba[i * 4 + 2]) / 3;
    return out;
  }

  function apart(a, b) {
    if (!a || !b) return 255;
    var sum = 0;
    for (var i = 0; i < a.length; i++) sum += Math.abs(a[i] - b[i]);
    return sum / a.length;
  }

  function send(video, sample) {
    busy = true;
    sentAt = Date.now();
    sentSample = sample;
    $("live-dot").className = "live-dot busy";
    var canvas = $("live-canvas");
    var scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(function (blob) {
      var form = new FormData();
      form.append("frame", blob, "frame.jpg");
      form.append("last_step", String(current));
      form.append("pending_step", String(pending));
      fetch("/api/live/" + jobId, { method: "POST", body: form })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (res.ok) { show(res.d, sample, blob); } else { $("live-say").textContent = res.d.error || "Could not read the frame."; }
        })
        .catch(function () { $("live-say").textContent = "No connection."; })
        .finally(function () { busy = false; $("live-dot").className = "live-dot on"; });
    }, "image/jpeg", 0.85);
  }

  function tick() {
    var video = $("live-camera");
    if (!video.videoWidth || document.hidden) return;
    var sample = grey(video);
    var now = Date.now();
    // The marks belong to the frame they were cut on: they go when the view does.
    $("live-marks").classList.toggle("stale", !!marksSample && apart(sample, marksSample) > MOVED);
    if (apart(sample, stillSample) > MOVED) { stillSample = sample; stillSince = now; }
    if (busy || now - sentAt < MIN_GAP_MS) return;
    var isNew = apart(sample, sentSample) > MOVED;
    var refresh = now - sentAt >= STILL_REFRESH_MS && now - stillSince < STILL_PAUSE_MS;
    if (isNew || refresh) send(video, sample);
  }

  $("live-prev").addEventListener("click", function () { enterStep(Math.max(1, current - 1), true); });
  $("live-next-step").addEventListener("click", function () { enterStep(Math.min(steps.length, current + 1), true); });
  $("live-repeat").addEventListener("click", function () { if (current) enterStep(current, true); });
  $("live-voice").addEventListener("click", function () {
    voiceOn = !voiceOn;
    $("live-voice").setAttribute("aria-pressed", String(voiceOn));
    $("live-voice").textContent = voiceOn ? "🔊" : "🔇";
    if (!voiceOn && synth) synth.cancel();
  });

  $("live-go").addEventListener("click", function () {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $("live-start").querySelector(".film-card-text").textContent =
        "This browser cannot open the camera here. Open FixScribe over https or on this computer (localhost).";
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false })
      .then(function (stream) {
        $("live-camera").srcObject = stream;
        $("live-start").classList.add("gone");
        $("live-panel").classList.remove("hidden");
        $("live-dot").className = "live-dot on";
        if (synth) synth.getVoices();
        drawRail();
        setInterval(tick, CHECK_MS);
      })
      .catch(function () {
        $("live-start").querySelector(".film-card-text").textContent = "Camera permission was refused.";
      });
  });
})();
