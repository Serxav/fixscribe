// Listens for one spoken sentence at a time and hands it over as a 16 kHz mono 16-bit WAV.
// onLevel, if given, gets the loudness of every frame (0..1) and whether it sounds like speech.
window.FixEar = function (onClip, onLevel) {
  "use strict";
  var RATE = 16000;
  var FRAME = 2048;
  var MIN_LEVEL = 0.012; // quieter than this is never speech
  var OVER_NOISE = 3; // speech is this many times louder than the room
  var LEAD_S = 0.3; // kept from before the voice was noticed, so the first word is whole
  var END_S = 0.7; // this much quiet ends the sentence
  var MIN_S = 0.3;
  var MAX_S = 6;
  var context = null;
  var stream = null;
  var node = null;
  var noise = 0.005;
  var lead = [];
  var talk = null;
  var quiet = 0;

  function level(samples) {
    var sum = 0;
    for (var i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    return Math.sqrt(sum / samples.length);
  }

  function toWav(chunks, from) {
    var total = chunks.reduce(function (n, c) { return n + c.length; }, 0);
    var step = from / RATE;
    var count = Math.floor(total / step);
    var buffer = new ArrayBuffer(44 + count * 2);
    var view = new DataView(buffer);
    function text(at, s) { for (var i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i)); }
    text(0, "RIFF"); view.setUint32(4, 36 + count * 2, true); text(8, "WAVEfmt ");
    view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, "data"); view.setUint32(40, count * 2, true);
    var flat = new Float32Array(total);
    var at = 0;
    chunks.forEach(function (c) { flat.set(c, at); at += c.length; });
    for (var n = 0; n < count; n++) { // each output sample is the mean of the inputs it covers
      var first = Math.floor(n * step), last = Math.max(first + 1, Math.floor((n + 1) * step));
      var sum = 0;
      for (var k = first; k < last; k++) sum += flat[k];
      var value = Math.max(-1, Math.min(1, sum / (last - first)));
      view.setInt16(44 + n * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  function hear(samples) {
    var chunk = new Float32Array(samples);
    var seconds = chunk.length / context.sampleRate;
    var loud = level(chunk);
    var speech = loud > Math.max(MIN_LEVEL, noise * OVER_NOISE);
    if (onLevel) onLevel(loud, speech);
    if (!talk) {
      noise = noise * 0.97 + loud * 0.03;
      lead.push(chunk);
      if (lead.length * seconds > LEAD_S) lead.shift();
      if (speech) { talk = lead.slice(); lead = []; quiet = 0; }
      return;
    }
    talk.push(chunk);
    quiet = speech ? 0 : quiet + seconds;
    var length = talk.length * seconds;
    if (quiet < END_S && length < MAX_S) return;
    var spoken = talk;
    talk = null;
    if (length - quiet >= MIN_S) onClip(toWav(spoken, context.sampleRate));
  }

  return {
    // Inside a tap: phones only start audio from one.
    start: function () {
      var Context = window.AudioContext || window.webkitAudioContext;
      if (!Context || !navigator.mediaDevices) return Promise.reject(new Error("no microphone"));
      context = context || new Context();
      context.resume();
      return navigator.mediaDevices
        .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } })
        .then(function (mic) {
          stream = mic;
          node = context.createScriptProcessor(FRAME, 1, 1);
          node.onaudioprocess = function (event) { hear(event.inputBuffer.getChannelData(0)); };
          context.createMediaStreamSource(mic).connect(node);
          node.connect(context.destination); // silent output: some browsers need it to keep running
        });
    },
    stop: function () {
      if (node) { node.disconnect(); node.onaudioprocess = null; node = null; }
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
      talk = null;
      lead = [];
    }
  };
};
