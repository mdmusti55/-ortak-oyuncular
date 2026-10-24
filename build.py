#!/usr/bin/env python3
import csv, json, re, time, urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
TMP = ROOT / ".build-cache"
DIST.mkdir(exist_ok=True)
TMP.mkdir(exist_ok=True)

PROFILE_URL = "https://media.githubusercontent.com/media/salimt/football-datasets/main/datalake/transfermarkt/player_profiles/player_profiles.csv"
TRANSFER_URL = "https://media.githubusercontent.com/media/salimt/football-datasets/main/datalake/transfermarkt/transfer_history/transfer_history.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OrtakOyuncularBuilder/2.0)"}
TEAM_RE = re.compile(r"/verein/(\d+)")
NAME_ID_RE = re.compile(r"\s+\(\d+\)$")
SPECIAL = {
    "retired", "without club", "career break", "unknown", "end of career",
    "retired from professional football"
}


def download(url: str, path: Path):
    if path.exists() and path.stat().st_size > 1000:
        print(f"cache: {path.name} ({path.stat().st_size/1024/1024:.1f} MiB)")
        return
    last = None
    for attempt in range(4):
        try:
            print(f"indiriliyor: {path.name}")
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=180) as r, path.open("wb") as f:
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            if path.stat().st_size < 1000:
                raise RuntimeError("indirilen dosya beklenenden küçük")
            return
        except Exception as e:
            last = e
            path.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{url} indirilemedi: {last}")


def team_id(url: str):
    m = TEAM_RE.search(url or "")
    return int(m.group(1)) if m else None


def clean_player_name(name: str):
    name = (name or "").strip()
    return NAME_ID_RE.sub("", name)


def valid_team(name: str, tid):
    return bool(tid and name and name.strip().casefold() not in SPECIAL)


profiles_path = TMP / "player_profiles.csv"
transfers_path = TMP / "transfer_history.csv"
download(PROFILE_URL, profiles_path)
download(TRANSFER_URL, transfers_path)

player_names = {}
with profiles_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
    for r in csv.DictReader(f):
        raw_id = (r.get("player_id") or "").strip()
        if not raw_id:
            continue
        try:
            pid = int(float(raw_id))
        except ValueError:
            continue
        name = clean_player_name(r.get("player_name"))
        if name:
            player_names[pid] = name
print(f"{len(player_names)} oyuncu profili okundu")

club_names = {}
memberships = defaultdict(set)
arrivals = defaultdict(lambda: defaultdict(set))
transfer_count = 0

with transfers_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
    for r in csv.DictReader(f):
        transfer_count += 1
        raw_id = (r.get("player_id") or "").strip()
        if not raw_id:
            continue
        try:
            pid = int(float(raw_id))
        except ValueError:
            continue

        from_name = (r.get("from_team_name") or "").strip()
        to_name = (r.get("to_team_name") or "").strip()
        from_id = team_id(r.get("from_team_url") or "")
        to_id = team_id(r.get("to_team_url") or "")

        if valid_team(from_name, from_id):
            club_names.setdefault(from_id, from_name)
            memberships[from_id].add(pid)
        if valid_team(to_name, to_id):
            club_names.setdefault(to_id, to_name)
            memberships[to_id].add(pid)
            date = (r.get("date_unformatted") or "").strip()
            if len(date) >= 4 and date[:4].isdigit():
                arrivals[to_id][pid].add(int(date[:4]))

# Sadece transfer geçmişinde gerçek bir oyuncu ile görünen kulüpleri bırak.
clubs = [[cid, name] for cid, name in club_names.items() if memberships.get(cid)]
clubs.sort(key=lambda x: x[1].casefold())

players_json = {
    str(pid): player_names.get(pid, f"Oyuncu #{pid}")
    for pid in sorted({p for ids in memberships.values() for p in ids})
}
memberships_json = {
    str(cid): sorted(pids)
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
        "source": "salimt/football-datasets · Transfermarkt-derived",
        "transferRows": transfer_count,
        "playerProfiles": len(player_names),
        "clubs": len(clubs),
    },
}
compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
print(f"İndeks hazır: {len(clubs)} kulüp, {len(players_json)} oyuncu, {transfer_count} transfer, {len(compact)/1024/1024:.2f} MiB JSON")

# Tarihsel veri için basit smoke test: Galatasaray / Rangers kesişimini logla.
def club_by_part(part):
    part = part.casefold()
    return next(((cid, name) for cid, name in clubs if part in name.casefold()), None)

gs = club_by_part("galatasaray")
rangers = club_by_part("rangers")
if gs and rangers:
    common = memberships[gs[0]] & memberships[rangers[0]]
    names = sorted(player_names.get(pid, str(pid)) for pid in common)
    print(f"SMOKE {gs[1]} × {rangers[1]}: {len(common)} ortak -> {', '.join(names[:20])}")
else:
    print("SMOKE: Galatasaray veya Rangers kulübü bulunamadı")

template = (SRC / "index.template.html").read_text(encoding="utf-8")
html = template.replace("/*__APP_DATA__*/", "window.APP_DATA=" + compact + ";")
(DIST / "index.html").write_text(html, encoding="utf-8")

for name in ("manifest.webmanifest", "sw.js", "icon.svg"):
    (DIST / name).write_bytes((SRC / name).read_bytes())

print("dist/ hazır")
