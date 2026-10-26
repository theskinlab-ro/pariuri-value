# -*- coding: utf-8 -*-
"""Generator site zilnic: alege top 10 meciuri, calculeaza probabilitati si sugestii,
rescrie site/index.html. Rulat local sau in GitHub Actions."""
import datetime
import json
import os
import urllib.request

import pandas as pd

import bet_mvp as bm
import combo_engine as ce

LEAGUES = ["E0", "E1", "E2", "E3", "SC0", "SC1", "D1", "D2", "I1", "I2",
           "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
LEAGUE_NAMES = {"E0": "Premier League", "E1": "Championship", "E2": "League One", "E3": "League Two",
                "SC0": "Scoția Premiership", "SC1": "Scoția Championship", "D1": "Bundesliga",
                "D2": "Bundesliga 2", "I1": "Serie A", "I2": "Serie B", "SP1": "La Liga",
                "SP2": "La Liga 2", "F1": "Ligue 1", "F2": "Ligue 2", "N1": "Olanda Eredivisie",
                "B1": "Belgia Pro League", "P1": "Primeira Liga", "T1": "Süper Lig", "G1": "Grecia Super League"}
SEASONS = ["2324", "2425", "2526", "2627"]
STAT_LINES = {"faulturi": [19.5, 21.5, 23.5], "cornere": [8.5, 9.5, 10.5], "galbene": [3.5, 4.5, 5.5]}
COMBOS = [(19.5, 3.5), (21.5, 4.5), (23.5, 5.5)]


def ensure_data():
    os.makedirs("data", exist_ok=True)
    for lg in LEAGUES:
        for s in SEASONS:
            p = f"data/{lg}_{s}.csv"
            if not os.path.exists(p) or os.path.getsize(p) < 1000:
                try:
                    urllib.request.urlretrieve(f"https://www.football-data.co.uk/mmz4281/{s}/{lg}.csv", p)
                except Exception:
                    pass


def analyze_match(model, combo, home, away):
    stats = {}
    for stat, lns in STAT_LINES.items():
        stats[stat] = [{"line": ln, "p": round(model.total_prob(home, away, stat, ln)[0], 4)} for ln in lns]
    combos = []
    for lf, lc in COMBOS:
        p = combo.joint_prob(home, away, lf, lc)
        combos.append({"lf": lf, "lc": lc, "p": round(p, 4)})
    ph, pd_, pa, po25, _ = bm.goal_probs(model, home, away)
    return stats, combos, {"p1": round(ph, 4), "px": round(pd_, 4), "p2": round(pa, 4), "po25": round(po25, 4)}


def suggestions(stats, combos):
    """Sugestii doar pe pietele in care avem incredere: faulturi, cartonaise, combinatii."""
    out = []
    for c in combos:
        p, fair = c["p"], 1 / c["p"]
        if 0.45 <= p <= 0.82:
            out.append({"tip": f'Peste {c["lf"]:g} faulturi + peste {c["lc"]:g} cartonașe',
                        "p": p, "fair": round(fair, 2), "min": round(fair * 1.03, 2),
                        "kind": "combo", "edge": "corelație"})
    pf = {d["line"]: d["p"] for d in stats["faulturi"]}
    if pf[21.5] >= 0.60:
        out.append({"tip": "Peste 21.5 faulturi", "p": pf[21.5], "fair": round(1 / pf[21.5], 2),
                    "min": round(1 / pf[21.5] * 1.03, 2), "kind": "faulturi", "edge": "rată faulturi"})
    py = {d["line"]: d["p"] for d in stats["galbene"]}
    if py[3.5] >= 0.66:
        out.append({"tip": "Peste 3.5 cartonașe", "p": py[3.5], "fair": round(1 / py[3.5], 2),
                    "min": round(1 / py[3.5] * 1.03, 2), "kind": "galbene", "edge": "severitate"})
    out.sort(key=lambda x: -x["p"])
    return out[:2]


def main():
    ensure_data()
    fixtures = pd.read_csv("data/fixtures.csv", encoding="utf-8-sig")
    fixtures["Date"] = pd.to_datetime(fixtures["Date"], dayfirst=True, errors="coerce")
    today = pd.Timestamp(datetime.date.today())
    fx = fixtures[(fixtures["Date"] == today) & (fixtures["Div"].isin(LEAGUES))]

    models, combos_eng = {}, {}
    matches = []
    for _, f in fx.iterrows():
        lg = f["Div"]
        if lg not in models:
            df = bm.load_league(lg, SEASONS)
            if df.empty or len(df) < 300:
                models[lg] = None
                continue
            models[lg] = bm.LeagueModel(df)
            combos_eng[lg] = ce.ComboEngine(lg, tuple(SEASONS))
        if models[lg] is None:
            continue
        home, away = f["HomeTeam"], f["AwayTeam"]
        stats, combos, goals = analyze_match(models[lg], combos_eng[lg], home, away)
        pj = max(c["p"] for c in combos)
        pf195 = stats["faulturi"][0]["p"]
        score = pj * 0.6 + pf195 * 0.4
        matches.append({"lg": lg, "liga": LEAGUE_NAMES.get(lg, lg), "home": home, "away": away,
                        "time": str(f.get("Time", "")), "score": score,
                        "stats": stats, "combos": combos, "goals": goals,
                        "sugestii": suggestions(stats, combos)})

    matches.sort(key=lambda m: -m["score"])
    top = matches[:10]
    for m in top:
        m.pop("score", None)
    data = {"date": today.strftime("%d.%m.%Y"), "generated": datetime.datetime.now().strftime("%d.%m %H:%M"),
            "count": len(matches), "matches": top}
    with open("site_template.html", encoding="utf-8") as fh:
        tpl = fh.read()
    html = tpl.replace("/*__DATA__*/null/*__END__*/", json.dumps(data, ensure_ascii=False))
    os.makedirs("site", exist_ok=True)
    with open("site/index.html", "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Site generat: {len(top)} meciuri (din {len(matches)} analizate) -> site/index.html")


if __name__ == "__main__":
    main()
