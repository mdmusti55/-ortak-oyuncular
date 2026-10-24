#!/usr/bin/env python3
import csv, gzip, io, json, time, urllib.request
from collections import defaultdict
from pathlib import Path

BASE = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data"
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OrtakOyuncularBuilder/1.0)"}

def download_gz(name: str) -> bytes:
    url = f"{BASE}/{name}.csv.gz"
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:
            last = e
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{url} indirilemedi: {last}")

def rows_from_gz(blob: bytes):
    text = gzip.decompress(blob).decode("utf-8-sig", errors="replace")
    return csv.DictReader(io.StringIO(text))

print("clubs.csv.gz indiriliyor…")
club_rows = list(rows_from_gz(download_gz("clubs")))
clubs = []
club_ids = set()
for r in club_rows:
    cid = str(r.get("club_id", "")).strip()
    name = (r.get("name") or "").strip()
    if not cid or not name:
        continue
    club_ids.add(cid)
    clubs.append([int(cid), name, (r.get("club_code") or "").strip()])
clubs.sort(key=lambda x: x[1].casefold())
print(f"{len(clubs)} kulüp bulundu")

print("transfers.csv.gz indiriliyor…")
transfer_rows = rows_from_gz(download_gz("transfers"))
player_names = {}
memberships = defaultdict(set)
arrivals = defaultdict(lambda: defaultdict(set))
transfer_count = 0
for r in transfer_rows:
    transfer_count += 1
    pid_s = str(r.get("player_id", "")).strip()
    if not pid_s:
        continue
    try:
        pid = int(float(pid_s))
    except ValueError:
        continue
    name = (r.get("player_name") or "").strip()
    if name:
        player_names[pid] = name
    for key in ("from_club_id", "to_club_id"):
        cid = str(r.get(key, "")).strip()
        if cid in club_ids:
            memberships[int(cid)].add(pid)

    # App'te gösterilen yıl = oyuncunun kulübe geliş/imza yılı.
    to_cid = str(r.get("to_club_id", "")).strip()
    transfer_date = (r.get("transfer_date") or "").strip()
    if to_cid in club_ids and len(transfer_date) >= 4 and transfer_date[:4].isdigit():
        arrivals[int(to_cid)][pid].add(int(transfer_date[:4]))

players_json = {str(pid): name for pid, name in sorted(player_names.items())}
memberships_json = {
    str(cid): sorted(pids, key=lambda pid: player_names.get(pid, "").casefold())
    for cid, pids in sorted(memberships.items())
}
arrivals_json = {
    str(cid): {str(pid): sorted(years) for pid, years in sorted(players.items())}
    for cid, players in sorted(arrivals.items())
}

payload = {
    "clubs": clubs,
    "players": players_json,
    "memberships": memberships_json,
    "arrivals": arrivals_json,
    "meta": {
        "snapshot": "2026-07-06",
        "source": "dcaribou / Transfermarkt datasets",
        "transferRows": transfer_count,
    },
}
compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
print(f"İndeks hazır: {len(player_names)} oyuncu, {transfer_count} transfer, {len(compact)/1024/1024:.2f} MiB JSON")

template = (SRC / "index.template.html").read_text(encoding="utf-8")
html = template.replace("/*__APP_DATA__*/", "window.APP_DATA=" + compact + ";")
(DIST / "index.html").write_text(html, encoding="utf-8")

for name in ("manifest.webmanifest", "sw.js", "icon.svg"):
    (DIST / name).write_bytes((SRC / name).read_bytes())

print("dist/ hazır")
