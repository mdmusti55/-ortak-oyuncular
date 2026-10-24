#!/usr/bin/env python3
import csv, json, re, time, urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
TMP = ROOT / ".build-cache"
EXT = ROOT / "external-football" / "datalake" / "transfermarkt"
DIST.mkdir(exist_ok=True)
TMP.mkdir(exist_ok=True)

PROFILE_URL = "https://raw.githubusercontent.com/salimt/football-datasets/main/datalake/transfermarkt/player_profiles/player_profiles.csv"
TRANSFER_URL = "https://github.com/salimt/football-datasets/raw/refs/heads/main/datalake/transfermarkt/transfer_history/transfer_history.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OrtakOyuncularBuilder/2.2)"}
TEAM_PATTERNS = [
    re.compile(r"/verein/(\d+)", re.I),
    re.compile(r"/club/(\d+)", re.I),
    re.compile(r"[?&](?:club_id|verein_id|id)=(\d+)", re.I),
]
ANY_NUM_RE = re.compile(r"(\d+)")
NAME_ID_RE = re.compile(r"\s+\(\d+\)$")
SPECIAL = {"retired", "without club", "career break", "unknown", "end of career", "retired from professional football"}


def download(url: str, path: Path):
    last = None
    for attempt in range(4):
        try:
            print(f"indiriliyor: {path.name}")
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=240) as r, path.open("wb") as f:
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


def resolve_source(local_path: Path, fallback_url: str, fallback_name: str):
    if local_path.exists() and local_path.stat().st_size > 1000:
        print(f"checkout: {local_path} ({local_path.stat().st_size/1024/1024:.1f} MiB)")
        return local_path
    target = TMP / fallback_name
    download(fallback_url, target)
    return target


def team_id(value: str):
    s = (value or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    for p in TEAM_PATTERNS:
        m = p.search(s)
        if m:
            return int(m.group(1))
    # Son çare: URL'deki ilk sayısal parçayı takım ID'si kabul et.
    m = ANY_NUM_RE.search(s)
    return int(m.group(1)) if m else None


def first(row, *keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return ""


def clean_player_name(name: str):
    return NAME_ID_RE.sub("", (name or "").strip())


def valid_team(name: str, tid):
    return bool(tid and name and name.strip().casefold() not in SPECIAL)


profiles_path = resolve_source(EXT / "player_profiles" / "player_profiles.csv", PROFILE_URL, "player_profiles.csv")
transfers_path = resolve_source(EXT / "transfer_history" / "transfer_history.csv", TRANSFER_URL, "transfer_history.csv")

player_names = {}
with profiles_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
    reader = csv.DictReader(f)
    print("profile fields:", reader.fieldnames)
    for r in reader:
        raw_id = first(r, "player_id", "playerId", "player_id_x").strip()
        if not raw_id:
            continue
        try:
            pid = int(float(raw_id))
        except ValueError:
            continue
        name = clean_player_name(first(r, "player_name", "name", "playerName"))
        if name:
            player_names[pid] = name
print(f"{len(player_names)} oyuncu profili okundu")

club_names = {}
memberships = defaultdict(set)
arrivals = defaultdict(lambda: defaultdict(set))
transfer_count = 0
sample_printed = False

with transfers_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
    reader = csv.DictReader(f)
    print("transfer fields:", reader.fieldnames)
    for r in reader:
        transfer_count += 1
        if not sample_printed:
            print("transfer sample:", {k: r.get(k) for k in (reader.fieldnames or [])[:12]})
            sample_printed = True
        raw_id = first(r, "player_id", "playerId", "player_id_x").strip()
        if not raw_id:
            continue
        try:
            pid = int(float(raw_id))
        except ValueError:
            continue

        from_name = first(r, "from_team_name", "from_club_name", "from_team").strip()
        to_name = first(r, "to_team_name", "to_club_name", "to_team").strip()
        from_raw = first(r, "from_team_url", "from_club_url", "from_team_id", "from_club_id")
        to_raw = first(r, "to_team_url", "to_club_url", "to_team_id", "to_club_id")
        from_id = team_id(from_raw)
        to_id = team_id(to_raw)

        if valid_team(from_name, from_id):
            club_names.setdefault(from_id, from_name)
            memberships[from_id].add(pid)
        if valid_team(to_name, to_id):
            club_names.setdefault(to_id, to_name)
            memberships[to_id].add(pid)
            date = first(r, "date_unformatted", "transfer_date", "date").strip()
            year = None
            if len(date) >= 4 and date[:4].isdigit():
                year = int(date[:4])
            elif len(date) >= 4 and date[-4:].isdigit():
                year = int(date[-4:])
            if year:
                arrivals[to_id][pid].add(year)

clubs = [[cid, name] for cid, name in club_names.items() if memberships.get(cid)]
clubs.sort(key=lambda x: x[1].casefold())
all_player_ids = {p for ids in memberships.values() for p in ids}
players_json = {str(pid): player_names.get(pid, f"Oyuncu #{pid}") for pid in sorted(all_player_ids)}
memberships_json = {str(cid): sorted(pids) for cid, pids in sorted(memberships.items())}
arrivals_json = {str(cid): {str(pid): sorted(years) for pid, years in sorted(players.items())} for cid, players in sorted(arrivals.items())}

if transfer_count < 100000 or len(clubs) < 500 or len(players_json) < 20000:
    raise RuntimeError(f"Historical index validation failed: {len(clubs)} clubs, {len(players_json)} players, {transfer_count} transfers")

payload = {"clubs": clubs, "players": players_json, "memberships": memberships_json, "arrivals": arrivals_json, "meta": {"source": "salimt/football-datasets · Transfermarkt-derived", "transferRows": transfer_count, "playerProfiles": len(player_names), "clubs": len(clubs)}}
compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
print(f"İndeks hazır: {len(clubs)} kulüp, {len(players_json)} oyuncu, {transfer_count} transfer, {len(compact)/1024/1024:.2f} MiB JSON")


def club_by_part(part):
    part = part.casefold()
    return next(((cid, name) for cid, name in clubs if part in name.casefold()), None)

gs = club_by_part("galatasaray")
rangers = club_by_part("rangers")
if gs and rangers:
    common = memberships[gs[0]] & memberships[rangers[0]]
    names = sorted(player_names.get(pid, str(pid)) for pid in common)
    print(f"SMOKE {gs[1]} × {rangers[1]}: {len(common)} ortak -> {', '.join(names[:30])}")
    if not any("tugay" in n.casefold() for n in names):
        raise RuntimeError("Smoke test failed: Tugay not found in Galatasaray × Rangers intersection")
else:
    raise RuntimeError("Smoke test failed: Galatasaray or Rangers club not found")

template = (SRC / "index.template.html").read_text(encoding="utf-8")
html = template.replace("/*__APP_DATA__*/", "window.APP_DATA=" + compact + ";")
(DIST / "index.html").write_text(html, encoding="utf-8")
for name in ("manifest.webmanifest", "sw.js", "icon.svg"):
    (DIST / name).write_bytes((SRC / name).read_bytes())
print("dist/ hazır")
