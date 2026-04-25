"""
從「房區與名單.xlsx」的「五月人員表」讀取護理師資料，
將班碼、卡號、職號、排列順序寫入 Supabase nurses 表。

執行前請先在 Supabase SQL Editor 執行：
  ALTER TABLE nurses
    ADD COLUMN IF NOT EXISTS staff_code TEXT,
    ADD COLUMN IF NOT EXISTS card_no    TEXT,
    ADD COLUMN IF NOT EXISTS employee_no TEXT,
    ADD COLUMN IF NOT EXISTS sort_order  INTEGER;

執行方式：
  python ot_raw_data/update_nurse_info.py
"""

import os
import sys
import requests
import openpyxl
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}

EXCEL_PATH = Path(r"C:\Wilson\claude_code\devoloping_project\hospital\護理師排班\原始資料\房區與名單.xlsx")
SHEET_NAME = "五月人員表"


def get_all_nurses():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/nurses?select=id,name&limit=1000",
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return {n["name"]: n["id"] for n in r.json()}


def patch_nurse(nurse_id: str, payload: dict):
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/nurses?id=eq.{nurse_id}",
        headers=HEADERS,
        json=payload,
        timeout=15,
    )
    return r.status_code < 300


def read_excel():
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # skip header
        name = row[0]
        if name is None:
            break
        staff_code = str(row[1]) if row[1] is not None else None
        card_no    = str(row[2]) if row[2] is not None else None
        employee_no = str(row[3]) if row[3] is not None else None
        rows.append({
            "name": name,
            "staff_code": staff_code,
            "card_no": card_no,
            "employee_no": employee_no,
            "sort_order": i,  # 1-based, preserves worksheet order
        })
    wb.close()
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    print("讀取 Excel...")
    excel_rows = read_excel()
    print(f"  共 {len(excel_rows)} 筆")

    print("從 Supabase 取得護理師清單...")
    nurses = get_all_nurses()
    print(f"  共 {len(nurses)} 人")

    excel_names = set()
    ok = skip = err = 0

    for row in excel_rows:
        name = row["name"]
        excel_names.add(name)
        nurse_id = nurses.get(name)
        if not nurse_id:
            print(f"  [找不到] {name}")
            skip += 1
            continue
        success = patch_nurse(nurse_id, {
            "staff_code":  row["staff_code"],
            "card_no":     row["card_no"],
            "employee_no": row["employee_no"],
            "sort_order":  row["sort_order"],
        })
        if success:
            print(f"  [OK] {name}  班碼:{row['staff_code']}  卡號:{row['card_no']}  職號:{row['employee_no']}")
            ok += 1
        else:
            print(f"  [錯誤] {name}")
            err += 1

    # 名單以外的人 → 排到最後
    for name, nurse_id in nurses.items():
        if name not in excel_names:
            patch_nurse(nurse_id, {"sort_order": 9999})
            print(f"  [尾部] {name}")

    print(f"\n完成：更新 {ok} 人 / 跳過 {skip} 人 / 錯誤 {err} 人")


if __name__ == "__main__":
    main()
