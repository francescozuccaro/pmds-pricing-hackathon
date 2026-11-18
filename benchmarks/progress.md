# zuccaro-agent tuning log

Screening: 3 seeds x 120 turns. Full test: 10 seeds (100-109) x 240 turns.
ext = default_extended approximation (benchmarks/configs/default_extended.yaml), 40-team roster.
Since 2026-11-18 the primary metric is **mean rank across horizons** (40/80/120/240 turns),
because the official ranking averages positions over default (40 turns) and extended (80/240).

| Ciclo | Variante | ext240 media | min | rank medio | default240 media | Δ vs migliore | Tenuta |
|---|---|---|---|---|---|---|---|
| 0 | v1 (baseline) | 37,325 | — | 7.90 | 93,596 | — | — |
| 0 | v9 (champion) | 55,489 | 53,675 | 1.00 | 135,492 | +49% vs v1 | sì |
| 1 | some100 (screen) | 50,488 (120t) | 47,584 | 1.00 | 103,182 (120t) | +1.9% | no (highdemand -29%) |
| 1 | qema6 (screen) | 50,848 (120t) | 49,903 | 1.00 | 96,981 (120t) | +2.6% | candidata |
| 2 | qema9 (screen) | 50,005 (120t) | 48,980 | 1.00 | 89,865 (120t) | -1.7% | no |
| 2 | q6mm11 (screen) | 51,145 (120t) | 50,664 | 1.00 | 95,404 (120t) | +0.6% | no |
| 3 | ip10 (screen) | 50,566 (120t) | 49,955 | 1.00 | 89,709 (120t) | -0.6% | no (hd_strong rank 1.33) |
| 3 | iq8 (screen) | 48,272 (120t) | 44,342 | 1.00 | 91,565 (120t) | -5.1% | no |
| 4 | repl (full) | 55,271 | 51,465 | 1.00 | 140,074 | -0.4% | no (tut_auction rank 5.3) |
| 4 | repl_mm11 (full) | 55,475 | 52,486 | 1.00 | 134,176 | -0.0% | no (tut_auction 99k->61k) |
| 5 | qema6 (full) | 55,369 | 53,216 | 1.00 | 140,450 | -0.2% ext / +3.7% default | sì (capacity_cap rank 2.2->1.2) |

## Dal ciclo 6: metrica = rank medio su arene (copie del campione) x durate 40/80/120
Screening 3 seed; "rank" = rank medio complessivo (più basso = meglio). Campione v10 = 6.89.

| Ciclo | Variante | rank medio | ext_arena@40 | hd_arena@40 | Δ vs migliore | Tenuta |
|---|---|---|---|---|---|---|
| 6 | iq2 | 8.41 | 11.0 | 17.7 | +1.52 | no |
| 6 | bi13 (prima offerta x1.3) | 5.37 | 4.3 | 14.7 | -1.52 | parziale (default_arena peggio) |
| 7 | crowd13 (x1.3 solo con >12 team) | 5.07 | 4.3 | 14.7 | -1.82 | sì |
| 8 | capadd4 | 5.11 | 4.3 | 14.7 | +0.04 | no |
| 8 | guard | 5.30 | 3.7 | 14.7 | +0.23 | no |
| 9 | hot10 (tetto x5 se >=10% rivali guadagna) | 2.63 | 4.3 | 2.0 | -2.44 | sì |
| 9 | hot25 | 3.44 | 4.3 | 6.3 | -1.63 | no |
| 10 | hot05 | 2.22 | 4.3 | 1.0 | -0.41 | sì |
| 10 | hot10m7 (tetto x7) | 3.56 | 5.0 | 2.0 | +0.93 | no |
| 11 | hot02 | 2.41 | 5.3 | 1.0 | +0.19 | no |
| 11 | hot05 senza crowd | 4.00 | 11.0 | 1.33 | +1.78 | no |
| 12 | full hot05 (10 seed, 40/80/240, 14 scenari) | 1.99 | 4.0 | 1.1 | — | sì, ma tut_auction@240 rank 3.6 |
| 12 | full hot02 | 2.09 | 6.0 | 1.0 | +0.10 | no |
| 13 | hotfix (caldo solo >12 team, materiali <= prezzo minimo) | — | — | — | tut_auction@240 rank 3.6 -> 1.0 | sì (v11) |

v11 full (hot05): extended@240 53,978 (min 51,124, rank 1.0); default@240 140,868; extended@40/80 = 46,309 / 48,909.
| 14 | gf40 (GOOD_F 0.4) full 10 seed 40/80/120/240 | rank 1.89 vs v11 1.71 | monopolio@80 389k vs 332k | tut_auction rank 4.0 | +0.18 | no |
| 14 | gf30 full | rank 2.11 | monopolio@80 405k | tut_auction rank 4.0 | +0.40 | no |
| 15 | some985 / some99p8 (discesa prezzo più lenta) | 1.65 / 1.60 vs 1.60 | monopolio@240 +55-62% | tut_pricing/highdemand peggio | ~0 | no |
| — | cornering DENY_SHARE 0.5/0.9 (ext_real2) | — | capitale 38k/32k a 80 turni | drawdown 27-52% | — | no |

Campione finale: v11 (commit 3fecc1f). Full suite 10 seed x 40/80/120/240, 14 scenari: rank medio 1.71.
v11 a 80 turni: ext_monopoly 332k, ext_highprice 154k, extended 48.9k, default 77k.
| 16 | el4 / el3g11 (test di elasticità) | 1.61 / 1.60 vs 1.60 | monopolio@80 +14% | highdemand -9%, hd_arena -11% | ~0 | no |
| 17 | ps40p20 (40% stock a 2x) | 1.50 | ext_arena@240 rank 5.7 -> 1.7 | tut_auction rank 2 (97k -> 35k) | -0.10 | no |
| 18 | tier40 (fascia premium in aggiunta + moltiplicatore appreso) | **1.39** | ext_arena@80 rank 1.7 | tut_pricing@240 rank 2.0 | -0.21 | promettente, manca test completo |
| 19 | cs05 (tetto spesa 5% in mercati affollati) | 2.46 vs 1.71 | default_crowd@40 rank 3 -> 6 | — | +0.75 | no |

Opzioni nel codice, tutte spente nel campione v11: ELAST_W, PROBE_SHARE/PM_ADAPT, CROWD_SPEND.
Prossimo passo: test completo di tier40 (PROBE_SHARE=0.4, PROBE=2.0, PM_ADAPT=True).
