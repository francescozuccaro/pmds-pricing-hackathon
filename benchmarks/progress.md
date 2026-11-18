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
