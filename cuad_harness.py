#!/usr/bin/env python3
"""
cuad_harness.py

CUAD evaluation harness for the TSC paper:
"Governed Composition of LLM Agent Services in Regulated Workflows:
 A Service-Oriented Case Study in Contract Intelligence"

It runs the configurations and ablations of Table 7 (C0, C1, C2, C3, A1 to A4),
computes the metrics of Section 7.4 (HRR, ER, EC, clause F1, coverage per
escalation, latency, cost, service failure rate), the statistics of Section 7.7
(paired bootstrap CIs, McNemar test at matched escalation rate), and writes
filled tables for Section 8 plus a real audit-trail example for Section 6.5.

QUICK START
  1) Mock test, free, no data or API key needed:
       python cuad_harness.py --provider mock --limit 5
  2) Pilot on real CUAD (50 contracts):
       python cuad_harness.py --provider anthropic --data data/test.json --limit 50 --max-usd 12
  3) Full run, all 102 test contracts (the first 50 come from the cache):
       python cuad_harness.py --provider anthropic --data data/test.json --max-usd 25

The default model is claude-haiku-5-5 ($0.10 / $0.50 per million tokens, prompts up to 100K). Check --price-in / --price-out against current pricing.

Mock runs need only the Python standard library.
Real runs need:   pip install anthropic     (or: pip install openai)
The figure needs: pip install matplotlib

API responses are cached on disk, so an interrupted run can be restarted
with the same command and will not pay twice for finished calls.
"""

import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

CUAD_CATEGORIES = [
    "Document Name", "Parties", "Agreement Date", "Effective Date", "Expiration Date",
    "Renewal Term", "Notice Period To Terminate Renewal", "Governing Law",
    "Most Favored Nation", "Non-Compete", "Exclusivity", "No-Solicit Of Customers",
    "Competitive Restriction Exception", "No-Solicit Of Employees", "Non-Disparagement",
    "Termination For Convenience", "Rofr/Rofo/Rofn", "Change Of Control",
    "Anti-Assignment", "Revenue/Profit Sharing", "Price Restrictions",
    "Minimum Commitment", "Volume Restriction", "Ip Ownership Assignment",
    "Joint Ip Ownership", "License Grant", "Non-Transferable License",
    "Affiliate License-Licensor", "Affiliate License-Licensee",
    "Unlimited/All-You-Can-Eat-License", "Irrevocable Or Perpetual License",
    "Source Code Escrow", "Post-Termination Services", "Audit Rights",
    "Uncapped Liability", "Cap On Liability", "Liquidated Damages",
    "Warranty Duration", "Insurance", "Covenant Not To Sue", "Third Party Beneficiary",
]
assert len(CUAD_CATEGORIES) == 41

# Table 6: high-risk CUAD categories, used as the mandatory set M and as G*.
HIGH_RISK = [
    "Uncapped Liability", "Cap On Liability", "Liquidated Damages",
    "Termination For Convenience", "Change Of Control", "Anti-Assignment",
    "Covenant Not To Sue", "Ip Ownership Assignment", "Non-Compete", "Exclusivity",
]
M = set(HIGH_RISK)

NONE = "None"
UNCLASSIFIED = "UNCLASSIFIED"

_CANON = {c.lower(): c for c in CUAD_CATEGORIES}
_CANON["ip ownership assignment"] = "Ip Ownership Assignment"
_CANON["none"] = NONE


def canon(name):
    if name is None:
        return None
    return _CANON.get(str(name).strip().lower())


# Playbook rules given to the risk-scoring service (S3).
PLAYBOOK = {
    "Uncapped Liability": "Liability must be capped. Uncapped liability needs legal approval.",
    "Cap On Liability": "The liability cap must apply to both parties and be at least 12 months of fees.",
    "Liquidated Damages": "Pre-set damages or penalties need legal approval.",
    "Termination For Convenience": "The counterparty may not terminate for convenience on less than 90 days notice.",
    "Change Of Control": "Terms that let the counterparty terminate or renegotiate on a change of control need approval.",
    "Anti-Assignment": "Assignment requires prior written consent of both parties.",
    "Covenant Not To Sue": "Any waiver of legal remedies needs legal approval.",
    "Ip Ownership Assignment": "Company intellectual property may not be assigned to the counterparty.",
    "Non-Compete": "Any restriction on the company's business activity needs approval.",
    "Exclusivity": "Exclusive arrangements need business and legal approval.",
}
DEFAULT_RULE = "Flag terms that deviate from market practice or create one-sided obligations."

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def load_cuad(path):
    """Load CUAD in its SQuAD-style JSON format (test.json or CUAD_v1.json)."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    contracts = []
    for doc in d["data"]:
        for p_i, para in enumerate(doc["paragraphs"]):
            ctx = para["context"]
            gold, seen = [], set()
            for qa in para["qas"]:
                cat = canon(qa["id"].split("__")[-1])
                if cat is None or cat == NONE:
                    continue
                for a in qa.get("answers", []):
                    t, s = a["text"], a["answer_start"]
                    key = (cat, s, len(t))
                    if not t.strip() or key in seen:
                        continue
                    seen.add(key)
                    gold.append({"category": cat, "text": t, "start": s, "end": s + len(t)})
            cid = doc["title"] if len(doc["paragraphs"]) == 1 else f'{doc["title"]}#{p_i}'
            contracts.append({"id": cid, "text": ctx, "gold": gold})
    return contracts


MOCK_TEMPLATES = {
    "Uncapped Liability": "Notwithstanding anything to the contrary, Supplier's liability for breach of its confidentiality and indemnification obligations shall be unlimited.",
    "Cap On Liability": "Except as stated otherwise, neither party's total liability under this Agreement shall exceed the fees paid in the six months before the claim.",
    "Liquidated Damages": "If Supplier fails to meet the delivery date, Supplier shall pay liquidated damages of two percent of the order value for each week of delay.",
    "Termination For Convenience": "Customer may terminate this Agreement for convenience at any time on thirty days written notice to Supplier.",
    "Change Of Control": "If either party undergoes a change of control, the other party may terminate this Agreement on written notice.",
    "Anti-Assignment": "Either party may assign this Agreement without the other party's consent in connection with a merger, acquisition, or sale of all or substantially all of its assets.",
    "Covenant Not To Sue": "Distributor agrees not to bring any claim challenging the validity of Company's patents during the term of this Agreement.",
    "Ip Ownership Assignment": "All inventions and work product created under this Agreement shall be the sole property of Customer, and Supplier hereby assigns all rights in them to Customer.",
    "Non-Compete": "During the term and for one year after, Distributor shall not market any product that competes with the Products in the Territory.",
    "Exclusivity": "Company appoints Distributor as its exclusive distributor of the Products in the Territory.",
    "Governing Law": "This Agreement shall be governed by the laws of the State of New York.",
    "Audit Rights": "Company may audit Distributor's books and records relating to the Products once per calendar year.",
    "Insurance": "Supplier shall maintain commercial general liability insurance of at least two million dollars per occurrence.",
    "Renewal Term": "This Agreement shall renew automatically for successive one-year terms unless either party gives notice of non-renewal.",
    "Warranty Duration": "Supplier warrants that the Products will be free from defects for twelve months after delivery.",
    "License Grant": "Company grants Distributor a non-exclusive license to use the Company trademarks to promote the Products.",
    "Minimum Commitment": "Distributor shall purchase Products worth at least five hundred thousand dollars in each contract year.",
    "Post-Termination Services": "For ninety days after termination, Supplier shall continue to provide support for Products already sold.",
}

MOCK_FILLER = [
    "The parties shall cooperate in good faith to carry out the purposes of this Agreement.",
    "Each party shall bear its own costs in connection with the negotiation of this Agreement.",
    "Notices under this Agreement shall be in writing and delivered to the addresses set out above.",
    "Headings are for convenience only and do not affect the meaning of any provision.",
    "Supplier shall deliver the Products to the delivery point named in each purchase order.",
    "Invoices are payable within forty-five days after receipt of a correct invoice.",
    "Each party shall comply with all laws that apply to its performance of this Agreement.",
    "The Products shall conform to the specifications set out in Exhibit A.",
    "Customer shall inspect the Products promptly after delivery and report any visible damage.",
    "This Agreement may be signed in counterparts, each of which is an original.",
    "No failure to exercise a right under this Agreement operates as a waiver of that right.",
    "If any provision is held invalid, the remaining provisions remain in full force.",
]


def make_mock_contracts(n, seed=7):
    rng = random.Random(seed)
    cats = list(MOCK_TEMPLATES)
    contracts = []
    for i in range(n):
        chosen = rng.sample(cats, rng.randint(6, 12))
        parts, gold, pos = [], [], 0
        head = f"SUPPLY AND DISTRIBUTION AGREEMENT {i + 1}\n\n"
        parts.append(head)
        pos += len(head)
        for sec, cat in enumerate(chosen, 1):
            filler = " ".join(rng.sample(MOCK_FILLER, rng.randint(3, 8)))
            block = f"{sec}. Section {sec}. {filler} "
            parts.append(block)
            pos += len(block)
            clause = MOCK_TEMPLATES[cat]
            gold.append({"category": cat, "text": clause, "start": pos, "end": pos + len(clause)})
            parts.append(clause + "\n\n")
            pos += len(clause) + 2
        contracts.append({"id": f"MOCK_CONTRACT_{i + 1:03d}", "text": "".join(parts), "gold": gold})
    return contracts


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_TOK = re.compile(r"\w+")


def toks(s):
    return set(_TOK.findall(s.lower()))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def chunk_text(text, size, overlap):
    out, i, n = [], 0, len(text)
    while i < n:
        j = min(n, i + size)
        if j < n:
            k = text.rfind("\n", i + size - 1500, j)
            if k == -1:
                k = text.rfind(". ", i + size - 1500, j)
            if k > i:
                j = k + 1
        out.append((i, j))
        if j >= n:
            break
        i = max(j - overlap, i + 1)
    return out


def locate(span, text, offset):
    """Evidence check: is the span present verbatim in the source? Returns (start, end) or None."""
    span = (span or "").strip()
    if not span:
        return None
    k = text.find(span)
    if k >= 0:
        return offset + k, offset + k + len(span)
    words = span.split()
    if not words:
        return None
    pat = r"\s+".join(re.escape(w) for w in words)
    m = re.search(pat, text)
    if m:
        return offset + m.start(), offset + m.end()
    return None


def salvage_items(text):
    """For a reply cut off mid-way: keep every complete item before the cut. Returns a list or None."""
    if not text:
        return None
    k = text.find("[", text.find('"items"') if '"items"' in text else 0)
    if k < 0:
        return None
    dec, i, out = json.JSONDecoder(), k + 1, []
    while True:
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] != "{":
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        out.append(obj)
    return out if out else None


def read_items(acct, service, text):
    """Parse a reply. A complete reply parses cleanly. A cut-off reply keeps its complete items
    but still counts as a service failure. Returns a list, or None if nothing is usable."""
    items = parse_items(text)
    if items is not None:
        return items
    fail(acct, service)
    return salvage_items(text)


def parse_items(text):
    """Pull {"items": [...]} out of a model reply. Returns a list, or None on a schema violation."""
    if text is None:
        return None
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    k = text.find("{")
    if k < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[k:])
    except json.JSONDecodeError:
        return None
    items = obj.get("items") if isinstance(obj, dict) else None
    return items if isinstance(items, list) else None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

OUT_BIG = 16000  # output token limit for services that quote clauses (S1, C0, A1)
OUT_MID = 8000   # output token limit for S2 and S3

CAT_LIST = "\n".join(f"- {c}" for c in CUAD_CATEGORIES)

SYS_S1 = "You are a contract clause extraction service. You only extract text. You never judge it."
SYS_S2 = "You are a contract clause classification service. You label clauses. You do not rate risk."
SYS_S3 = "You are a contract risk scoring service. You rate each clause against the company playbook."
SYS_S4 = "You are a contract summarization service. You write a short brief for a legal reviewer."
SYS_C0 = "You are a contract review assistant."


def prompt_s1(chunk):
    return f"""Extract every clause in the contract excerpt below that relates to any of these categories:
{CAT_LIST}

Rules:
- Copy each clause EXACTLY as it appears, character for character. Do not paraphrase, fix typos, or join separate passages.
- Quote only the sentence or sentences that carry the clause, not whole sections.
- If nothing relevant appears, return an empty list.

Return only JSON in this form: {{"items": [{{"text": "<exact quote>"}}]}}

Excerpt:
<<<
{chunk}
>>>"""


def prompt_s2(clauses):
    numbered = "\n".join(f"[{i}] {c}" for i, c in enumerate(clauses))
    return f"""Assign each clause below exactly one category from this list, or "None" if no category fits:
{CAT_LIST}

For each clause, also give your confidence from 0 to 1 that the label is correct.

Return only JSON in this form: {{"items": [{{"id": 0, "category": "<category or None>", "confidence": 0.0}}]}}

Clauses:
{numbered}"""


def prompt_s3(clauses, cats):
    lines = []
    for i, (c, cat) in enumerate(zip(clauses, cats)):
        rule = PLAYBOOK.get(cat, DEFAULT_RULE)
        lines.append(f"[{i}] Category: {cat}\nPlaybook rule: {rule}\nClause: {c}")
    body = "\n\n".join(lines)
    return f"""Rate the risk to the company of each clause as "low", "medium", or "high", judged against its playbook rule.
In the rationale, name the rule and quote the few words that drove your rating. Keep each rationale under 20 words.

Return only JSON in this form: {{"items": [{{"id": 0, "risk": "low|medium|high", "rationale": "<under 20 words>"}}]}}

{body}"""


def prompt_s4(text):
    return f"""Write a brief for a legal reviewer of this contract: at most 5 points, each tied to an exact quote.

Return only JSON in this form: {{"items": [{{"point": "<one sentence>", "quote": "<exact quote>"}}]}}

Contract:
<<<
{text}
>>>"""


def prompt_c0(chunk):
    return f"""Review the contract excerpt below. Find every clause that relates to any of these categories:
{CAT_LIST}

For each clause give: the exact quoted text, its category, its risk to the company (low, medium, or high), and your confidence from 0 to 1 that the category is correct.

Return only JSON in this form: {{"items": [{{"text": "<exact quote>", "category": "<category>", "risk": "low|medium|high", "confidence": 0.0}}]}}

Excerpt:
<<<
{chunk}
>>>"""


def prompt_a1(chunk):
    return f"""Find every clause in the contract excerpt below that relates to any of these categories, and label it:
{CAT_LIST}

For each clause give the exact quoted text, its category, and your confidence from 0 to 1 that the category is correct.

Return only JSON in this form: {{"items": [{{"text": "<exact quote>", "category": "<category>", "confidence": 0.0}}]}}

Excerpt:
<<<
{chunk}
>>>"""


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class MockProvider:
    """Simulated LLM. It answers in the same JSON format as a real model, using the gold
    labels plus noise, so every code path (schema failures, evidence failures, confidently
    wrong labels) is exercised for free. Its numbers mean nothing for the paper."""

    name = "mock"

    def __init__(self, seed):
        self.seed = seed

    def _rng(self, *key):
        h = hashlib.sha256(repr((self.seed,) + key).encode()).hexdigest()
        return random.Random(int(h[:16], 16))

    def complete(self, service, system, user, meta, max_tokens):
        rng = self._rng(meta["run"], meta["cid"], service, meta.get("chunk", (0, 0)), meta.get("n", 0))
        tin = len(system + user) // 4
        if rng.random() < 0.02:
            text = "Sorry, I could not produce valid output for this request."
        else:
            text = json.dumps({"items": getattr(self, "_" + service)(rng, meta)})
            if rng.random() < 0.03:
                text = text[: int(len(text) * 0.6)]  # simulate a reply cut off at the output limit
        tout = len(text) // 4
        secs = 0.4 + tout / 60.0
        return text, tin, tout, secs

    @staticmethod
    def _gold_in(meta):
        a, b = meta["chunk"]
        return [g for g in meta["gold"] if g["start"] >= a and g["end"] <= b]

    @staticmethod
    def _distractors(rng, meta, k):
        a, b = meta["chunk"]
        sents = [s for s in MOCK_FILLER if s in meta["text"][a:b]]
        return rng.sample(sents, min(k, len(sents)))

    def _extract_like(self, rng, meta, p_found, p_cat, with_risk):
        out = []
        for g in self._gold_in(meta):
            if rng.random() > p_found:
                continue
            t = g["text"] if rng.random() > 0.04 else g["text"] + " (as amended)"
            if rng.random() < p_cat:
                cat, conf = g["category"], rng.uniform(0.88, 0.99)
            else:
                cat = rng.choice([c for c in CUAD_CATEGORIES if c != g["category"]])
                conf = rng.uniform(0.86, 0.99) if rng.random() < 0.6 else rng.uniform(0.40, 0.85)
            item = {"text": t, "category": cat, "confidence": round(conf, 3)}
            if with_risk:
                item["risk"] = "high" if cat in M and rng.random() < 0.7 else rng.choice(["low", "medium"])
            out.append(item)
        for s in self._distractors(rng, meta, rng.randint(0, 2)):
            item = {"text": s, "category": rng.choice(CUAD_CATEGORIES), "confidence": round(rng.uniform(0.4, 0.9), 3)}
            if with_risk:
                item["risk"] = "low"
            out.append(item)
        return out

    def _extract(self, rng, meta):
        return [{"text": i["text"]} for i in self._extract_like(rng, meta, 0.92, 1.0, False)]

    def _classify(self, rng, meta):
        out = []
        for i, c in enumerate(meta["clauses"]):
            tc = toks(c)
            match = [g for g in meta["gold"] if jaccard(tc, toks(g["text"])) >= 0.5]
            if match:
                g = match[0]
                if rng.random() < 0.85:
                    cat, conf = g["category"], rng.uniform(0.88, 0.99)
                else:
                    cat = rng.choice([x for x in CUAD_CATEGORIES if x != g["category"]])
                    conf = rng.uniform(0.86, 0.99) if rng.random() < 0.6 else rng.uniform(0.40, 0.85)
            elif rng.random() < 0.7:
                cat, conf = NONE, rng.uniform(0.7, 0.99)
            else:
                cat, conf = rng.choice(CUAD_CATEGORIES), rng.uniform(0.4, 0.9)
            out.append({"id": i, "category": cat, "confidence": round(conf, 3)})
        return out

    def _risk(self, rng, meta):
        out = []
        for i, cat in enumerate(meta["cats"]):
            if cat in M:
                r = "high" if rng.random() < 0.8 else "medium"
            else:
                r = "low" if rng.random() < 0.7 else "medium"
            rule = PLAYBOOK.get(cat, DEFAULT_RULE)
            out.append({"id": i, "risk": r, "rationale": f"Rated {r} against the rule: {rule}"})
        return out

    def _summary(self, rng, meta):
        return [{"point": "Mock reviewer brief point.", "quote": ""}]

    def _mono(self, rng, meta):
        return self._extract_like(rng, meta, 0.80, 0.75, True)

    def _a1(self, rng, meta):
        return self._extract_like(rng, meta, 0.82, 0.80, False)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.use_temp = True

    def complete(self, service, system, user, meta, max_tokens):
        kw = dict(model=self.model, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": user}])
        if self.use_temp:
            kw["temperature"] = 0
        t0 = time.time()
        try:
            r = self.client.messages.create(**kw)
        except Exception as e:
            if self.use_temp and "temperature" in str(e).lower():
                self.use_temp = False
                return self.complete(service, system, user, meta, max_tokens)
            raise
        text = "".join(getattr(b, "text", "") for b in r.content)
        return text, r.usage.input_tokens, r.usage.output_tokens, time.time() - t0


class OpenAIProvider:
    name = "openai"

    def __init__(self, model):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = model

    def complete(self, service, system, user, meta, max_tokens):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        t0 = time.time()
        try:
            r = self.client.chat.completions.create(model=self.model, messages=msgs, temperature=0,
                                                    max_completion_tokens=max_tokens)
        except Exception:
            r = self.client.chat.completions.create(model=self.model, messages=msgs, max_completion_tokens=max_tokens)
        return (r.choices[0].message.content, r.usage.prompt_tokens, r.usage.completion_tokens,
                time.time() - t0)


# ---------------------------------------------------------------------------
# Calling services: cache, retries, accounting
# ---------------------------------------------------------------------------


class FatalAPIError(Exception):
    """An error no retry can fix (no credit, bad key, unknown model). The run stops at once."""


FATAL_MARKERS = ("credit balance", "authentication", "invalid x-api-key", "invalid api key",
                 "permission", "not_found_error", "model not found", "insufficient_quota")


class Caller:
    def __init__(self, provider, model, cache_dir, price_in=0.0, price_out=0.0, max_usd=None):
        self.p = provider
        self.model = model
        self.price_in, self.price_out, self.max_usd = price_in, price_out, max_usd
        self.spent = 0.0  # estimated USD for new (uncached) calls in this session
        self.lock = threading.Lock()
        self.stop = None  # set to an error message when a fatal API error occurs
        self.cache = Path(cache_dir) if cache_dir and provider.name != "mock" else None
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)

    def call(self, acct, service, system, user, meta, max_tokens):
        """One service call. Updates acct in place. Returns reply text, or None if the call failed."""
        key = hashlib.sha256(json.dumps([self.p.name, self.model, meta["run"], service, system, user]).encode()).hexdigest()
        path = self.cache / f"{key}.json" if self.cache else None
        rec = None
        if path and path.exists():
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                rec = None
            if rec is not None and parse_items(rec.get("text")) is None and rec.get("max_tokens", 0) < max_tokens:
                rec = None  # cut off under an older, smaller output limit: ask again with the larger one
        if rec is None:
            for attempt in range(4):
                if self.stop:
                    raise FatalAPIError(self.stop)
                try:
                    text, tin, tout, secs = self.p.complete(service, system, user, meta, max_tokens)
                    rec = {"text": text, "in": tin, "out": tout, "secs": secs, "max_tokens": max_tokens}
                    with self.lock:
                        self.spent += tin / 1e6 * self.price_in + tout / 1e6 * self.price_out
                        if self.max_usd is not None and self.spent > self.max_usd and not self.stop:
                            self.stop = f"Budget reached: about ${self.spent:.2f} spent this session (limit ${self.max_usd:.2f})."
                    break
                except Exception as e:
                    if any(k in str(e).lower() for k in FATAL_MARKERS):
                        self.stop = str(e)[:300]
                        raise FatalAPIError(self.stop)
                    if attempt == 3:
                        print(f"  ! {service} call failed after retries: {e}", file=sys.stderr)
                        rec = {"text": None, "in": 0, "out": 0, "secs": 0.0}
                    else:
                        time.sleep(2 ** attempt * 3)
            if path and rec["text"] is not None:
                path.write_text(json.dumps(rec), encoding="utf-8")
        s = acct.setdefault(service, {"calls": 0, "fails": 0, "in": 0, "out": 0, "secs": 0.0})
        s["calls"] += 1
        s["in"] += rec["in"]
        s["out"] += rec["out"]
        s["secs"] += rec["secs"]
        return rec["text"]


def fail(acct, service):
    acct[service]["fails"] += 1


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------


def new_record(cid, text, loc, chunk):
    return {
        "cid": cid, "text": text,
        "start": loc[0] if loc else -1, "end": loc[1] if loc else -1,
        "evidence_ok": loc is not None, "chunk": list(chunk),
        "category": NONE, "confidence": 0.0, "risk": "low", "rationale": "",
    }


def dedupe(records):
    kept = []
    for r in records:
        dup = False
        for k in kept:
            if r["evidence_ok"] and k["evidence_ok"]:
                ov = min(r["end"], k["end"]) - max(r["start"], k["start"])
                if ov > 0.5 * min(r["end"] - r["start"], k["end"] - k["start"]):
                    dup = True
                    break
            elif r["text"].strip().lower() == k["text"].strip().lower():
                dup = True
                break
        if not dup:
            kept.append(r)
    return kept


def run_s3(C, acct, meta, recs):
    """Risk scoring on records that have a real category. Failure default: treat as high risk."""
    todo = [r for r in recs if r["category"] in CUAD_CATEGORIES]
    if not todo:
        return
    m = dict(meta, clauses=[r["text"] for r in todo], cats=[r["category"] for r in todo], n=len(todo))
    reply = C.call(acct, "risk", SYS_S3, prompt_s3(m["clauses"], m["cats"]), m, OUT_MID)
    items = read_items(acct, "risk", reply)
    got = {}
    if items is not None:
        for it in items:
            try:
                rk = str(it["risk"]).lower()
                if rk in ("low", "medium", "high"):
                    got[int(it["id"])] = (rk, str(it.get("rationale", "")))
            except (KeyError, ValueError, TypeError):
                pass
        if len(got) < len(todo):
            fail(acct, "risk")
    for i, r in enumerate(todo):
        if i in got:
            r["risk"], r["rationale"] = got[i]
        else:
            r["risk"], r["rationale"] = "high", "Risk service failed. Treated as high risk (fail-to-human default)."


def composed(C, contract, run, args):
    """C1/C2/C3 share this pipeline: S1 extraction, evidence check, S2, S3, plus S4 for the brief."""
    acct, recs, failed = {}, [], False
    text = contract["text"]
    base = {"run": run, "cid": contract["id"], "gold": contract["gold"], "text": text}
    for ch in chunk_text(text, args.chunk_chars, args.overlap):
        meta = dict(base, chunk=ch)
        sub = text[ch[0]:ch[1]]
        # S1 failure default: if nothing usable comes back, send the whole contract to a human.
        # (A retry at temperature 0 returns the same reply, so it is not repeated.)
        items = read_items(acct, "extract", C.call(acct, "extract", SYS_S1, prompt_s1(sub), meta, OUT_BIG))
        if items is None:
            failed = True
            break
        chunk_recs = []
        for it in items:
            t = it.get("text") if isinstance(it, dict) else None
            if isinstance(t, str) and t.strip():
                chunk_recs.append(new_record(contract["id"], t, locate(t, sub, ch[0]), ch))
        chunk_recs = dedupe(chunk_recs)
        if not chunk_recs:
            continue
        m = dict(meta, clauses=[r["text"] for r in chunk_recs], n=len(chunk_recs))
        cls_text = C.call(acct, "classify", SYS_S2, prompt_s2(m["clauses"]), m, OUT_MID)
        cls = read_items(acct, "classify", cls_text)
        got = {}
        if cls is not None:
            for it in cls:
                try:
                    cat = canon(it["category"])
                    if cat is not None:
                        got[int(it["id"])] = (cat, float(it["confidence"]))
                except (KeyError, ValueError, TypeError):
                    pass
            if len(got) < len(chunk_recs):
                fail(acct, "classify")
        for i, r in enumerate(chunk_recs):
            if i in got:
                r["category"], r["confidence"] = got[i][0], max(0.0, min(1.0, got[i][1]))
            else:  # S2 failure default: mark unclassified, escalate
                r["category"], r["confidence"] = UNCLASSIFIED, 0.0
        run_s3(C, acct, meta, chunk_recs)
        recs.extend(chunk_recs)
    recs = dedupe(recs)
    if args.summary:
        C.call(acct, "summary", SYS_S4, prompt_s4(text[:args.summary_chars]), dict(base, chunk=(0, 0)), 800)
    return {"cid": contract["id"], "records": recs, "failed": failed, "acct": acct}


def monolithic(C, contract, run, args):
    """C0: one prompt does extraction, classification, and risk."""
    acct, recs = {}, []
    text = contract["text"]
    base = {"run": run, "cid": contract["id"], "gold": contract["gold"], "text": text}
    for ch in chunk_text(text, args.chunk_chars, args.overlap):
        sub = text[ch[0]:ch[1]]
        items = read_items(acct, "mono", C.call(acct, "mono", SYS_C0, prompt_c0(sub), dict(base, chunk=ch), OUT_BIG))
        if items is None:
            continue  # a monolithic agent has no fail-to-human path: the chunk is simply lost
        for it in items:
            if not isinstance(it, dict) or not isinstance(it.get("text"), str):
                continue
            r = new_record(contract["id"], it["text"], locate(it["text"], sub, ch[0]), ch)
            r["category"] = canon(it.get("category")) or NONE
            try:
                r["confidence"] = max(0.0, min(1.0, float(it.get("confidence", 0))))
            except (TypeError, ValueError):
                r["confidence"] = 0.0
            rk = str(it.get("risk", "low")).lower()
            r["risk"] = rk if rk in ("low", "medium", "high") else "low"
            recs.append(r)
    return {"cid": contract["id"], "records": dedupe(recs), "failed": False, "acct": acct}


def no_extraction(C, contract, run, args):
    """A1: C3 without S1. The classifier reads raw chunks and quotes clauses itself."""
    acct, recs = {}, []
    text = contract["text"]
    base = {"run": run, "cid": contract["id"], "gold": contract["gold"], "text": text}
    for ch in chunk_text(text, args.chunk_chars, args.overlap):
        meta = dict(base, chunk=ch)
        sub = text[ch[0]:ch[1]]
        items = read_items(acct, "a1", C.call(acct, "a1", SYS_S2, prompt_a1(sub), meta, OUT_BIG))
        if items is None:
            r = new_record(contract["id"], "[classification failed for this section]", None, ch)
            r["category"] = UNCLASSIFIED
            recs.append(r)
            continue
        chunk_recs = []
        for it in items:
            if not isinstance(it, dict) or not isinstance(it.get("text"), str):
                continue
            r = new_record(contract["id"], it["text"], locate(it["text"], sub, ch[0]), ch)
            r["category"] = canon(it.get("category")) or UNCLASSIFIED
            try:
                r["confidence"] = max(0.0, min(1.0, float(it.get("confidence", 0))))
            except (TypeError, ValueError):
                r["confidence"] = 0.0
            chunk_recs.append(r)
        chunk_recs = dedupe(chunk_recs)
        run_s3(C, acct, meta, chunk_recs)
        recs.extend(chunk_recs)
    if args.summary:
        C.call(acct, "summary", SYS_S4, prompt_s4(text[:args.summary_chars]), dict(base, chunk=(0, 0)), 800)
    return {"cid": contract["id"], "records": dedupe(recs), "failed": False, "acct": acct}


# ---------------------------------------------------------------------------
# Policies (Section 6, Table 5)
# ---------------------------------------------------------------------------


def p_none():
    return lambda r: ("auto", "default")


def p_conf(tau):
    return lambda r: ("human", "E4") if r["confidence"] < tau else ("auto", "default")


def p_gov(tau, e1=True, e3=True):
    def f(r):
        if e1 and r["category"] in M:
            return "human", "E1"
        if r["risk"] == "high":
            return "human", "E2"
        if e3 and (not r["evidence_ok"] or r["category"] == UNCLASSIFIED):
            return "human", "E3"
        if r["confidence"] < tau:
            return "human", "E4"
        return "auto", "default"
    return f


def risk_from_category(r):
    """A2: no risk-scoring service. Risk is read off the category alone."""
    return dict(r, risk="high" if r["category"] in M else "low")


# ---------------------------------------------------------------------------
# Metrics (Section 7.4)
# ---------------------------------------------------------------------------


def eval_contract(res, gold, policy, misses, transform=None):
    recs = [transform(r) for r in res["records"]] if transform else res["records"]
    dec = [(r, policy(r)) for r in recs]
    hr_gold = [g for g in gold if g["category"] in M]
    out = {"cid": res["cid"], "hrr_den": len(hr_gold)}
    if res["failed"]:
        out.update(er_num=1, er_den=1, ec_num=0, ec_den=0, eca_num=0, eca_den=0, any_esc=1)
        out["gold"] = [{"category": g["category"], "s": {m: 1.0 - m for m in misses}} for g in hr_gold]
    else:
        hum = sum(1 for _, d in dec if d[0] == "human")
        auto = [r for r, d in dec if d[0] == "auto"]
        out.update(er_num=hum, er_den=len(dec),
                   ec_num=sum(1 for r in recs if r["evidence_ok"]), ec_den=len(recs),
                   eca_num=sum(1 for r in auto if r["evidence_ok"]), eca_den=len(auto),
                   any_esc=1 if hum else 0)
        gl = []
        for g in hr_gold:
            tg = toks(g["text"])
            s = {m: 0.0 for m in misses}
            for r, d in dec:
                if jaccard(toks(r["text"]), tg) < 0.5:
                    continue
                for m in misses:
                    v = (1.0 - m) if d[0] == "human" else (1.0 if r["category"] == g["category"] else 0.0)
                    s[m] = max(s[m], v)
            gl.append({"category": g["category"], "s": s})
        out["gold"] = gl
    out["hrr_num"] = {m: sum(x["s"][m] for x in out["gold"]) for m in misses}
    # Clause F1 over all 41 categories (policy independent)
    preds = [r for r in recs if r["category"] in CUAD_CATEGORIES] if not res["failed"] else []
    used, tp = set(), 0
    for g in gold:
        tg = toks(g["text"])
        for i, r in enumerate(preds):
            if i not in used and r["category"] == g["category"] and jaccard(toks(r["text"]), tg) >= 0.5:
                used.add(i)
                tp += 1
                break
    out.update(tp=tp, fp=len(preds) - tp, fn=len(gold) - tp)
    return out


def ratio(rows, num, den):
    n = sum(r[num] for r in rows)
    d = sum(r[den] for r in rows)
    return n / d if d else float("nan")


MATCH_RULES = {
    "Jaccard >= 0.5 (paper rule)": lambda a, g: jaccard(a, g) >= 0.5,
    "Jaccard >= 0.3": lambda a, g: jaccard(a, g) >= 0.3,
    "Covers >= 50% of gold words": lambda a, g: (len(a & g) / len(g) if g else 0.0) >= 0.5,
}


def human_coverage(results_list, gold, policy, rule):
    """For every high-risk gold clause: was it extracted, and did a human see it? (requirement R1).
    A contract sent whole to a human counts as seen."""
    n = ext = seen = auto_right = auto_wrong = 0
    for res in results_list:
        gs = [g for g in gold[res["cid"]] if g["category"] in M]
        n += len(gs)
        if res["failed"]:
            ext += len(gs)
            seen += len(gs)
            continue
        rs = [(toks(r["text"]), r) for r in res["records"]]
        for g in gs:
            tg = toks(g["text"])
            m = [r for t, r in rs if rule(t, tg)]
            if not m:
                continue
            ext += 1
            if any(policy(r)[0] == "human" for r in m):
                seen += 1
            elif any(r["category"] == g["category"] for r in m):
                auto_right += 1
            else:
                auto_wrong += 1
    f = (lambda x: x / n) if n else (lambda x: float("nan"))
    return {"extracted": f(ext), "seen": f(seen), "auto_right": f(auto_right), "auto_wrong": f(auto_wrong),
            "counts": [n, ext, seen, auto_right, auto_wrong]}


def summarize(rows, m0=0.0):
    hn = sum(r["hrr_num"][m0] for r in rows)
    hd = sum(r["hrr_den"] for r in rows)
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    hrr = hn / hd if hd else float("nan")
    er = ratio(rows, "er_num", "er_den")
    return {
        "HRR": hrr, "ER": er,
        "EC": ratio(rows, "ec_num", "ec_den"),
        "EC_auto": ratio(rows, "eca_num", "eca_den"),
        "F1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
        "contracts_escalated": sum(r["any_esc"] for r in rows) / len(rows) if rows else float("nan"),
        "coverage_per_escalation": hrr / er if er and er == er and er > 0 else float("nan"),
    }


def bootstrap(rows_by_cid, key, n_boot, seed, m0=0.0):
    """Paired bootstrap over contracts. rows_by_cid: {cid: [rows from each run]}."""
    cids = list(rows_by_cid)
    rng = random.Random(seed)
    vals = []
    for _ in range(n_boot):
        pick = [rows_by_cid[c] for c in rng.choices(cids, k=len(cids))]
        flat = [r for rs in pick for r in rs]
        v = summarize(flat, m0)[key]
        if v == v:
            vals.append(v)
    if not vals:
        return float("nan"), float("nan")
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[min(len(vals) - 1, int(0.975 * len(vals)))]


def mcnemar(a, b):
    """Exact two-sided McNemar test on paired binary outcomes."""
    b_only = sum(1 for x, y in zip(a, b) if not x and y)
    a_only = sum(1 for x, y in zip(a, b) if x and not y)
    n = a_only + b_only
    if n == 0:
        return 1.0, a_only, b_only
    k = min(a_only, b_only)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p), a_only, b_only


def cost_latency(results, services, args):
    """Per-contract cost (USD) and latency (s) for the given service set."""
    costs, lats, calls, fails = [], [], 0, 0
    for res in results:
        a = res["acct"]
        tin = sum(a[s]["in"] for s in services if s in a)
        tout = sum(a[s]["out"] for s in services if s in a)
        costs.append(tin / 1e6 * args.price_in + tout / 1e6 * args.price_out)
        path = sum(a[s]["secs"] for s in services if s in a and s != "summary")
        summ = a["summary"]["secs"] if "summary" in services and "summary" in a else 0.0
        lats.append(max(path, summ))
        calls += sum(a[s]["calls"] for s in services if s in a)
        fails += sum(a[s]["fails"] for s in services if s in a)
    lats.sort()
    p95 = lats[min(len(lats) - 1, int(math.ceil(0.95 * len(lats))) - 1)] if lats else float("nan")
    return {
        "cost_per_contract": statistics.mean(costs) if costs else float("nan"),
        "latency_median": statistics.median(lats) if lats else float("nan"),
        "latency_p95": p95,
        "failures_per_100_calls": 100.0 * fails / calls if calls else float("nan"),
        "calls": calls,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def cache_report(C, args):
    """Print the tokens and estimated spend of every cached call so far."""
    if not C.cache:
        return
    n = tin = tout = 0
    for f in C.cache.glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        n += 1
        tin += r.get("in", 0)
        tout += r.get("out", 0)
    usd = tin / 1e6 * args.price_in + tout / 1e6 * args.price_out
    print(f"Cache: {n} calls, {tin:,} input + {tout:,} output tokens, about ${usd:.2f} at the prices given.")


def fmt(x, pct=True, nd=1):
    if x is None or x != x:
        return "n/a"
    return f"{100 * x:.{nd}f}%" if pct else f"{x:.{nd}f}"


def fmt_ci(v, ci):
    return f"{fmt(v)} [{fmt(ci[0])}, {fmt(ci[1])}]"


def main():
    ap = argparse.ArgumentParser(description="CUAD harness for the TSC governed-composition paper.")
    ap.add_argument("--provider", choices=["mock", "anthropic", "openai"], default="mock")
    ap.add_argument("--model", default=None, help="Model id. Defaults: anthropic claude-haiku-5-5, openai gpt-5.")
    ap.add_argument("--data", default=None, help="CUAD SQuAD-style JSON, e.g. data/test.json. Mock builds synthetic contracts if omitted.")
    ap.add_argument("--limit", type=int, default=None, help="Use only the first N contracts.")
    ap.add_argument("--runs", type=int, default=1, help="Repeat each configuration this many times. At temperature 0, one run is enough; CIs come from the bootstrap.")
    ap.add_argument("--workers", type=int, default=4, help="Contracts processed in parallel.")
    ap.add_argument("--tau", type=float, default=0.85, help="Confidence threshold for E4 and for C0/C2 (paper: 0.85).")
    ap.add_argument("--price-in", type=float, default=0.10, help="USD per million input tokens. Set to your model's price.")
    ap.add_argument("--price-out", type=float, default=0.50, help="USD per million output tokens. Set to your model's price.")
    ap.add_argument("--chunk-chars", type=int, default=16000, help="Larger chunks mean fewer calls and less repeated prompt text.")
    ap.add_argument("--overlap", type=int, default=400)
    ap.add_argument("--summary-chars", type=int, default=12000)
    ap.add_argument("--summary", action="store_true", help="Also run S4, the advisory reviewer brief. Off by default to save cost; no metric depends on it.")
    ap.add_argument("--max-usd", type=float, default=None, help="Stop the run before spending more than this (estimated from token counts).")
    ap.add_argument("--boot", type=int, default=10000, help="Bootstrap resamples (paper: 10,000).")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", default=None, help="Output folder (default: results, or results_sonnet with --sonnet-check).")
    ap.add_argument("--cache-root", default="results", help="Folder whose cache/ subfolder holds saved API answers.")
    ap.add_argument("--sonnet-check", action="store_true",
                    help="Cross-model check: same settings as the main run, with Claude Sonnet, composed pipeline only.")
    ap.add_argument("--audit", action="store_true", help="Free: count cached replies that were cut off and estimate the cost to re-ask them. No API calls.")
    ap.add_argument("--pipelines", default="composed,mono,a1", help="Which pipelines to run (comma list of composed, mono, a1).")
    args = ap.parse_args()

    if args.sonnet_check:
        args.model = args.model or "claude-sonnet-5-5"
        args.pipelines = "composed"
        if args.price_in == 0.10 and args.price_out == 0.50:
            args.price_in, args.price_out = 3.0, 15.0
        print("Sonnet check: same prompts and settings as the Haiku run, only the model changes. "
              "Runs the composed pipeline (C1, C2, C3, A2 to A4). Cached answers are reused.")
    args.out = args.out or ("results_sonnet" if args.sonnet_check else "results")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.provider == "mock":
        provider, model = MockProvider(args.seed), "mock"
    elif args.provider == "anthropic":
        model = args.model or "claude-haiku-5-5"
        provider = AnthropicProvider(model)
    else:
        model = args.model or "gpt-5"
        provider = OpenAIProvider(model)

    if args.data:
        contracts = load_cuad(args.data)
    elif args.provider == "mock":
        contracts = make_mock_contracts(args.limit or 20, args.seed)
    else:
        sys.exit("Real runs need --data pointing at the CUAD test JSON.")
    if args.limit:
        contracts = contracts[:args.limit]
    gold = {c["id"]: c["gold"] for c in contracts}
    n_hr = sum(1 for c in contracts for g in c["gold"] if g["category"] in M)
    print(f"Provider {provider.name} | model {model} | {len(contracts)} contracts | "
          f"{sum(len(c['gold']) for c in contracts)} gold spans, {n_hr} high-risk | runs {args.runs}")
    if n_hr == 0:
        print("Warning: no high-risk gold clauses in this sample. HRR will be n/a. Use more contracts.")

    C = Caller(provider, model, Path(args.cache_root) / "cache" / f"{provider.name}_{model}".replace("/", "_"),
               args.price_in, args.price_out, args.max_usd)
    if args.audit:
        bad = tin = 0
        for f in (C.cache.glob("*.json") if C.cache else []):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if parse_items(r.get("text")) is None:
                bad += 1
                tin += r.get("in", 0)
        est = tin / 1e6 * args.price_in + bad * 7000 / 1e6 * args.price_out
        print(f"Audit ({model}): {bad} cached replies were cut off or unreadable and will be re-asked.")
        print(f"Estimated cost to re-ask them: about ${est:.2f}, plus about ${0.8 * est:.2f} for the follow-on calls "
              f"they unlock. Suggested --max-usd: {max(1, math.ceil(1.8 * est + 0.5))}")
        return
    all_pipes = {"composed": composed, "mono": monolithic, "a1": no_extraction}
    want = [x.strip() for x in args.pipelines.split(",") if x.strip()]
    if "composed" not in want:
        sys.exit("--pipelines must include composed (C2 and C3 depend on it).")
    pipelines = {k: v for k, v in all_pipes.items() if k in want}
    raw = {p: {} for p in pipelines}  # raw[pipeline][run] = [results]
    lock = threading.Lock()
    t_start = time.time()
    for run in range(args.runs):
        for pname, fn in pipelines.items():
            done = [0]

            def work(c, fn=fn, run=run):
                r = fn(C, c, run, args)
                with lock:
                    done[0] += 1
                    print(f"\r  run {run + 1}/{args.runs}  {pname:9s} {done[0]}/{len(contracts)} contracts  (new spend ~${C.spent:.2f})", end="", flush=True)
                return r

            try:
                with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
                    raw[pname][run] = list(ex.map(work, contracts))
            except FatalAPIError as e:
                print(f"\n\nSTOPPED.\n  {e}\n"
                      "Fix the cause (add credit, set a valid key, or raise --max-usd), then run the SAME command again.\n"
                      "Calls that already succeeded are cached and will not be charged twice.")
                sys.exit(2)
            print()
    cache_report(C, args)

    misses = [0.0, 0.05, 0.10]
    tau = args.tau
    configs = {
        "C0": ("mono", p_conf(tau), None),
        "C1": ("composed", p_none(), None),
        "C2": ("composed", p_conf(tau), None),
        "C3": ("composed", p_gov(tau), None),
        "A1": ("a1", p_gov(tau), None),
        "A2": ("composed", p_gov(tau), risk_from_category),
        "A3": ("composed", p_gov(tau, e3=False), None),
        "A4": ("composed", p_gov(tau, e1=False), None),
    }
    services = {
        "C0": ["mono"],
        "C1": ["extract", "classify", "risk", "summary"],
        "A1": ["a1", "risk", "summary"],
        "A2": ["extract", "classify", "summary"],
    }
    for k in ("C2", "C3", "A3", "A4"):
        services[k] = services["C1"]
    if not args.summary:
        services = {k: [s for s in v if s != "summary"] for k, v in services.items()}

    def rows_for(pipe, policy, transform):
        by_run = {r: [eval_contract(res, gold[res["cid"]], policy, misses, transform) for res in raw[pipe][r]]
                  for r in range(args.runs)}
        by_cid = {}
        for r in range(args.runs):
            for row in by_run[r]:
                by_cid.setdefault(row["cid"], []).append(row)
        return by_run, by_cid

    results = {}
    evals = {}
    configs = {k: v for k, v in configs.items() if v[0] in pipelines}
    for name, (pipe, pol, tr) in configs.items():
        by_run, by_cid = rows_for(pipe, pol, tr)
        flat = [x for rs in by_run.values() for x in rs]
        s = summarize(flat)
        s["HRR_by_miss"] = {str(m): summarize(flat, m)["HRR"] for m in misses}
        s["HRR_run_sd"] = statistics.pstdev([summarize(by_run[r])["HRR"] for r in range(args.runs)]) if args.runs > 1 else 0.0
        s["CI"] = {k: bootstrap(by_cid, k, args.boot, args.seed) for k in ("HRR", "ER", "EC", "F1")}
        s.update(cost_latency([x for r in range(args.runs) for x in raw[pipe][r]], services[name], args))
        results[name] = s
        evals[name] = by_run
        print(f"  {name}: HRR {fmt(s['HRR'])}  ER {fmt(s['ER'])}  F1 {fmt(s['F1'])}  cost ${s['cost_per_contract']:.4f}")

    # RQ2: sweep tau for C2, read off HRR at C3's ER
    sweep = []
    for t in [round(0.50 + 0.005 * i, 3) for i in range(100)]:
        by_run, _ = rows_for("composed", p_conf(t), None)
        flat = [x for rs in by_run.values() for x in rs]
        ss = summarize(flat)
        sweep.append({"tau": t, "ER": ss["ER"], "HRR": ss["HRR"]})
    er3 = results["C3"]["ER"]
    best = min(sweep, key=lambda x: abs(x["ER"] - er3) if x["ER"] == x["ER"] else 9)
    by_run_m, by_cid_m = rows_for("composed", p_conf(best["tau"]), None)
    flat_m = [x for rs in by_run_m.values() for x in rs]
    matched = summarize(flat_m)
    matched["tau"] = best["tau"]
    matched["HRR_by_miss"] = {str(m): summarize(flat_m, m)["HRR"] for m in misses}
    matched["CI"] = {k: bootstrap(by_cid_m, k, args.boot, args.seed) for k in ("HRR", "ER")}
    o2 = [g["s"][0.0] >= 1.0 for rs in by_run_m.values() for row in rs for g in row["gold"]]
    o3 = [g["s"][0.0] >= 1.0 for rs in evals["C3"].values() for row in rs for g in row["gold"]]
    p, c2_only, c3_only = mcnemar(o2, o3)
    matched["mcnemar_p"], matched["c2_only"], matched["c3_only"] = p, c2_only, c3_only

    # Per-category HRR
    def per_cat(by_run):
        tot, hit = {}, {}
        for rs in by_run.values():
            for row in rs:
                for g in row["gold"]:
                    tot[g["category"]] = tot.get(g["category"], 0) + 1
                    hit[g["category"]] = hit.get(g["category"], 0) + g["s"][0.0]
        return {c: (hit.get(c, 0) / tot[c] if tot.get(c) else float("nan"), tot.get(c, 0) // args.runs) for c in HIGH_RISK}

    nan_cat = {c: (float("nan"), 0) for c in HIGH_RISK}
    pc = {"C0": per_cat(evals["C0"]) if "C0" in evals else nan_cat, "C2@matched": per_cat(by_run_m), "C3": per_cat(evals["C3"])}

    # Human-review coverage of high-risk clauses (R1), plus its sensitivity to the matching rule
    flat_raw = {pn: [x for r in range(args.runs) for x in raw[pn][r]] for pn in pipelines}
    cov_pols = [("C0 Monolithic (conf tau)", "mono", p_conf(tau)), ("C2 Confidence (tau)", "composed", p_conf(tau)),
                (f"C2 at matched effort (tau {matched['tau']})", "composed", p_conf(matched["tau"])),
                ("C3 Governed policy", "composed", p_gov(tau)), ("A4 Governed without E1", "composed", p_gov(tau, e1=False))]
    cov_pols = [c for c in cov_pols if c[1] in pipelines]
    coverage = {rn: {name: human_coverage(flat_raw[pipe], gold, pol, rule) for name, pipe, pol in cov_pols}
                for rn, rule in MATCH_RULES.items()}

    # Audit example for Section 6.5: E1 fired on a confident, grounded, correct high-risk clause
    example = None
    pol3 = p_gov(tau)
    for res in raw["composed"][0]:
        for r in res["records"]:
            d = pol3(r)
            if d[1] != "E1" or not r["evidence_ok"] or r["confidence"] < tau:
                continue
            tr = toks(r["text"])
            if any(g["category"] == r["category"] and jaccard(tr, toks(g["text"])) >= 0.5 for g in gold[res["cid"]]):
                example = dict(r, decision=d[0], rule=d[1])
                break
        if example:
            break

    # Write decision logs (the audit trail)
    for name, pipe, pol, tr in (("C0", "mono", p_conf(tau), None), ("C3", "composed", p_gov(tau), None), ("A1", "a1", p_gov(tau), None)):
        if pipe not in pipelines:
            continue
        with open(out / f"decisions_{name}.jsonl", "w", encoding="utf-8") as f:
            for run in range(args.runs):
                for res in raw[pipe][run]:
                    for r in res["records"]:
                        d = pol(r)
                        f.write(json.dumps(dict(r, run=run, config=name, decision=d[0], rule=d[1], contract_failed=res["failed"])) + "\n")

    meta = {"provider": provider.name, "model": model, "contracts": len(contracts), "runs": args.runs,
            "tau": tau, "price_in": args.price_in, "price_out": args.price_out,
            "high_risk_gold": n_hr, "seconds": round(time.time() - t_start, 1),
            "data": args.data or "synthetic mock contracts"}
    json.dump({"meta": meta, "configs": results, "matched_C2": matched, "sweep": sweep,
               "per_category": {k: {c: v[0] for c, v in d.items()} for k, d in pc.items()},
               "audit_example": example, "coverage": coverage}, open(out / "results.json", "w", encoding="utf-8"), indent=2)

    # Figure 2
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5.2, 3.8), dpi=200)
        xs = [s["ER"] for s in sweep]
        ys = [s["HRR"] for s in sweep]
        ax.plot(xs, ys, color="#9aa5b1", lw=1.4, marker="o", ms=2.5, label="C2 confidence routing (tau swept)")
        ax.scatter([results["C3"]["ER"]], [results["C3"]["HRR"]], color="#3b6fb6", s=40, zorder=3, label="C3 governed policy P")
        if "C0" in results:
            ax.scatter([results["C0"]["ER"]], [results["C0"]["HRR"]], color="#555555", marker="s", s=28, zorder=3, label="C0 monolithic")
        ax.set_xlabel("Escalation rate (share of decisions sent to a human)")
        ax.set_ylabel("High-risk recall (HRR)")
        ax.grid(color="#e5e5e5", lw=0.6)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.legend(frameon=False, fontsize=7.5, loc="lower right")
        fig.tight_layout()
        fig.savefig(out / "hrr_vs_er.png")
        fig_note = "Fig. 2 written to hrr_vs_er.png"
    except ImportError:
        fig_note = "Install matplotlib to draw Fig. 2 (pip install matplotlib)."

    # Tables for Section 8
    L = []
    mock = provider.name == "mock"
    L.append("# Results tables for Section 8")
    if mock:
        L.append("\n**MOCK RUN. These numbers come from a simulated model and synthetic contracts. Do not put them in the paper.**")
    L.append(f"\n{meta['contracts']} contracts, {meta['runs']} run(s), model {model}, tau {tau}, "
             f"{n_hr} high-risk gold clauses per run. Price ${args.price_in}/${args.price_out} per M tokens in/out.")
    L.append("\n## Table 9. Main results on CUAD\n")
    L.append("| Config | HRR | ER | EC | Clause F1 | Coverage per escalation | Median latency (s) | Cost per contract (USD) |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    labels = {"C0": "C0 Monolithic", "C1": "C1 Composed, ungoverned", "C2": f"C2 Composed, confidence (tau = {tau})", "C3": "C3 Composed, governed"}
    for k in ("C0", "C1", "C2", "C3"):
        if k not in results:
            L.append(f"| {labels[k]} | not run | | | | | | |")
            continue
        s = results[k]
        cpe = "n/a" if k == "C1" else fmt(s["coverage_per_escalation"], pct=False, nd=2)
        L.append(f"| {labels[k]} | {fmt_ci(s['HRR'], s['CI']['HRR'])} | {fmt(s['ER'])} | {fmt(s['EC'])} | "
                 f"{fmt_ci(s['F1'], s['CI']['F1'])} | {cpe} | {fmt(s['latency_median'], pct=False)} | {s['cost_per_contract']:.4f} |")
    n_failed = sum(1 for r in range(args.runs) for res in raw["composed"][r] if res["failed"])
    L.append(f"\nContracts sent whole to a human because extraction returned nothing usable: {n_failed} of {len(contracts) * args.runs}.")
    L.append(f"\nShare of contracts with at least one escalation: C2 {fmt(results['C2']['contracts_escalated'])}, C3 {fmt(results['C3']['contracts_escalated'])}.")
    L.append("\n## Table 10. C2 and C3 at matched escalation rate\n")
    L.append("| Policy | ER | HRR (reviewer perfect) | HRR (5% miss) | HRR (10% miss) | McNemar p vs C3 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    L.append(f"| C2 at C3's ER (tau = {matched['tau']}) | {fmt(matched['ER'])} | {fmt(matched['HRR_by_miss']['0.0'])} | "
             f"{fmt(matched['HRR_by_miss']['0.05'])} | {fmt(matched['HRR_by_miss']['0.1'])} | {matched['mcnemar_p']:.4f} |")
    s3 = results["C3"]
    L.append(f"| C3 governed | {fmt(s3['ER'])} | {fmt(s3['HRR_by_miss']['0.0'])} | {fmt(s3['HRR_by_miss']['0.05'])} | "
             f"{fmt(s3['HRR_by_miss']['0.1'])} | n/a |")
    L.append(f"\nDiscordant high-risk clauses: caught only by C3 = {matched['c3_only']}, caught only by C2 = {matched['c2_only']}.")
    L.append("\n## Table 11. Leave-one-out ablation (change from C3)\n")
    L.append("| Ablation | Delta HRR | Delta ER | Delta EC (auto-accepted) | Delta cost per contract | Service failures per 100 calls |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    names = {"A1": "A1 without S1 (extraction)", "A2": "A2 without S3 (risk scoring)", "A3": "A3 without evidence check", "A4": "A4 without E1 (mandatory set)"}

    def dpp(a, b):
        return "n/a" if a != a or b != b else f"{100 * (a - b):+.1f} pp"

    for k in ("A1", "A2", "A3", "A4"):
        if k not in results:
            L.append(f"| {names[k]} | not run | | | | |")
            continue
        s = results[k]
        L.append(f"| {names[k]} | {dpp(s['HRR'], s3['HRR'])} | {dpp(s['ER'], s3['ER'])} | {dpp(s['EC_auto'], s3['EC_auto'])} | "
                 f"{s['cost_per_contract'] - s3['cost_per_contract']:+.4f} | {fmt(s['failures_per_100_calls'], pct=False)} |")
    L.append(f"\nC3 reference: EC over all decisions {fmt(s3['EC'])}, EC over auto-accepted decisions {fmt(s3['EC_auto'])}, "
             f"service failures {fmt(s3['failures_per_100_calls'], pct=False)} per 100 calls, latency p95 {fmt(s3['latency_p95'], pct=False)} s.")
    L.append("\n## Human-review coverage of high-risk clauses (requirement R1)\n")
    L.append("| Policy | ER | Extracted | Seen by a human | Auto-accepted, labeled right | Auto-accepted, mislabeled |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    er_of = {"C0 Monolithic (conf tau)": results.get("C0", {}).get("ER"), "C2 Confidence (tau)": results["C2"]["ER"],
             f"C2 at matched effort (tau {matched['tau']})": matched["ER"], "C3 Governed policy": results["C3"]["ER"],
             "A4 Governed without E1": results.get("A4", {}).get("ER")}
    for name, cv in coverage["Jaccard >= 0.5 (paper rule)"].items():
        L.append(f"| {name} | {fmt(er_of.get(name))} | {fmt(cv['extracted'])} | {fmt(cv['seen'])} | {fmt(cv['auto_right'])} | {fmt(cv['auto_wrong'])} |")
    L.append("\nSensitivity to the span-matching rule (share of high-risk gold clauses seen by a human):\n")
    L.append("| Matching rule | " + " | ".join(coverage["Jaccard >= 0.5 (paper rule)"]) + " |")
    L.append("| --- |" + " --- |" * len(coverage["Jaccard >= 0.5 (paper rule)"]))
    for rn, d in coverage.items():
        L.append(f"| {rn} | " + " | ".join(fmt(v["seen"]) for v in d.values()) + " |")
    L.append("\n## Per-category HRR (Section 7.4)\n")
    L.append("| Category | Gold per run | C0 | C2 at matched ER | C3 |")
    L.append("| --- | --- | --- | --- | --- |")
    for c in HIGH_RISK:
        L.append(f"| {c} | {pc['C3'][c][1]} | {fmt(pc['C0'][c][0])} | {fmt(pc['C2@matched'][c][0])} | {fmt(pc['C3'][c][0])} |")
    L.append("\n## Audit-trail example for Section 6.5\n")
    if example:
        L.append(f"Contract: {example['cid']}  \nClause: \"{example['text'][:400]}\"  \n"
                 f"Span offsets: {example['start']} to {example['end']} (evidence check: pass)  \n"
                 f"S2 category: {example['category']}, confidence {example['confidence']:.2f}  \n"
                 f"S3 risk: {example['risk']}. Rationale: {example['rationale'][:300]}  \n"
                 f"Policy P: rule {example['rule']} fired, routed to {example['decision']}.  \n"
                 f"Under confidence routing at tau = {tau}, this clause would have been auto-accepted, because confidence {example['confidence']:.2f} >= {tau}.")
    else:
        L.append("No qualifying example found in run 1. Check decisions_C3.jsonl by hand.")
    L.append(f"\n{fig_note}. Full audit logs: decisions_C0.jsonl, decisions_C3.jsonl, decisions_A1.jsonl.")
    (out / "tables.md").write_text("\n".join(L), encoding="utf-8")

    print(f"\nDone in {meta['seconds']} s. Wrote {out}/tables.md, results.json, decisions_*.jsonl. {fig_note}.")
    if mock:
        print("This was a MOCK run: it checks the pipeline only. Its numbers must not go in the paper.")


if __name__ == "__main__":
    main()
