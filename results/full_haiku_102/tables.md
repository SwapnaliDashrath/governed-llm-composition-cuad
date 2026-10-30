# Results tables for Section 8

102 contracts, 1 run(s), model claude-haiku-5-5, tau 0.85, 639 high-risk gold clauses per run. Price $1.0/$5.0 per M tokens in/out.

## Table 9. Main results on CUAD

| Config | HRR | ER | EC | Clause F1 | Coverage per escalation | Median latency (s) | Cost per contract (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C0 Monolithic | 62.6% [57.9%, 67.7%] | 71.6% | 98.1% | 34.6% [32.0%, 37.3%] | 0.87 | 28.8 | 0.0783 |
| C1 Composed, ungoverned | 52.1% [47.8%, 56.8%] | 0.0% | 98.9% | 44.3% [41.6%, 47.1%] | n/a | 43.5 | 0.0975 |
| C2 Composed, confidence (tau = 0.85) | 62.8% [57.9%, 67.7%] | 51.9% | 98.9% | 44.3% [41.6%, 47.1%] | 1.21 | 43.5 | 0.0975 |
| C3 Composed, governed | 65.3% [60.5%, 70.1%] | 65.7% | 98.9% | 44.3% [41.6%, 47.1%] | 0.99 | 43.5 | 0.0975 |

Contracts sent whole to a human because extraction returned nothing usable: 0 of 102.

Share of contracts with at least one escalation: C2 97.1%, C3 97.1%.

## Table 10. C2 and C3 at matched escalation rate

| Policy | ER | HRR (reviewer perfect) | HRR (5% miss) | HRR (10% miss) | McNemar p vs C3 |
| --- | --- | --- | --- | --- | --- |
| C2 at C3's ER (tau = 0.885) | 61.4% | 63.8% | 62.1% | 60.4% | 0.0636 |
| C3 governed | 65.7% | 65.3% | 62.0% | 58.7% | n/a |

Discordant high-risk clauses: caught only by C3 = 14, caught only by C2 = 5.

## Table 11. Leave-one-out ablation (change from C3)

| Ablation | Delta HRR | Delta ER | Delta EC (auto-accepted) | Delta cost per contract | Service failures per 100 calls |
| --- | --- | --- | --- | --- | --- |
| A1 without S1 (extraction) | -9.1 pp | +10.5 pp | +0.0 pp | -0.0043 | 0.4 |
| A2 without S3 (risk scoring) | -0.2 pp | -1.8 pp | +0.0 pp | -0.0214 | 0.0 |
| A3 without evidence check | +0.0 pp | -0.2 pp | -0.6 pp | +0.0000 | 0.1 |
| A4 without E1 (mandatory set) | -1.9 pp | -7.3 pp | +0.0 pp | +0.0000 | 0.1 |

C3 reference: EC over all decisions 98.9%, EC over auto-accepted decisions 100.0%, service failures 0.1 per 100 calls, latency p95 199.3 s.

## Human-review coverage of high-risk clauses (requirement R1)

| Policy | ER | Extracted | Seen by a human | Auto-accepted, labeled right | Auto-accepted, mislabeled |
| --- | --- | --- | --- | --- | --- |
| C0 Monolithic (conf tau) | 71.6% | 66.8% | 33.5% | 29.1% | 4.2% |
| C2 Confidence (tau) | 51.9% | 66.2% | 28.6% | 34.1% | 3.4% |
| C2 at matched effort (tau 0.885) | 61.4% | 66.2% | 36.3% | 27.5% | 2.3% |
| C3 Governed policy | 65.7% | 66.2% | 65.3% | 0.0% | 0.9% |
| A4 Governed without E1 | 58.3% | 66.2% | 44.0% | 19.4% | 2.8% |

Sensitivity to the span-matching rule (share of high-risk gold clauses seen by a human):

| Matching rule | C0 Monolithic (conf tau) | C2 Confidence (tau) | C2 at matched effort (tau 0.885) | C3 Governed policy | A4 Governed without E1 |
| --- | --- | --- | --- | --- | --- |
| Jaccard >= 0.5 (paper rule) | 33.5% | 28.6% | 36.3% | 65.3% | 44.0% |
| Jaccard >= 0.3 | 49.6% | 39.3% | 46.5% | 74.2% | 54.9% |
| Covers >= 50% of gold words | 47.9% | 46.6% | 54.5% | 79.0% | 62.9% |

## Per-category HRR (Section 7.4)

| Category | Gold per run | C0 | C2 at matched ER | C3 |
| --- | --- | --- | --- | --- |
| Uncapped Liability | 16 | 50.0% | 31.2% | 56.2% |
| Cap On Liability | 118 | 60.2% | 38.1% | 38.1% |
| Liquidated Damages | 23 | 52.2% | 56.5% | 60.9% |
| Termination For Convenience | 41 | 82.9% | 87.8% | 87.8% |
| Change Of Control | 62 | 56.5% | 62.9% | 69.4% |
| Anti-Assignment | 137 | 71.5% | 73.7% | 75.2% |
| Covenant Not To Sue | 44 | 45.5% | 18.2% | 18.2% |
| Ip Ownership Assignment | 61 | 55.7% | 65.6% | 65.6% |
| Non-Compete | 59 | 72.9% | 88.1% | 88.1% |
| Exclusivity | 78 | 57.7% | 88.5% | 85.9% |

## Audit-trail example for Section 6.5

Contract: CENTRACKINTERNATIONALINC_10_29_1999-EX-10.3-WEB SITE HOSTING AGREEMENT  
Clause: "Either party may terminate this Agreement without cause at any time effective upon thirty (30) days' written notice."  
Span offsets: 10880 to 10996 (evidence check: pass)  
S2 category: Termination For Convenience, confidence 0.95  
S3 risk: high. Rationale: Rule requires 90 days' notice, but clause allows "either party" to terminate on "thirty (30) days' written notice."  
Policy P: rule E1 fired, routed to human.  
Under confidence routing at tau = 0.85, this clause would have been auto-accepted, because confidence 0.95 >= 0.85.

Fig. 2 written to hrr_vs_er.png. Full audit logs: decisions_C0.jsonl, decisions_C3.jsonl, decisions_A1.jsonl.