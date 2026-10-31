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
  return { pick: pick, score: score };
})();
