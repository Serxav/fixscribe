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
  var STEADY = 5; // below this the view is held still: hands moving would give a blurred, wrong mark
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
  var waiting = null; // the last answer, until the view holds still long enough to mark its parts
  var stillSample = null;
  var stillSince = Date.now();
  var lastSaid = "";
  var micOn = false;
  var hearing = false;
  var voice = window.FixVoice.player(jobId, lang, root.dataset.metaVoice === "yes");

  function say(text, first) {
    if (!voiceOn || !text) return;
    if (first) voice.cancel();
    lastSaid = plain(text);
    voice.say(text);
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
  function drawMarks(parts, sample, checked) {
    var svg = $("live-marks");
    var video = $("live-camera");
    var w = video.videoWidth, h = video.videoHeight;
    svg.innerHTML = "";
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    // Sizes in screen pixels, whatever the camera's resolution: names stay small, as on the landing.
    var unit = 1 / Math.max(svg.clientWidth / w, svg.clientHeight / h);
    parts.forEach(function (part, i) {
      var points = part.outline.map(function (p) { return [p[0] * w / 1000, p[1] * h / 1000]; });
      var cx = points.reduce(function (a, p) { return a + p[0]; }, 0) / points.length;
      var cy = points.reduce(function (a, p) { return a + p[1]; }, 0) / points.length;
      var top = Math.min.apply(null, points.map(function (p) { return p[1]; }));
      var g = node("g", { "class": "live-part" + (part.target ? " target" : "") + (checked ? "" : " checking"), style: "--i:" + i }, svg);
      node("polygon", { points: points.map(function (p) { return p.join(","); }).join(" ") }, g);
      node("path", { d: "M" + cx + " " + cy + "L" + cx + " " + top, "class": "live-lead" }, g);
      node("circle", { cx: cx, cy: cy, r: 5 * unit }, g);
      var size = 13 * unit, high = 24 * unit;
      var width = (part.label.length * 0.62 * size) + 24 * unit;
      var left = Math.max(0, Math.min(w - width, cx - width / 2));
      var y = Math.max(0, top - high);
      node("rect", { x: left, y: y, width: width, height: high, rx: 14 * unit }, g);
      var text = node("text", { x: left + 12 * unit, y: y + 16.5 * unit, "font-size": size }, g);
      text.textContent = part.label + (checked ? "" : "…");
    });
    marksSample = parts.length ? sample : null;
    svg.classList.remove("stale");
  }

  // The answer comes one JSON line at a time: the cut-outs first, the confirmed ones after.
  function readLines(response, onLine) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var held = "";
    function pump() {
      return reader.read().then(function (part) {
        held += decoder.decode(part.value || new Uint8Array(), { stream: !part.done });
        var lines = held.split("\n");
        held = lines.pop();
        lines.forEach(function (line) { if (line.trim()) onLine(JSON.parse(line)); });
        return part.done ? null : pump();
      });
    }
    return pump();
  }

  // The parts take longer than the step: asked once per still view, drawn only if it stayed.
  function askMarks(answer, sample, blob) {
    var video = $("live-camera");
    var step = answer.step || current;
    if (!answer.object_box || !answer.object_box.length) return;
    if (step === askedStep && apart(sample, askedSample) <= MOVED) return;
    marksBusy = true;
    askedSample = sample;
    askedStep = step;
    var form = new FormData();
    form.append("frame", blob, "frame.jpg");
    form.append("step", String(step));
    form.append("region", answer.object_box.join(","));
    fetch("/api/live/" + jobId + "/marks", { method: "POST", body: form })
      .then(function (r) {
        if (!r.ok) return;
        return readLines(r, function (line) {
          if (apart(grey(video), sample) <= MOVED) drawMarks(line.parts || [], sample, line.checked);
        });
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
    waiting = { answer: answer, sample: sample, blob: blob };
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

  function snapshot(video, done) {
    var canvas = $("live-canvas");
    var scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(done, "image/jpeg", 0.85);
  }

  function send(video, sample) {
    busy = true;
    sentAt = Date.now();
    sentSample = sample;
    $("live-dot").className = "live-dot busy";
    snapshot(video, function (blob) {
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
    });
  }

  function plain(text) {
    return text.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
  }

  function setVoice(on) {
    voiceOn = on;
    $("live-voice").setAttribute("aria-pressed", String(on));
    $("live-voice").textContent = on ? "🔊" : "🔇";
    if (!on) voice.cancel();
  }

  // Next, back and repeat move the manual; a question gets its answer on the screen and out loud.
  function obey(res) {
    if (res.command === "none" || !res.heard) return;
    // The microphone can catch the coach itself: its own words are not an order.
    if (voice.speaking() && (" " + lastSaid + " ").indexOf(" " + plain(res.heard) + " ") >= 0) return;
    $("live-heard").textContent = "“" + res.heard + "”";
    if (res.command === "next") enterStep(Math.min(steps.length, current + 1), true);
    if (res.command === "back") enterStep(Math.max(1, current - 1), true);
    if (res.command === "repeat" && current) enterStep(current, true);
    if (res.command === "quiet") setVoice(false);
    if (res.command === "question" && res.answer) {
      $("live-say").textContent = res.answer;
      say(res.answer, true);
    }
  }

  function heardClip(wav) {
    if (!micOn || hearing) return;
    hearing = true;
    $("live-mic").classList.add("busy");
    var video = $("live-camera");
    var post = function (picture) {
      var form = new FormData();
      form.append("audio", wav, "voice.wav");
      if (picture) form.append("frame", picture, "frame.jpg");
      form.append("step", String(current));
      fetch("/api/live/" + jobId + "/hear", { method: "POST", body: form })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) { if (res.ok) obey(res.d); })
        .catch(function () {})
        .finally(function () { hearing = false; $("live-mic").classList.remove("busy"); });
    };
    if (video.videoWidth) { snapshot(video, post); } else { post(null); }
  }

  function tick() {
    var video = $("live-camera");
    if (!video.videoWidth || document.hidden) return;
    var sample = grey(video);
    var now = Date.now();
    // The marks belong to the frame they were cut on: they go when the view does.
    $("live-marks").classList.toggle("stale", !!marksSample && apart(sample, marksSample) > MOVED);
    if (apart(sample, stillSample) > MOVED) { stillSample = sample; stillSince = now; }
    if (waiting && !marksBusy && apart(sample, waiting.sample) <= STEADY) {
      askMarks(waiting.answer, waiting.sample, waiting.blob);
      waiting = null;
    }
    if (busy || now - sentAt < MIN_GAP_MS) return;
    var isNew = apart(sample, sentSample) > MOVED;
    var refresh = now - sentAt >= STILL_REFRESH_MS && now - stillSince < STILL_PAUSE_MS;
    if (isNew || refresh) send(video, sample);
  }

  $("live-prev").addEventListener("click", function () { enterStep(Math.max(1, current - 1), true); });
  $("live-next-step").addEventListener("click", function () { enterStep(Math.min(steps.length, current + 1), true); });
  $("live-repeat").addEventListener("click", function () { if (current) enterStep(current, true); });
  $("live-voice").addEventListener("click", function () { setVoice(!voiceOn); });

  var ear = window.FixEar(heardClip);
  $("live-mic").addEventListener("click", function () {
    if (micOn) {
      micOn = false;
      ear.stop();
      $("live-mic").setAttribute("aria-pressed", "false");
      $("live-mic").classList.remove("on");
      $("live-hint").textContent = "";
      return;
    }
    $("live-hint").textContent = "Opening the microphone…";
    var late = new Promise(function (_, refuse) { setTimeout(refuse, 8000); });
    Promise.race([ear.start(), late]).then(function () {
      micOn = true;
      $("live-mic").setAttribute("aria-pressed", "true");
      $("live-mic").classList.add("on");
      $("live-hint").textContent = "Say “next”, “back”, “repeat”, or ask a question.";
    }).catch(function () {
      $("live-hint").textContent = "The microphone is not available: use the buttons.";
    });
  });

  function begin() {
    $("live-start").classList.add("gone");
    $("live-panel").classList.remove("hidden");
    $("live-dot").className = "live-dot on";
    drawRail();
    // The manual sits under the picture, never over the parts it marks.
    var fit = function () {
      root.style.setProperty("--panel", $("live-panel").getBoundingClientRect().height + 24 + "px");
    };
    fit();
    if (window.ResizeObserver) new ResizeObserver(fit).observe($("live-panel"));
    setInterval(tick, CHECK_MS);
  }

  $("live-go").addEventListener("click", function () {
    voice.unlock();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      $("live-start").querySelector(".film-card-text").textContent =
        "This browser cannot open the camera here. Open FixScribe over https or on this computer (localhost).";
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false })
      .then(function (stream) {
        $("live-camera").srcObject = stream;
        begin();
      })
      .catch(function () {
        $("live-start").querySelector(".film-card-text").textContent = "Camera permission was refused.";
      });
  });

  // No object at hand: the guide's own video stands in for the camera. Parts are only marked on a
  // still view, so holding the video is how they show.
  $("live-sample").addEventListener("click", function () {
    voice.unlock();
    var video = $("live-camera");
    video.src = root.dataset.video;
    video.loop = true;
    video.play().catch(function () {});
    $("live-hold").classList.remove("hidden");
    $("live-hint").textContent = "This is the guide's own video, not your camera. Hold it to see the parts marked.";
    begin();
  });

  $("live-hold").addEventListener("click", function () {
    var video = $("live-camera");
    if (video.paused) { video.play().catch(function () {}); } else { video.pause(); }
    $("live-hold").textContent = video.paused ? "▶" : "⏸";
  });
})();
