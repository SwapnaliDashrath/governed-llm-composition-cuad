# Results tables for Section 8

40 contracts, 1 run(s), model claude-sonnet-5-5, tau 0.85, 220 high-risk gold clauses per run. Price $3.0/$15.0 per M tokens in/out.

## Table 9. Main results on CUAD

| Config | HRR | ER | EC | Clause F1 | Coverage per escalation | Median latency (s) | Cost per contract (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C0 Monolithic | not run | | | | | | |
| C1 Composed, ungoverned | 54.5% [47.8%, 62.9%] | 0.0% | 100.0% | 49.9% [46.0%, 54.0%] | n/a | 35.2 | 0.1762 |
| C2 Composed, confidence (tau = 0.85) | 65.9% [59.8%, 73.9%] | 42.7% | 100.0% | 49.9% [46.0%, 54.0%] | 1.54 | 35.2 | 0.1762 |
| C3 Composed, governed | 69.5% [63.9%, 76.2%] | 58.8% | 100.0% | 49.9% [46.0%, 54.0%] | 1.18 | 35.2 | 0.1762 |

Contracts sent whole to a human because extraction returned nothing usable: 0 of 40.

Share of contracts with at least one escalation: C2 97.5%, C3 97.5%.

## Table 10. C2 and C3 at matched escalation rate

| Policy | ER | HRR (reviewer perfect) | HRR (5% miss) | HRR (10% miss) | McNemar p vs C3 |
| --- | --- | --- | --- | --- | --- |
| C2 at C3's ER (tau = 0.885) | 52.8% | 67.7% | 66.0% | 64.3% | 0.2188 |
| C3 governed | 58.8% | 69.5% | 66.1% | 62.6% | n/a |

Discordant high-risk clauses: caught only by C3 = 5, caught only by C2 = 1.

## Table 11. Leave-one-out ablation (change from C3)

| Ablation | Delta HRR | Delta ER | Delta EC (auto-accepted) | Delta cost per contract | Service failures per 100 calls |
| --- | --- | --- | --- | --- | --- |
| A1 without S1 (extraction) | not run | | | | |
| A2 without S3 (risk scoring) | -0.5 pp | -1.4 pp | +0.0 pp | -0.0376 | 0.0 |
| A3 without evidence check | +0.0 pp | +0.0 pp | +0.0 pp | +0.0000 | 0.0 |
| A4 without E1 (mandatory set) | -1.8 pp | -7.6 pp | +0.0 pp | +0.0000 | 0.0 |

C3 reference: EC over all decisions 100.0%, EC over auto-accepted decisions 100.0%, service failures 0.0 per 100 calls, latency p95 187.7 s.

## Human-review coverage of high-risk clauses (requirement R1)

| Policy | ER | Extracted | Seen by a human | Auto-accepted, labeled right | Auto-accepted, mislabeled |
| --- | --- | --- | --- | --- | --- |
| C2 Confidence (tau) | 42.7% | 71.8% | 25.0% | 40.9% | 5.9% |
| C2 at matched effort (tau 0.885) | 52.8% | 71.8% | 35.0% | 32.7% | 4.1% |
| C3 Governed policy | 58.8% | 71.8% | 69.5% | 0.0% | 2.3% |
| A4 Governed without E1 | 51.3% | 71.8% | 46.4% | 21.4% | 4.1% |

Sensitivity to the span-matching rule (share of high-risk gold clauses seen by a human):

| Matching rule | C2 Confidence (tau) | C2 at matched effort (tau 0.885) | C3 Governed policy | A4 Governed without E1 |
| --- | --- | --- | --- | --- |
| Jaccard >= 0.5 (paper rule) | 25.0% | 35.0% | 69.5% | 46.4% |
| Jaccard >= 0.3 | 35.5% | 45.9% | 77.7% | 58.2% |
| Covers >= 50% of gold words | 42.7% | 53.6% | 81.8% | 62.7% |

## Per-category HRR (Section 7.4)

| Category | Gold per run | C0 | C2 at matched ER | C3 |
| --- | --- | --- | --- | --- |
| Uncapped Liability | 8 | n/a | 62.5% | 87.5% |
| Cap On Liability | 43 | n/a | 51.2% | 51.2% |
| Liquidated Damages | 6 | n/a | 50.0% | 50.0% |
| Termination For Convenience | 11 | n/a | 81.8% | 81.8% |
| Change Of Control | 20 | n/a | 60.0% | 75.0% |
| Anti-Assignment | 41 | n/a | 80.5% | 80.5% |
| Covenant Not To Sue | 16 | n/a | 43.8% | 43.8% |
| Ip Ownership Assignment | 17 | n/a | 58.8% | 58.8% |
| Non-Compete | 18 | n/a | 88.9% | 88.9% |
| Exclusivity | 40 | n/a | 80.0% | 77.5% |

## Audit-trail example for Section 6.5

Contract: CENTRACKINTERNATIONALINC_10_29_1999-EX-10.3-WEB SITE HOSTING AGREEMENT  
Clause: "Either party may terminate this Agreement without cause at any time effective upon thirty (30) days' written notice."  
Span offsets: 10880 to 10996 (evidence check: pass)  
S2 category: Termination For Convenience, confidence 0.96  
S3 risk: high. Rationale: Rule: counterparty not terminate on less than 90 days. "thirty (30) days' written notice" falls well short.  
Policy P: rule E1 fired, routed to human.  
Under confidence routing at tau = 0.85, this clause would have been auto-accepted, because confidence 0.96 >= 0.85.

Fig. 2 written to hrr_vs_er.png. Full audit logs: decisions_C0.jsonl, decisions_C3.jsonl, decisions_A1.jsonl.