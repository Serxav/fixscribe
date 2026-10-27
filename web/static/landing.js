// Page motion: content rises in as it enters the screen, the table comes apart as you scroll,
// and the agent trace types itself in. Everything is visible without this script.
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 1. Reveal on scroll
  var items = document.querySelectorAll("[data-reveal]");
  if (reduce || !("IntersectionObserver" in window)) {
    items.forEach(function (el) { el.classList.add("in"); });
  } else {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("in");
        seen.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    items.forEach(function (el) { seen.observe(el); });
  }

  // 2. The table: assembled at the start of its section, exploded at the end
  var stage = document.querySelector("[data-assemble]");
  var svg = stage && stage.querySelector("svg");
  if (svg) {
    var top = svg.querySelector(".fs-top");
    var bolts = svg.querySelector(".fs-bolts");
    var guides = svg.querySelector(".fs-guides");
    var callouts = svg.querySelector(".fs-callouts");
    var liftTop = parseFloat(svg.getAttribute("data-lift-top")) || 0;
    var liftBolt = parseFloat(svg.getAttribute("data-lift-bolt")) || 0;
    var ease = function (t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; };
    var clamp = function (v) { return Math.min(1, Math.max(0, v)); };
    var queued = false;
    var draw = function () {
      queued = false;
      var box = stage.getBoundingClientRect();
      var room = box.height - window.innerHeight;
      var p = reduce ? 1 : (room > 0 ? clamp(-box.top / room) : 1);
      var e = ease(clamp(p / 0.7));
      top.setAttribute("transform", "translate(0 " + ((1 - e) * liftTop).toFixed(1) + ")");
      bolts.setAttribute("transform", "translate(0 " + ((1 - e) * liftBolt).toFixed(1) + ")");
      guides.style.opacity = e.toFixed(2);
      callouts.style.opacity = clamp((p - 0.62) / 0.25).toFixed(2);
    };
    window.addEventListener("scroll", function () {
      if (!queued) { queued = true; window.requestAnimationFrame(draw); }
    }, { passive: true });
    window.addEventListener("resize", draw);
    draw();
  }
})();
