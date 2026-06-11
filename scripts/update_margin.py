#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信用残・信用評価損益率 週次データ更新スクリプト（dailyweek2.json 確定版）
--------------------------------------------------------------------------
public/margin-data.json（全履歴）に、最新の1週分だけを追記する。

データ源（確定）:
  https://nikkei225jp.com/_data/_nfsWEB/DAY/dailyweek2.json
  1行 = 1週で、各行は次の並び（F12で確認済み）:
    [0] 日付(ミリ秒タイムスタンプ)
    [1] 日経平均(参考)
    [2] (別指標)
    [3] 売り残 枚数(千株)
    [4] 売り残 金額(百万円)
    [5] 買い残 枚数(千株)
    [6] 買い残 金額(百万円)
    [7] 評価損益率(%)
    [8] 信用倍率
  ※ このファイルは既に「千株・百万円」単位なので変換不要。

保険:
  GitHub の「Run workflow」→ manual_row に1週分のJSONを貼れば手動追記もできる。
  例: {"d":"2026-06-12","sN":440000,"sA":890000,"bN":3930000,"bA":6700000,"r":7.53,"e":-0.55}

出力単位:  株数 = 千株 / 金額 = 百万円 / 評価損益率 = % / 倍率 = 倍
"""
import os, re, json, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.normpath(os.path.join(HERE, "..", "public", "margin-data.json"))

DATA_URL = (os.environ.get("MARGIN_DATA_URL", "").strip()
            or "https://nikkei225jp.com/_data/_nfsWEB/DAY/dailyweek2.json")
MANUAL_ROW = os.environ.get("MANUAL_ROW", "").strip()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# dailyweek2.json の列位置
IDX = {"ts": 0, "sN": 3, "sA": 4, "bN": 5, "bA": 6, "e": 7, "r": 8}


def load_data():
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_data(rows):
    rows = sorted(rows, key=lambda x: x["d"])
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))

def http_get(url):
    import requests
    r = requests.get(url, headers={"User-Agent": UA,
                                   "Referer": "https://nikkei225jp.com/data/sinyou.php"},
                     timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None

def ts_to_date(ms):
    # ミリ秒タイムスタンプ -> JSTの暦日 (取引日)
    dt = datetime.datetime.utcfromtimestamp(float(ms) / 1000.0) + datetime.timedelta(hours=9)
    return dt.date().isoformat()


def parse_dailyweek(text):
    """dailyweek2.json から (date, row_dict) のリストを返す（古い→新しい）。
       JSON配列でもJS(var X=[...])でも対応。"""
    t = text.strip()
    if not t.startswith("["):
        m = re.search(r"=\s*(\[.*\])\s*;?\s*$", t, re.S)
        if m:
            t = m.group(1)
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        # 行ごとに [ ... ] を拾う保険
        data = []
        for m in re.finditer(r"\[[^\[\]]*\]", t):
            try:
                data.append(json.loads(m.group(0)))
            except json.JSONDecodeError:
                pass
    out = []
    for arr in data:
        if not isinstance(arr, list) or len(arr) <= IDX["r"]:
            continue
        ts = num(arr[IDX["ts"]])
        sN = num(arr[IDX["sN"]]); sA = num(arr[IDX["sA"]])
        bN = num(arr[IDX["bN"]]); bA = num(arr[IDX["bA"]])
        e  = num(arr[IDX["e"]]);  r  = num(arr[IDX["r"]])
        if None in (ts, sN, sA, bN, bA, e, r):
            continue
        # 妥当性: 評価損益率 -45〜+6 / 倍率 0.2〜30 / 金額が現実レンジ(百万円)
        if not (-45 <= e <= 6 and 0.2 <= r <= 30 and 100000 <= bA <= 30000000):
            continue
        if ts < 1e12:          # 秒なら ms に補正
            ts *= 1000
        out.append({"d": ts_to_date(ts),
                    "sN": int(round(sN)), "sA": int(round(sA)),
                    "bN": int(round(bN)), "bA": int(round(bA)),
                    "r": round(r, 2), "e": round(e, 2)})
    out.sort(key=lambda x: x["d"])
    return out


def get_latest_from_source():
    text = http_get(DATA_URL)
    rows = parse_dailyweek(text)
    if not rows:
        print("[!] dailyweek2.json から信用残行を抽出できませんでした。先頭400字:",
              file=sys.stderr)
        print(text[:400], file=sys.stderr)
        return None
    row = rows[-1]
    print(f"[i] source latest: {row['d']} -> {json.dumps(row, ensure_ascii=False)}")
    return row


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
