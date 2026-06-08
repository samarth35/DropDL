const form = document.querySelector("#download-form");
const urlInput = document.querySelector("#url");
const fetchButton = document.querySelector("#fetch-button");
const downloadButton = document.querySelector("#download-button");
const mediaPreview = document.querySelector("#media-preview");
const previewImage = document.querySelector("#preview-image");
const previewTitle = document.querySelector("#preview-title");
const previewMeta = document.querySelector("#preview-meta");
const quality = document.querySelector("#quality");
const audioFormat = document.querySelector("#audio-format");
const videoOutput = document.querySelector("#video-output");
const trimEnabled = document.querySelector("#trim-enabled");
const trimControls = document.querySelector("#trim-controls");
const startTime = document.querySelector("#start-time");
const endTime = document.querySelector("#end-time");
const clipDuration = document.querySelector("#clip-duration");
const trimFill = document.querySelector("#trim-fill");
const startHandle = document.querySelector("#start-handle");
const endHandle = document.querySelector("#end-handle");
const emptyState = document.querySelector("#empty-state");
const activeState = document.querySelector("#active-state");
const jobState = document.querySelector("#job-state");
const activeThumbnail = document.querySelector("#active-thumbnail");
const activeTitle = document.querySelector("#active-title");
const activeSource = document.querySelector("#active-source");
const progressMessage = document.querySelector("#progress-message");
const progressValue = document.querySelector("#progress-value");
const progressBar = document.querySelector("#progress-bar");
const speed = document.querySelector("#speed");
const eta = document.querySelector("#eta");
const saveFile = document.querySelector("#save-file");
const resetButton = document.querySelector("#reset-button");
const errorMessage = document.querySelector("#error-message");
const recentList = document.querySelector("#recent-list");

let currentInfo = null;
let pollTimer = null;

function getMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function setMode(mode) {
  const isAudio = mode === "audio";
  quality.disabled = isAudio;
  audioFormat.disabled = !isAudio;
  audioFormat.classList.toggle("hidden", !isAudio);
  videoOutput.classList.toggle("hidden", isAudio);
}

function durationLabel(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = (total % 60).toString().padStart(2, "0");
  return hours
    ? `${hours}:${minutes.toString().padStart(2, "0")}:${remainder}`
    : `${minutes}:${remainder}`;
}

function parseTime(value) {
  const text = value.trim();
  if (!text) return null;
  const parts = text.split(":");
  if (parts.length > 3 || parts.some((part) => part === "" || !/^\d+(?:\.\d+)?$/.test(part))) {
    return Number.NaN;
  }
  return parts.reduce((seconds, part) => seconds * 60 + Number(part), 0);
}

function updateTrimPreview() {
  const start = parseTime(startTime.value);
  const end = parseTime(endTime.value);
  const mediaDuration = currentInfo?.duration;
  const valid = Number.isFinite(start) && Number.isFinite(end) && end > start;

  clipDuration.textContent = valid ? `${durationLabel(end - start)} selected` : "Select a valid range";
  if (!valid || !mediaDuration) {
    trimFill.style.left = "0%";
    trimFill.style.width = "100%";
    startHandle.style.left = "0%";
    endHandle.style.left = "100%";
    return;
  }

  const startPercent = Math.max(0, Math.min(100, start * 100 / mediaDuration));
  const endPercent = Math.max(startPercent, Math.min(100, end * 100 / mediaDuration));
  trimFill.style.left = `${startPercent}%`;
  trimFill.style.width = `${endPercent - startPercent}%`;
  startHandle.style.left = `${startPercent}%`;
  endHandle.style.left = `${endPercent}%`;
}

function trimValues() {
  if (!trimEnabled.checked) {
    return { trim_enabled: false, start_time: null, end_time: null };
  }
  const start = parseTime(startTime.value);
  const end = parseTime(endTime.value);
  if (!Number.isFinite(start) || start < 0) throw new Error("Enter a valid start time.");
  if (!Number.isFinite(end) || end <= start) throw new Error("End time must be later than start time.");
  if (currentInfo?.duration && end > currentInfo.duration + 0.5) {
    throw new Error(`End time cannot exceed ${durationLabel(currentInfo.duration)}.`);
  }
  return { trim_enabled: true, start_time: start, end_time: end };
}

async function fetchJSON(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Something went wrong.");
  return data;
}

async function fetchDetails() {
  if (!urlInput.reportValidity()) return;
  fetchButton.disabled = true;
  fetchButton.textContent = "Fetching...";
  try {
    currentInfo = await fetchJSON("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: urlInput.value }),
    });
    previewImage.src = currentInfo.thumbnail || "";
    previewImage.hidden = !currentInfo.thumbnail;
    previewTitle.textContent = currentInfo.title;
    const details = [
      currentInfo.uploader,
      currentInfo.is_playlist ? `${currentInfo.playlist_count || "Multiple"} items` : durationLabel(currentInfo.duration),
    ].filter(Boolean);
    previewMeta.textContent = details.join(" / ");
    mediaPreview.classList.remove("hidden");
    if (currentInfo.duration && !currentInfo.is_playlist) {
      if (!endTime.value) endTime.value = durationLabel(currentInfo.duration);
      updateTrimPreview();
    }
  } catch (error) {
    showError(error.message);
  } finally {
    fetchButton.disabled = false;
    fetchButton.textContent = "Fetch details";
  }
}

function showError(message) {
  emptyState.classList.add("hidden");
  activeState.classList.remove("hidden");
  errorMessage.textContent = message;
  errorMessage.classList.remove("hidden");
  resetButton.classList.remove("hidden");
  jobState.textContent = "Error";
}

function showActive() {
  emptyState.classList.add("hidden");
  activeState.classList.remove("hidden");
  errorMessage.classList.add("hidden");
  saveFile.classList.add("hidden");
  resetButton.classList.add("hidden");
  activeTitle.textContent = currentInfo?.title || "Preparing download";
  activeSource.textContent = urlInput.value;
  activeThumbnail.src = currentInfo?.thumbnail || "";
  activeThumbnail.hidden = !currentInfo?.thumbnail;
  progressBar.style.width = "0%";
  progressValue.textContent = "0%";
}

function updateJob(job) {
  const labels = {
    queued: "Queued",
    downloading: "Downloading",
    processing: "Processing",
    complete: "Complete",
    error: "Error",
  };
  jobState.textContent = labels[job.status] || job.status;
  activeTitle.textContent = job.title || activeTitle.textContent;
  if (job.thumbnail) {
    activeThumbnail.src = job.thumbnail;
    activeThumbnail.hidden = false;
  }
  const value = Math.max(0, Math.min(100, job.progress || 0));
  progressBar.style.width = `${value}%`;
  progressValue.textContent = `${Math.round(value)}%`;
  progressMessage.textContent = job.status === "processing" ? "Finishing the file..." : labels[job.status];
  speed.textContent = job.speed ? `${job.speed}/s` : "";
  eta.textContent = job.eta ? `ETA ${job.eta}` : "";

  if (job.status === "complete") {
    clearInterval(pollTimer);
    saveFile.href = `/api/jobs/${job.id}/file`;
    saveFile.classList.remove("hidden");
    resetButton.classList.remove("hidden");
    downloadButton.disabled = false;
    addRecent(job);
  } else if (job.status === "error") {
    clearInterval(pollTimer);
    downloadButton.disabled = false;
    showError(job.error || "The download failed.");
  }
}

async function pollJob(jobId) {
  try {
    updateJob(await fetchJSON(`/api/jobs/${jobId}`));
  } catch (error) {
    clearInterval(pollTimer);
    downloadButton.disabled = false;
    showError(error.message);
  }
}

function addRecent(job) {
  recentList.querySelector(".recent-empty")?.remove();
  const item = document.createElement("li");
  const title = document.createElement("span");
  const link = document.createElement("a");
  title.textContent = job.title;
  link.href = `/api/jobs/${job.id}/file`;
  link.textContent = "Save again";
  item.append(title, link);
  recentList.prepend(item);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!urlInput.reportValidity()) return;
  clearInterval(pollTimer);
  downloadButton.disabled = true;
  try {
    const trim = trimValues();
    showActive();
    const data = await fetchJSON("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: urlInput.value,
        mode: getMode(),
        quality: quality.value,
        audio_format: audioFormat.value,
        subtitles: document.querySelector("#subtitles").checked,
        ...trim,
      }),
    });
    await pollJob(data.job_id);
    pollTimer = setInterval(() => pollJob(data.job_id), 800);
  } catch (error) {
    downloadButton.disabled = false;
    showError(error.message);
  }
});

fetchButton.addEventListener("click", fetchDetails);
trimEnabled.addEventListener("change", () => {
  trimControls.classList.toggle("hidden", !trimEnabled.checked);
  if (trimEnabled.checked && !startTime.value) startTime.value = "00:00";
  updateTrimPreview();
});
[startTime, endTime].forEach((input) => input.addEventListener("input", updateTrimPreview));
document.querySelectorAll('input[name="mode"]').forEach((input) => {
  input.addEventListener("change", () => setMode(input.value));
});
resetButton.addEventListener("click", () => {
  activeState.classList.add("hidden");
  emptyState.classList.remove("hidden");
  jobState.textContent = "Ready";
  urlInput.focus();
});
setMode("video");
