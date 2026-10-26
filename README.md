# Pariuri Value — site zilnic cu top 10 meciuri

Site static generat zilnic: probabilitati statistice (faulturi, cornere, cartonase, goluri),
cote corecte, sugestii pe fiecare meci si calculator de value (introduci cota Superbet, vezi instant EV).

Date: football-data.co.uk (istoric ~4 sezoane pe 19 campionate europene).
Model: Poisson cu ponderi de recenta + model conjunct faulturi–cartonase (corelatie + severitate arbitru).

## Cum il pui online (3 minute, gratuit)

1. Creeaza un cont pe https://github.com (gratuit)
2. Fa un repository **public** nou, numit `pariuri-value` (fara README, gol)
3. Incarca TOATE fisierele din acest folder in repo (butonul "uploading an existing file" sau Add file → Upload files; mentine structura: `site/index.html` in folderul `site`, `.github/workflows/daily.yml` in `.github/workflows`)
4. Settings → Pages → Source: **Deploy from a branch** → Branch: `main` → folder `/ (root)` → Save
5. Linkul tau apare in 1-2 minute: `https://<numele-tau>.github.io/pariuri-value/`

## Actualizare automata

GitHub Actions ruleaza `gen_site.py` zilnic la 07:23 UTC (10:23 ora Romaniei in iarna),
descarca datele proaspete si republica site-ul. Poti porni manual din tab-ul Actions → analiza-zilnica → Run workflow.

## Folosire

Pe fiecare meci: sectiunea „Sugestii model" iti arata ce merita jucat si **cota minima** de la Superbet.
Scrie cota reala in casuta → verdict instant: verde = value, rosu = evita.
