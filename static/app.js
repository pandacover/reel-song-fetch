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

$("#file-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const file = fileInput.files[0];
  if (!file) { setStatus("Pick a file first.", true); return; }
  const form = new FormData();
  form.append("file", file);
  run(() => fetch("/api/identify/file", { method: "POST", body: form }),
    e.submitter || e.target.querySelector("button"));
});
