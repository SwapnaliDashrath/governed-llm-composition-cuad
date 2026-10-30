# Governed Composition of LLM Agent Services: CUAD Harness

This repository holds the code and results for the paper:

> S. Dashrath, "Governed Composition of LLM Agent Services in Regulated Workflows: A Service-Oriented Case Study in Contract Intelligence." Submitted to *IEEE Transactions on Services Computing*, Special Issue on Large Language Models in Service-Oriented Ecosystems Design, 2026.

The paper asks a simple question. When several LLM services work together on contract review, which risky clauses actually reach a human? It compares a governed escalation policy with plain confidence routing on the public CUAD benchmark.

## What is here

| Path | What it is |
| --- | --- |
| `cuad_harness.py` | The full experiment in one file: the four services, the policy gate, all configurations (C0 to C3) and ablations (A1 to A4), metrics, statistics, and the tables in the paper |
| `results/full_haiku_102/` | Main run: Claude Haiku 5.5, all 102 CUAD test contracts (Tables 9 to 11, Fig. 2) |
| `results/haiku_40/` | Haiku on the first 40 test contracts, for the cross-model check |
| `results/sonnet_40/` | Claude Sonnet 5.5 on the same 40 contracts (Section 8.6) |
| `results/*/decisions_*.jsonl` | Audit logs: one line per decision, with the quoted span, category, confidence, risk, the rule that fired, and the outcome |
| `data/` | Empty. Put the CUAD file here (see below) |

## Quick start

Python 3.10 or later.

**1. Free test with no data or API key.** This uses a mock model and synthetic contracts:

```
python cuad_harness.py --provider mock --limit 5
```

**2. Get CUAD.** Download CUAD v1 from the [Atticus Project](https://www.atticusprojectai.org/cuad) or [its GitHub repository](https://github.com/TheAtticusProject/cuad). Unzip `data.zip` and copy `test.json` into `data/`.

**3. Install packages for real runs:**

```
pip install -r requirements.txt
```

**4. Set your API key** (never put it in a file):

```
set ANTHROPIC_API_KEY=your-key        (Windows)
export ANTHROPIC_API_KEY=your-key     (macOS or Linux)
```

## Reproduce the paper

| Result | Command |
| --- | --- |
| Main results, 102 contracts (Haiku) | `python cuad_harness.py --provider anthropic --data data/test.json --out results_full --max-usd 5` |
| Cross-model check, Sonnet | `python cuad_harness.py --provider anthropic --data data/test.json --limit 40 --sonnet-check --max-usd 5` |
| Cross-model check, Haiku on the same 40 | `python cuad_harness.py --provider anthropic --data data/test.json --limit 40 --pipelines composed --out results_subset40` |

Useful options:

- `--audit` estimates cost before a run and spends nothing.
- `--max-usd N` stops the run before it spends more than N US dollars.
- Replies are cached on disk, so an interrupted run restarts where it stopped and never pays twice.

At list prices of $0.10 and $0.50 per million input and output tokens, the composed Haiku pipeline costs about one US cent per contract. All runs use temperature 0 and one run per configuration.

## Main findings

- At matched human effort, the governed policy puts 65.3% of high-risk clauses in front of a human. Confidence routing puts about 40% there.
- The policy also protects high-risk categories it does not name. In 252 held-out splits it won every time (45.7% against 36.7%).
- A larger model (Sonnet 5.5) extracts better (clause F1 49.9% against 42.8%) but does not close the coverage gap (69.5% against 35.0%).

See the paper for the full method, statistics, and limitations.

## Data and licenses

- Code: MIT License (see `LICENSE`).
- CUAD is by The Atticus Project and is released under CC BY 4.0. The audit logs in `results/` quote short clause spans from CUAD contracts, with the CUAD contract ID on each line.
- Results come from Anthropic's Claude models through the public API.
- No data from the production deployment described in the paper is included.

## Citation

Use GitHub's "Cite this repository" button, or see `CITATION.cff`.

## Contact

Swapnali Dashrath, ORCID [0009-0006-0366-1578](https://orcid.org/0009-0006-0366-1578)
