#!/usr/bin/env python3
"""
Football Value Betting Model - VERSIUNE COMPLETĂ AUTOMATĂ
=========================================================
Descarcă automat date istorice de pe football-data.co.uk
Analizează value pe goluri, cartonașe, fouls, șuturi pe poartă
Compară cu cotele pe care le pui de pe Superbet

Utilizare:
python3 football_value_betting_model.py
"""

import numpy as np
import pandas as pd
from scipy.stats import poisson
from typing import Dict, List, Optional
from datetime import datetime
import soccerdata as sd
import warnings
warnings.filterwarnings("ignore")


# =============================================================================
# 1. DESCĂRCARE AUTOMATĂ DATE ISTORICE
# =============================================================================

def download_historical_data(
    leagues: List[str] = None,
    seasons: List[int] = None
) -> pd.DataFrame:
    """
    Descarcă date reale de pe football-data.co.uk prin soccerdata.
    Ligi implicite: top 5 europene (au statistici complete: shots, fouls, cards).
    """
    if leagues is None:
        leagues = [
            "ENG-Premier League",
            "ESP-La Liga",
            "ITA-Serie A",
            "GER-Bundesliga",
            "FRA-Ligue 1",
        ]
    if seasons is None:
        seasons = [2022, 2023, 2024, 2025]

    print(f"Descarc date pentru: {leagues}")
    print(f"Sezoane: {seasons}")

    mh = sd.MatchHistory(leagues=leagues, seasons=seasons)
    df = mh.read_games()

    # Redenumim coloanele în formatul folosit de model
    rename_map = {
        "FTHG": "home_goals",
        "FTAG": "away_goals",
        "HY": "home_cards",
        "AY": "away_cards",
        "HF": "home_fouls",
        "AF": "away_fouls",
        "HST": "home_shots_on_target",
        "AST": "away_shots_on_target",
        "Referee": "referee",
        "HomeTeam": "home_team",
        "AwayTeam": "away_team",
        "Date": "date",
    }
    # soccerdata poate returna deja nume diferite; verificăm
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Asigurăm tipurile
    for col in ["home_goals", "away_goals", "home_cards", "away_cards",
                "home_fouls", "away_fouls", "home_shots_on_target", "away_shots_on_target"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["home_team", "away_team", "date"])

    print(f"Date descărcate cu succes: {len(df)} meciuri\n")
    return df


# =============================================================================
# 2. FUNCȚII MODEL (aceleași ca înainte)
# =============================================================================

def poisson_over_prob(lam: float, line: float) -> float:
    if line < 0:
        return 1.0
    k = int(np.floor(line))
    return 1.0 - poisson.cdf(k, lam)


def poisson_under_prob(lam: float, line: float) -> float:
    return 1.0 - poisson_over_prob(lam, line)


def calculate_team_strengths(
    df: pd.DataFrame,
    market: str = "goals",
    days_weight: int = 365,
) -> tuple:
    col_home = f"home_{market}"
    col_away = f"away_{market}"

    if col_home not in df.columns:
        raise ValueError(f"Lipsește coloana {col_home}")

    df = df.copy()
    max_date = df["date"].max()
    df["weight"] = np.exp(-(max_date - df["date"]).dt.days / days_weight)

    league_avg = (df[col_home].mean() + df[col_away].mean()) / 2

    strengths = {}
    for team in set(df["home_team"]).union(set(df["away_team"])):
        home_games = df[df["home_team"] == team]
        away_games = df[df["away_team"] == team]

        att_home = (home_games[col_home] * home_games["weight"]).sum() / max(home_games["weight"].sum(), 1)
        att_away = (away_games[col_away] * away_games["weight"]).sum() / max(away_games["weight"].sum(), 1)
        def_home = (home_games[col_away] * home_games["weight"]).sum() / max(home_games["weight"].sum(), 1)
        def_away = (away_games[col_home] * away_games["weight"]).sum() / max(away_games["weight"].sum(), 1)

        strengths[team] = {
            "attack_home": att_home / league_avg if league_avg else 1,
            "attack_away": att_away / league_avg if league_avg else 1,
            "defense_home": def_home / league_avg if league_avg else 1,
            "defense_away": def_away / league_avg if league_avg else 1,
        }

    return strengths, league_avg


def get_referee_factor(df: pd.DataFrame, referee: str, market: str = "cards") -> float:
    if "referee" not in df.columns or pd.isna(referee):
        return 1.0
    col_home = f"home_{market}"
    col_away = f"away_{market}"
    ref_df = df[df["referee"] == referee]
    if len(ref_df) < 5:
        return 1.0
    ref_avg = (ref_df[col_home].mean() + ref_df[col_away].mean()) / 2
    league_avg = (df[col_home].mean() + df[col_away].mean()) / 2
    return ref_avg / league_avg if league_avg > 0 else 1.0


def predict_match(home_team, away_team, strengths, league_avg, home_adv, ref_factor, market):
    h = strengths.get(home_team, {})
    a = strengths.get(away_team, {})

    lambda_home = (
        h.get("attack_home", 1.0)
        * a.get("defense_away", 1.0)
        * league_avg
        * (1 + home_adv if market == "goals" else 1.0)
        * ref_factor
    )
    lambda_away = (
        a.get("attack_away", 1.0)
        * h.get("defense_home", 1.0)
        * league_avg
        * ref_factor
    )
    return {
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "lambda_total": lambda_home + lambda_away,
    }


def calculate_ev(prob_model: float, odds: float) -> float:
    if odds <= 1.0 or prob_model <= 0:
        return -1.0
    return (prob_model * odds) - 1.0


def analyze_market(lambda_total, line, odds_over, odds_under, min_ev=0.05):
    results = []
    p_over = poisson_over_prob(lambda_total, line)
    p_under = poisson_under_prob(lambda_total, line)

    if odds_over and odds_over > 1.0:
        ev = calculate_ev(p_over, odds_over)
        if ev >= min_ev:
            results.append({
                "selection": f"Over {line}",
                "prob_model": round(p_over, 4),
                "odds": odds_over,
                "ev": round(ev, 4),
                "implied_prob": round(1 / odds_over, 4),
            })
    if odds_under and odds_under > 1.0:
        ev = calculate_ev(p_under, odds_under)
        if ev >= min_ev:
            results.append({
                "selection": f"Under {line}",
                "prob_model": round(p_under, 4),
                "odds": odds_under,
                "ev": round(ev, 4),
                "implied_prob": round(1 / odds_under, 4),
            })
    return results


def analyze_fixture(
    home_team: str,
    away_team: str,
    referee: str,
    historical_df: pd.DataFrame,
    superbet_odds: Dict,
    min_ev: float = 0.04,
) -> Dict:
    results = {
        "match": f"{home_team} vs {away_team}",
        "referee": referee,
        "recommendations": [],
    }

    markets_config = {
        "goals": 0.22,
        "cards": 0.03,
        "fouls": 0.06,
        "shots_on_target": 0.08,
    }

    for market, home_adv in markets_config.items():
        if market not in superbet_odds:
            continue

        strengths, league_avg = calculate_team_strengths(historical_df, market)
        ref_factor = get_referee_factor(historical_df, referee, market)
        pred = predict_match(home_team, away_team, strengths, league_avg, home_adv, ref_factor, market)

        odds_dict = superbet_odds[market]
        for key, odd in odds_dict.items():
            if key.startswith("over_"):
                try:
                    line = float(key.split("_")[1])
                except:
                    continue
                under_key = f"under_{line}"
                bets = analyze_market(pred["lambda_total"], line, odd, odds_dict.get(under_key), min_ev)
                for b in bets:
                    b["market"] = market
                    b["lambda"] = round(pred["lambda_total"], 2)
                    results["recommendations"].append(b)

    results["recommendations"].sort(key=lambda x: x["ev"], reverse=True)
    return results


# =============================================================================
# 3. RULARE PRINCIPALĂ
# =============================================================================

if __name__ == "__main__":
    print("=== Football Value Betting Model (Automat) ===\n")

    # 1. Descarcă date reale
    df = download_historical_data()

    # 2. Exemplu: pune aici cotele pe care le vezi pe Superbet
    # (poți copia din aplicație / site)
    superbet_odds_example = {
        "goals": {
            "over_2.5": 1.85,
            "under_2.5": 1.95,
        },
        "cards": {
            "over_3.5": 1.80,
            "under_3.5": 2.00,
            "over_4.5": 2.40,
            "under_4.5": 1.55,
        },
        "fouls": {
            "over_20.5": 1.85,
            "under_20.5": 1.95,
        },
        "shots_on_target": {
            "over_4.5": 1.75,
            "under_4.5": 2.05,
        },
    }

    # 3. Analizează un meci (schimbă echipele și arbitrul cu cele reale)
    analysis = analyze_fixture(
        home_team="Arsenal",
        away_team="Chelsea",
        referee="M. Oliver",          # pune numele exact din date sau lasă gol
        historical_df=df,
        superbet_odds=superbet_odds_example,
        min_ev=0.03,
    )

    print(f"Meci analizat: {analysis['match']}")
    print(f"Arbitru: {analysis['referee']}\n")

    if analysis["recommendations"]:
        print(">>> VALUE BETS găsite <<<")
        for rec in analysis["recommendations"]:
            print(
                f"  [{rec['market'].upper()}] {rec['selection']} "
                f"@ {rec['odds']}  |  Prob model: {rec['prob_model']*100:.1f}%  |  "
                f"EV: +{rec['ev']*100:.1f}%  |  λ={rec['lambda']}"
            )
    else:
        print("Nicio valoare peste pragul setat.")

    print("\n" + "="*50)
    print("Cum folosești:")
    print("1. Rulezi scriptul (descarcă datele singur).")
    print("2. Te uiți pe Superbet la meciul dorit.")
    print("3. Copiezi cotele în dicționarul superbet_odds_example.")
    print("4. Schimbi home_team, away_team, referee.")
    print("5. Rulezi din nou și vezi doar piețele cu EV pozitiv.")
    print("Pariază maxim 1-2% din bankroll pe un pariu.")
