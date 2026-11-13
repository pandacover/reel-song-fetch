const $ = (sel) => document.querySelector(sel);
const statusEl = $("#status");
const resultsEl = $("#results");

// Tabs
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t === tab);
      t.setAttribute("aria-selected", String(t === tab));
    });
    document.querySelectorAll(".panel").forEach((p) => {
      p.classList.toggle("hidden", p.dataset.panel !== tab.dataset.tab);
    });
  });
});

function switchTab(name) {
  document.querySelector(`.tab[data-tab="${name}"]`).click();
}

// File picker and drag and drop
const drop = $("#drop");
const fileInput = $("#file");
fileInput.addEventListener("change", () => {
  $("#drop-text").textContent = fileInput.files[0]?.name || "Drop a video or audio file here, or tap to choose one";
});
["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    fileInput.dispatchEvent(new Event("change"));
  }
});

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
  statusEl.classList.toggle("hidden", !text);
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") node.className = v; else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

function fmtTime(s) {
  s = Math.round(s);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const LINK_NAMES = {
  spotify: "Spotify", apple_music: "Apple Music", youtube: "YouTube",
  shazam: "Shazam", songlink: "All platforms",
};

function songCard(song) {
  const cover = song.cover ? el("img", { src: song.cover, alt: "" }) : el("div", { class: "ph" });
  const details = [song.album, song.release].filter(Boolean).join(" · ");
  const when = `Heard at ${fmtTime(song.start)} to ${fmtTime(song.end)} · found by ${song.sources.join(", ")}`;
  const links = el("div", { class: "links" });
  for (const [key, url] of Object.entries(song.links || {})) {
    links.append(el("a", { href: url, target: "_blank", rel: "noopener" }, LINK_NAMES[key] || key));
  }
  return el("article", { class: "card" }, cover,
    el("div", {},
      el("h3", {}, song.title),
      el("p", { class: "artist" }, song.artist),
      details ? el("p", { class: "meta" }, details) : null,
      el("p", { class: "meta" }, when),
      links));
}

function render(data) {
  resultsEl.innerHTML = "";
  const ig = data.instagram_music;
  if (ig && (ig.title || ig.artist)) {
    resultsEl.append(el("p", { class: "label" }, "Instagram says"));
    const kind = ig.original_audio ? "Original audio" : "Song tagged on the reel";
    resultsEl.append(el("article", { class: "card" }, el("div", { class: "ph" }),
      el("div", {},
        el("h3", {}, ig.title || "Unknown title"),
        el("p", { class: "artist" }, ig.artist || ""),
        el("p", { class: "meta" }, kind))));
  }

  resultsEl.append(el("p", { class: "label" },
    data.songs.length ? `Songs heard in the audio (${data.songs.length})` : "Songs heard in the audio"));
  if (!data.songs.length) {
    resultsEl.append(el("p", { class: "note" },
      "No song was recognized. The music may be too quiet under speech, heavily edited, or not in the database."));
  }
  data.songs.forEach((s) => resultsEl.append(songCard(s)));

  let note = `Scanned ${fmtTime(data.scanned_seconds)} of audio.`;
  if (data.duration > data.scanned_seconds) note += ` Only the first ${fmtTime(data.scanned_seconds)} was checked.`;
  if (data.errors?.length) note += ` Some lookups failed: ${data.errors.join("; ")}`;
  resultsEl.append(el("p", { class: "note" }, note));
}

async function run(request, button) {
  button.disabled = true;
  resultsEl.innerHTML = "";
  setStatus("Working on it. This can take up to a minute…");
  try {
    const res = await request();
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
    setStatus("");
    render(data);
  } catch (err) {
    setStatus(err.message || String(err), true);
  } finally {
    button.disabled = false;
  }
}

$("#url-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const url = $("#url").value.trim();
  run(() => fetch("/api/identify/url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  }), e.submitter || e.target.querySelector("button"))
    .then(() => {
      if (statusEl.classList.contains("error") && /upload/i.test(statusEl.textContent)) {
        // Make the fallback one tap away.
        const btn = el("button", { type: "button", class: "tab" }, "Upload the video instead");
        btn.addEventListener("click", () => switchTab("file"));
        statusEl.append(el("div", { style: "margin-top:8px" }, btn));
      }
    });
});

// Hosts like Vercel cap request bodies at about 4.5 MB, so we shrink the file
// in the browser first: decode it, keep up to 2 minutes of 16 kHz mono audio,
// and send that as a small WAV. If the browser cannot decode it, we send the original.
const MAX_CLIENT_SECONDS = 120;
const TARGET_RATE = 16000;
const RAW_UPLOAD_LIMIT = 4 * 1024 * 1024;

async function toSmallWav(file) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx || !window.OfflineAudioContext) throw new Error("no Web Audio");
  const ctx = new Ctx();
  try {
    const decoded = await ctx.decodeAudioData(await file.arrayBuffer());
    const seconds = Math.min(decoded.duration, MAX_CLIENT_SECONDS);
    const offline = new OfflineAudioContext(1, Math.ceil(seconds * TARGET_RATE), TARGET_RATE);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start(0);
    const rendered = await offline.startRendering();
    return encodeWav(rendered.getChannelData(0), TARGET_RATE);
  } finally {
    ctx.close?.();
  }
}

function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const x = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

$("#file-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const button = e.submitter || e.target.querySelector("button");
  const file = fileInput.files[0];
  if (!file) { setStatus("Pick a file first.", true); return; }
  button.disabled = true;
  setStatus("Reading the audio from your file…");
  let upload = file, name = file.name;
  try {
    upload = await toSmallWav(file);
    name = file.name.replace(/\.[^.]+$/, "") + ".wav";
  } catch (err) {
    if (file.size > RAW_UPLOAD_LIMIT) {
      setStatus("Your browser could not read this file, and it is too big to send as is (over 4 MB). Try a different browser or a shorter clip.", true);
      button.disabled = false;
      return;
    }
  }
  const form = new FormData();
  form.append("file", upload, name);
  run(() => fetch("/api/identify/file", { method: "POST", body: form }), button);
});
