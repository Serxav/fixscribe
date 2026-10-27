// Repair film: plays the SAM motion clips step by step, with captions and the device voice.
// "Take apart" plays the steps in order; "Put back" plays them in reverse order, each clip
// backwards, with the assembly lines.
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("film-data").textContent);
  var $ = function (id) { return document.getElementById(id); };
  var video = $("film-video");
  var synth = window.speechSynthesis || null;
  var mode = "apart";
  var index = -1; // -1 = intro card
  var playing = false;
  var voiceOn = true;
  var token = 0; // cancels the timers of a step we left
  var MIN_STEP_MS = 4500;

  function order() {
    return mode === "apart" ? data.steps : data.steps.slice().reverse();
  }

  // The best voice the device has for the film language. Neural voices first ("Premium",
  // "Enhanced", "Natural", "Neural"), robotic ones last ("Compact", eSpeak, novelty voices).
  var GOOD = [/premium/i, /enhanced|mejorada|améliorée|optimierte/i, /natural/i, /neural/i, /siri/i, /google/i];
  var BAD = [/compact/i, /espeak/i, /albert|bad news|bahh|bells|boing|bubbles|cellos|good news|jester|organ|superstar|trinoids|whisper|wobble|zarvox|fred|junior|ralph|kathy/i];
  var chosen = null;
  function score(v) {
    var s = 0;
    GOOD.forEach(function (re, i) { if (re.test(v.name)) s += 60 - i * 8; });
    BAD.forEach(function (re) { if (re.test(v.name)) s -= 100; });
    if (v.localService) s += 3;
    return s;
  }
  function pickVoice() {
    if (!synth) return null;
    if (chosen) return chosen;
    var lang = (data.language || "en").toLowerCase().split("-")[0];
    var voices = synth.getVoices().filter(function (v) { return v.lang.toLowerCase().indexOf(lang) === 0; });
    if (!voices.length) return null;
    chosen = voices.sort(function (a, b) { return score(b) - score(a); })[0];
    var label = $("film-voice-name");
    if (label) {
      label.textContent = "Voice: " + chosen.name + (score(chosen) < 20 ? " — for a more natural voice, install a Premium/Enhanced voice in your system settings (Spoken Content)." : "");
    }
    return chosen;
  }

  // Speak sentence by sentence with a short breath in between: it sounds far less robotic.
  function speak(text, done) {
    if (!synth || !voiceOn || !text) { setTimeout(done, Math.max(MIN_STEP_MS, (text || "").split(" ").length * 380)); return; }
    synth.cancel();
    var sentences = text.match(/[^.!?…]+[.!?…]*/g) || [text];
    var voice = pickVoice();
    var mine = ++speechToken;
    (function next(i) {
      if (mine !== speechToken) return;
      if (i >= sentences.length) { done(); return; }
      var utterance = new SpeechSynthesisUtterance(sentences[i].trim());
      if (voice) utterance.voice = voice;
      utterance.lang = voice ? voice.lang : data.language || "en";
      utterance.rate = 0.94;
      utterance.pitch = 1.0;
      utterance.onend = function () { setTimeout(function () { next(i + 1); }, 260); };
      utterance.onerror = function () { next(i + 1); };
      synth.speak(utterance);
    })(0);
  }
  var speechToken = 0;

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
    if (i >= steps.length) { // the end
      video.pause();
      playing = false;
      $("film-toggle").textContent = "▶";
      var outro = mode === "apart" ? data.outro : data.outro_back;
      showCard(mode === "apart" ? "Taken apart" : "Put back together", data.title, outro);
      $("film-start").textContent = mode === "apart" ? "▶ Now put it back" : "▶ Watch again";
      speak(outro, function () {});
      return;
    }
    var step = steps[i];
    $("film-card").classList.add("gone");
    $("film-caption").classList.remove("hidden");
    $("film-step").textContent = (mode === "apart" ? "Step " : "Put back · step ") + step.index + " · " + step.title;
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
      video.loop = !ownVoice; // with the real voice, play the moment once, as it was said
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
      speak(data.intro, function () {});
      setTimeout(function () { playStep(0); }, 2200);
    } else {
      playStep(index);
    }
  }

  function go(i) {
    playing = true;
    $("film-toggle").textContent = "⏸";
    if (synth) synth.cancel();
    playStep(Math.max(0, Math.min(order().length - 1, i)));
  }

  $("film-start").addEventListener("click", function () {
    if (index >= order().length && mode === "apart") { setMode("back"); }
    index = -1;
    start();
  });
  $("film-toggle").addEventListener("click", function () {
    playing = !playing;
    $("film-toggle").textContent = playing ? "⏸" : "▶";
    if (playing) { video.play().catch(function () {}); if (synth) synth.resume(); if (index === -1) start(); }
    else { video.pause(); if (synth) synth.pause(); }
  });
  $("film-prev").addEventListener("click", function () { go(index - 1); });
  $("film-next").addEventListener("click", function () { go(index + 1); });
  $("film-voice").addEventListener("click", function () {
    voiceOn = !voiceOn;
    $("film-voice").setAttribute("aria-pressed", String(voiceOn));
    $("film-voice").textContent = voiceOn ? "🔊" : "🔇";
    if (!voiceOn && synth) synth.cancel();
    video.muted = !voiceOn || video.loop; // the real voice clips are the ones that do not loop
  });

  function setMode(next) {
    mode = next;
    document.querySelectorAll("[data-mode]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.mode === mode)); });
    $("film-mode-label").textContent = mode === "apart" ? "Take apart" : "Put back";
    token++;
    if (synth) synth.cancel();
    index = -1;
    drawRail();
    showCard(mode === "apart" ? "FixScribe film" : "Putting it back", data.title, mode === "apart" ? data.intro : "The same repair, backwards: every part and every fastener back in its place.");
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
  if (synth) synth.onvoiceschanged = function () { chosen = null; pickVoice(); };
  pickVoice();
  var first = data.steps[0];
  if (first && first.poster) video.poster = first.poster;
  if (new URLSearchParams(location.search).get("mode") === "back") setMode("back");
  drawRail();
})();
