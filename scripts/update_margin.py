#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信用残・信用評価損益率 週次データ更新スクリプト（自動発見版）
------------------------------------------------------------------
public/margin-data.json（全履歴）に、最新の1週分だけを追記する。

データ源: https://nikkei225jp.com/data/sinyou.php
  ※ このページの表は JavaScript で描画されるため、HTML自体にデータ行は無い
    （確認済み: 生HTMLでは「JavaScriptが無効になっています」と空の表のみ）。
  そこで本スクリプトは3段構えで取得する:
    Strategy A: ページHTMLの表を直接パース（将来サーバー描画に変わった場合の保険）
    Strategy B: ページが参照する同一ドメインの .js / .php を自動収集し、
                その中から「日付 + 数値列」の信用残データ配列を探して抽出
    Strategy C: 失敗時は候補ファイルのURLと先頭サンプルをログに出力
                → そのログを貼ってもらえれば1回でマッピング確定できる

保険（常時有効）:
  GitHub の「Run workflow」→ manual_row に1週分のJSONを貼れば手動追記できる。
  例: {"d":"2026-06-12","sN":440000,"sA":890000,"bN":3930000,"bA":6700000,"r":7.53,"e":-0.55}

出力単位:  株数 = 千株 / 金額 = 百万円 / 評価損益率 = % / 倍率 = 倍
"""
import os, re, json, sys, datetime, io
from urllib.parse import urljoin, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.normpath(os.path.join(HERE, "..", "public", "margin-data.json"))

PAGE_URL   = os.environ.get("SINYOU_URL", "").strip() or "https://nikkei225jp.com/data/sinyou.php"
DATA_URL   = os.environ.get("MARGIN_DATA_URL", "").strip()   # 特定済みなら直指定で高速化
MANUAL_ROW = os.environ.get("MANUAL_ROW", "").strip()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

DATE_RE = re.compile(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})")
NUM_RE  = re.compile(r"-?\d+(?:\.\d+)?")

# ログで判明した命名規則（/_data/_nfsWEB/min|DAY|ajaxindex|HS_DATA_DAY/...）から、
# 信用残(sinyou)データの在りかを総当たりで試す候補。妥当性チェックで誤検出は弾く。
CANDIDATE_DATA_URLS = [
    "https://nikkei225jp.com/_data/_nfsWEB/min/sinyou.js",
    "https://nikkei225jp.com/_data/_nfsWEB/min/sinyou_min.js",
    "https://nikkei225jp.com/_data/_nfsWEB/min/NK225_sinyou.js",
    "https://nikkei225jp.com/_data/_nfsWEB/min/NK225_sinyou_min.js",
    "https://nikkei225jp.com/_data/_nfsWEB/min/sinyo.js",
    "https://nikkei225jp.com/_data/_nfsWEB/ajaxindex/ajax_sinyou_min.js",
    "https://nikkei225jp.com/_data/_nfsWEB/DAY/sinyou.json",
    "https://nikkei225jp.com/_data/_nfsWEB/DAY/sinyou2.json",
    "https://nikkei225jp.com/_data/_nfsWEB/DAY/sinyouweek.json",
    "https://nikkei225jp.com/_data/_nfsWEB/HS_DATA_DAY/sinyou.json",
    "https://nikkei225jp.com/_data/_nfsWEB/sinyou.json",
    "https://nikkei225jp.com/_data/_nfsWEB/sinyou.js",
    "https://nikkei225jp.com/_data/sinyou.json",
    "https://nikkei225jp.com/_data/sinyou.js",
]


def load_data():
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_data(rows):
    rows = sorted(rows, key=lambda x: x["d"])
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))

def http_get(url):
    import requests
    r = requests.get(url, headers={"User-Agent": UA, "Referer": PAGE_URL}, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

# ---- 単位変換（出典 = 百万株 / 億円）----
def man_kabu_to_sen(v):   # 百万株 -> 千株
    return int(round(float(v) * 1000))
def oku_to_hyakuman(v):   # 億円 -> 百万円
    return int(round(float(v) * 100))

def to_float(cell):
    s = re.sub(r"[^\d.\-]", "", str(cell).replace("±0", "0"))
    try:
        return float(s)
    except ValueError:
        return None

def parse_date_cell(cell):
    s = str(cell).strip()
    if re.fullmatch(r"\d{4,6}(\.0)?", s):                       # Excelシリアル
        n = int(float(s))
        if n > 30000:
            return (datetime.date(1899, 12, 30) + datetime.timedelta(days=n)).isoformat()
    m = DATE_RE.search(s)
    if m:
        y, mo, d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"(\d{1,2})[/-](\d{1,2})", s)                 # MM/DD（年なし）
    if m:
        mo, d = map(int, m.groups())
        y = datetime.date.today().year
        cand = datetime.date(y, mo, d)
        if cand > datetime.date.today() + datetime.timedelta(days=7):
            cand = datetime.date(y - 1, mo, d)
        return cand.isoformat()
    return None


def plausible(nums):
    """10値が xlsx と同じ並びとして妥当か:
       [0]売株数 [1]売前比 [2]売金額 [3]売前比 [4]買株数 [5]買前比 [6]買金額 [7]買前比 [8]損益率 [9]倍率"""
    if len(nums) < 10 or any(n is None for n in nums[:10]):
        return False
    sN, _, sA, _, bN, _, bA, _, e, r = nums[:10]
    return (50 <= sN <= 5000 and 1000 <= sA <= 50000 and       # 百万株 / 億円の現実レンジ
            500 <= bN <= 20000 and 10000 <= bA <= 200000 and
            -45 <= e <= 6 and 0.2 <= r <= 30)

def normalize(date_iso, nums):
    sN, _, sA, _, bN, _, bA, _, e, r = nums[:10]
    return {"d": date_iso,
            "sN": man_kabu_to_sen(sN), "sA": oku_to_hyakuman(sA),
            "bN": man_kabu_to_sen(bN), "bA": oku_to_hyakuman(bA),
            "r": round(float(r), 2), "e": round(float(e), 2)}


# ---------- Strategy A: HTMLの表を直接 ----------
def rows_from_html_tables(html):
    try:
        import pandas as pd
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return []
    out = []
    for t in tables:
        if t.shape[1] < 11:
            continue
        rows = []
        for _, raw in t.iterrows():
            cells = list(raw.values)
            d = parse_date_cell(cells[0])
            if not d:
                continue
            nums = [to_float(c) for c in cells[1:11]]
            if plausible(nums):
                rows.append((d, nums))
        if rows:
            out = rows
            break
    out.sort(key=lambda x: x[0])
    return out


# ---------- Strategy B: 参照スクリプトから自動発見 ----------
def find_script_urls(html, base):
    urls = []
    for m in re.finditer(r'''(?:src|href)\s*=\s*["']([^"']+\.(?:js|php|json|csv)(?:\?[^"']*)?)["']''',
                         html, re.I):
        u = urljoin(base, m.group(1))
        if urlparse(u).netloc == urlparse(base).netloc:
            urls.append(u)
    # fetch/XHR 呼び出しのURL文字列も拾う
    for m in re.finditer(r'''["']((?:https?:)?//?[^"']*?\.(?:js|php|json|csv)(?:\?[^"']*)?)["']''',
                         html):
        u = urljoin(base, m.group(1))
        if urlparse(u).netloc == urlparse(base).netloc:
            urls.append(u)
    seen, ordered = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u); ordered.append(u)
    return ordered

def rows_from_blob(text):
    """テキスト中の『日付 → 続く数値10個』レコードを総当たりで抽出。"""
    rows = []
    positions = [(m.start(), f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
                 for m in DATE_RE.finditer(text)]
    for idx, (pos, d) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else min(len(text), pos + 600)
        seg = text[pos:end]
        seg = DATE_RE.sub(" ", seg, count=1)            # 日付自身の数字を除去
        nums = [float(x) for x in NUM_RE.findall(seg)][:12]
        if plausible(nums):
            rows.append((d, nums))
    # 同日重複は最初を採用
    seen, out = set(), []
    for d, n in rows:
        if d not in seen:
            seen.add(d); out.append((d, n))
    out.sort(key=lambda x: x[0])
    return out


def get_latest_from_source():
    # 0) データURLが特定済みならそれだけ叩く
    if DATA_URL:
        text = http_get(DATA_URL)
        rows = rows_from_blob(text) or rows_from_html_tables(text)
        if rows:
            d, nums = rows[-1]
            row = normalize(d, nums)
            print(f"[i] DATA_URL latest: {d} -> {json.dumps(row, ensure_ascii=False)}")
            return row
        print(f"[!] MARGIN_DATA_URL から抽出失敗。先頭1000字:\n{text[:1000]}", file=sys.stderr)

    html = http_get(PAGE_URL)

    # A) ページ内の表
    rows = rows_from_html_tables(html)
    if rows:
        d, nums = rows[-1]
        row = normalize(d, nums)
        print(f"[i] page-table latest: {d} -> {json.dumps(row, ensure_ascii=False)}")
        return row

    # A2) 命名規則からの候補を総当たり
    for u in CANDIDATE_DATA_URLS:
        try:
            text = http_get(u)
        except Exception:
            continue
        rows = rows_from_blob(text)
        if rows:
            d, nums = rows[-1]
            row = normalize(d, nums)
            print(f"[i] candidate hit: {u}")
            print(f"[i] latest: {d} -> {json.dumps(row, ensure_ascii=False)}")
            print(f"[i] 次回から高速化するには Secrets MARGIN_DATA_URL に上記URLを設定可")
            return row

    # B) 参照スクリプトを巡回
    candidates = find_script_urls(html, PAGE_URL)
    print(f"[i] script candidates: {len(candidates)}")
    samples = []
    for u in candidates[:20]:
        try:
            text = http_get(u)
        except Exception as ex:
            print(f"[i]   skip {u} ({ex})")
            continue
        rows = rows_from_blob(text)
        if rows:
            d, nums = rows[-1]
            row = normalize(d, nums)
            print(f"[i] discovered data file: {u}")
            print(f"[i] latest: {d} -> {json.dumps(row, ensure_ascii=False)}")
            print(f"[i] 次回から高速化するには Secrets MARGIN_DATA_URL に上記URLを設定可")
            return row
        samples.append((u, text[:200].replace("\n", " ")))

    # C) 失敗: 調査用ログ
    print("[!] データを自動発見できませんでした。以下の候補一覧を貼ってもらえれば調整します:",
          file=sys.stderr)
    for u, s in samples:
        print(f"  - {u}\n      head: {s}", file=sys.stderr)
    return None


def get_new_row():
    if MANUAL_ROW:
        return json.loads(MANUAL_ROW)
    return get_latest_from_source()


def main():
    rows = load_data()
    have = {r["d"] for r in rows}
    new = get_new_row()
    if not new:
        print("no new row (source unavailable)")
        return 0
    d = new["d"]
    if d in have:
        print(f"already have {d}; nothing to do")
        return 0
    prev = sorted(rows, key=lambda x: x["d"])[-1]
    def pct(cur, pv):
        return round((cur - pv) / pv * 100, 2) if pv else 0.0
    new.setdefault("sC", pct(new["sA"], prev["sA"]))
    new.setdefault("bC", pct(new["bA"], prev["bA"]))
    if not new.get("r"):
        new["r"] = round(new["bA"] / new["sA"], 2) if new.get("sA") else 0.0
    ordered = {k: new[k] for k in ["d","sN","sA","sC","bN","bA","bC","r","e"] if k in new}
    rows.append(ordered)
    save_data(rows)
    print(f"added {d}: {json.dumps(ordered, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
