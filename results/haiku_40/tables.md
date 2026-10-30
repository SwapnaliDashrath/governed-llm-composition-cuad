# Results tables for Section 8

40 contracts, 1 run(s), model claude-haiku-5-5, tau 0.85, 220 high-risk gold clauses per run. Price $0.1/$0.5 per M tokens in/out.

## Table 9. Main results on CUAD

| Config | HRR | ER | EC | Clause F1 | Coverage per escalation | Median latency (s) | Cost per contract (USD) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C0 Monolithic | not run | | | | | | |
| C1 Composed, ungoverned | 50.5% [43.3%, 57.9%] | 0.0% | 99.2% | 42.8% [39.2%, 46.8%] | n/a | 41.2 | 0.0096 |
| C2 Composed, confidence (tau = 0.85) | 64.5% [57.0%, 71.4%] | 53.3% | 99.2% | 42.8% [39.2%, 46.8%] | 1.21 | 41.2 | 0.0096 |
| C3 Composed, governed | 66.4% [57.7%, 73.9%] | 65.8% | 99.2% | 42.8% [39.2%, 46.8%] | 1.01 | 41.2 | 0.0096 |

Contracts sent whole to a human because extraction returned nothing usable: 0 of 40.

Share of contracts with at least one escalation: C2 97.5%, C3 97.5%.

## Table 10. C2 and C3 at matched escalation rate

| Policy | ER | HRR (reviewer perfect) | HRR (5% miss) | HRR (10% miss) | McNemar p vs C3 |
| --- | --- | --- | --- | --- | --- |
| C2 at C3's ER (tau = 0.885) | 62.6% | 65.5% | 63.7% | 62.0% | 0.6250 |
| C3 governed | 65.8% | 66.4% | 63.0% | 59.7% | n/a |

Discordant high-risk clauses: caught only by C3 = 3, caught only by C2 = 1.

## Table 11. Leave-one-out ablation (change from C3)

| Ablation | Delta HRR | Delta ER | Delta EC (auto-accepted) | Delta cost per contract | Service failures per 100 calls |
| --- | --- | --- | --- | --- | --- |
| A1 without S1 (extraction) | not run | | | | |
| A2 without S3 (risk scoring) | +0.0 pp | -1.4 pp | +0.0 pp | -0.0021 | 0.0 |
| A3 without evidence check | +0.0 pp | -0.1 pp | -0.3 pp | +0.0000 | 0.0 |
| A4 without E1 (mandatory set) | -0.5 pp | -6.5 pp | +0.0 pp | +0.0000 | 0.0 |

C3 reference: EC over all decisions 99.2%, EC over auto-accepted decisions 100.0%, service failures 0.0 per 100 calls, latency p95 199.3 s.

## Human-review coverage of high-risk clauses (requirement R1)

| Policy | ER | Extracted | Seen by a human | Auto-accepted, labeled right | Auto-accepted, mislabeled |
| --- | --- | --- | --- | --- | --- |
| C2 Confidence (tau) | 53.3% | 67.3% | 29.1% | 35.5% | 2.7% |
| C2 at matched effort (tau 0.885) | 62.6% | 67.3% | 35.0% | 30.5% | 1.8% |
| C3 Governed policy | 65.8% | 67.3% | 66.4% | 0.0% | 0.9% |
| A4 Governed without E1 | 59.4% | 67.3% | 46.8% | 19.1% | 1.4% |

Sensitivity to the span-matching rule (share of high-risk gold clauses seen by a human):

| Matching rule | C2 Confidence (tau) | C2 at matched effort (tau 0.885) | C3 Governed policy | A4 Governed without E1 |
| --- | --- | --- | --- | --- |
| Jaccard >= 0.5 (paper rule) | 29.1% | 35.0% | 66.4% | 46.8% |
| Jaccard >= 0.3 | 42.7% | 47.3% | 74.5% | 59.1% |
| Covers >= 50% of gold words | 48.6% | 54.1% | 77.3% | 64.5% |

## Per-category HRR (Section 7.4)

| Category | Gold per run | C0 | C2 at matched ER | C3 |
| --- | --- | --- | --- | --- |
| Uncapped Liability | 8 | n/a | 25.0% | 50.0% |
| Cap On Liability | 43 | n/a | 37.2% | 37.2% |
| Liquidated Damages | 6 | n/a | 83.3% | 83.3% |
| Termination For Convenience | 11 | n/a | 81.8% | 81.8% |
| Change Of Control | 20 | n/a | 60.0% | 60.0% |
| Anti-Assignment | 41 | n/a | 78.0% | 80.5% |
| Covenant Not To Sue | 16 | n/a | 25.0% | 25.0% |
| Ip Ownership Assignment | 17 | n/a | 76.5% | 76.5% |
| Non-Compete | 18 | n/a | 88.9% | 88.9% |
| Exclusivity | 40 | n/a | 87.5% | 85.0% |

## Audit-trail example for Section 6.5

Contract: CENTRACKINTERNATIONALINC_10_29_1999-EX-10.3-WEB SITE HOSTING AGREEMENT  
Clause: "Either party may terminate this Agreement without cause at any time effective upon thirty (30) days' written notice."  
Span offsets: 10880 to 10996 (evidence check: pass)  
S2 category: Termination For Convenience, confidence 0.95  
S3 risk: high. Rationale: Rule requires 90 days' notice, but clause allows "either party" to terminate on "thirty (30) days' written notice."  
Policy P: rule E1 fired, routed to human.  
Under confidence routing at tau = 0.85, this clause would have been auto-accepted, because confidence 0.95 >= 0.85.

Fig. 2 written to hrr_vs_er.png. Full audit logs: decisions_C0.jsonl, decisions_C3.jsonl, decisions_A1.jsonl.