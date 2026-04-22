import os
import re
import calendar
import requests
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
REQUEST_TIMEOUT_SECONDS = 15
DOCS_DIR = Path(__file__).resolve().parent / "docs"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # GitHub Pages 部署後可改成指定網域
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# 為了向下相容，保留 headers 別名
headers = SUPABASE_HEADERS


# ── LINE helpers ──────────────────────────────────────────────────────────────

def reply_message(reply_token, text):
    url = "https://api.line.me/v2/bot/message/reply"
    headers_line = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    }
    response = requests.post(
        url, headers=headers_line, json=data, timeout=REQUEST_TIMEOUT_SECONDS
    )
    print("LINE reply:", response.status_code, response.text)


def push_message(line_user_id, text):
    """主動推播給指定使用者（不需 replyToken）。"""
    url = "https://api.line.me/v2/bot/message/push"
    headers_line = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "to": line_user_id,
        "messages": [{"type": "text", "text": text}],
    }
    response = requests.post(
        url, headers=headers_line, json=data, timeout=REQUEST_TIMEOUT_SECONDS
    )
    print("LINE push:", response.status_code, response.text)


# ── Supabase helpers ──────────────────────────────────────────────────────────
# 使用者資料統一存放在 nurses 表。
# 欄位：id, name, role (nurse/manager/admin/pending), line_user_id, bound_at

VALID_ROLES = ("nurse", "manager", "admin", "pending")


def bind_user(line_user_id, name):
    """\n    綁定邏輯：\n    1. 名字在 nurses 表 → 更新 line_user_id 與 bound_at，保留原有 role。\n    2. 名字不在 nurses 表 → 新增一筆，role = 'pending'，等 admin 審核。\n    回傳 (nurse_record, is_new, is_pending)。\n    """
    existing = get_user_by_name(name)
    now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    if existing:
        url = f"{SUPABASE_URL}/rest/v1/nurses?id=eq.{existing['id']}"
        resp = requests.patch(
            url,
            headers=headers,
            json={"line_user_id": line_user_id, "bound_at": now_iso},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        print("Bind existing nurse:", resp.status_code, resp.text)
        updated = get_user_by_name(name)
        return updated, False, updated.get("role") == "pending"
    else:
        url = f"{SUPABASE_URL}/rest/v1/nurses"
        resp = requests.post(
            url,
            headers=headers,
            json={
                "name": name,
                "role": "pending",
                "line_user_id": line_user_id,
                "bound_at": now_iso,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        print("Bind new pending nurse:", resp.status_code, resp.text)
        new_rec = resp.json()
        record = new_rec[0] if isinstance(new_rec, list) and new_rec else None
        return record, True, True


def get_user_by_line_id(line_user_id):
    url = f"{SUPABASE_URL}/rest/v1/nurses?line_user_id=eq.{line_user_id}&select=*"
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    print("Get nurse by line_id:", response.status_code)
    if response.status_code != 200:
        return None
    data = response.json()
    return data[0] if data else None


def get_user_by_id(user_id):
    url = f"{SUPABASE_URL}/rest/v1/nurses?id=eq.{user_id}&select=*"
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        return None
    data = response.json()
    return data[0] if data else None


def get_user_by_name(name):
    """以姓名查護理師（取第一筆）。"""
    url = f"{SUPABASE_URL}/rest/v1/nurses?name=eq.{requests.utils.quote(name)}&select=*"
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        return None
    data = response.json()
    return data[0] if data else None


def update_user_role(user_id, role):
    url = f"{SUPABASE_URL}/rest/v1/nurses?id=eq.{user_id}"
    response = requests.patch(
        url, headers=headers, json={"role": role}, timeout=REQUEST_TIMEOUT_SECONDS
    )
    print("Update nurse role:", response.status_code, response.text)
    return response


def get_all_users():
    url = f"{SUPABASE_URL}/rest/v1/nurses?order=name.asc&select=*"
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        return None
    return response.json()


def get_pending_users():
    """取得所有待審核（role = pending）的護理師。"""
    url = f"{SUPABASE_URL}/rest/v1/nurses?role=eq.pending&order=bound_at.asc&select=*"
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        return []
    return response.json()


def get_reviewers():
    """取得所有 admin 和 manager（用來推播新申請通知）。"""
    url = f"{SUPABASE_URL}/rest/v1/nurses?role=in.(admin,manager)&select=*"
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code != 200:
        return []
    return response.json()


def insert_overtime_record(user_id, work_date, shift_type, other_shift_text, overtime_minutes, record_type="overtime"):
    url = f"{SUPABASE_URL}/rest/v1/overtime_records"
    data = {
        "user_id": user_id,
        "work_date": work_date,
        "shift_type": shift_type,
        "other_shift_text": other_shift_text,
        "overtime_minutes": overtime_minutes,
        "record_type": record_type,
        "status": "審核中",
    }
    response = requests.post(
        url, headers=headers, json=data, timeout=REQUEST_TIMEOUT_SECONDS
    )
    print("Insert overtime:", response.status_code, response.text)
    return response


def get_records_by_date_range(user_id=None, start_date=None, end_date=None):
    """\n    查詢加班記錄，依日期區間過濾。\n    user_id=None 表示查所有人（主管用）。\n    start_date / end_date 為 YYYY-MM-DD 字串，可為 None（不設限）。\n    回傳 list，失敗回傳 None。\n    """
    filters = ["status=neq.已取消"]
    if user_id is not None:
        filters.append(f"user_id=eq.{user_id}")
    if start_date:
        filters.append(f"work_date=gte.{start_date}")
    if end_date:
        filters.append(f"work_date=lte.{end_date}")

    query = "&".join(filters)
    url = (
        f"{SUPABASE_URL}/rest/v1/overtime_records"
        f"?{query}&order=work_date.asc&select=*"
    )
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    print("Get records by range:", response.status_code)
    if response.status_code != 200:
        return None
    return response.json()


def month_range(year_month: str):
    """回傳 (start, end_inclusive) 字串，end_inclusive 為該月最後一天。"""
    y, m = int(year_month[:4]), int(year_month[5:7])
    import calendar
    last_day = calendar.monthrange(y, m)[1]
    return f"{year_month}-01", f"{year_month}-{last_day:02d}"


def week_range_of(date: datetime):
    """回傳 date 所在週的週一與週日（字串）。"""
    monday = date - timedelta(days=date.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def get_record_by_id(record_id):
    raw_id = str(record_id).strip()
    url = f"{SUPABASE_URL}/rest/v1/overtime_records"
    response = requests.get(
        url,
        headers=headers,
        params={"id": f"eq.{raw_id}", "select": "*"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return None
    data = response.json()
    if data:
        return data[0]

    # Fallback: some environments return ids with inconsistent typing, so scan locally.
    fallback_url = (
        f"{SUPABASE_URL}/rest/v1/overtime_records"
        f"?order=work_date.desc&limit=1000&select=*"
    )
    fallback_response = requests.get(
        fallback_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if fallback_response.status_code != 200:
        return None

    target = str(record_id).strip()
    for rec in fallback_response.json():
        if str(rec.get("id", "")).strip() == target:
            return rec

    return None


def update_record_status(record_id, status, reviewer_id=None, reviewed_at=None):
    """更新記錄狀態。若提供 reviewer_id，一併寫入審核者資訊。"""
    raw_id = str(record_id).strip()
    url = f"{SUPABASE_URL}/rest/v1/overtime_records"
    payload = {"status": status}
    if reviewer_id is not None:
        payload["reviewed_by_id"] = reviewer_id
        payload["reviewed_at"] = reviewed_at or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    response = requests.patch(
        url,
        headers=headers,
        params={"id": f"eq.{raw_id}"},
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    print("Update record status:", raw_id, response.status_code, response.text)
    return response


def get_pending_records():
    """取得所有審核中的記錄（主管用）。"""
    url = (
        f"{SUPABASE_URL}/rest/v1/overtime_records"
        f"?status=eq.審核中&order=work_date.asc&select=*"
    )
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    print("Get pending records:", response.status_code, response.text)
    if response.status_code != 200:
        return None
    return response.json()


def insert_history_record(record, nurse_name):
    """將已核准的 overtime_records 同步至 overtime_history。
    source_record_id 設有 UNIQUE 約束，重複呼叫會被 DB 拒絕，不會產生重複資料。
    """
    shift = record["shift_type"]
    if shift == "其他" and record.get("other_shift_text"):
        shift = f"其他({record['other_shift_text']})"
    data = {
        "work_date": record["work_date"],
        "user_id": record["user_id"],
        "name": nurse_name,
        "shift_type": shift,
        "overtime_minutes": record["overtime_minutes"],
        "source_record_id": record["id"],
    }
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/overtime_history",
        headers=SUPABASE_HEADERS,
        json=data,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    print("Insert history:", resp.status_code, resp.text)
    return resp


# ── 格式化工具 ────────────────────────────────────────────────────────────────

def format_minutes(total_minutes):
    """支援負數（早走）。"""
    prefix = "早走 " if total_minutes < 0 else ""
    abs_min = abs(total_minutes)
    hours = abs_min // 60
    minutes = abs_min % 60
    if hours == 0:
        return f"{prefix}{minutes}分鐘"
    if minutes == 0:
        return f"{prefix}{hours}小時"
    return f"{prefix}{hours}小時{minutes}分鐘"


def is_approved_record(rec):
    return rec.get("status") == "已核准"


def format_record_line(rec, show_name=False):
    shift = rec["shift_type"]
    if shift == "其他" and rec.get("other_shift_text"):
        shift += f"（{rec['other_shift_text']}）"
    name_part = f" [{rec.get('name', '')}]" if show_name else ""
    is_leave = rec.get("record_type") == "leave_early" or rec.get("overtime_minutes", 0) < 0
    type_tag = "【早走】" if is_leave else ""
    return (
        f"#{rec['id']} {type_tag}{rec['work_date']}{name_part} {shift} "
        f"{format_minutes(rec['overtime_minutes'])} ─ {rec['status']}"
    )


# ── 指令解析 ──────────────────────────────────────────────────────────────────

def format_shift_display(shift_type, other_shift_text=None):
    if shift_type == "其他" and other_shift_text:
        return f"{shift_type}（{other_shift_text}）"
    return shift_type


def build_overtime_message(
    title,
    work_date,
    shift_display,
    overtime_minutes,
    record_id,
    applicant_name=None,
    extra_lines=None,
):
    lines = [title]
    if applicant_name:
        lines.append(f"申請人：{applicant_name}")
    lines.append(f"日期：{work_date}")
    lines.append(f"班別：{shift_display}")
    type_label = "早走時數" if overtime_minutes < 0 else "加班時數"
    lines.append(f"{type_label}：{format_minutes(overtime_minutes)}")
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)
    lines.append("")
    lines.append(f"編號：#{record_id}")
    return "\n".join(lines)


def parse_overtime_duration(duration_str):
    match = re.fullmatch(r"(\d+):([0-5]\d)", duration_str)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if minutes > 59:
        return None
    total_minutes = hours * 60 + minutes
    return total_minutes if total_minutes > 0 else None


def parse_overtime_command(text):
    """\n    格式 1：加班 2026-04-17 7-3 2:15\n    格式 2：加班 2026-04-17 其他 急診支援 0:45\n    """
    parts = text.strip().split()
    if len(parts) < 4:
        return {"ok": False, "error": "格式不足"}
    if parts[0] != "加班":
        return {"ok": False, "error": "不是加班指令"}

    work_date = parts[1]
    shift_type = parts[2]

    try:
        datetime.strptime(work_date, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "error": "日期格式錯誤"}

    allowed_shift_types = {"7-3", "9-5", "10-6", "12-8", "3-11", "11-7", "其他"}
    if shift_type not in allowed_shift_types:
        return {"ok": False, "error": "班別錯誤（可用：7-3 / 9-5 / 10-6 / 12-8 / 3-11 / 11-7 / 其他）"}

    other_shift_text = None
    if shift_type == "其他":
        if len(parts) < 5:
            return {"ok": False, "error": "其他班別需輸入班別名稱與時數"}
        duration_str = parts[-1]
        other_shift_text = " ".join(parts[3:-1]).strip()
        if not other_shift_text:
            return {"ok": False, "error": "其他班別名稱不可空白"}
    else:
        if len(parts) != 4:
            return {"ok": False, "error": "固定班別格式錯誤"}
        duration_str = parts[3]

    overtime_minutes = parse_overtime_duration(duration_str)
    if overtime_minutes is None:
        return {"ok": False, "error": "加班時數格式錯誤（格式：小時:分鐘，例如 2:30）"}

    return {
        "ok": True,
        "work_date": work_date,
        "shift_type": shift_type,
        "other_shift_text": other_shift_text,
        "overtime_minutes": overtime_minutes,
        "record_type": "overtime",
    }


# ── HTTP 端點 ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"service": "nurse-ot-line", "status": "ok"}


def serve_docs_file(filename: str):
    path = DOCS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(path)


@app.get("/index.html")
def docs_index():
    return serve_docs_file("index.html")


@app.get("/nurse.html")
def docs_nurse():
    return serve_docs_file("nurse.html")


@app.get("/manager.html")
def docs_manager():
    return serve_docs_file("manager.html")


@app.get("/admin.html")
def docs_admin():
    return serve_docs_file("admin.html")


@app.get("/bot-links.html")
def docs_bot_links():
    return serve_docs_file("bot-links.html")


@app.get("/health")
def health():
    missing_env = [
        key
        for key, value in {
            "LINE_CHANNEL_ACCESS_TOKEN": LINE_TOKEN,
            "SUPABASE_URL": SUPABASE_URL,
            "SUPABASE_KEY": SUPABASE_KEY,
        }.items()
        if not value
    ]
    # 快速確認 nurses 表是否可存取
    nurses_ok = True
    if not missing_env:
        try:
            r = requests.get(
                f"{SUPABASE_URL}/rest/v1/nurses?limit=1&select=id",
                headers=SUPABASE_HEADERS,
                timeout=5,
            )
            nurses_ok = r.status_code == 200
        except Exception:
            nurses_ok = False
    status = "ok" if (not missing_env and nurses_ok) else "degraded"
    return {
        "status": status,
        "missing_env": missing_env,
        "nurses_table": "ok" if nurses_ok else "unreachable",
    }


# ── Pydantic models ───────────────────────────────────────────────────────────

class OvertimeSubmit(BaseModel):
    work_date: str
    shift_type: str
    other_shift_text: Optional[str] = None
    overtime_minutes: int
    record_type: str = "overtime"  # "overtime" | "leave_early"

class RoleUpdate(BaseModel):
    target_name: str
    role: str  # nurse / manager / admin

class RecordAction(BaseModel):
    record_id: str
    action: str  # approve / reject / cancel


# ── LIFF 身分驗證 helper ──────────────────────────────────────────────────────
# LIFF 頁面取得 liff.getProfile() 後，把 line_user_id 帶在 Header: X-Line-User-Id

def get_current_user(request: Request):
    line_user_id = request.headers.get("X-Line-User-Id")
    if not line_user_id:
        raise HTTPException(status_code=401, detail="Missing X-Line-User-Id header")
    user = get_user_by_line_id(line_user_id)
    if not user:
        raise HTTPException(status_code=403, detail="User not registered. Please bind first.")
    if user.get("role") == "pending":
        raise HTTPException(status_code=403, detail="Account pending approval. Please contact admin.")
    return user

def require_manager(user=Depends(get_current_user)):
    if user.get("role") not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="Manager or admin role required")
    return user

def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


# ── LIFF API endpoints ────────────────────────────────────────────────────────

@app.get("/api/me")
def api_me(request: Request):
    """取得目前登入者資料與角色。"""
    user = get_current_user(request)
    return {
        "id": user["id"],
        "name": user["name"],
        "role": user.get("role", "nurse"),
        "line_user_id": user["line_user_id"],
    }


@app.post("/api/bind")
async def api_bind(request: Request):
    """綁定姓名（首次登入時呼叫）。"""
    line_user_id = request.headers.get("X-Line-User-Id")
    if not line_user_id:
        raise HTTPException(status_code=401, detail="Missing X-Line-User-Id header")
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    nurse, is_new, is_pending = bind_user(line_user_id, name)
    if not nurse:
        raise HTTPException(status_code=500, detail="Failed to bind user")

    if is_pending:
        for admin in get_reviewers():
            if admin.get("line_user_id") and admin.get("role") == "admin":
                admin_msg = (
                    "⚠️ 有新使用者待審核\n"
                    "姓名：" + name + "\n"
                    "請用「設定角色 " + name + " nurse」核准，或「刪除護理師 " + name + "」拒絕。"
                )
                push_message(admin["line_user_id"], admin_msg)

    return {"ok": True, "name": name, "role": nurse.get("role", "pending"), "pending": is_pending}


@app.get("/api/records/me")
def api_records_me(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    month: Optional[str] = None,
):
    """\n    查詢本人加班記錄。\n    ?month=2026-04         → 指定月份\n    ?start=2026-04-01&end=2026-04-30 → 自訂區間\n    無參數 → 最近 20 筆\n    """
    user = get_current_user(request)

    if month:
        try:
            datetime.strptime(month + "-01", "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month format, use YYYY-MM")
        start_date, end_date = month_range(month)
        records = get_records_by_date_range(user_id=user["id"], start_date=start_date, end_date=end_date)
    elif start or end:
        try:
            if start:
                datetime.strptime(start, "%Y-%m-%d")
            if end:
                datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
        records = get_records_by_date_range(user_id=user["id"], start_date=start, end_date=end)
    else:
        url = (
            f"{SUPABASE_URL}/rest/v1/overtime_records"
            f"?user_id=eq.{user['id']}&status=neq.已取消"
            f"&order=work_date.desc&limit=20&select=*"
        )
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        records = resp.json() if resp.status_code == 200 else None

    if records is None:
        raise HTTPException(status_code=500, detail="Query failed")

    total_minutes = sum(r["overtime_minutes"] for r in records)
    return {"records": records, "total_minutes": total_minutes, "count": len(records)}


@app.get("/api/history/me")
def api_history_me(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    month: Optional[str] = None,
):
    """查詢本人完整加班歷史（overtime_history，含歷史匯入與已核准記錄）。
    ?month=2026-04         → 指定月份
    ?start=2026-01-01&end=2026-03-31 → 自訂區間
    無參數 → 全部（依日期升冪）
    """
    user = get_current_user(request)
    filters = [f"user_id=eq.{user['id']}"]
    if month:
        try:
            datetime.strptime(month + "-01", "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month format, use YYYY-MM")
        s, e = month_range(month)
        filters += [f"work_date=gte.{s}", f"work_date=lte.{e}"]
    elif start or end:
        try:
            if start:
                datetime.strptime(start, "%Y-%m-%d")
            if end:
                datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
        if start:
            filters.append(f"work_date=gte.{start}")
        if end:
            filters.append(f"work_date=lte.{end}")
    query = "&".join(filters)
    url = f"{SUPABASE_URL}/rest/v1/overtime_history?{query}&order=work_date.asc&limit=10000&select=*"
    resp = requests.get(url, headers=SUPABASE_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Query failed")
    records = resp.json()
    total_minutes = sum(r["overtime_minutes"] for r in records)
    return {"records": records, "total_minutes": total_minutes, "count": len(records)}


@app.get("/api/history/all")
def api_history_all(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    month: Optional[str] = None,
    week: Optional[str] = None,  # "current"
):
    """全員加班歷史（overtime_history，manager / admin）。"""
    require_manager(get_current_user(request))
    filters = []
    now = datetime.now()
    if week == "current":
        s, e = week_range_of(now)
        filters += [f"work_date=gte.{s}", f"work_date=lte.{e}"]
    elif month:
        try:
            datetime.strptime(month + "-01", "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month format, use YYYY-MM")
        s, e = month_range(month)
        filters += [f"work_date=gte.{s}", f"work_date=lte.{e}"]
    elif start or end:
        if start:
            filters.append(f"work_date=gte.{start}")
        if end:
            filters.append(f"work_date=lte.{end}")
    q = "&".join(filters)
    base = f"{SUPABASE_URL}/rest/v1/overtime_history"
    url = f"{base}?{q}&order=work_date.asc&limit=10000&select=*" if q else f"{base}?order=work_date.asc&limit=10000&select=*"
    resp = requests.get(url, headers=SUPABASE_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Query failed")
    records = resp.json()
    person_totals: dict = {}
    for r in records:
        name = r.get("name") or "未知"
        person_totals[name] = person_totals.get(name, 0) + r["overtime_minutes"]
    total_minutes = sum(r["overtime_minutes"] for r in records)
    return {"records": records, "count": len(records), "total_minutes": total_minutes, "person_totals": person_totals}


@app.get("/api/history/monthly-summary")
def api_history_monthly_summary(request: Request, year: Optional[int] = None):
    """全年各月統計（overtime_history，manager / admin）。"""
    require_manager(get_current_user(request))
    year = year or datetime.now().year
    result = []
    for m in range(1, 13):
        ym = f"{year}-{m:02d}"
        s, e = month_range(ym)
        url = (f"{SUPABASE_URL}/rest/v1/overtime_history"
               f"?work_date=gte.{s}&work_date=lte.{e}&limit=10000&select=overtime_minutes")
        resp = requests.get(url, headers=SUPABASE_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        recs = resp.json() if resp.status_code == 200 else []
        total = sum(r["overtime_minutes"] for r in recs)
        result.append({"month": ym, "count": len(recs), "total_minutes": total})
    return {"year": year, "months": result}


@app.post("/api/overtime")
async def api_overtime_submit(request: Request, body: OvertimeSubmit):
    """提交加班申請。"""
    user = get_current_user(request)

    # 驗證
    try:
        datetime.strptime(body.work_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid work_date format")
    if body.shift_type not in ("7-3", "9-5", "10-6", "12-8", "3-11", "11-7", "其他"):
        raise HTTPException(status_code=400, detail="Invalid shift_type")
    if body.shift_type == "其他" and not body.other_shift_text:
        raise HTTPException(status_code=400, detail="other_shift_text required for 其他")
    if body.record_type not in ("overtime", "leave_early"):
        raise HTTPException(status_code=400, detail="record_type must be overtime or leave_early")
    if body.overtime_minutes == 0:
        raise HTTPException(status_code=400, detail="overtime_minutes cannot be zero")
    if body.record_type == "overtime" and body.overtime_minutes < 0:
        raise HTTPException(status_code=400, detail="overtime_minutes must be positive for overtime")
    # 前端一律送正數，早走在後端轉成負數
    final_minutes = (
        -abs(body.overtime_minutes)
        if body.record_type == "leave_early"
        else abs(body.overtime_minutes)
    )

    resp = insert_overtime_record(
        user_id=user["id"],
        work_date=body.work_date,
        shift_type=body.shift_type,
        other_shift_text=body.other_shift_text,
        overtime_minutes=final_minutes,
        record_type=body.record_type,
    )
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail="Failed to submit overtime")

    new_rec = resp.json()
    rec_id = new_rec[0]["id"] if new_rec else "?"
    shift_display = format_shift_display(body.shift_type, body.other_shift_text)

    return {"ok": True, "record_id": rec_id}


@app.post("/api/overtime/{record_id}/cancel")
def api_overtime_cancel(record_id: int, request: Request):
    """取消自己的加班申請。"""
    user = get_current_user(request)
    rec = get_record_by_id(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    if str(rec["user_id"]) != str(user["id"]):
        raise HTTPException(status_code=403, detail="Cannot cancel other's record")
    if rec["status"] != "審核中":
        raise HTTPException(status_code=400, detail=f"Cannot cancel record with status: {rec['status']}")
    resp = update_record_status(record_id, "已取消")
    if resp.status_code not in (200, 204):
        raise HTTPException(status_code=500, detail="Failed to cancel")
    return {"ok": True}


# ── Manager / Admin API ───────────────────────────────────────────────────────

@app.get("/api/records/pending")
def api_pending(request: Request):
    """待審核清單（manager / admin）。"""
    user = require_manager(get_current_user(request))
    records = get_pending_records()
    if records is None:
        raise HTTPException(status_code=500, detail="Query failed")
    # 補充申請人姓名
    user_cache = {}
    for rec in records:
        uid = rec["user_id"]
        if uid not in user_cache:
            u = get_user_by_id(uid)
            user_cache[uid] = u["name"] if u else "未知"
        rec["applicant_name"] = user_cache[uid]
    return {"records": records, "count": len(records)}


@app.get("/api/records/all")
def api_records_all(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    month: Optional[str] = None,
    week: Optional[str] = None,  # "current"
):
    """全員加班記錄（manager / admin）。"""
    user = require_manager(get_current_user(request))
    now = datetime.now()

    if week == "current":
        start_date, end_date = week_range_of(now)
    elif month == "current":
        start_date, end_date = month_range(now.strftime("%Y-%m"))
    elif month:
        try:
            datetime.strptime(month + "-01", "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month format")
        start_date, end_date = month_range(month)
    else:
        start_date, end_date = start, end

    records = get_records_by_date_range(user_id=None, start_date=start_date, end_date=end_date)
    if records is None:
        raise HTTPException(status_code=500, detail="Query failed")

    user_cache = {}
    person_totals = {}
    for rec in records:
        uid = rec["user_id"]
        if uid not in user_cache:
            u = get_user_by_id(uid)
            user_cache[uid] = u["name"] if u else "未知"
        rec["applicant_name"] = user_cache[uid]
        if is_approved_record(rec):
            person_totals[user_cache[uid]] = person_totals.get(user_cache[uid], 0) + rec["overtime_minutes"]

    approved_records = [rec for rec in records if is_approved_record(rec)]
    approved_total_minutes = sum(r["overtime_minutes"] for r in approved_records)
    total_minutes = sum(r["overtime_minutes"] for r in records)
    return {
        "records": records,
        "count": len(records),
        "total_minutes": total_minutes,
        "person_totals": person_totals,
        "approved_count": len(approved_records),
        "approved_total_minutes": approved_total_minutes,
        "approved_person_totals": person_totals,
    }


@app.get("/api/records/monthly-summary")
def api_monthly_summary(request: Request, year: Optional[int] = None):
    """全年各月統計（manager / admin）。"""
    user = require_manager(get_current_user(request))
    year = year or datetime.now().year
    result = []
    for m in range(1, 13):
        ym = f"{year}-{m:02d}"
        s, e = month_range(ym)
        recs = get_records_by_date_range(user_id=None, start_date=s, end_date=e)
        approved_recs = [r for r in (recs or []) if is_approved_record(r)]
        total = sum(r["overtime_minutes"] for r in approved_recs)
        result.append({"month": ym, "count": len(approved_recs), "total_minutes": total})
    return {"year": year, "months": result}


@app.post("/api/records/{record_id}/review")
async def api_review(record_id: str, request: Request):
    """審核加班申請（manager / admin）。"""
    user = require_manager(get_current_user(request))
    body = await request.json()
    action = body.get("action")  # "approve" | "reject"
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be approve or reject")

    rec = get_record_by_id(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    if rec["status"] != "審核中":
        raise HTTPException(status_code=400, detail=f"Record status is already: {rec['status']}")

    new_status = "已核准" if action == "approve" else "已拒絕"
    resp = update_record_status(record_id, new_status, reviewer_id=user["id"])
    if resp.status_code not in (200, 204):
        detail = resp.text.strip() or "Failed to update status"
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update status: {resp.status_code} {detail}",
        )

    applicant = get_user_by_id(rec["user_id"])

    # 同步至 overtime_history（失敗不 rollback 審核結果）
    if new_status == "已核准":
        try:
            insert_history_record(
                rec,
                applicant["name"] if applicant else str(rec["user_id"]),
            )
        except Exception as exc:
            print("History sync failed:", exc)

    # 推播通知申請人；通知失敗不應讓審核流程回滾
    if applicant and applicant.get("line_user_id"):
        shift_display = format_shift_display(rec["shift_type"], rec.get("other_shift_text"))
        icon = "✅" if new_status == "已核准" else "❌"
        reviewer_name = user.get("name") or "主管"
        try:
            push_message(
                applicant["line_user_id"],
                build_overtime_message(
                    f"{icon} 加班申請已{new_status}",
                    rec["work_date"],
                    shift_display,
                    rec["overtime_minutes"],
                    record_id,
                    extra_lines=[f"審核者：{reviewer_name}"],
                ),
            )
        except Exception as exc:
            print("Push applicant notification failed:", exc)

    return {"ok": True, "new_status": new_status}


# ── 審核紀錄 API ──────────────────────────────────────────────────────────────

@app.get("/api/records/review-log")
def api_review_log(
    request: Request,
    start: Optional[str] = None,
    end: Optional[str] = None,
    reviewer_id: Optional[str] = None,
    applicant_name: Optional[str] = None,
):
    """審核紀錄查詢（manager / admin）。
    - manager：只能查自己審核的記錄（reviewer_id 固定為自己）。
    - admin：可查所有人的審核記錄，也可用 reviewer_id 篩選特定審核者。
    """
    user = require_manager(get_current_user(request))
    is_admin = user["role"] == "admin"

    filters = ["status=in.(已核准,已拒絕)", "reviewed_by_id=not.is.null"]

    # manager 只能看自己審的
    effective_reviewer_id = reviewer_id if is_admin else str(user["id"])
    if effective_reviewer_id:
        filters.append(f"reviewed_by_id=eq.{effective_reviewer_id}")

    if start:
        filters.append(f"reviewed_at=gte.{start}T00:00:00Z")
    if end:
        filters.append(f"reviewed_at=lte.{end}T23:59:59Z")

    url = (
        f"{SUPABASE_URL}/rest/v1/overtime_records"
        f"?{'&'.join(filters)}&order=reviewed_at.desc&limit=500&select=*"
    )
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Query failed")

    records = resp.json()

    # 補上申請人姓名與審核者姓名
    user_cache = {}
    def resolve_name(uid):
        if uid not in user_cache:
            u = get_user_by_id(uid)
            user_cache[uid] = u["name"] if u else "未知"
        return user_cache[uid]

    for rec in records:
        rec["applicant_name"] = resolve_name(rec["user_id"])
        rec["reviewer_name"] = resolve_name(rec["reviewed_by_id"]) if rec.get("reviewed_by_id") else ""

    # 前端姓名篩選（applicant_name）
    if applicant_name:
        records = [r for r in records if applicant_name in r["applicant_name"]]

    # 若 admin 查全部，額外回傳可用的審核者清單供下拉篩選
    reviewers = []
    if is_admin:
        seen = {}
        for rec in records:
            rid = rec.get("reviewed_by_id")
            if rid and rid not in seen:
                seen[rid] = rec["reviewer_name"]
        reviewers = [{"id": k, "name": v} for k, v in seen.items()]

    return {
        "records": records,
        "count": len(records),
        "reviewers": reviewers,
    }


# ── Admin API ─────────────────────────────────────────────────────────────────

@app.get("/api/members")
def api_members(request: Request):
    """成員清單（admin）。"""
    user = require_admin(get_current_user(request))
    all_users = get_all_users()
    if all_users is None:
        raise HTTPException(status_code=500, detail="Query failed")
    return {"members": all_users, "count": len(all_users)}


@app.post("/api/members/role")
async def api_set_role(request: Request, body: RoleUpdate):
    """設定成員角色（admin）。"""
    user = require_admin(get_current_user(request))
    if body.role not in ("nurse", "manager", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")
    target = get_user_by_name(body.target_name)
    if not target:
        raise HTTPException(status_code=404, detail=f"User not found: {body.target_name}")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    resp = update_user_role(target["id"], body.role)
    if resp.status_code not in (200, 204):
        raise HTTPException(status_code=500, detail="Failed to update role")
    return {"ok": True, "name": body.target_name, "new_role": body.role}



@app.post("/webhook")
async def webhook(request: Request, x_line_signature: str = Header(None)):
    body = await request.json()
    print("Webhook body:", body)

    for event in body.get("events", []):
        event_type = event.get("type")

        # ── 加入好友 ──────────────────────────────────────────────────────────
        if event_type == "follow":
            reply_message(
                event["replyToken"],
                "歡迎使用加班系統！\n請先輸入：綁定 姓名\n例如：綁定 王小美",
            )
            continue

        if event_type != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        line_user_id = event["source"]["userId"]
        text = message["text"].strip()
        reply_token = event["replyToken"]

        # ── 綁定 ──────────────────────────────────────────────────────────────
        if text.startswith("綁定"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                reply_message(reply_token, "請輸入：綁定 姓名")
                continue
            name = parts[1].strip()
            nurse, is_new, is_pending = bind_user(line_user_id, name)
            if not nurse:
                reply_message(reply_token, "綁定失敗，請稍後再試")
                continue
            if is_pending:
                reply_msg = (
                    "已收到綁定申請：" + name + "\n"
                    "您的名字不在護理師名單中，已通知管理員審核。\n"
                    "審核通過後即可使用系統。"
                )
                reply_message(reply_token, reply_msg)
                for adm in get_reviewers():
                    if adm.get("line_user_id") and adm.get("role") == "admin":
                        adm_msg = (
                            "⚠️ 有新使用者待審核\n"
                            "姓名：" + name + "\n"
                            "請用「設定角色 " + name + " nurse」核准，或「刪除護理師 " + name + "」拒絕。"
                        )
                        push_message(adm["line_user_id"], adm_msg)
            else:
                reply_message(reply_token, "已綁定為 " + name + "（" + nurse.get("role", "nurse") + "）")
            continue

        # ── 查使用者（綁定後才能用其他指令）────────────────────────────────────
        user = get_user_by_line_id(line_user_id)
        if not user:
            reply_message(reply_token, "請先輸入：綁定 姓名")
            continue

        # pending 使用者只能等待審核
        if user.get("role") == "pending":
            reply_message(
                reply_token,
                "⏳ 您的帳號正在審核中，請聯絡管理員。\n審核通過後即可使用系統。",
            )
            continue

        is_admin = user.get("role") == "admin"
        is_manager = is_admin or user.get("role") == "manager"  # manager + admin 都有審核/全員查詢權

        # ── 加班回報 ──────────────────────────────────────────────────────────
        if text.startswith("加班"):
            parsed = parse_overtime_command(text)
            if not parsed["ok"]:
                reply_message(
                    reply_token,
                    f"格式錯誤：{parsed['error']}\n\n"
                    "請使用：\n"
                    "加班 2026-04-17 7-3 2:15\n"
                    "或\n"
                    "加班 2026-04-17 其他 急診支援 0:45",
                )
                continue

            response = insert_overtime_record(
                user_id=user["id"],
                work_date=parsed["work_date"],
                shift_type=parsed["shift_type"],
                other_shift_text=parsed["other_shift_text"],
                overtime_minutes=parsed["overtime_minutes"],
            )

            if response.status_code in (200, 201):
                new_rec = response.json()
                rec_id = new_rec[0]["id"] if new_rec else "?"
                shift_display = format_shift_display(parsed["shift_type"], parsed["other_shift_text"])
                reply_message(
                    reply_token,
                    build_overtime_message(
                        "✅ 已送出加班申請",
                        parsed["work_date"],
                        shift_display,
                        parsed["overtime_minutes"],
                        rec_id,
                        extra_lines=["目前狀態：審核中"],
                    ),
                )

            else:
                reply_message(reply_token, "加班回報失敗，請稍後再試")
            continue


        # ── 早走申請 ──────────────────────────────────────────────────────────
        # 格式：早走 2026-04-17 7-3 0:30
        if text.startswith("早走"):
            parsed = parse_overtime_command("加班" + text[2:])
            if not parsed["ok"]:
                reply_message(
                    reply_token,
                    "格式錯誤：" + parsed["error"] + "\n\n"
                    "請使用：\n"
                    "早走 2026-04-17 7-3 0:30\n"
                    "或\n"
                    "早走 2026-04-17 其他 急診支援 0:30",
                )
                continue

            leave_minutes = -parsed["overtime_minutes"]
            response = insert_overtime_record(
                user_id=user["id"],
                work_date=parsed["work_date"],
                shift_type=parsed["shift_type"],
                other_shift_text=parsed["other_shift_text"],
                overtime_minutes=leave_minutes,
                record_type="leave_early",
            )

            if response.status_code in (200, 201):
                new_rec = response.json()
                rec_id = new_rec[0]["id"] if new_rec else "?"
                shift_display = format_shift_display(parsed["shift_type"], parsed["other_shift_text"])
                reply_message(
                    reply_token,
                    build_overtime_message(
                        "✅ 已送出早走申請",
                        parsed["work_date"],
                        shift_display,
                        leave_minutes,
                        rec_id,
                        extra_lines=["目前狀態：審核中"],
                    ),
                )

            else:
                reply_message(reply_token, "早走申請失敗，請稍後再試")
            continue

        # ── 查詢本人記錄 ─────────────────────────────────────────────────────
        # 格式：
        #   我的記錄                   → 最近 20 筆
        #   我的記錄 2026-04           → 指定月份
        #   我的記錄 2026-04-01 2026-04-30  → 自訂起訖日
        if text.startswith("我的記錄"):
            parts = text.split()
            start_date = end_date = None
            label = "最近記錄"

            if len(parts) == 2:
                # 月份格式 YYYY-MM
                ym = parts[1]
                try:
                    datetime.strptime(ym + "-01", "%Y-%m-%d")
                except ValueError:
                    reply_message(reply_token, "日期格式錯誤\n月份請用：我的記錄 2026-04\n或自訂：我的記錄 2026-04-01 2026-04-30")
                    continue
                start_date, end_date = month_range(ym)
                label = f"{ym} 記錄"

            elif len(parts) == 3:
                # 自訂起訖 YYYY-MM-DD YYYY-MM-DD
                try:
                    datetime.strptime(parts[1], "%Y-%m-%d")
                    datetime.strptime(parts[2], "%Y-%m-%d")
                except ValueError:
                    reply_message(reply_token, "日期格式錯誤\n請用：我的記錄 2026-04-01 2026-04-30")
                    continue
                if parts[1] > parts[2]:
                    reply_message(reply_token, "起始日期不可晚於結束日期")
                    continue
                start_date, end_date = parts[1], parts[2]
                label = f"{start_date} ～ {end_date} 記錄"

            elif len(parts) == 1:
                # 不限日期，取最近 20 筆（透過 order 降冪，再限筆數）
                url = (
                    f"{SUPABASE_URL}/rest/v1/overtime_records"
                    f"?user_id=eq.{user['id']}&status=neq.已取消"
                    f"&order=work_date.desc&limit=20&select=*"
                )
                resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
                records = resp.json() if resp.status_code == 200 else None
                if records is None:
                    reply_message(reply_token, "查詢失敗，請稍後再試")
                    continue
                records = list(reversed(records))  # 改回升冪顯示
            else:
                reply_message(reply_token, "格式錯誤\n我的記錄\n我的記錄 2026-04\n我的記錄 2026-04-01 2026-04-30")
                continue

            if start_date:
                records = get_records_by_date_range(user_id=user["id"], start_date=start_date, end_date=end_date)
                if records is None:
                    reply_message(reply_token, "查詢失敗，請稍後再試")
                    continue

            if not records:
                reply_message(reply_token, f"📋 {label}：無資料")
                continue

            total_min = sum(r["overtime_minutes"] for r in records)
            lines = [f"📋 {label}（共 {len(records)} 筆，合計 {format_minutes(total_min)}）："]
            for rec in records:
                lines.append(format_record_line(rec))
            reply_message(reply_token, "\n".join(lines))
            continue

        # ── 查詢所有人（主管專用）────────────────────────────────────────────
        # 格式：
        #   全員查詢 當週
        #   全員查詢 當月
        #   全員查詢 2026-04         → 指定月份
        #   全員查詢 2026-04-01 2026-04-30  → 自訂起訖
        if text.startswith("全員查詢"):
            if not is_manager:
                reply_message(reply_token, "您沒有查詢全員記錄的權限")
                continue

            parts = text.split()
            now = datetime.now()
            start_date = end_date = None
            label = ""

            if len(parts) == 1:
                reply_message(
                    reply_token,
                    "請指定時間範圍：\n"
                    "全員查詢 當週\n"
                    "全員查詢 當月\n"
                    "全員查詢 2026-04\n"
                    "全員查詢 2026-04-01 2026-04-30",
                )
                continue

            elif len(parts) == 2 and parts[1] == "當週":
                start_date, end_date = week_range_of(now)
                label = f"當週（{start_date} ～ {end_date}）"

            elif len(parts) == 2 and parts[1] == "當月":
                ym = now.strftime("%Y-%m")
                start_date, end_date = month_range(ym)
                label = f"當月（{ym}）"

            elif len(parts) == 2:
                # YYYY-MM 指定月份
                ym = parts[1]
                try:
                    datetime.strptime(ym + "-01", "%Y-%m-%d")
                except ValueError:
                    reply_message(reply_token, "格式錯誤，月份請用 YYYY-MM，例如 2026-04")
                    continue
                start_date, end_date = month_range(ym)
                label = f"{ym}"

            elif len(parts) == 3:
                # 自訂起訖
                try:
                    datetime.strptime(parts[1], "%Y-%m-%d")
                    datetime.strptime(parts[2], "%Y-%m-%d")
                except ValueError:
                    reply_message(reply_token, "日期格式錯誤，請用 YYYY-MM-DD")
                    continue
                if parts[1] > parts[2]:
                    reply_message(reply_token, "起始日期不可晚於結束日期")
                    continue
                start_date, end_date = parts[1], parts[2]
                label = f"{start_date} ～ {end_date}"

            else:
                reply_message(reply_token, "格式錯誤，請重新輸入")
                continue

            records = get_records_by_date_range(user_id=None, start_date=start_date, end_date=end_date)
            if records is None:
                reply_message(reply_token, "查詢失敗，請稍後再試")
                continue
            if not records:
                reply_message(reply_token, f"📊 全員 {label}：無資料")
                continue

            # 補充申請人姓名，並依人分組統計
            user_map = {}
            for rec in records:
                uid = rec["user_id"]
                if uid not in user_map:
                    applicant = get_user_by_id(uid)
                    user_map[uid] = applicant["name"] if applicant else f"uid:{uid}"
                rec["name"] = user_map[uid]

            # 按人分組加總
            from collections import defaultdict
            approved_records = [rec for rec in records if is_approved_record(rec)]
            person_totals = defaultdict(int)
            for rec in approved_records:
                person_totals[rec["name"]] += rec["overtime_minutes"]

            total_all = sum(r["overtime_minutes"] for r in approved_records)
            lines = [
                f"📊 全員加班 {label}",
                f"共 {len(approved_records)} 筆  合計 {format_minutes(total_all)}",
                "",
                "── 個人合計 ──",
            ]
            for name, mins in sorted(person_totals.items(), key=lambda item: item[1], reverse=True):
                lines.append(f"  {name}：{format_minutes(mins)}")
            lines.append("")
            lines.append("── 明細 ──")
            for rec in records:
                lines.append(format_record_line(rec, show_name=True))
            reply_message(reply_token, "\n".join(lines))
            continue

        # ── 每月分統計（主管專用）────────────────────────────────────────────
        # 格式：月份統計 2026
        if text.startswith("月份統計"):
            if not is_manager:
                reply_message(reply_token, "您沒有查詢月份統計的權限")
                continue

            parts = text.split()
            year = now.year if len(parts) < 2 else None
            if len(parts) >= 2:
                try:
                    year = int(parts[1])
                    if not (2000 <= year <= 2100):
                        raise ValueError
                except ValueError:
                    reply_message(reply_token, "格式錯誤，請用：月份統計 2026")
                    continue
            else:
                year = datetime.now().year

            lines = [f"📊 {year} 年各月加班統計"]
            grand_total = 0
            for m in range(1, 13):
                ym = f"{year}-{m:02d}"
                s, e = month_range(ym)
                recs = get_records_by_date_range(user_id=None, start_date=s, end_date=e)
                if recs is None:
                    lines.append(f"  {m:02d}月：查詢失敗")
                    continue
                approved_recs = [r for r in recs if is_approved_record(r)]
                mins = sum(r["overtime_minutes"] for r in approved_recs)
                grand_total += mins
                count = len(approved_recs)
                if count > 0:
                    lines.append(f"  {m:02d}月：{format_minutes(mins)}（{count} 筆）")
                else:
                    lines.append(f"  {m:02d}月：—")
            lines.append(f"\n全年合計：{format_minutes(grand_total)}")
            reply_message(reply_token, "\n".join(lines))
            continue

        # ── 取消加班申請 ──────────────────────────────────────────────────────
        # 格式：取消 123
        if text.startswith("取消"):
            parts = text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                reply_message(reply_token, "請輸入：取消 申請編號\n例如：取消 123")
                continue

            record_id = int(parts[1])
            rec = get_record_by_id(record_id)

            if not rec:
                reply_message(reply_token, f"找不到申請 #{record_id}")
                continue
            if str(rec["user_id"]) != str(user["id"]):
                reply_message(reply_token, "只能取消自己的申請")
                continue
            if rec["status"] != "審核中":
                reply_message(
                    reply_token,
                    f"申請 #{record_id} 目前狀態為「{rec['status']}」，無法取消",
                )
                continue

            response = update_record_status(record_id, "已取消")
            if response.status_code in (200, 204):
                reply_message(reply_token, f"已取消申請 #{record_id}")
            else:
                reply_message(reply_token, "取消失敗，請稍後再試")
            continue

        # ── 主管審核 ──────────────────────────────────────────────────────────
        # 格式：核准 123  /  拒絕 123
        if text.startswith("核准") or text.startswith("拒絕"):
            if not is_manager:
                reply_message(reply_token, "您沒有審核權限")
                continue

            parts = text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                reply_message(
                    reply_token,
                    "請輸入：核准 申請編號\n或：拒絕 申請編號\n例如：核准 123",
                )
                continue

            action = parts[0]  # 核准 / 拒絕
            record_id = int(parts[1])
            new_status = "已核准" if action == "核准" else "已拒絕"

            rec = get_record_by_id(record_id)
            if not rec:
                reply_message(reply_token, f"找不到申請 #{record_id}")
                continue
            if rec["status"] != "審核中":
                reply_message(
                    reply_token,
                    f"申請 #{record_id} 目前狀態為「{rec['status']}」，無需重複審核",
                )
                continue

            response = update_record_status(record_id, new_status, reviewer_id=user["id"])
            if response.status_code not in (200, 204):
                reply_message(reply_token, "審核失敗，請稍後再試")
                continue

            # 通知申請人
            applicant = get_user_by_id(rec["user_id"])

            # 同步至 overtime_history
            if new_status == "已核准":
                try:
                    insert_history_record(
                        rec,
                        applicant["name"] if applicant else str(rec["user_id"]),
                    )
                except Exception as exc:
                    print("History sync failed:", exc)

            if applicant and applicant.get("line_user_id"):
                shift_display = format_shift_display(rec["shift_type"], rec.get("other_shift_text"))
                icon = "✅" if new_status == "已核准" else "❌"
                reviewer_name = user.get("name") or "主管"
                push_message(
                    applicant["line_user_id"],
                    build_overtime_message(
                        f"{icon} 加班申請已{new_status}",
                        rec["work_date"],
                        shift_display,
                        rec["overtime_minutes"],
                        record_id,
                        extra_lines=[f"審核者：{reviewer_name}"],
                    ),
                )

            reply_message(reply_token, f"申請 #{record_id} 已{new_status}")
            continue

        # ── 待審清單（主管專用）───────────────────────────────
        # 格式：待審清單
        if text == "待審清單":
            if not is_manager:
                reply_message(reply_token, "您沒有查看待審清單的權限")
                continue

            records = get_pending_records()
            if records is None:
                reply_message(reply_token, "查詢失敗，請稍後再試")
                continue
            if not records:
                reply_message(reply_token, "目前沒有待審核的申請")
                continue

            enriched = []
            for rec in records:
                applicant = get_user_by_id(rec["user_id"])
                rec["name"] = applicant["name"] if applicant else "未知"
                enriched.append(rec)

            lines = [f"📋 待審核申請（共 {len(enriched)} 筆）："]
            for rec in enriched:
                lines.append(format_record_line(rec, show_name=True))
            lines.append("\n審核：核准 編號  或  拒絕 編號")
            reply_message(reply_token, "\n".join(lines))
            continue

        # ── 角色管理（admin 專用）───────────────────────────────
        # 設定角色 王小美 admin
        # 移除角色 王小美        → 改回 nurse
        # 成員清單
        if text == "成員清單":
            if not is_admin:
                reply_message(reply_token, "您沒有查看成員清單的權限")
                continue
            all_users = get_all_users()
            if all_users is None:
                reply_message(reply_token, "查詢失敗，請稍後再試")
                continue
            if not all_users:
                reply_message(reply_token, "目前沒有成員")
                continue
            role_icon = {"admin": "\U0001f511", "manager": "\U0001f454", "nurse": "\U0001f469\u200d\u2695\ufe0f"}
            lines = [f"\U0001f465 成員清單（共 {len(all_users)} 人）："]
            for u in all_users:
                icon = role_icon.get(u.get("role", "nurse"), "\U0001f464")
                lines.append(f"{icon} {u['name']}（{u.get('role', 'nurse')}）")
            reply_message(reply_token, "\n".join(lines))
            continue

        if text.startswith("設定角色"):
            if not is_admin:
                reply_message(reply_token, "您沒有設定角色的權限")
                continue
            parts = text.split()
            if len(parts) != 3 or parts[2] not in ("admin", "manager", "nurse"):
                reply_message(reply_token, "格式：設定角色 姓名 admin\n或：設定角色 姓名 manager\n或：設定角色 姓名 nurse")
                continue
            target_name, new_role = parts[1], parts[2]
            target = get_user_by_name(target_name)
            if not target:
                reply_message(reply_token, f"找不到成員：{target_name}")
                continue
            if target["id"] == user["id"]:
                reply_message(reply_token, "不能修改自己的角色")
                continue
            resp = update_user_role(target["id"], new_role)
            if resp.status_code in (200, 204):
                role_label = {"admin": "管理員", "manager": "組長", "nurse": "護理師"}.get(new_role, new_role)
                reply_message(reply_token, f"已將 {target_name} 設定為{role_label}（{new_role}）")
            else:
                reply_message(reply_token, "設定失敗，請稍後再試")
            continue

        if text.startswith("移除角色"):
            if not is_admin:
                reply_message(reply_token, "您沒有移除角色的權限")
                continue
            parts = text.split()
            if len(parts) != 2:
                reply_message(reply_token, "格式：移除角色 姓名")
                continue
            target_name = parts[1]
            target = get_user_by_name(target_name)
            if not target:
                reply_message(reply_token, f"找不到成員：{target_name}")
                continue
            if target["id"] == user["id"]:
                reply_message(reply_token, "不能修改自己的角色")
                continue
            resp = update_user_role(target["id"], "nurse")
            if resp.status_code in (200, 204):
                reply_message(reply_token, f"已將 {target_name} 改回護理師（nurse）")
            else:
                reply_message(reply_token, "移除失敗，請稍後再試")
            continue

        # ── 待審名單（admin 專用）─────────────────────────────────────────────
        if text == "待審名單":
            if not is_admin:
                reply_message(reply_token, "您沒有查看待審名單的權限")
                continue
            pending = get_pending_users()
            if not pending:
                reply_message(reply_token, "目前沒有待審核的帳號")
                continue
            lines = [f"⏳ 待審核帳號（共 {len(pending)} 人）："]
            for p in pending:
                bound = p.get("bound_at", "")[:10] if p.get("bound_at") else "未知"
                lines.append(f"  {p['name']}（綁定日：{bound}）")
            lines.append("")
            lines.append("核准：設定角色 姓名 nurse")
            lines.append("拒絕：刪除護理師 姓名")
            reply_message(reply_token, "\n".join(lines))
            continue

        # ── 刪除護理師（admin 專用）──────────────────────────────────────────
        # 用途：拒絕 pending 帳號，或從名單移除離職人員
        if text.startswith("刪除護理師"):
            if not is_admin:
                reply_message(reply_token, "您沒有刪除護理師的權限")
                continue
            parts = text.split()
            if len(parts) != 2:
                reply_message(reply_token, "格式：刪除護理師 姓名")
                continue
            target_name = parts[1]
            target = get_user_by_name(target_name)
            if not target:
                reply_message(reply_token, f"找不到護理師：{target_name}")
                continue
            if target["id"] == user["id"]:
                reply_message(reply_token, "不能刪除自己")
                continue
            del_url = f"{SUPABASE_URL}/rest/v1/nurses?id=eq.{target['id']}"
            del_resp = requests.delete(del_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            if del_resp.status_code in (200, 204):
                reply_message(reply_token, f"已刪除護理師：{target_name}")
            else:
                reply_message(reply_token, "刪除失敗，請稍後再試")
            continue

        # ── 預設回覆 ──────────────────────────────────────────────────────────
        manager_hint = (
            "\n\n【組長指令】\n"
            "待審清單\n"
            "核准 編號 / 拒絕 編號\n"
            "全員查詢 當週\n"
            "全員查詢 當月\n"
            "全員查詢 2026-04\n"
            "全員查詢 2026-04-01 2026-04-30\n"
            "月份統計 2026"
        ) if is_manager else ""
        admin_hint = (
            "\n\n【Admin 專屬】\n"
            "成員清單\n"
            "待審名單\n"
            "設定角色 姓名 admin／manager／nurse\n"
            "移除角色 姓名\n"
            "刪除護理師 姓名"
        ) if is_admin else ""
        reply_message(
            reply_token,
            "可用指令：\n"
            "綁定 姓名\n"
            "加班 2026-04-17 7-3 2:15\n"
            "加班 2026-04-17 其他 急診支援 0:45\n"
            "取消 申請編號\n\n"
            "【查詢本人】\n"
            "我的記錄\n"
            "我的記錄 2026-04\n"
            "我的記錄 2026-04-01 2026-04-30"
            + manager_hint
            + admin_hint,
        )

    return {"status": "ok"}
