"""
讀取 2024-01~2026-03 加班明細，整理輸出成單一 Excel 檔。
- 來源 1：overtime_weekly_summary_202401_202512.xlsx（加班詳情工作表，取 2024-01~2025-12）
- 來源 2：overtime_details_2026_0{1,2,3} 三個月檔案
輸出欄位：日期 / 姓名 / 實際上班時間 / 加班時間 / 加班時數(分鐘) / 班別
"""

import re
import pandas as pd
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────────────────────────────

INPUT_DIR = Path(__file__).parent
OUTPUT_FILE = INPUT_DIR / "overtime_detail_202401_202603.xlsx"

Q1_2026_FILES = [
    "overtime_details_2026_01_with_hourly_summary.xlsx",
    "overtime_details_2026_02.xlsx",
    "overtime_details_2026_03_有算班公式.xlsx",
]
SUMMARY_FILE = "overtime_weekly_summary_202401_202512.xlsx"

# ── 班別對應表 ────────────────────────────────────────────────────────────────
# (加班開始分鐘數下限, 上限_含, 班別, 班別正常開始時間)
# 實際上班時間 = 班別開始時間 ~ 加班結束時間

SHIFT_MAP = [
    # (start_min_lo, start_min_hi, 班別, 班別起始)
    (7 * 60,   7 * 60 + 59,  "11-7",      "23:00"),
    (8 * 60,   9 * 60 + 59,  "其他(8-4)", "08:00"),
    (15 * 60,  15 * 60 + 59, "7-3",       "07:00"),
    (16 * 60,  16 * 60 + 59, "其他(8-4)", "08:00"),
    (17 * 60,  17 * 60 + 59, "9-5",       "09:00"),
    (18 * 60,  19 * 60 + 59, "10-6",      "10:00"),
    (20 * 60,  21 * 60 + 59, "12-8",      "12:00"),
    (23 * 60,  23 * 60 + 59, "3-11",      "15:00"),
]


def _parse_hhmm(hh: str, mm: str) -> str:
    return f"{int(hh):02d}:{int(mm):02d}"


def classify_period(raw: str):
    """
    回傳 (班別, 實際上班時間, 加班時間) 三元組。
    實際上班時間 = 班別正常起始 ~ 加班結束（颱風加班則等同加班時間）。
    """
    if not isinstance(raw, str):
        return "其他", "", str(raw)

    raw_lower = raw.lower()
    time_str = _extract_time_str(raw)

    # typhoon_base_overtime_hours_N：無時段資訊，只有總時數
    if raw_lower.startswith("typhoon_base"):
        hours_m = re.search(r'_(\d+)$', raw)
        label = f"颱風基本({hours_m.group(1)}h)" if hours_m else "颱風基本"
        return "其他(颱風)", label, label

    # 解析 HHMM-HHMM 前綴取得開始/結束時間
    m = re.match(r'(\d{2})(\d{2})-(\d{2})(\d{2})', raw)
    if not m:
        if "typhoon" in raw_lower:
            return "其他(颱風)", time_str, time_str
        return "其他", "", raw

    ot_end = _parse_hhmm(m.group(3), m.group(4))
    start_min = int(m.group(1)) * 60 + int(m.group(2))

    # 颱風加班：無原班別，實際上班時間 = 加班時間
    if "typhoon" in raw_lower:
        return "其他(颱風)", time_str, time_str

    # 一般加班：查班別 → 組合「班別起始~加班結束」
    for lo, hi, shift, shift_start in SHIFT_MAP:
        if lo <= start_min <= hi:
            actual_work = f"{shift_start}~{ot_end}"
            return shift, actual_work, time_str

    return "其他", time_str, time_str


def _extract_time_str(raw: str) -> str:
    """
    從加班時段字串萃取可讀時間區間。
    優先抓括號內 HH:MM~HH:MM，否則從 HHMM-HHMM 前綴轉換。
    """
    m = re.search(r'\((\d{2}:\d{2}~\d{2}:\d{2})\)', raw)
    if m:
        return m.group(1)
    m = re.match(r'(\d{2})(\d{2})-(\d{2})(\d{2})', raw)
    if m:
        return f"{m.group(1)}:{m.group(2)}~{m.group(3)}:{m.group(4)}"
    return raw


def process_df(df_raw: pd.DataFrame, has_employee_id: bool = False) -> pd.DataFrame:
    """
    統一處理原始 DataFrame，輸出標準化欄位。
    """
    if has_employee_id:
        df_raw.columns = ["日期", "廠號", "姓名", "_raw_period", "_hours"]
        df_raw = df_raw.drop(columns=["廠號"])
    else:
        df_raw.columns = ["日期", "姓名", "_raw_period", "_hours"]

    df_raw.dropna(subset=["日期", "姓名", "_raw_period", "_hours"], how="any", inplace=True)

    df_raw["日期"] = pd.to_datetime(df_raw["日期"]).dt.strftime("%Y-%m-%d")
    df_raw["加班時數(分鐘)"] = (
        pd.to_numeric(df_raw["_hours"], errors="coerce") * 60
    ).round(0).astype("Int64")

    classified = df_raw["_raw_period"].apply(classify_period)
    df_raw["班別"]        = [r[0] for r in classified]
    df_raw["實際上班時間"] = [r[1] for r in classified]
    df_raw["加班時間"]    = [r[2] for r in classified]

    return df_raw[["日期", "姓名", "實際上班時間", "加班時間", "加班時數(分鐘)", "班別"]].copy()


# ── 讀取 summary 檔（2024-01 ~ 2025-12）────────────────────────────────────────

print(f"[載入] {SUMMARY_FILE}")
df_summary_raw = pd.read_excel(INPUT_DIR / SUMMARY_FILE, sheet_name=0)
df_summary = process_df(df_summary_raw, has_employee_id=True)
# 只取 2024-01 ~ 2025-12（理論上全在此範圍，但防呆）
df_summary = df_summary[df_summary["日期"] < "2026-01-01"].copy()
print(f"  {len(df_summary)} 筆（{df_summary['日期'].min()} ~ {df_summary['日期'].max()}）")

# ── 讀取 2026 Q1 三個月檔 ────────────────────────────────────────────────────

frames_2026 = []
for fname in Q1_2026_FILES:
    path = INPUT_DIR / fname
    if not path.exists():
        print(f"[警告] 找不到：{fname}，跳過")
        continue
    df_raw = pd.read_excel(path, sheet_name=0)
    df_proc = process_df(df_raw, has_employee_id=False)
    print(f"[載入] {fname}：{len(df_proc)} 筆")
    frames_2026.append(df_proc)

df_2026 = pd.concat(frames_2026, ignore_index=True) if frames_2026 else pd.DataFrame()

# ── 合併並排序 ─────────────────────────────────────────────────────────────────

combined = pd.concat([df_summary, df_2026], ignore_index=True)
combined.sort_values(["日期", "姓名"], inplace=True)
combined.reset_index(drop=True, inplace=True)

print(f"\n合計 {len(combined)} 筆（{combined['日期'].min()} ~ {combined['日期'].max()}）")

# ── 班別分佈統計 ───────────────────────────────────────────────────────────────

print("\n班別分佈：")
print(combined["班別"].value_counts().to_string())

other_rows = combined[combined["班別"] == "其他"]
if not other_rows.empty:
    print(f"\n[注意] 無法判斷班別（其他）的記錄共 {len(other_rows)} 筆，請人工確認：")
    print(other_rows[["日期", "姓名", "加班時間"]].head(20).to_string(index=False))

# ── 輸出 Excel ────────────────────────────────────────────────────────────────

with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
    combined.to_excel(writer, sheet_name="加班詳情", index=False)

    ws = writer.sheets["加班詳情"]
    col_widths = {"A": 12, "B": 14, "C": 14, "D": 14, "E": 14, "F": 12}
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

print(f"\n完成：已輸出 {len(combined)} 筆 -> {OUTPUT_FILE}")
