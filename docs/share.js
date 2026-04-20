const API_BASE = "https://nurse-ot-line.onrender.com";
const LIFF_ID = "2009821321-HS1gs2c4";

let _lineUserId = null;
let _currentUser = null;

function getLineUserId() {
  return _lineUserId;
}

function getCurrentUser() {
  return _currentUser;
}

async function initLiff(liffId, requiredRole) {
  try {
    await liff.init({ liffId });
  } catch (error) {
    showToast(`LIFF 初始化失敗: ${error.message}`, false);
    return null;
  }

  if (!liff.isLoggedIn()) {
    liff.login();
    return null;
  }

  try {
    const profile = await liff.getProfile();
    _lineUserId = profile.userId;
  } catch (error) {
    showToast(`無法取得 LINE 使用者資訊: ${error.message}`, false);
    return null;
  }

  let response;
  try {
    response = await apiFetch("/api/me");
  } catch (error) {
    showToast(`無法讀取使用者資料: ${error.message}`, false);
    return null;
  }

  if (!response.ok) {
    location.replace("index.html");
    return null;
  }

  _currentUser = await response.json();
  const roleOrder = { nurse: 1, manager: 2, admin: 3 };

  if (requiredRole && (roleOrder[_currentUser.role] || 0) < (roleOrder[requiredRole] || 0)) {
    location.replace("index.html");
    return null;
  }

  return _currentUser;
}

async function apiFetch(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Line-User-Id": _lineUserId || "",
    ...(options.headers || {}),
  };

  return fetch(`${API_BASE}${path}`, { ...options, headers });
}

function formatApiErrorDetail(detail) {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => formatApiErrorDetail(item)).filter(Boolean).join("; ");
  }
  if (typeof detail === "object") {
    if (typeof detail.msg === "string") return detail.msg;
    if (Array.isArray(detail.loc) && typeof detail.msg === "string") {
      return `${detail.loc.join(".")}: ${detail.msg}`;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return String(detail);
    }
  }
  return String(detail);
}

async function getErrorMessage(response, fallback = "操作失敗") {
  try {
    const payload = await response.json();
    const message = formatApiErrorDetail(payload.detail || payload.error || payload);
    return message || fallback;
  } catch {
    try {
      const text = await response.text();
      return text || fallback;
    } catch {
      return fallback;
    }
  }
}

function formatMinutes(minutes) {
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  return remaining === 0 ? `${hours}小時` : `${hours}小時${remaining}分鐘`;
}

function statusBadge(status) {
  const styles = {
    審核中: { bg: "#FFF3CD", color: "#856404" },
    已核准: { bg: "#D1F0DA", color: "#1A6B35" },
    已拒絕: { bg: "#F8D7DA", color: "#842029" },
    已取消: { bg: "#E9ECEF", color: "#6C757D" },
  };
  const style = styles[status] || { bg: "#eee", color: "#555" };
  return `<span style="background:${style.bg};color:${style.color};padding:2px 10px;border-radius:20px;font-size:13px;font-weight:500;">${status}</span>`;
}

function shiftLabel(record) {
  if (record.shift_type === "其他" && record.other_shift_text) {
    return `其他（${record.other_shift_text}）`;
  }
  return record.shift_type;
}

function showToast(message, ok = true) {
  let toast = document.getElementById("_toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "_toast";
    toast.style.cssText = [
      "position:fixed",
      "bottom:80px",
      "left:50%",
      "transform:translateX(-50%)",
      "padding:10px 22px",
      "border-radius:24px",
      "font-size:14px",
      "font-weight:500",
      "color:#fff",
      "z-index:10000",
      "opacity:0",
      "transition:opacity 0.25s",
      "pointer-events:none",
      "white-space:nowrap",
      "max-width:calc(100vw - 32px)",
      "overflow:hidden",
      "text-overflow:ellipsis",
    ].join(";");
    document.body.appendChild(toast);
  }

  toast.style.background = ok ? "#1A6B35" : "#842029";
  toast.textContent = message;
  toast.style.opacity = "1";

  window.clearTimeout(showToast._timer);
  showToast._timer = window.setTimeout(() => {
    toast.style.opacity = "0";
  }, 2200);
}

function loading(show) {
  let el = document.getElementById("_loading");
  if (!el) {
    el = document.createElement("div");
    el.id = "_loading";
    el.innerHTML = '<div style="width:40px;height:40px;border:3px solid #e0e0e0;border-top-color:#06C755;border-radius:50%;animation:spin 0.8s linear infinite;"></div>';
    el.style.cssText = "position:fixed;inset:0;background:rgba(255,255,255,0.75);display:none;align-items:center;justify-content:center;z-index:9998;";

    const style = document.createElement("style");
    style.textContent = "@keyframes spin{to{transform:rotate(360deg)}}";
    document.head.appendChild(style);
    document.body.appendChild(el);
  }

  el.style.display = show ? "flex" : "none";
}

function showConfirm(message, options = {}) {
  const {
    title = "請確認",
    confirmText = "確認",
    cancelText = "取消",
    danger = false,
  } = options;

  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.38);display:flex;align-items:center;justify-content:center;padding:20px;z-index:10001;";

    const dialog = document.createElement("div");
    dialog.style.cssText = "width:min(360px,100%);background:#fff;border-radius:16px;padding:20px;box-shadow:0 12px 36px rgba(0,0,0,0.18);";
    dialog.innerHTML = `
      <div style="font-size:17px;font-weight:700;color:#1a1a1a;margin-bottom:10px;">${title}</div>
      <div style="font-size:14px;line-height:1.6;color:#444;margin-bottom:18px;">${message}</div>
      <div style="display:flex;gap:10px;justify-content:flex-end;">
        <button type="button" data-action="cancel" style="padding:10px 16px;border:1px solid #d0d7de;border-radius:10px;background:#fff;color:#333;font-size:14px;cursor:pointer;">${cancelText}</button>
        <button type="button" data-action="confirm" style="padding:10px 16px;border:none;border-radius:10px;background:${danger ? "#d32f2f" : "#06C755"};color:#fff;font-size:14px;font-weight:600;cursor:pointer;">${confirmText}</button>
      </div>
    `;

    const close = (result) => {
      overlay.remove();
      resolve(result);
    };

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) {
        close(false);
      }
    });

    dialog.querySelector('[data-action="cancel"]').addEventListener("click", () => close(false));
    dialog.querySelector('[data-action="confirm"]').addEventListener("click", () => close(true));

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
  });
}
