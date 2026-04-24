"""
匯入腳本：將 Excel 上傳至 Supabase overtime_history 表（支援重複執行覆蓋）。

執行前請確認：
1. 專案根目錄已建立 .env（或在此腳本同層目錄有 .env）
2. Supabase 已建立 overtime_history 表（見 README 或計畫文件中的 SQL）
3. pip install openpyxl python-dotenv requests

執行：
  python import_history_to_supabase.py

覆蓋邏輯：
  先刪除 overtime_history 中 source_record_id IS NULL（歷史匯入）且
  work_date 落在 Excel 日期範圍內的所有記錄，再重新插入。
  系統核准記錄（source_record_id 有值）不受影響。
"""

import os
import sys
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# ── 載入 .env ─────────────────────────────────────────────────────────────────

# 優先從專案根目錄讀取 .env
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("[錯誤] 缺少 SUPABASE_URL 或 SUPABASE_KEY，請確認 .env 設定")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

EXCEL_FILE = Path(__file__).parent / "overtime_detail_202401_202603.xlsx"
BATCH_SIZE = 200

# ── 讀取護理師名冊，建立 name → id 對照 ────────────────────────────────────────

print("讀取 nurses 表...")
resp = requests.get(
    f"{SUPABASE_URL}/rest/v1/nurses?select=id,name",
    headers=HEADERS,
    timeout=15,
)
if resp.status_code != 200:
    sys.exit(f"[錯誤] 無法讀取 nurses 表：{resp.status_code} {resp.text}")

name_to_id = {row["name"]: row["id"] for row in resp.json()}
print(f"  共 {len(name_to_id)} 位護理師")

# ── 讀取 Excel ────────────────────────────────────────────────────────────────

print(f"讀取 {EXCEL_FILE.name}...")
df = pd.read_excel(EXCEL_FILE, sheet_name="加班詳情")
df.columns = ["work_date", "name", "actual_work_time", "overtime_period",
              "overtime_minutes", "shift_type"]
df.dropna(subset=["work_date", "name", "overtime_minutes", "shift_type"], inplace=True)
df["overtime_minutes"] = df["overtime_minutes"].astype(int)
df["work_date"] = pd.to_datetime(df["work_date"]).dt.strftime("%Y-%m-%d")
print(f"  共 {len(df)} 筆記錄")

date_min = df["work_date"].min()
date_max = df["work_date"].max()
print(f"  日期範圍：{date_min} ～ {date_max}")

# ── 刪除舊的歷史匯入記錄（同日期範圍、source_record_id IS NULL）────────────────

print(f"\n刪除舊歷史匯入（{date_min} ～ {date_max}，source_record_id IS NULL）...")
del_url = (
    f"{SUPABASE_URL}/rest/v1/overtime_history"
    f"?source_record_id=is.null"
    f"&work_date=gte.{date_min}"
    f"&work_date=lte.{date_max}"
)
del_resp = requests.delete(del_url, headers=HEADERS, timeout=30)
if del_resp.status_code in (200, 204):
    print("  刪除完成")
else:
    sys.exit(f"[錯誤] 刪除失敗：{del_resp.status_code} {del_resp.text}")

# ── 組成 records ──────────────────────────────────────────────────────────────

unmatched_names = set()
records = []
for _, row in df.iterrows():
    name = str(row["name"]).strip()
    user_id = name_to_id.get(name)
    if user_id is None:
        unmatched_names.add(name)
    records.append({
        "work_date": row["work_date"],
        "user_id": user_id,          # null if not found
        "name": name,
        "shift_type": str(row["shift_type"]),
        "overtime_minutes": int(row["overtime_minutes"]),
        "source_record_id": None,    # 歷史匯入
    })

if unmatched_names:
    print(f"\n[注意] 以下 {len(unmatched_names)} 個姓名在 nurses 表中找不到對應（user_id 將為 null）：")
    for n in sorted(unmatched_names):
        print(f"  - {n}")

# ── 分批插入 ──────────────────────────────────────────────────────────────────

print(f"\n開始插入 {len(records)} 筆（每批 {BATCH_SIZE} 筆）...")
success = 0
errors = 0
for i in range(0, len(records), BATCH_SIZE):
    batch = records[i : i + BATCH_SIZE]
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/overtime_history",
        headers=HEADERS,
        json=batch,
        timeout=30,
    )
    if resp.status_code in (200, 201):
        success += len(batch)
        print(f"  批次 {i // BATCH_SIZE + 1}：{len(batch)} 筆 OK（累計 {success}）")
    else:
        errors += len(batch)
        print(f"  批次 {i // BATCH_SIZE + 1}：失敗 {resp.status_code} {resp.text[:200]}")

print(f"\n完成：成功 {success} 筆，失敗 {errors} 筆")
if unmatched_names:
    print(f"提醒：{len(unmatched_names)} 個姓名無法對應 nurses 表，這些記錄的 user_id 為 null，無法透過 API 查詢。")
