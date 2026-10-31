(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("film-data").textContent);
  var $ = function (id) { return document.getElementById(id); };
  var video = $("film-video");
  var synth = window.speechSynthesis || null;
  var voice = window.FixVoice.player(location.pathname.split("/")[2], data.language, !!data.meta_voice);
  var mode = "apart";
  var index = -1;
  var playing = false;
  var voiceOn = true;
  var token = 0;
  var MIN_STEP_MS = 4500;

  function order() {
    return mode === "apart" ? data.steps : data.steps.slice().reverse();
  }

  function showVoice() {
    var label = $("film-voice-name");
    if (!label) return;
    var text = voice.label();
    var chosen = !data.meta_voice && synth ? window.FixVoice.pick(synth, data.language) : null;
    label.textContent = text + (chosen && window.FixVoice.score(chosen) < 20 ? " — for a more natural voice, install a Premium/Enhanced voice in your system settings (Spoken Content)." : "");
  }

  function speak(text, done) {
    if (!voice.ready() || !voiceOn || !text) { setTimeout(done, Math.max(MIN_STEP_MS, (text || "").split(" ").length * 380)); return; }
    voice.cancel();
    voice.say(text, done);
  }

  function drawRail() {
    var steps = order();
    $("film-rail").innerHTML = steps.map(function (s, i) {
      return '<button type="button" data-i="' + i + '" class="' + (i < index ? "done" : "") + '" aria-label="Step ' + s.index + '"><i></i></button>';
    }).join("");
    $("film-rail").querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () { go(parseInt(b.dataset.i, 10)); });
    });
  }

  function progress(fraction) {
    var bar = $("film-rail").querySelector('button[data-i="' + index + '"] i');
    if (bar) bar.style.width = Math.min(100, fraction * 100) + "%";
  }

  function showCard(kicker, title, text) {
    $("film-kicker").textContent = kicker;
    $("film-card-title").textContent = title;
    $("film-card-text").textContent = text;
    $("film-card").classList.remove("gone");
    $("film-caption").classList.add("hidden");
  }

  function playStep(i) {
    var steps = order();
    var mine = ++token;
    index = i;
    drawRail();
    if (i >= steps.length) {
      video.pause();
      playing = false;
      $("film-toggle").textContent = "▶";
      var outro = mode === "apart" ? data.outro : data.outro_back;
      showCard(mode === "apart" ? "Done" : "Done", data.title, outro);
      $("film-start").textContent = mode === "apart" ? "▶ Now: " + data.backward_label : "▶ Watch again";
      speak(outro, function () {});
      return;
    }
    var step = steps[i];
    $("film-card").classList.add("gone");
    $("film-caption").classList.remove("hidden");
    $("film-step").textContent = (mode === "apart" ? "Step " : data.backward_label + " · step ") + step.index + " · " + step.title;
    var ownVoice = mode === "apart" && step.voice;
    var line = mode === "apart" ? (ownVoice && step.words ? step.words : step.say) : step.say_back;
    $("film-line").textContent = line;
    var warn = step.warnings && step.warnings.length ? "⚠︎ " + step.warnings[0] : "";
    $("film-warn").textContent = warn;
    $("film-warn").classList.toggle("hidden", !warn);
    var src = mode === "apart" ? step.clip : step.reverse;
    var clipDone = !ownVoice;
    if (src) {
      video.src = src;
      video.poster = step.poster || "";
      video.loop = !ownVoice;
      video.muted = !ownVoice || !voiceOn;
      video.onended = function () { clipDone = true; };
      video.play().catch(function () { video.muted = true; video.play().catch(function () {}); });
    }
    var started = Date.now();
    var spoken = false;
    var tick = setInterval(function () {
      if (mine !== token) { clearInterval(tick); return; }
      progress((Date.now() - started) / Math.max(MIN_STEP_MS, 1));
    }, 120);
    if (ownVoice) { spoken = true; } else { speak(line, function () { spoken = true; }); }
    (function waitThenNext() {
      if (mine !== token) return;
      if (!playing) { setTimeout(waitThenNext, 300); return; }
      if (spoken && clipDone && Date.now() - started >= MIN_STEP_MS) { clearInterval(tick); playStep(i + 1); return; }
      setTimeout(waitThenNext, 250);
    })();
  }

  function start() {
    playing = true;
    $("film-toggle").textContent = "⏸";
    if (index >= order().length) index = -1;
    if (data.blocked) {
      showCard("Professional only", data.title, data.intro);
      speak(data.intro, function () {});
      return;
    }
    if (index === -1) {
      var opening = token;
      speak(data.intro, function () { if (opening === token && playing) playStep(0); });
    } else {
      playStep(index);
    }
  }

  function go(i) {
    playing = true;
    $("film-toggle").textContent = "⏸";
    voice.cancel();
    playStep(Math.max(0, Math.min(order().length - 1, i)));
  }

  $("film-start").addEventListener("click", function () {
    voice.unlock();
    if (index >= order().length && mode === "apart") { setMode("back"); }
    index = -1;
    start();
  });
  $("film-toggle").addEventListener("click", function () {
    playing = !playing;
    $("film-toggle").textContent = playing ? "⏸" : "▶";
    if (playing) { video.play().catch(function () {}); voice.resume(); if (index === -1) start(); }
    else { video.pause(); voice.pause(); }
  });
  $("film-prev").addEventListener("click", function () { go(index - 1); });
  $("film-next").addEventListener("click", function () { go(index + 1); });
  $("film-voice").addEventListener("click", function () {
    voiceOn = !voiceOn;
    $("film-voice").setAttribute("aria-pressed", String(voiceOn));
    $("film-voice").textContent = voiceOn ? "🔊" : "🔇";
    if (!voiceOn) voice.cancel(true);
    video.muted = !voiceOn || video.loop;
  });

  function setMode(next) {
    mode = next;
    document.querySelectorAll("[data-mode]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.mode === mode)); });
    $("film-mode-label").textContent = mode === "apart" ? data.forward_label : data.backward_label;
    token++;
    voice.cancel();
    index = -1;
    drawRail();
    showCard(mode === "apart" ? "FixScribe film" : data.backward_label, data.title, mode === "apart" ? data.intro : "The same video, backwards, step by step: every part and every fastener.");
    $("film-start").textContent = "▶ Play with voice";
  }
  document.querySelectorAll("[data-mode]").forEach(function (b) {
    b.addEventListener("click", function () { setMode(b.dataset.mode); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === " ") { e.preventDefault(); $("film-toggle").click(); }
    if (e.key === "ArrowRight") go(index + 1);
    if (e.key === "ArrowLeft") go(index - 1);
  });
  if (synth) synth.onvoiceschanged = showVoice;
  showVoice();
  var first = data.steps[0];
  if (first && first.poster) video.poster = first.poster;
  if (new URLSearchParams(location.search).get("mode") === "back") setMode("back");
  drawRail();
})();
