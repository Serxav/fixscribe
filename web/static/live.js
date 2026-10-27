(function () {
  "use strict";
  var root = document.getElementById("live");
  var $ = function (id) { return document.getElementById(id); };
  var jobId = root.dataset.jobId;
  var lang = (root.dataset.lang || "en").toLowerCase();
  var EVERY_MS = 2500;
  var lastStep = 0;
  var lastSaid = "";
  var busy = false;
  var synth = window.speechSynthesis || null;
  var STATUS = { on_track: "On track", done_step: "Step done", wrong: "Check this", unclear: "Not sure" };

  function bestVoice() {
    if (!synth) return null;
    var voices = synth.getVoices().filter(function (v) { return v.lang.toLowerCase().indexOf(lang.split("-")[0]) === 0; });
    var good = /premium|enhanced|mejorada|natural|neural|siri|google/i, bad = /compact|espeak/i;
    voices.sort(function (a, b) { return (good.test(b.name) - bad.test(b.name)) - (good.test(a.name) - bad.test(a.name)); });
    return voices[0] || null;
  }

  function say(text) {
    if (!synth || !text || text === lastSaid) return;
    lastSaid = text;
    synth.cancel();
    var u = new SpeechSynthesisUtterance(text);
    var v = bestVoice();
    if (v) u.voice = v;
    u.lang = v ? v.lang : lang;
    u.rate = 0.95;
    synth.speak(u);
  }

  function show(answer) {
    $("live-step").textContent = answer.step ? "Step " + answer.step + " of " + root.dataset.steps : "Looking…";
    var status = $("live-status");
    status.className = "live-status " + answer.status;
    status.textContent = STATUS[answer.status] || "";
    if (answer.say) $("live-say").textContent = answer.say;
    $("live-next").textContent = answer.next ? "Next: " + answer.next : "";
    if (answer.step) lastStep = answer.step;
    if (answer.status !== "unclear") say(answer.say);
  }

  function tick() {
    var video = $("live-camera");
    if (busy || !video.videoWidth) return;
    busy = true;
    $("live-dot").className = "live-dot busy";
    var canvas = $("live-canvas");
    var scale = Math.min(1, 768 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(function (blob) {
      var form = new FormData();
      form.append("frame", blob, "frame.jpg");
      form.append("last_step", String(lastStep));
      fetch("/api/live/" + jobId, { method: "POST", body: form })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (res.ok) { show(res.d); } else { $("live-say").textContent = res.d.error || "Could not read the frame."; }
        })
        .catch(function () { $("live-say").textContent = "No connection."; })
        .finally(function () { busy = false; $("live-dot").className = "live-dot on"; });
    }, "image/jpeg", 0.8);
  }

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
        setInterval(tick, EVERY_MS);
      })
      .catch(function () {
        $("live-start").querySelector(".film-card-text").textContent = "Camera permission was refused.";
      });
  });
})();
