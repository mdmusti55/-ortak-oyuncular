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
TEAMMATES_URL = "https://raw.githubusercontent.com/salimt/football-datasets/main/datalake/transfermarkt/player_teammates_played_with/player_teammates_played_with.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; OrtakOyuncularBuilder/2.6)"}
TEAM_PATTERNS = [re.compile(r"/verein/(\d+)", re.I), re.compile(r"/club/(\d+)", re.I), re.compile(r"[?&](?:club_id|verein_id|id)=(\d+)", re.I)]
ANY_NUM_RE = re.compile(r"(\d+)")
NAME_ID_RE = re.compile(r"\s+\(\d+\)$")
SPECIAL = {"retired", "without club", "career break", "unknown", "end of career", "retired from professional football"}
# Doğrulanmış Transfermarkt ID'leri için kaynak veri boşlukları.
KNOWN_NAME_OVERRIDES = {3518: "Frank de Boer"}


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


def extract_numeric_id(value: str):
    s = (value or "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        m = ANY_NUM_RE.search(s)
        return int(m.group(1)) if m else None


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
    return extract_numeric_id(s)


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
teammates_path = resolve_source(EXT / "player_teammates_played_with" / "player_teammates_played_with.csv", TEAMMATES_URL, "player_teammates_played_with.csv")
transfers_path = resolve_source(EXT / "transfer_history" / "transfer_history.csv", TRANSFER_URL, "transfer_history.csv")

player_names = {}
with profiles_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
    for r in csv.DictReader(f):
        pid = extract_numeric_id(first(r, "player_id", "playerId", "player_id_x"))
        if not pid:
            continue
        name = clean_player_name(first(r, "player_name", "name", "playerName"))
        if name:
            player_names[pid] = name
print(f"{len(player_names)} oyuncu profili okundu")

# Eski/emekli bazı oyuncular ana profil tablosunda yok; teammate tablosu ID + isim içeriyor.
profile_names_before = len(player_names)
with teammates_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
    reader = csv.DictReader(f)
    print("teammate fields:", reader.fieldnames)
    for r in reader:
        other_id = extract_numeric_id(first(r, "teammate_player_id", "player_with_id", "player_with_url", "teammate_url"))
        other_name = clean_player_name(first(r, "teammate_player_name", "player_with_name", "teammate_name"))
        if other_id and other_name and other_id not in player_names:
            player_names[other_id] = other_name
player_names.update(KNOWN_NAME_OVERRIDES)
print(f"isim haritası tamamlandı: {profile_names_before} -> {len(player_names)}")

club_names = {}
memberships = defaultdict(set)
arrivals = defaultdict(lambda: defaultdict(set))
transfer_count = 0
with transfers_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
    reader = csv.DictReader(f)
    print("transfer fields:", reader.fieldnames)
    for r in reader:
        transfer_count += 1
        pid = extract_numeric_id(first(r, "player_id", "playerId", "player_id_x"))
        if not pid:
            continue
        from_name = first(r, "from_team_name", "from_club_name", "from_team").strip()
        to_name = first(r, "to_team_name", "to_club_name", "to_team").strip()
        from_id = team_id(first(r, "from_team_url", "from_club_url", "from_team_id", "from_club_id"))
        to_id = team_id(first(r, "to_team_url", "to_club_url", "to_team_id", "to_club_id"))
        if valid_team(from_name, from_id):
            club_names.setdefault(from_id, from_name)
            memberships[from_id].add(pid)
        if valid_team(to_name, to_id):
            club_names.setdefault(to_id, to_name)
            memberships[to_id].add(pid)
            date = first(r, "date_unformatted", "transfer_date", "date").strip()
            year = int(date[:4]) if len(date) >= 4 and date[:4].isdigit() else (int(date[-4:]) if len(date) >= 4 and date[-4:].isdigit() else None)
            if year:
                arrivals[to_id][pid].add(year)

clubs = [[cid, name] for cid, name in club_names.items() if memberships.get(cid)]
clubs.sort(key=lambda x: x[1].casefold())
all_player_ids = {p for ids in memberships.values() for p in ids}
unknown_ids = sorted(pid for pid in all_player_ids if pid not in player_names)
players_json = {str(pid): player_names.get(pid, f"Oyuncu #{pid}") for pid in sorted(all_player_ids)}
memberships_json = {str(cid): sorted(pids) for cid, pids in sorted(memberships.items())}
arrivals_json = {str(cid): {str(pid): sorted(years) for pid, years in sorted(players.items())} for cid, players in sorted(arrivals.items())}

if transfer_count < 100000 or len(clubs) < 500 or len(players_json) < 20000:
    raise RuntimeError(f"Historical index validation failed: {len(clubs)} clubs, {len(players_json)} players, {transfer_count} transfers")

payload = {"clubs": clubs, "players": players_json, "memberships": memberships_json, "arrivals": arrivals_json, "meta": {"source": "salimt/football-datasets · Transfermarkt-derived", "transferRows": transfer_count, "playerProfiles": len(player_names), "clubs": len(clubs), "unknownNames": len(unknown_ids)}}
compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
print(f"İndeks hazır: {len(clubs)} kulüp, {len(players_json)} oyuncu, {transfer_count} transfer, {len(compact)/1024/1024:.2f} MiB JSON; isimsiz={len(unknown_ids)}")


def preferred_club(exact_names, contains=None):
    exact_cf = [x.casefold() for x in exact_names]
    for target in exact_cf:
        for cid, name in clubs:
            if name.casefold() == target:
                return cid, name
    if contains:
        candidates = [(cid, name) for cid, name in clubs if contains.casefold() in name.casefold()]
        candidates.sort(key=lambda x: (not x[1].casefold().startswith(contains.casefold()), len(x[1]), x[1].casefold()))
        return candidates[0] if candidates else None
    return None

gs = preferred_club(["Galatasaray", "Galatasaray SK", "Galatasaray A.Ş."], "Galatasaray")
rangers = preferred_club(["Rangers FC", "Rangers"], "Rangers")
if gs and rangers:
    common = memberships[gs[0]] & memberships[rangers[0]]
    names = sorted(player_names.get(pid, str(pid)) for pid in common)
    print(f"SMOKE {gs[1]} × {rangers[1]}: {len(common)} ortak -> {', '.join(names[:30])}")
    low = [n.casefold() for n in names]
    if not any("tugay" in n for n in low) or "frank de boer" not in low:
        raise RuntimeError("Smoke test failed: expected Tugay Kerimoğlu + Frank de Boer not found for Galatasaray × Rangers")
else:
    raise RuntimeError("Smoke test failed: Galatasaray or Rangers club not found")

template = (SRC / "index.template.html").read_text(encoding="utf-8")
html = template.replace("/*__APP_DATA__*/", "window.APP_DATA=" + compact + ";")
(DIST / "index.html").write_text(html, encoding="utf-8")
for name in ("manifest.webmanifest", "sw.js", "icon.svg"):
    (DIST / name).write_bytes((SRC / name).read_bytes())
print("dist/ hazır")
