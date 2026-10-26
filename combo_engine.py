# -*- coding: utf-8 -*-
"""Motor bet builder: probabilitate COMUNA faulturi + cartonaase.
Cartonaasele NU sunt modelate independent: C | F=k ~ Poisson(k * cpf_meci).
cpf_meci = cart./fault al ligii x factor arbitru x factor echipa-gazda x factor echipa-oaspete.
"""
import math
import pandas as pd
import numpy as np
import bet_mvp as bm

PRIOR_CPF = 8  # pseudo-meciuri la media ligii pentru rata cart./fault


def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


class ComboEngine:
    def __init__(self, league, seasons=("2324", "2425", "2526", "2627")):
        self.df = bm.load_league(league, list(seasons))
        self.foul_model = bm.LeagueModel(self.df)
        df = self.df.dropna(subset=["HF", "AF", "HY", "AY"]).copy()
        df["F"] = df["HF"] + df["AF"]
        df["C"] = df["HY"] + df["AY"]
        self.base_cpf = df["C"].sum() / df["F"].sum()

        # factor arbitru (cart./fault in meciurile lui), cu shrinkage
        self.ref_cpf = {}
        if "Referee" in df.columns:
            for ref, g in df.groupby("Referee"):
                if len(g) >= 8 and len(ref) > 2:
                    cpf = (g["C"].sum() + PRIOR_CPF * self.base_cpf * 20) / (g["F"].sum() + PRIOR_CPF * 20)
                    self.ref_cpf[ref] = cpf / self.base_cpf

        # factor echipa: cart./fault proprii, cu shrinkage
        self.team_cpf = {}
        for t in set(df["HomeTeam"]) | set(df["AwayTeam"]):
            own = df[(df["HomeTeam"] == t)]
            away = df[(df["AwayTeam"] == t)]
            cards = own["HY"].sum() + away["AY"].sum()
            fouls = own["HF"].sum() + away["AF"].sum()
            if fouls > 0:
                self.team_cpf[t] = ((cards + PRIOR_CPF * self.base_cpf * 20) / (fouls + PRIOR_CPF * 20)) / self.base_cpf

        # oboseala: pauza <=3 zile -> ~4% mai putine faulturi (masurat)
        self.rest = {}
        d2 = self.df.dropna(subset=["Date"]).sort_values("Date")
        for t in set(d2["HomeTeam"]) | set(d2["AwayTeam"]):
            g = d2[(d2["HomeTeam"] == t) | (d2["AwayTeam"] == t)].sort_values("Date")
            self.rest[t] = g["Date"].diff().dt.days.iloc[-1]

    def analyze(self, home, away, referee=None, max_fouls=60):
        lh, la = self.foul_model.expected(home, away, "faulturi")
        lam_f = lh + la
        for t in (home, away):
            r = self.rest.get(t)
            if r is not None and r <= 3:
                lam_f *= 0.96  # coefficient masurat: oboseala usoara -> mai putine faulturi
        cpf = self.base_cpf
        parts = {"liga": 1.0}
        if referee and referee in self.ref_cpf:
            parts["arbitru"] = self.ref_cpf[referee]
            cpf *= self.ref_cpf[referee]
        for t in (home, away):
            f = self.team_cpf.get(t, 1.0)
            parts[t] = f
            cpf *= f

        # distributia conjuncta: P(F=kf) * P(C>lc | F=kf)
        def joint(lf, lc):
            p = 0.0
            for k in range(int(math.floor(lf)) + 1, max_fouls):
                lam_c = k * cpf
                p += poisson_pmf(k, lam_f) * (1 - bm.poisson_cdf(int(math.floor(lc)), lam_c))
            return p, lam_f, cpf

        return joint, parts

    def joint_prob(self, home, away, lf, lc, referee=None):
        j, _ = self.analyze(home, away, referee)
        return j(lf, lc)[0]


def report(league, home, away, referee=None):
    eng = ComboEngine(league)
    j, parts = eng.analyze(home, away, referee)
    print(f"\n{'='*70}\n{home} - {away}  [{league}]")
    print("factori cart./fault:", {k: round(v, 3) for k, v in parts.items()})
    for lf, lc in [(19.5, 3.5), (21.5, 4.5), (23.5, 5.5)]:
        p, lam_f, cpf = j(lf, lc)
        pf, _ = eng.foul_model.total_prob(home, away, "faulturi", lf)
        pc = 0.0
        for k in range(0, 61):
            pc += poisson_pmf(k, lam_f) * (1 - bm.poisson_cdf(int(lc), k * cpf))
        indep = pf * pc
        print(f"  peste {lf} faulturi & peste {lc} cart.: P(comuna)={p*100:5.1f}%  "
              f"(independent ar fi {indep*100:5.1f}%)  cotă corectă={1/p:.2f}  "
              f"{'<< CORELATA +' + format((p-indep)*100,'.1f') + '%' if p > indep else ''}")


def calibration(league):
    """Validare: sezonul 25/26, model antrenat pe sezoanele anterioare."""
    df_all = bm.load_league(league, ["2324", "2425", "2526"])
    cutoff = df_all[df_all["Season"] == "2526"]["Date"].min()
    test = df_all[(df_all["Season"] == "2526")].dropna(subset=["HF", "HY"])
    train = df_all[df_all["Date"] < cutoff]
    eng = ComboEngine(league, ("2324", "2425"))
    rows = []
    has_ref = "Referee" in test.columns
    for _, m in test.iterrows():
        ref = m.get("Referee") if has_ref else None
        p = eng.joint_prob(m["HomeTeam"], m["AwayTeam"], 21.5, 4.5, ref)
        rows.append((p, m["HF"] + m["AF"] > 21.5 and m["HY"] + m["AY"] > 4.5))
    res = pd.DataFrame(rows, columns=["p", "hit"]).dropna()
    if len(res) < 50:
        return
    res["bin"] = pd.cut(res["p"], bins=[0, .15, .25, .35, .5, 1])
    g = res.groupby("bin", observed=True).agg(n=("hit", "size"), p_med=("p", "mean"), real=("hit", "mean"))
    print(f"\n=== CALIBRARE CONJUNCTA {league}: peste 21.5 faulturi & peste 4.5 cart. (sezon 25/26) ===")
    print(g.round(3).to_string())


if __name__ == "__main__":
    report("SP1", "Sevilla", "Osasuna")          # arbitru necunoscut inca
    calibration("SP1")
    calibration("F1")
