# -*- coding: utf-8 -*-
"""
MVP value-betting: faulturi / cornere / cartonașe / goluri
Model: rate multiplicative cu shrinkage (prior = media ligii), total ~ Poisson.
"""
import math
import pandas as pd
import numpy as np
from collections import defaultdict

DATA = "data"
SEASONS = ["2324", "2425", "2526", "2627"]
LEAGUES_TODAY = ["SP1", "F1", "T1", "P1", "E3"]
PRIOR = 6  # pseudo-meciuri la media ligii


def poisson_cdf(k, lam):
    """P(X <= k) pentru X ~ Poisson(lam)."""
    if lam <= 0:
        return 1.0 if k >= 0 else 0.0
    s, term = 0.0, math.exp(-lam)
    for i in range(0, int(k) + 1):
        s += term
        term *= lam / (i + 1)
    return min(s, 1.0)


def load_league(league, seasons):
    frames = []
    for s in seasons:
        try:
            df = pd.read_csv(f"{DATA}/{league}_{s}.csv", encoding="utf-8-sig")
            df["Season"] = s
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    cols = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HF", "AF", "HC", "AC", "HY", "AY"]
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam"])
    for c in cols[3:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("Date").reset_index(drop=True)


class LeagueModel:
    """Rate atac/apărare pe fiecare statistică, cu shrinkage spre media ligii."""

    def __init__(self, df):
        self.df = df
        self.stats = {
            "faulturi": ("HF", "AF"),
            "cornere": ("HC", "AC"),
            "galbene": ("HY", "AY"),
            "goluri": ("FTHG", "FTAG"),
        }
        self._fit()

    def _fit(self):
        df = self.df.copy()
        # ponderi de recență: meciurile vechi contează mai puțin (înjumătățire ~ la 6 luni)
        tmax = df["Date"].max()
        df["_w"] = 0.88 ** ((tmax - df["Date"]).dt.days / 30.0)
        self.df = df
        self.avg = {}
        for name, (hc, ac) in self.stats.items():
            sub = df.dropna(subset=[hc, ac])
            w = sub["_w"]
            w_h, w_a = w.sum(), w.sum()
            vals = np.concatenate([sub[hc].to_numpy(), sub[ac].to_numpy()])
            ws = np.concatenate([w.to_numpy(), w.to_numpy()])
            self.avg[name] = {
                "home": np.average(sub[hc], weights=w),
                "away": np.average(sub[ac], weights=w),
                "all": np.average(vals, weights=ws),
            }
        # per echipă: acasă (statistica proprie, primită), deplasare
        self.rate = defaultdict(dict)
        for team in set(df["HomeTeam"]) | set(df["AwayTeam"]):
            h = df[df["HomeTeam"] == team]
            a = df[df["AwayTeam"] == team]
            r = {}
            for name, (hc, ac) in self.stats.items():
                hh = h.dropna(subset=[hc, ac])
                aa = a.dropna(subset=[hc, ac])
                wh, wa = hh["_w"], aa["_w"]
                avg = self.avg[name]
                # atac propriu acasă / deplasare (prior = PRIOR meciuri la media ligii)
                # medie ponderată robustă: fără date -> doar priorul (media ligii)
                def wrate(vals, w, prior_mean):
                    ws = w.sum()
                    if ws <= 0:
                        return 1.0
                    return (float(np.average(vals, weights=w)) * ws + PRIOR * prior_mean) / (ws + PRIOR) / prior_mean
                att_h = wrate(hh[hc], wh, avg["home"])
                att_a = wrate(aa[ac], wa, avg["away"])
                # apărare: cât ia (statistica adversarului)
                def_h = wrate(hh[ac], wh, avg["away"])
                def_a = wrate(aa[hc], wa, avg["home"])
                r[name] = {"att_h": att_h, "att_a": att_a, "def_h": def_h, "def_a": def_a,
                           "n_home": len(hh), "n_away": len(aa)}
            self.rate[team] = r

    def expected(self, home, away, stat):
        """λ pentru (acasă, deplasare) într-un meci home vs away."""
        avg = self.avg[stat]
        rh = self.rate.get(home)
        ra = self.rate.get(away)
        if rh is None or ra is None:
            # echipă necunoscăută -> medii de ligă
            return avg["home"], avg["away"]
        lam_h = avg["home"] * rh[stat]["att_h"] * ra[stat]["def_a"]
        lam_a = avg["away"] * ra[stat]["att_a"] * rh[stat]["def_h"]
        return lam_h, lam_a

    def total_prob(self, home, away, stat, line):
        """P(total > line) pentru suma celor două echipe."""
        lh, la = self.expected(home, away, stat)
        lam = lh + la
        return 1 - poisson_cdf(math.floor(line), lam), lam


def goal_probs(model, home, away, maxg=9):
    lh, la = model.expected(home, away, "goluri")
    mat = np.zeros((maxg + 1, maxg + 1))
    for i in range(maxg + 1):
        pi = math.exp(-lh) * lh ** i / math.factorial(i)
        for j in range(maxg + 1):
            pj = math.exp(-la) * la ** j / math.factorial(j)
            mat[i, j] = pi * pj
    ph = np.tril(mat, -1).sum()
    pd = np.trace(mat)
    pa = np.triu(mat, 1).sum()
    tail = 1 - mat.sum()
    ph += tail * 0.5
    pa += tail * 0.5  # cozi rare: le împărțim
    p_over = sum(mat[i, j] for i in range(maxg + 1) for j in range(maxg + 1) if i + j >= 3)
    return ph, pd, pa, p_over, lh + la


def fair(p):
    return round(1 / p, 2) if p > 0.001 else None


def ev(p, odds):
    try:
        odds = float(odds)
    except (TypeError, ValueError):
        return None
    return round(p * odds - 1, 3)


def load_manual_odds():
    """Cote introduse manual din casa ta (vezi odds_manual.csv)."""
    try:
        df = pd.read_csv("odds_manual.csv", encoding="utf-8-sig")
        return {(r["league"], r["home"], r["away"], r["market"], float(r["line"])): float(r["odds"])
                for _, r in df.iterrows()}
    except FileNotFoundError:
        return {}


def fetch_odds_api(key, leagues=("soccer_spain_la_liga", "soccer_france_ligue_one",
                                  "soccer_turkey_super_league", "soccer_portugal_primeira_liga",
                                  "soccer_england_league_one")):
    """The Odds API (the-odds-api.com) — h2h + total goluri. Necesită cheie gratuită."""
    import urllib.request, json
    out = {}
    for lg in leagues:
        url = (f"https://api.the-odds-api.com/v4/sports/{lg}/odds/?apiKey={key}"
               f"&regions=eu&markets=h2h,totals&oddsFormat=decimal")
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as e:
            print(f"  [odds-api] {lg}: {e}")
            continue
        for ev_ in data:
            key_m = (lg.split("_", 1)[1], ev_["home_team"], ev_["away_team"])
            for bk in ev_.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt["key"] == "h2h":
                        for o in mkt["outcomes"]:
                            lbl = {"home": "1", "away": "2", "draw": "X"}.get(o["name"])
                            if lbl:
                                out[(key_m, "1X2", lbl)] = o["price"]
                    elif mkt["key"] == "totals":
                        for o in mkt["outcomes"]:
                            if o["name"] == "Over":
                                out[(key_m, "P2.5", o["point"])] = o["price"]
    return out


def calibration_check(league):
    """Backtest simplu: antrenăm pe 2324+2425, evaluăm pe 2526."""
    df = load_league(league, ["2324", "2425", "2526"])
    if df.empty:
        return
    cutoff = df[df["Season"] == "2526"]["Date"].min()
    train = df[df["Date"] < cutoff]
    test = df[(df["Season"] == "2526")].dropna(subset=["HC", "HF"])
    if len(test) < 50:
        return
    m = LeagueModel(train)
    rows = []
    for _, r in test.iterrows():
        pc, _ = m.total_prob(r["HomeTeam"], r["AwayTeam"], "cornere", 9.5)
        pf, _ = m.total_prob(r["HomeTeam"], r["AwayTeam"], "faulturi", 21.5)
        py, _ = m.total_prob(r["HomeTeam"], r["AwayTeam"], "galbene", 4.5)
        rows.append((pc, r["HC"] + r["AC"] > 9.5, pf, r["HF"] + r["AF"] > 21.5,
                     py, r["HY"] + r["AY"] > 4.5))
    res = pd.DataFrame(rows, columns=["p_c", "c_hit", "p_f", "f_hit", "p_y", "y_hit"])
    print(f"\n=== CALIBRARE {league} (sezon 25/26, {len(res)} meciuri, model antrenat pe 23-25) ===")
    for col, hit, label in [("p_c", "c_hit", "cornere peste 9.5"),
                            ("p_f", "f_hit", "faulturi peste 21.5"),
                            ("p_y", "y_hit", "galbene peste 4.5")]:
        res["bin"] = pd.cut(res[col], bins=[0, .35, .45, .55, .65, 1])
        g = res.groupby("bin", observed=True).agg(n=(hit, "size"), prob_medie=(col, "mean"), rata_reală=(hit, "mean"))
        print(f"\n{label}:")
        print(g.round(3).to_string())


def main():
    fixtures = pd.read_csv(f"{DATA}/fixtures.csv", encoding="utf-8-sig")
    fixtures["Date"] = pd.to_datetime(fixtures["Date"], dayfirst=True, errors="coerce")
    today = pd.Timestamp("2026-10-26")
    fx = fixtures[(fixtures["Date"] == today) & (fixtures["Div"].isin(LEAGUES_TODAY))]

    print("MECIURI DE ANALIZAT AZI:", len(fx))
    models = {}
    for lg in LEAGUES_TODAY:
        df = load_league(lg, SEASONS)
        models[lg] = (LeagueModel(df), df)

    manual_odds = load_manual_odds()
    if manual_odds:
        print(f"Cote manuale încărcate: {len(manual_odds)} (din odds_manual.csv)")
    import os
    api_key = os.environ.get("ODDS_API_KEY", "")
    live_odds = fetch_odds_api(api_key) if api_key else {}

    lines = {
        "faulturi": [19.5, 21.5, 23.5],
        "cornere": [8.5, 9.5, 10.5, 11.5],
        "galbene": [3.5, 4.5, 5.5],
    }
    STAT_LABEL = {"faulturi": "Faulturi", "cornere": "Cornere", "galbene": "Cart. galbene"}

    picks = []
    for _, f in fx.iterrows():
        lg = f["Div"]
        model, df = models[lg]
        home, away = f["HomeTeam"], f["AwayTeam"]
        print(f"\n{'='*72}\n[{lg}] {home} vs {away}  ({f['Time']})")
        print(f"  Cote medii 1X2: {f.get('AvgH')} / {f.get('AvgD')} / {f.get('AvgA')}   "
              f"Peste 2.5 goluri: {f.get('Avg>2.5')}")

        for stat, lns in lines.items():
            for ln in lns:
                p, lam = model.total_prob(home, away, stat, ln)
                mo = manual_odds.get((lg, home, away, stat, ln))
                ev_s = ""
                if mo:
                    e = ev(p, mo)
                    ev_s = f"  | cota ta {mo} -> EV={e*100:+.1f}%"
                    if e >= 0.05:
                        picks.append((lg, f"{home} - {away}", f"{STAT_LABEL[stat]} peste {ln}", p, mo, e))
                        ev_s += "  << VALUE!"
                flag = "  << VALUE?" if p > 0.65 and not mo else ""
                print(f"  {STAT_LABEL[stat]:>15} peste {ln:>4}: P={p*100:5.1f}%  cotă corectă={fair(p)}{ev_s}{flag}")

        ph, pd_, pa, po25, lamg = goal_probs(model, home, away)
        print(f"  Goluri: λ total={lamg:.2f} | 1={ph*100:.1f}% X={pd_*100:.1f}% 2={pa*100:.1f}% | Peste2.5={po25*100:.1f}%")
        print(f"           cote corecte: 1={fair(ph)} X={fair(pd_)} 2={fair(pa)} P2.5={fair(po25)}")

        # value pe piețele cu cote reale
        for name, p, odds_col in [("1", ph, "AvgH"), ("X", pd_, "AvgD"), ("2", pa, "AvgA"), ("Peste2.5", po25, "Avg>2.5")]:
            o = f.get(odds_col)
            e = ev(p, o)
            if e is not None:
                best = f"EV={e*100:+.1f}%" if abs(e) < 9 else ""
                if e >= 0.05:
                    picks.append((lg, f"{home} - {away}", name, p, o, e))
                print(f"           {name:>9}: cota {o} -> {best}")

    print("\n" + "=" * 72)
    print("SELECȚII VALUE (EV >= +5% vs cote medii):")
    if picks:
        for lg, m, mkt, p, o, e in picks:
            print(f"  [{lg}] {m} | {mkt}: P={p*100:.1f}% cota={o} EV={e*100:+.1f}%")
    else:
        print("  Nicio selecție peste prag. (Semn bun pentru onestitatea modelului — vezi calibrarea.)")

    for lg in LEAGUES_TODAY:
        calibration_check(lg)


WIDGET_WORKSPACE = (r"C:\Users\User\AppData\Roaming\kimi-desktop\daimon-share\daimon"
                    r"\agents\main\blueprint\widgets\widget_b2a7e819-2466-499f-87e9-14cca295c0d0\workspace")


def export_widget(out_path=None):
    """Generează widgetul zilnic: recalculează probabilitățile și rescrie index.html."""
    import json, datetime, os
    out_path = out_path or WIDGET_WORKSPACE
    fixtures = pd.read_csv(f"{DATA}/fixtures.csv", encoding="utf-8-sig")
    fixtures["Date"] = pd.to_datetime(fixtures["Date"], dayfirst=True, errors="coerce")
    today = pd.Timestamp(datetime.date.today())
    fx = fixtures[(fixtures["Date"] == today) & (fixtures["Div"].isin(LEAGUES_TODAY))]

    lines = {"faulturi": [19.5, 21.5, 23.5], "cornere": [8.5, 9.5, 10.5, 11.5], "galbene": [3.5, 4.5, 5.5]}
    matches = []
    for _, f in fx.iterrows():
        lg = f["Div"]
        df = load_league(lg, SEASONS)
        if df.empty:
            continue
        model = LeagueModel(df)
        home, away = f["HomeTeam"], f["AwayTeam"]
        stats = {}
        for stat, lns in lines.items():
            stats[stat] = [{"line": ln, "p": round(model.total_prob(home, away, stat, ln)[0], 4)} for ln in lns]
        ph, pd_, pa, po25, _ = goal_probs(model, home, away)
        matches.append({
            "lg": lg, "home": home, "away": away, "time": str(f.get("Time", "")),
            "stats": stats,
            "g": {"p1": round(ph, 4), "px": round(pd_, 4), "p2": round(pa, 4), "po25": round(po25, 4)},
        })
    data = {
        "dateLabel": today.strftime("%d.%m.%Y"),
        "generatedAt": datetime.datetime.now().strftime("%H:%M"),
        "matches": matches,
    }
    with open("widget_template.html", encoding="utf-8") as fh:
        tpl = fh.read()
    html = tpl.replace("/*__PV_DATA__*/null/*__END_PV_DATA__*/", json.dumps(data, ensure_ascii=False))
    with open(os.path.join(out_path, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Widget actualizat: {len(matches)} meciuri -> {out_path}")


if __name__ == "__main__":
    import sys
    if "--widget" in sys.argv:
        export_widget(sys.argv[sys.argv.index("--widget") + 1] if len(sys.argv) > sys.argv.index("--widget") + 1 else None)
    else:
        main()
