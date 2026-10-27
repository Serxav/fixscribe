(function () {
  "use strict";
  var root = document.getElementById("job");
  if (!root) return;
  var jobId = root.dataset.jobId;
  var POLL_MS = 1500;
  var $ = function (id) { return document.getElementById(id); };

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  function render(data) {
    var percent = Math.round((data.progress || 0) * 100);
    if (data.state === "done") percent = 100;
    $("ring").style.setProperty("--p", percent);
    $("percent").textContent = percent + "%";
    var stages = data.stages || [];
    var running = stages.filter(function (s) { return s.status === "running"; })[0];
    $("stage-label").textContent = data.state === "done" ? "Your guide is ready"
      : data.state === "failed" ? "Stopped" : running ? running.label + "…" : "Starting…";
    $("state-label").textContent = data.warnings && data.warnings.length
      ? data.warnings.length + " optional step(s) skipped" : "";
    $("error").textContent = data.error || "";
    $("error").classList.toggle("hidden", !data.error);
    $("guide-link").classList.toggle("hidden", data.state !== "done");
    $("resume-button").classList.toggle("hidden", data.state !== "failed");
    $("retry-link").classList.toggle("hidden", data.state !== "failed");
    if (data.state === "done") $("headline").textContent = "Done";
    if (stages.length) {
      $("stage-list").innerHTML = stages.map(function (s) {
        var time = s.seconds != null && s.status !== "waiting" ? s.seconds.toFixed(1) + " s" : "";
        var error = s.error ? '<span class="err">' + escapeHtml(s.error) + "</span>" : "";
        return '<li class="' + s.status + '"><i class="dot ' + s.status + '"></i><span>' + escapeHtml(s.label) +
          '</span><span class="muted small tabular">' + time + "</span>" + error + "</li>";
      }).join("");
    }
  }

  function poll() {
    fetch("/api/jobs/" + jobId, { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        render(data);
        if (data.state === "done") { setTimeout(function () { window.location.href = "/guides/" + jobId; }, 900); return; }
        if (data.state !== "failed") setTimeout(poll, POLL_MS);
      })
      .catch(function () { setTimeout(poll, POLL_MS * 2); });
  }

  $("resume-button").addEventListener("click", function () {
    $("resume-button").disabled = true;
    fetch("/api/jobs/" + jobId + "/resume", { method: "POST" })
      .then(function () { $("resume-button").disabled = false; poll(); })
      .catch(function () { $("resume-button").disabled = false; });
  });

  poll();
})();
