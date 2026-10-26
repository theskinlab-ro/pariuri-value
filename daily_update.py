# -*- coding: utf-8 -*-
"""Update zilnic automat:
1. Ia meciurile zilei de la Superbet (toate sporturile).
2. Pastreaza doar meciurile din ligile acoperite de model (football-data),
   identificate prin numele echipelor (nu prin ID-uri de turneu).
3. Ruleaza modelul, compara cu cotele Superbet, alege value-urile.
4. Rescrie site/index.html si (cu --push) face commit+push pe GitHub.

Utilizare:
  python daily_update.py            -> analizeaza ZIUA CURENTA, dry-run
  python daily_update.py --push     -> analizeaza ziua curenta + publica
  python daily_update.py 2026-10-27 -> alta zi, dry-run
"""
import datetime
import json
import math
import re
import subprocess
import sys
import time
import urllib.request

import bet_mvp as bm

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
DAY_API = "https://production-superbet-offer-ro.freetls.fastly.net/v3/ro-RO/events?startDate={s}%2B02:00&endDate={e}%2B02:00"
EV_API = "https://production-superbet-offer-ro.freetls.fastly.net/v3/ro-RO/events?events={}"
MARKET_MAP = {"faulturi": "Total faulturi", "galbene": "Total cartonașe", "cornere": "Total cornere"}
CAL = {"Total faulturi": 3, "Total cartonașe": 2, "Total cornere": 1}
LEAGUE_PRIORITY = ["I1", "SP1", "E0", "F1", "D1", "P1", "T1", "SC0", "N1", "B1", "I2", "SP2", "E1", "D2", "F2", "E2", "G1", "SC1", "B1", "E3", "SC3", "SC2"]

# Turnee reale (fotbal senior) — descoperite din API; filtreaza e-sport/U19/U21/virtuale
TOURNAMENTS = {
    106: "E0", 27: "E1", 215: "E2", 146: "E3",
    4: "SC0", 348: "SC1",
    245: "D1", 50: "D2",
    104: "I1", 244: "I2",
    98: "SP1", 191: "SP2",
    100: "F1", 143: "F2",
    256: "N1", 324: "B1",
    142: "P1", 323: "T1", 168: "G1",
}

# Alias: nume Superbet (normalizat) -> nume football-data
ALIAS = {
    "psg": "Paris SG", "borussia dortmund": "Dortmund", "bayer leverkusen": "Leverkusen",
    "rb leipzig": "Leipzig", "eintracht frankfurt": "Ein Frankfurt", "borussia monchengladbach": "M'Gladbach",
    "gladbach": "M'Gladbach", "karlsruher": "Karlsruhe", "fortuna dusseldorf": "Dusseldorf",
    "preussen munster": "Munster", "athletic bilbao": "Athletic Club", "atletico madrid": "Ath Madrid",
    "celta vigo": "Celta", "rayo vallecano": "Vallecano", "deportivo alaves": "Alaves",
    "sporting cp": "Sporting", "vitoria guimaraes": "Guimaraes", "estrela amadora": "Estrela",
    "saint-etienne": "St Etienne", "saint etienne": "St Etienne", "basaksehir": "Buyuksehyr",
    "adana demirspor": "Adana Demirs", "manchester city": "Man City", "manchester united": "Man United",
    "tottenham hotspur": "Spurs", "tottenham": "Spurs", "wolverhampton": "Wolves",
    "wolverhampton wanderers": "Wolves", "nottingham forest": "Nott'm Forest",
    "west ham united": "West Ham", "newcastle united": "Newcastle", "sheffield united": "Sheff Utd",
    "sheffield wednesday": "Sheff Wed", "brighton and hove albion": "Brighton",
    "leicester city": "Leicester", "leeds united": "Leeds", "norwich city": "Norwich",
    "stoke city": "Stoke", "swansea city": "Swansea", "cardiff city": "Cardiff",
    "hull city": "Hull", "preston north end": "Preston", "middlesbrough": "Middlesbrough",
    "blackburn rovers": "Blackburn", "coventry city": "Coventry", "bristol rovers": "Bristol Rvs",
    "mk dons": "MK Dons", "wimbledon": "Wimbledon", "plymouth argyle": "Plymouth",
    "oxford united": "Oxford", "luton town": "Luton", "bolton wanderers": "Bolton",
    "peterborough united": "Peterborough", "lincoln city": "Lincoln", "burton albion": "Burton",
    "wigan athletic": "Wigan", "cambridge united": "Cambridge", "shrewsbury town": "Shrewsbury",
    "exeter city": "Exeter", "wycombe wanderers": "Wycombe", "cheltenham town": "Cheltenham",
    "colchester united": "Colchester", "crewe alexandra": "Crewe", "doncaster rovers": "Doncaster",
    "grimsby town": "Grimsby", "mansfield town": "Mansfield", "oldham athletic": "Oldham",
    "swindon town": "Swindon", "tranmere rovers": "Tranmere", "accrington stanley": "Accrington",
    "forest green rovers": "Forest Green", "koln": "Koln", "hamburg": "Hamburg",
    "hamburger": "Hamburg", "1 fc nurnberg": "Nurnberg", "nurnberg": "Nurnberg",
    "fc schalke 04": "Schalke", "schalke 04": "Schalke", "hertha bsc": "Hertha",
    "az alkmaar": "AZ Alkmaar", "nec nijmegen": "Nijmegen", "pec zwolle": "Zwolle",
    "fc twente": "Twente", "fc utrecht": "Utrecht", "fc groningen": "Groningen",
    "sparta rotterdam": "Sparta Rotterdam", "kaa gent": "Gent", "k aa gent": "Gent",
    "standard liege": "Standard", "ohl": "OHL", "oud-heverlee leuven": "OHL",
    "cercle brugge": "Cercle Brugge", "club brugge kv": "Club Brugge",
    "queens park rangers": "QPR", "west bromwich albion": "West Brom",
    "blackpool": "Blackpool", "derby county": "Derby", "birmingham city": "Birmingham",
    "bristol city": "Bristol City", "charlton athletic": "Charlton", "huddersfield town": "Huddersfield",
    "millwall": "Millwall", "portsmouth": "Portsmouth", "rotherham united": "Rotherham",
    "stoke": "Stoke", "swansea": "Swansea", "watford": "Watford",
    "dunfermline athletic": "Dunfermline", "raith rovers": "Raith", "partick thistle": "Partick",
    "greenock morton": "Morton", "hamilton academical": "Hamilton", "airdrieonians": "Airdrieonians",
    "queens park": "Queens Park", "ross county": "Ross County", "st johnstone": "St Johnstone",
    "st mirren": "St Mirren", "dundee united": "Dundee United", "dundee fc": "Dundee",
    "heart of midlothian": "Hearts", "hibernian": "Hibernian", "kilmarnock": "Kilmarnock",
    "motherwell": "Motherwell", "fiorentina": "Fiorentina", "hellas verona": "Verona",
    "verona": "Verona", "internazionale": "Inter", "inter milan": "Inter",
    "ssc napoli": "Napoli", "ac milan": "Milan", "as roma": "Roma", "torino fc": "Torino",
    "ac monza": "Monza", "us sassuolo": "Sassuolo", "genoa cfc": "Genoa",
    "boavista fc": "Boavista", "rio ave fc": "Rio Ave", "gil vicente fc": "Gil Vicente",
    "sc braga": "Braga", "fc porto": "Porto", "sl benfica": "Benfica",
    "cd santa clara": "Santa Clara", "moreirense fc": "Moreirense", "fc famalicao": "Famalicao",
    "estoril praia": "Estoril", "fc arouca": "Arouca", "cd nacional": "Nacional",
    "sc farense": "Farense", "cd tondela": "Tondela", "gd estoril": "Estoril",
    "fc vizela": "Vizela", "vitoria de guimaraes": "Guimaraes", "vitoria de guimaraes sc": "Guimaraes",
    "fenerbahce sk": "Fenerbahce", "galatasaray sk": "Galatasaray", "besiktas jk": "Besiktas",
    "trabzonspor": "Trabzonspor", "sivasspor": "Sivasspor", "konyaspor": "Konyaspor",
    "basaksehir fk": "Buyuksehyr", "goztepe": "Goztepe", "goztepe izmir": "Goztepe",
    "kasimpasa": "Kasimpasa", "kayserispor": "Kayserispor", "alanyaspor": "Alanyaspor",
    "antalyaspor": "Antalyaspor", "gaziantep fk": "Gaziantep", "pendikspor": "Pendikspor",
    "samsunspor": "Samsunspor", "eyupspor": "Eyupspor", "mke ankaragucu": "Ankaragucu",
    "hatayspor": "Hatayspor", "rizespor": "Rizespor", "malmo ff": "Malmo FF",
    "malmo": "Malmo FF", "athletic club": "Athletic Club", "ca osasuna": "Osasuna",
    "rcd mallorca": "Mallorca", "rcd espanyol": "Espanyol", "getafe cf": "Getafe",
    "real betis": "Real Betis", "real sociedad": "Real Sociedad", "real madrid cf": "Real Madrid",
    "fc barcelona": "Barcelona", "sevilla fc": "Sevilla", "girona fc": "Girona",
    "ud las palmas": "Las Palmas", "deportivo la coruna": "La Coruna", "leganes": "Leganes",
    "real valladolid": "Valladolid", "real valladolid cf": "Valladolid", "elche cf": "Elche",
    "valencia cf": "Valencia", "levante ud": "Levante", "real oviedo": "Oviedo",
    "real zaragoza": "Zaragoza", "sd huesca": "Huesca", "burgos cf": "Burgos",
    "fc cartagena": "Cartagena", "sd eibar": "Eibar", "sporting gijon": "Sp Gijon",
    "real santander": "Santander", "cd tenerife": "Tenerife", "albacete balompie": "Albacete",
    "fc andorra": "Andorra", "cd mirandes": "Mirandes", "sd amorebieta": "Amorebieta",
    "granada cf": "Granada", "malaga cf": "Malaga", "cd leganes": "Leganes",
    "levante": "Levante", "real madrid": "Real Madrid", "atletic club": "Athletic Club",
}
ALIAS = {k.lower(): v for k, v in ALIAS.items()}


def norm(s):
    s = s.lower().strip()
    s = re.sub(r"[\.']", "", s)
    s = re.sub(r"\b(fc|ac|as|cf|sc|ud|cd|rcd|afc|bsc|fk|sk|jk|mke)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_TEAMS = None

def league_teams():
    """{liga: set echipe CSV} pentru toate ligile, sezoanele 2526+2627."""
    global _TEAMS
    if _TEAMS is not None:
        return _TEAMS
    _TEAMS = {}
    for lg in ["E0", "E1", "E2", "E3", "SC0", "SC1", "SC2", "SC3", "D1", "D2",
               "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]:
        try:
            df = bm.load_league(lg, ["2627"])
            _TEAMS[lg] = set(df["HomeTeam"].dropna()) | set(df["AwayTeam"].dropna())
        except Exception:
            pass
    return _TEAMS


def resolve(name, teams_by_league):
    """Returneaza (liga, nume CSV) sau None."""
    n = norm(name)
    if n in ALIAS:
        csv_name = ALIAS[n]
        for lg, teams in teams_by_league.items():
            if csv_name in teams:
                return lg, csv_name
        return None
    for lg, teams in teams_by_league.items():
        if name in teams:
            return lg, name
    # incercare fuzzy: nume CSV continut in numele Superbet sau invers
    for lg, teams in teams_by_league.items():
        for t in teams:
            tn = norm(t)
            if tn and (tn in n or n in tn):
                if len(tn) >= 4:
                    return lg, t
    return None


def get_json(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            time.sleep(2 + i * 2)
    return None


def day_events(date_s):
    url = DAY_API.format(s=date_s + "T00:00:00", e=date_s + "T23:00:00")
    d = get_json(url)
    return (d or {}).get("events", [])


def parse_markets(ev):
    out = {}
    for m in ev.get("markets", []):
        name = m.get("name")
        if name not in list(MARKET_MAP.values()):
            continue
        d = out.setdefault(name, {})
        for o in m.get("odds", []):
            if o.get("status") != 1:
                continue
            nm = (o.get("metadata") or {}).get("name", "")
            if nm.startswith("Peste"):
                try:
                    d[float(nm.replace("Peste", "").strip())] = o["price"]
                except ValueError:
                    pass
    return out


def pick_best(rows):
    best = None
    for r in rows:
        if r["ev"] >= 0.05:
            score = r["ev"] * CAL.get(r["piata"], 1)
            if best is None or score > best[0]:
                best = (score, r)
    alts = sorted([r for r in rows if r["ev"] >= 0.05 and (best is None or r is not best[1])],
                  key=lambda x: -x["ev"])[:1]
    return (best[1] if best else None), alts


def analyze_day(date_s, limit=10):
    teams = league_teams()
    cands = []
    for ev in day_events(date_s):
        fx = ev.get("fixture", {})
        en = fx.get("event_name", "")
        lg = TOURNAMENTS.get(fx.get("tournament_id"))
        if not lg or "·" not in en or "(" in en:
            continue
        h, a = [x.strip() for x in en.split("·", 1)]
        rh = resolve(h, teams)
        ra = resolve(a, teams)
        if not rh or not ra or rh[0] != lg or ra[0] != lg:
            continue
        cands.append({"eid": ev.get("event_id"), "lg": lg, "home": rh[1], "away": ra[1],
                      "sb_home": h, "sb_away": a})
    prio = {lg: i for i, lg in enumerate(LEAGUE_PRIORITY)}
    cands.sort(key=lambda c: prio.get(c["lg"], 99))
    results = []
    for c in cands:
        if len(results) >= limit:
            break
        d = get_json(EV_API.format(c["eid"]))
        if not d or not d.get("events"):
            continue
        ev = d["events"][0]
        if not ev.get("markets"):
            continue
        sb = parse_markets(ev)
        try:
            df = bm.load_league(c["lg"], bm.SEASONS)
            model = bm.LeagueModel(df)
            rows = []
            for stat, sbname in MARKET_MAP.items():
                for line, odds in sorted(sb.get(sbname, {}).items()):
                    p, lam = model.total_prob(c["home"], c["away"], stat, line)
                    rows.append({"piata": sbname, "line": line, "p": p, "odds": odds,
                                 "fair": 1 / p, "ev": p * odds - 1})
            best, alts = pick_best(rows)
            maxev = max((r["ev"] for r in rows), default=0)
            results.append({**c, "best": best, "alts": alts, "maxev": maxev, "rows": len(rows)})
        except Exception as ex:
            print(f"  [{c['lg']}] {c['home']}-{c['away']}: model error: {ex}")
        time.sleep(0.8)
    return results


VERDICT_PLAY = "JOCI"
VERDICT_SMALL = "miză mică"
VERDICT_SKIP = "NU JOCI"


def verdict(m):
    if m["best"] is None:
        return VERDICT_SKIP
    r = m["best"]
    if r["piata"] == "Total cornere" and r["ev"] < 0.30:
        return VERDICT_SMALL
    return VERDICT_PLAY


def render_html(results, date_s, gen_at):
    rows_html = []
    vclass = {VERDICT_PLAY: "play", VERDICT_SMALL: "small", VERDICT_SKIP: "skip"}
    for m in results:
        v = verdict(m)
        if m["best"]:
            b = m["best"]
            sel = f'peste {b["line"]:.1f} {b["piata"].replace("Total ", "").lower()}'
            mine, sb, chance = f'{b["fair"]:.2f}', f'{b["odds"]:.2f}', f'{b["p"]*100:.0f}%'
        else:
            sel = "—"
            mine = sb = chance = "—"
        alt_txt = ""
        for a in m["alts"]:
            alt_txt += (f'<div class="alt">variantă: peste {a["line"]:.1f} '
                        f'{a["piata"].replace("Total ","").lower()} — cota mea {a["fair"]:.2f}, '
                        f'SB {a["odds"]:.2f}</div>')
        rows_html.append(
            f'<tr class="{vclass[v]}"><td class="meci">{m["home"]} – {m["away"]}'
            f'<span class="liga">{m["lg"]}</span></td>'
            f'<td class="sel">{sel}{alt_txt}</td><td>{mine}</td><td class="sb">{sb}</td>'
            f'<td>{chance}</td><td class="vd {vclass[v]}">{v}</td></tr>')
    if not rows_html:
        rows_html.append('<tr><td colspan="6" class="none">Nicio selecție cu value azi. '
                         'Nu se joacă nimic — asta e disciplina.</td></tr>')
    return TEMPLATE.format(date=date_s, gen_at=gen_at, rows="\n".join(rows_html))


TEMPLATE = """<!DOCTYPE html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pariuri Value — Top 10 meciuri</title>
<style>
  :root {{ --bg:#0f1115; --card:#171a21; --line:#262b36; --txt:#e8eaf0; --mut:#9aa3b2; --ok:#2ecc71; --bad:#e74c3c; --warn:#f1c40f; --acc:#5b9dff; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--txt); font-family:'Segoe UI',system-ui,sans-serif; padding:16px; max-width:980px; margin:0 auto; }}
  header h1 {{ font-size:22px; font-weight:600; }}
  header .sub {{ color:var(--mut); font-size:13px; margin-top:4px; }}
  .regula {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:14px 0; font-size:14px; line-height:1.55; }}
  .regula b {{ color:var(--ok); }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; font-size:14px; }}
  th, td {{ padding:10px 10px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; }}
  th {{ background:#1d212b; color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.4px; }}
  tr:last-child td {{ border-bottom:none; }}
  .meci {{ font-weight:600; white-space:nowrap; }}
  .liga {{ display:inline-block; margin-left:6px; font-size:11px; color:var(--mut); border:1px solid var(--line); border-radius:4px; padding:1px 5px; }}
  .sel {{ font-weight:600; }}
  .alt {{ font-weight:400; color:var(--mut); font-size:12px; margin-top:3px; }}
  .sb {{ font-weight:700; color:var(--acc); }}
  .vd {{ font-weight:700; white-space:nowrap; }}
  .vd.play {{ color:var(--ok); }} .vd.small {{ color:var(--warn); }} .vd.skip {{ color:var(--bad); }}
  .none {{ color:var(--mut); text-align:center; padding:24px; }}
  footer {{ color:var(--mut); font-size:12px; margin-top:14px; line-height:1.6; }}
</style>
</head>
<body>
<header>
  <h1>📋 Pariuri Value — {date}</h1>
  <div class="sub">Generat {gen_at} · model Poisson pe ultimele 4 sezoane · 10 meciuri din ligile acoperite</div>
</header>
<div class="regula">
  <b>Regula de citire (5 secunde):</b> coloana „COTA MEA" e cota corectă calculată din statistici.
  Dacă <b>COTA SB e mai mare</b> → Superbet plătește peste merit → <b>joci</b>.
  Dacă e mai mică → nu joci, chiar dacă ți se pare „sigur". Value-ul se prinde dimineața — cotele scad spre start.
</div>
<table>
  <thead><tr><th>Meci</th><th>Ce pariezi</th><th>Cota mea</th><th>Cota SB</th><th>Șansă</th><th>Verdict</th></tr></thead>
  <tbody>
{rows}
  </tbody>
</table>
<footer>
  Piața „faulturi" e cea mai bine calibrată a modelului; „cornere" cea mai slabă — de aceea cornerele au doar miză mică.
  Aici nu se joacă goluri: modelul a pierdut la backtest pe goluri. Fără meciuri de cupă (modelul e calibrat pe campionat).
</footer>
</body>
</html>
"""


def main():
    args = [a for a in sys.argv[1:] if a != "--push"]
    do_push = "--push" in sys.argv
    date_s = args[0] if args else datetime.date.today().isoformat()
    print(f"Ziua: {date_s} (push={'da' if do_push else 'nu'})")
    results = analyze_day(date_s)
    print(f"Analizate: {len(results)} meciuri")
    for m in results:
        v = verdict(m)
        if m["best"]:
            b = m["best"]
            print(f'  [{m["lg"]}] {m["home"]}-{m["away"]}: {b["piata"]} {b["line"]} '
                  f'cota_mea={b["fair"]:.2f} SB={b["odds"]:.2f} EV={b["ev"]*100:.1f}% -> {v}')
        else:
            print(f'  [{m["lg"]}] {m["home"]}-{m["away"]}: maxEV={m["maxev"]*100:.1f}% -> {v}')
    gen_at = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    html = render_html(results, date_s, gen_at)
    out = "site/index.html"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("scris:", out)
    if do_push:
        subprocess.run(["git", "add", "site/index.html"], cwd=".", check=False)
        subprocess.run(["git", "commit", "-m", f"update {date_s}"], cwd=".", check=False)
        r = subprocess.run(["git", "push"], cwd=".", capture_output=True, text=True)
        print("push:", "OK" if r.returncode == 0 else r.stderr[-300:])


if __name__ == "__main__":
    main()
