// shared.js — 所有頁面共用的工具函式

const API_BASE = "https://nurse-ot-line.onrender.com"; // ← 替換成你的 Render URL
const LIFF_ID = "2009821318-dMWMvXFd";

let _lineUserId = null;
let _currentUser = null;

// 讓各頁面可以直接讀取
function getLineUserId() { return _lineUserId; }

// ── LIFF 初始化 ───────────────────────────────────────────────────────────────

async function initLiff(liffId, requiredRole) {
  try {
    await liff.init({ liffId });
    showToast("LIFF init 成功");
  } catch(e) {
    showToast(`LIFF init 失敗: ${e.message}`, false);
    return null;
  }

  if (!liff.isLoggedIn()) { liff.login(); return null; }

  let profile;
  try {
    profile = await liff.getProfile();
    _lineUserId = profile.userId;
    showToast(`取得 userId 成功`);
  } catch(e) {
    showToast(`getProfile 失敗: ${e.message}`, false);
    return null;
  }

  let res;
  try {
    res = await apiFetch("/api/me");
    showToast(`/api/me 狀態: ${res.status}`);
  } catch(e) {
    showToast(`/api/me 呼叫失敗: ${e.message}`, false);
    return null;
  }

  if (!res.ok) {
    const body = await res.text();
    showToast(`/api/me 錯誤 ${res.status}: ${body.slice(0,60)}`, false);
    location.href = "index.html";
    return null;
  }

  _currentUser = await res.json();
  const roleOrder = { nurse: 1, manager: 2, admin: 3 };
  if (requiredRole && (roleOrder[_currentUser.role] || 0) < (roleOrder[requiredRole] || 0)) {
    location.href = "index.html";
    return null;
  }
  return _currentUser;
}

// ── API 呼叫 ──────────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Line-User-Id": _lineUserId || "",
    ...(options.headers || {}),
  };
  return fetch(`${API_BASE}${path}`, { ...options, headers });
}

// ── 工具函式 ──────────────────────────────────────────────────────────────────

function formatMinutes(m) {
  const h = Math.floor(m / 60), min = m % 60;
  return min === 0 ? `${h}小時` : `${h}小時${min}分鐘`;
}

function statusBadge(status) {
  const map = {
    "審核中":  { bg: "#FFF3CD", color: "#856404" },
    "已核准":  { bg: "#D1F0DA", color: "#1A6B35" },
    "已拒絕":  { bg: "#F8D7DA", color: "#842029" },
    "已取消":  { bg: "#E9ECEF", color: "#6C757D" },
  };
  const s = map[status] || { bg: "#eee", color: "#555" };
  return `<span style="
    background:${s.bg}; color:${s.color};
    padding:2px 10px; border-radius:20px; font-size:13px; font-weight:500;
  ">${status}</span>`;
}

function shiftLabel(rec) {
  return rec.shift_type === "其他" && rec.other_shift_text
    ? `其他（${rec.other_shift_text}）`
    : rec.shift_type;
}

function showToast(msg, ok = true) {
  let t = document.getElementById("_toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "_toast";
    t.style.cssText = `
      position:fixed; bottom:80px; left:50%; transform:translateX(-50%);
      padding:10px 22px; border-radius:24px; font-size:14px; font-weight:500;
      color:#fff; z-index:9999; opacity:0; transition:opacity 0.25s;
      pointer-events:none; white-space:nowrap;
    `;
    document.body.appendChild(t);
  }
  t.style.background = ok ? "#1A6B35" : "#842029";
  t.textContent = msg;
  t.style.opacity = "1";
  setTimeout(() => { t.style.opacity = "0"; }, 2200);
}

function loading(show) {
  let el = document.getElementById("_loading");
  if (!el) {
    el = document.createElement("div");
    el.id = "_loading";
    el.innerHTML = `<div style="
      width:40px;height:40px;border:3px solid #e0e0e0;
      border-top-color:#06C755;border-radius:50%;
      animation:spin 0.8s linear infinite;
    "></div>`;
    el.style.cssText = `
      position:fixed;inset:0;background:rgba(255,255,255,0.75);
      display:flex;align-items:center;justify-content:center;z-index:9998;
    `;
    const style = document.createElement("style");
    style.textContent = "@keyframes spin{to{transform:rotate(360deg)}}";
    document.head.appendChild(style);
    document.body.appendChild(el);
  }
  el.style.display = show ? "flex" : "none";
}
