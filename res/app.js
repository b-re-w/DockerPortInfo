"use strict";

const BASE = (typeof window !== "undefined" && window.DPI_BASE) || ""; // URL prefix
const THEME_KEY = "dpi-theme-mode"; // "auto" | "light" | "dark"
const REFRESH_SEC = 60; // auto-refresh interval (seconds)
const STALE_MS = 3 * 60 * 1000; // mark stale if a server hasn't reported for over 3 minutes
const RING_LEN = 97.4; // circumference of the countdown ring (2*pi*15.5)

let countdown = REFRESH_SEC;

// ---------- theme (auto by time + manual toggle) ----------
function effectiveTheme(mode) {
  if (mode === "light" || mode === "dark") return mode;
  const h = new Date().getHours();
  return h >= 19 || h < 7 ? "dark" : "light"; // night -> dark
}

function applyTheme() {
  const mode = localStorage.getItem(THEME_KEY) || "auto";
  document.documentElement.setAttribute("data-theme", effectiveTheme(mode));
  const btn = document.getElementById("theme-btn");
  if (btn) {
    const icon = mode === "auto" ? "🌗" : mode === "dark" ? "🌙" : "☀️";
    const label = mode === "auto" ? "자동" : mode === "dark" ? "다크" : "라이트";
    btn.textContent = icon;
    btn.title = `테마: ${label} (클릭하여 전환)`;
  }
}

function cycleTheme() {
  const cur = localStorage.getItem(THEME_KEY) || "auto";
  const next = cur === "auto" ? "light" : cur === "light" ? "dark" : "auto";
  localStorage.setItem(THEME_KEY, next);
  applyTheme();
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function timeAgo(iso) {
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec}초 전`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}분 전`;
  return `${Math.round(min / 60)}시간 전`;
}

function isLoopback(ip) {
  // host-internal only bindings - not reachable from outside
  return ip === "127.0.0.1" || ip === "::1" || ip === "[::1]";
}

function chips(img) {
  const out = [];
  if (img.language && img.language_version) {
    out.push(`<span class="chip python"><i></i><span class="k">${esc(img.language)}</span><span class="v">${esc(img.language_version)}</span></span>`);
  }
  if (img.ubuntu) {
    out.push(`<span class="chip ubuntu"><i></i><span class="k">ubuntu</span><span class="v">${esc(img.ubuntu)}</span></span>`);
  }
  if (img.cuda) {
    out.push(`<span class="chip cuda"><i></i><span class="k">cuda</span><span class="v">${esc(img.cuda)}</span></span>`);
  }
  if (out.length === 0) {
    out.push(`<span class="chip raw">${esc(img.raw_image)}</span>`);
  }
  return out.join("");
}

function ports(list) {
  const mapped = list.filter((p) => p.host_port && !isLoopback(p.host_ip));
  if (mapped.length === 0) {
    return `<div class="no-ports">외부 공개 포트 없음</div>`;
  }
  // sort by container port number for predictable order
  mapped.sort((a, b) => parseInt(a.container_port, 10) - parseInt(b.container_port, 10));
  const rows = mapped
    .map((p) => {
      const endpoint = `${p.host_ip}:${p.host_port}`;
      return `<div class="port" data-copy="${esc(endpoint)}" title="클릭하여 ${esc(endpoint)} 복사">
        <span class="pc">${esc(p.container_port)}<span class="proto">/${esc(p.proto)}</span></span>
        <span class="arrow">→</span>
        <span class="ph">${esc(p.host_port)}</span>
        <span class="pip">${esc(p.host_ip)}</span>
      </div>`;
    })
    .join("");
  return `<div class="ports">${rows}</div>`;
}

function card(c) {
  return `<div class="card">
    <div class="card-name">${esc(c.names)}</div>
    <div class="card-meta">
      <span class="cid">${esc(c.container_id.slice(0, 12))}</span>
      <span>${esc(c.status)}</span>
    </div>
    <div class="chips">${chips(c.image)}</div>
    <div class="ports-label">포트 · 컨테이너 → 호스트</div>
    ${ports(c.ports)}
  </div>`;
}

function serverPanel(s) {
  const stale = Date.now() - new Date(s.updated_at).getTime() > STALE_MS;
  const body = s.containers.length
    ? s.containers.map(card).join("")
    : `<div class="no-ports">backend.ai 컨테이너 없음</div>`;
  return `<section class="server">
    <div class="server-head">
      <div class="server-title">
        <h2>${esc(s.server_name)}</h2>
        <span class="age">${esc(timeAgo(s.updated_at))}</span>
      </div>
      <div class="head-right">
        <span class="count"><b>${s.container_count}</b> / ${s.total_containers}</span>
        <span class="health ${stale ? "stale" : "ok"}"><span class="hd"></span>${stale ? "지연" : "정상"}</span>
      </div>
    </div>
    <div class="cards">${body}</div>
  </section>`;
}

function setLive(online, label) {
  const el = document.getElementById("live");
  el.classList.toggle("online", online);
  el.classList.toggle("offline", !online);
  document.getElementById("live-text").textContent = label;
}

function setRing(remaining) {
  document.getElementById("countdown-num").textContent = remaining;
  const offset = RING_LEN * (1 - remaining / REFRESH_SEC);
  document.getElementById("ring-fg").style.strokeDashoffset = offset.toFixed(1);
}

let toastTimer = null;
function toast(html) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.innerHTML = html;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 1600);
}

async function load() {
  try {
    const res = await fetch(`${BASE}/snapshots`, { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const servers = data.servers || [];
    const root = document.getElementById("servers");
    if (servers.length === 0) {
      root.innerHTML = `<div class="placeholder">아직 수신된 서버 데이터가 없습니다.<br>크론탭(send_docker_ps.sh)이 동작 중인지 확인하세요.</div>`;
    } else {
      root.innerHTML = servers.map(serverPanel).join("");
    }
    setLive(true, `갱신 ${new Date().toLocaleTimeString("ko-KR", { hour12: false })}`);
  } catch (err) {
    setLive(false, `연결 실패 (${err.message})`);
  }
  applyTheme(); // re-evaluate auto theme as the hour changes
  countdown = REFRESH_SEC;
  setRing(countdown);
}

// port endpoint copy-to-clipboard (event delegation)
document.addEventListener("click", (e) => {
  const port = e.target.closest(".port");
  if (!port) return;
  const text = port.getAttribute("data-copy");
  navigator.clipboard?.writeText(text).then(
    () => toast(`복사됨 · <b>${esc(text)}</b>`),
    () => toast("복사 실패")
  );
});

document.getElementById("refresh-btn").addEventListener("click", load);
document.getElementById("theme-btn").addEventListener("click", cycleTheme);

// 1-second tick: drive the countdown ring, reload at zero
setInterval(() => {
  countdown -= 1;
  if (countdown <= 0) {
    load();
  } else {
    setRing(countdown);
  }
}, 1000);

applyTheme();
setRing(countdown);
load();
