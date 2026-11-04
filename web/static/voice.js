// The best voice this device offers for a language: the same choice for the film and the coach.
window.FixVoice = (function () {
  "use strict";
  var GOOD = [/premium/i, /enhanced|mejorada|améliorée|optimierte/i, /natural/i, /neural/i, /siri/i, /google/i];
  var BAD = [/compact/i, /espeak/i, /albert|bad news|bahh|bells|boing|bubbles|cellos|good news|jester|organ|superstar|trinoids|whisper|wobble|zarvox|fred|junior|ralph|kathy/i];
  function score(v) {
    var s = 0;
    GOOD.forEach(function (re, i) { if (re.test(v.name)) s += 60 - i * 8; });
    BAD.forEach(function (re) { if (re.test(v.name)) s -= 100; });
    if (v.localService) s += 3;
    return s;
  }
  function pick(synth, language) {
    if (!synth) return null;
    var lang = (language || "en").toLowerCase().split("-")[0];
    var voices = synth.getVoices().filter(function (v) { return v.lang.toLowerCase().indexOf(lang) === 0; });
    return voices.sort(function (a, b) { return score(b) - score(a); })[0] || null;
  }

  // Says lines one after another with the device's own voice.
  function player(language) {
    var synth = window.speechSynthesis || null;
    var queue = [];
    var busy = null;
    var turn = 0;

    function finish(mine) {
      if (mine !== turn) return;
      var done = busy && busy.done;
      busy = null;
      if (done) done();
      next();
    }

    function device(text, mine) {
      if (!synth) { finish(mine); return; }
      var parts = text.match(/[^.!?…]+[.!?…]*/g) || [text];
      var voice = pick(synth, language);
      (function say(i) {
        if (mine !== turn) return;
        if (i >= parts.length) { finish(mine); return; }
        var u = new SpeechSynthesisUtterance(parts[i].trim());
        if (voice) u.voice = voice;
        u.lang = voice ? voice.lang : language || "en";
        u.rate = 0.94;
        u.onend = function () { setTimeout(function () { say(i + 1); }, 260); };
        u.onerror = function () { say(i + 1); };
        synth.speak(u);
      })(0);
    }

    function next() {
      if (busy || !queue.length) return;
      busy = queue.shift();
      device(busy.text, turn);
    }

    return {
      ready: function () { return !!synth; },
      label: function () {
        var voice = pick(synth, language);
        return voice ? "Voice: " + voice.name : "";
      },
      unlock: function () {},
      speaking: function () { return !!busy || queue.length > 0; },
      say: function (text, done) { queue.push({ text: text, done: done }); next(); },
      // Stops at once; with finished, whoever waits on these lines is told they are over.
      cancel: function (finished) {
        var waiting = finished ? [busy].concat(queue).filter(Boolean) : [];
        turn++;
        queue = [];
        busy = null;
        if (synth) synth.cancel();
        waiting.forEach(function (item) { if (item.done) item.done(); });
      },
      pause: function () { if (synth) synth.pause(); },
      resume: function () { if (synth) synth.resume(); }
    };
  }

  return { pick: pick, score: score, player: player };
})();
