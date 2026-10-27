const $ = (selector) => document.querySelector(selector);
const form = $("#download-form");
const urlInput = $("#url");
const fetchButton = $("#fetch-button");
const downloadButton = $("#download-button");
const trimEnabled = $("#trim-enabled");
const startTime = $("#start-time");
const endTime = $("#end-time");
const playlist = $("#playlist");
const labels = { queued: "Queued", downloading: "Downloading", processing: "Processing", complete: "Complete", error: "Failed" };
const activeStatuses = new Set(["queued", "downloading", "processing"]);
let currentInfo = null;
let currentJobId = null;
let history = [];
let detailsController = null;
let historyRequest = 0;
let hasFFmpeg = false;
let submitting = false;
let historySignature = "";

function getMode() {
  return $('input[name="mode"]:checked').value;
}

function setMode(mode) {
  const isAudio = mode === "audio";
  $("#quality").disabled = isAudio;
  $("#audio-format").disabled = !isAudio;
  $("#audio-format").classList.toggle("hidden", !isAudio);
  $("#video-output").classList.toggle("hidden", isAudio);
}

function durationLabel(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = (total % 60).toString().padStart(2, "0");
  return hours ? `${hours}:${minutes.toString().padStart(2, "0")}:${remainder}` : `${minutes}:${remainder}`;
}

function parseTime(value) {
  const text = value.trim();
  if (!text) return null;
  const parts = text.split(":");
  if (parts.length > 3 || parts.some((part, index) =>
    !/^\d+(?:\.\d+)?$/.test(part) || (index < parts.length - 1 && part.includes(".")) || (index > 0 && Number(part) >= 60)
  )) return Number.NaN;
  return parts.reduce((seconds, part) => seconds * 60 + Number(part), 0);
}

function updateTrimPreview() {
  const start = parseTime(startTime.value);
  const end = parseTime(endTime.value);
  const duration = currentInfo?.duration;
  const valid = Number.isFinite(start) && Number.isFinite(end) && end > start;
  $("#clip-duration").textContent = valid ? `${(end - start).toFixed(2).replace(/\.00$/, "")}s selected` : "Select a valid range";
  const left = valid && duration ? Math.min(100, start * 100 / duration) : 0;
  const right = valid && duration ? Math.min(100, end * 100 / duration) : 100;
  $("#trim-fill").style.left = $("#start-handle").style.left = `${left}%`;
  $("#trim-fill").style.width = `${Math.max(0, right - left)}%`;
  $("#end-handle").style.left = `${right}%`;
}

function trimValues() {
  if (!trimEnabled.checked) return { trim_enabled: false };
  if (playlist.checked) throw new Error("Turn off playlist download to trim a single video.");
  const start = parseTime(startTime.value) ?? 0;
  const end = parseTime(endTime.value);
  if (!Number.isFinite(start) || start < 0) throw new Error("Enter a valid start time.");
  if (!Number.isFinite(end) || end <= start) throw new Error("End time must be later than start time.");
  if (end - start < 0.25) throw new Error("Select a clip of at least 0.25 seconds.");
  if (currentInfo?.duration && end > currentInfo.duration + 0.5) {
    throw new Error(`End time cannot exceed ${durationLabel(currentInfo.duration)}.`);
  }
  return { trim_enabled: true, start_time: start, end_time: end };
}

async function fetchJSON(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { ...options, signal: options.signal || AbortSignal.timeout(60000) });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("Cannot reach DropDL. Keep its launcher window open and try again.");
  }
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join("; ") : data.detail;
    throw new Error(detail || "Something went wrong. Try again.");
  }
  return data;
}

function formError(message = "") {
  $("#form-error").textContent = message;
  $("#form-error").classList.toggle("hidden", !message);
}

function setImage(element, url) {
  if (url && /^https?:\/\//i.test(url)) {
    element.src = url;
    element.hidden = false;
  } else {
    element.removeAttribute("src");
    element.hidden = true;
  }
}

async function fetchDetails() {
  if (!urlInput.reportValidity()) return;
  detailsController?.abort();
  const controller = new AbortController();
  detailsController = controller;
  const requestedURL = urlInput.value;
  fetchButton.disabled = true;
  fetchButton.textContent = "Fetching...";
  formError();
  try {
    const info = await fetchJSON("/api/info", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: requestedURL }), signal: controller.signal,
    });
    if (urlInput.value !== requestedURL) return;
    currentInfo = info;
    setImage($("#preview-image"), info.thumbnail);
    $("#preview-title").textContent = info.title;
    $("#preview-meta").textContent = [info.uploader, info.is_playlist ? `${info.playlist_count || "Multiple"} items` : durationLabel(info.duration)].filter(Boolean).join(" / ");
    $("#media-preview").classList.remove("hidden");
    if (info.is_playlist) playlist.checked = true;
    if (info.duration && !endTime.value) endTime.value = durationLabel(info.duration);
    updateTrimPreview();
  } catch (error) {
    if (error.name !== "AbortError") formError(error.message);
  } finally {
    if (detailsController === controller) {
      fetchButton.disabled = false;
      fetchButton.textContent = "Fetch details";
    }
  }
}

function updateJob(job) {
  $("#empty-state").classList.add("hidden");
  $("#active-state").classList.remove("hidden");
  $("#job-state").textContent = labels[job.status] || job.status;
  $("#active-title").textContent = job.title;
  $("#active-source").textContent = job.url;
  setImage($("#active-thumbnail"), job.thumbnail);
  const value = Math.max(0, Math.min(100, job.progress || 0));
  $("#progress-bar").style.width = `${value}%`;
  $(".progress-track").setAttribute("aria-valuenow", Math.round(value));
  $("#progress-value").textContent = `${Math.round(value)}%`;
  $("#progress-message").textContent = job.status === "processing" ? "Finishing files..." : labels[job.status];
  $("#speed").textContent = job.speed || "";
  $("#eta").textContent = job.eta ? `ETA ${job.eta}` : "";
  $("#error-message").textContent = job.error || "";
  $("#error-message").classList.toggle("hidden", job.status !== "error");
  $("#save-file").classList.toggle("hidden", job.status !== "complete");
  $("#save-file").href = `/api/jobs/${job.id}/file`;
  $("#save-file").textContent = job.filename?.endsWith(".zip") ? `Save ZIP (${job.files.length} files)` : "Save file";
  $("#reset-button").classList.toggle("hidden", activeStatuses.has(job.status));
}

function renderHistory() {
  const current = history.find((job) => job.id === currentJobId);
  if (current) updateJob(current);
  const active = history.filter((job) => activeStatuses.has(job.status)).length;
  downloadButton.querySelector("span").textContent = active ? "Add to queue" : "Start download";
  const signature = JSON.stringify(history.map(({ id, title, status, filename }) => ({ id, title, status, filename })));
  if (signature === historySignature) return;
  historySignature = signature;
  const list = $("#recent-list");
  list.replaceChildren();
  if (!history.length) {
    const empty = document.createElement("li");
    empty.className = "recent-empty";
    empty.textContent = "Nothing here yet. Your downloads will be saved here.";
    list.append(empty);
  }
  history.forEach((job) => {
    const item = document.createElement("li");
    const copy = document.createElement("div");
    copy.className = "job-copy";
    const title = document.createElement("strong");
    title.textContent = job.title;
    title.title = job.title;
    const meta = document.createElement("small");
    meta.textContent = `${labels[job.status]} · ${job.mode} · ${new Date(job.created_at * 1000).toLocaleDateString()}`;
    copy.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "job-actions";
    const view = document.createElement("button");
    view.type = "button";
    view.textContent = job.status === "error" ? "Retry" : "View";
    view.setAttribute("aria-label", `${view.textContent} ${job.title}`);
    view.addEventListener("click", () => {
      currentJobId = job.id;
      updateJob(job);
      if (job.status === "error") {
        urlInput.value = job.url;
        clearDetails();
        urlInput.focus();
        formError("Link restored. Choose your settings and press Start download to retry.");
      }
    });
    actions.append(view);
    if (job.status === "complete") {
      const save = document.createElement("a");
      save.href = `/api/jobs/${job.id}/file`;
      save.textContent = job.filename?.endsWith(".zip") ? "Save ZIP" : "Save";
      save.setAttribute("aria-label", `Save ${job.title}`);
      actions.append(save);
    }
    item.append(copy, actions);
    list.append(item);
  });
}

async function refreshHistory(restore = false) {
  const request = ++historyRequest;
  const data = await fetchJSON("/api/jobs");
  if (request !== historyRequest) return;
  history = data;
  if (restore && history.length) currentJobId = history.find((job) => activeStatuses.has(job.status))?.id || history[0].id;
  renderHistory();
}

function clearDetails() {
  detailsController?.abort();
  currentInfo = null;
  endTime.value = "";
  $("#media-preview").classList.add("hidden");
  formError();
  updateTrimPreview();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submitting || !urlInput.reportValidity()) return;
  submitting = true;
  downloadButton.disabled = true;
  formError();
  try {
    const payload = {
      url: urlInput.value, mode: getMode(), quality: $("#quality").value,
      audio_format: $("#audio-format").value, playlist: playlist.checked,
      subtitles: $("#subtitles").checked, ...trimValues(),
    };
    const data = await fetchJSON("/api/download", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    currentJobId = data.job_id;
    await refreshHistory();
  } catch (error) {
    formError(error.message);
  } finally {
    submitting = false;
    downloadButton.disabled = false;
  }
});

fetchButton.addEventListener("click", fetchDetails);
urlInput.addEventListener("input", clearDetails);
trimEnabled.addEventListener("change", () => {
  $("#trim-controls").classList.toggle("hidden", !trimEnabled.checked);
  if (trimEnabled.checked && !startTime.value) startTime.value = "00:00";
  updateTrimPreview();
});
[startTime, endTime].forEach((input) => input.addEventListener("input", updateTrimPreview));
document.querySelectorAll('input[name="mode"]').forEach((input) => input.addEventListener("change", () => setMode(input.value)));
$("#reset-button").addEventListener("click", () => {
  currentJobId = null;
  $("#active-state").classList.add("hidden");
  $("#empty-state").classList.remove("hidden");
  $("#job-state").textContent = "Ready";
  formError();
  urlInput.focus();
});
document.querySelectorAll("img").forEach((img) => img.addEventListener("error", () => { img.hidden = true; }));

async function refreshHealth() {
  const health = await fetchJSON("/api/health");
  hasFFmpeg = health.ffmpeg;
  $("#download-directory").textContent = health.download_dir;
  $('input[name="mode"][value="audio"]').disabled = !hasFFmpeg;
  trimEnabled.disabled = !hasFFmpeg;
  if (!hasFFmpeg) {
    $('input[name="mode"][value="video"]').checked = true;
    setMode("video");
    trimEnabled.checked = false;
    $("#trim-controls").classList.add("hidden");
    $("#video-output").textContent = "Original video format";
  }
  $("#setup-notice").textContent = "Basic video downloads are available. Install FFmpeg and ffprobe, then restart DropDL for audio, clips, and the highest video quality.";
  $("#setup-notice").classList.toggle("hidden", hasFFmpeg);
  if ($("#connection-status").textContent !== "Local only · Connected") {
    $("#connection-status").replaceChildren();
    $("#connection-status").append(document.createElement("span"), "Local only · Connected");
  }
  $("#connection-status").classList.remove("offline");
}

async function sync(restore = false) {
  try {
    await refreshHealth();
    await refreshHistory(restore);
  } catch (error) {
    $("#connection-status").replaceChildren();
    $("#connection-status").append(document.createElement("span"), "Reconnecting...");
    $("#connection-status").classList.add("offline");
    if (restore) formError(error.message);
  } finally {
    setTimeout(() => sync(false), 1500);
  }
}
setMode("video");
sync(true);
