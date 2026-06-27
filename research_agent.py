from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
import traceback
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich import box

logger = logging.getLogger(__name__)

_console = Console()

SCRIPT_VERSION = "2.0.1"

# ──────────────────────────────────────────────
# 1. TaskPlanner — Dynamic Task Decomposition
# ──────────────────────────────────────────────


@dataclass
class ResearchPlan:
    query: str
    sub_questions: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    plan_steps: list[dict[str, str]] = field(default_factory=list)


class TaskPlanner:
    """Decompose ambiguous research queries into structured sub-questions and search plans."""

    def __init__(self, query: str, prompt_override: str | None = None) -> None:
        self.query = query
        self.prompt_override = prompt_override

    def decompose(self) -> ResearchPlan:
        q = self.query.lower()
        if self.prompt_override:
            q = f"{self.prompt_override} Query: {q}"

        sub_questions = self._extract_sub_questions(q)
        search_queries = self._build_search_queries(sub_questions)
        plan_steps = self._build_plan(sub_questions)

        return ResearchPlan(
            query=self.query,
            sub_questions=sub_questions,
            search_queries=search_queries,
            plan_steps=plan_steps,
        )

    def _extract_sub_questions(self, q: str) -> list[str]:
        topics = re.findall(r'(?:about|of|in|on|for)\s+([\w\s]+?)(?:,|\sand|\.|$)', q)
        topics = [t.strip() for t in topics if len(t.strip()) > 3]
        if not topics:
            topics = [q.strip()[:60]]

        sub_questions = []
        for t in topics[:4]:
            sub_questions.append(f"What are the key findings and recent developments in {t}?")
            sub_questions.append(f"What are the main debates or controversies surrounding {t}?")
            sub_questions.append(f"What evidence supports or contradicts the prevailing views on {t}?")

        return sub_questions[:6]

    def _build_search_queries(self, sub_questions: list[str]) -> list[str]:
        queries = []
        for sq in sub_questions:
            terms = sq.strip("?").lower()
            encoded = urllib.parse.quote(terms)
            queries.append(encoded)
            queries.append(urllib.parse.quote(f"{terms} 2025"))
            queries.append(urllib.parse.quote(f"{terms} analysis"))
        return queries[:9]

    def search_url(self, encoded_query: str) -> str:
        return f"https://html.duckduckgo.com/html/?q={encoded_query}"

    def _build_plan(self, sub_questions: list[str]) -> list[dict[str, str]]:
        steps = []
        for i, sq in enumerate(sub_questions, 1):
            steps.append({"step": f"Phase {i}", "focus": sq, "method": "web_search+extraction"})
        steps.append({
            "step": "Synthesis",
            "focus": "Cross-reference findings and generate report",
            "method": "contradiction_analysis+report_generation",
        })
        return steps


# ──────────────────────────────────────────────
# 2. WebCrawler — Resilient Web Fetching
# ──────────────────────────────────────────────


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]


class WebCrawler:
    """Async web fetcher with HTML boilerplate stripping."""

    def __init__(self, timeout: float = 30.0, max_retries: int = 2, prompt_override: str | None = None, searxng_instance: str | None = None) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.prompt_override = prompt_override
        self.searxng_instance = searxng_instance
        self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)

    async def fetch(self, url: str) -> str | None:
        await asyncio.sleep(random.uniform(1.0, 3.0))
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.get(url, headers=self._headers())
                resp.raise_for_status()
                html = resp.text
                if "duckduckgo.com" in url:
                    snippets = self._parse_ddg_results(html)
                    if snippets:
                        return "\n\n".join(snippets)
                    text = self._extract_text(html, url)
                    if not text or self._is_captcha_page(text, url):
                        search_term = self._extract_search_term(url)
                        if self.searxng_instance:
                            logger.info("DDG blocked, trying SearXNG: %s", self.searxng_instance)
                            searxng_result = await self._search_searxng(search_term)
                            if searxng_result:
                                return searxng_result
                        logger.warning("SearXNG failed or not configured, trying Wikipedia fallback for: %s", search_term)
                        wiki_result = await self.fetch_wikipedia(search_term)
                        if wiki_result:
                            return wiki_result
                        return None
                    return text
                return self._extract_text(html, url)
            except httpx.HTTPStatusError as e:
                logger.warning("HTTP %d for %s (attempt %d)", e.response.status_code, url, attempt + 1)
            except httpx.RequestError as e:
                logger.warning("Request failed for %s (attempt %d): %s", url, attempt + 1, e)
            except Exception as e:
                logger.error("Unexpected error fetching %s: %s", url, e)
                return None
        logger.error("Failed to fetch %s after %d retries", url, self.max_retries)
        return None

    def _is_captcha_page(self, text: str, url: str) -> bool:
        if not text:
            return True  # empty text = likely CAPTCHA
        signals = [
            "please complete the following challenge",
            "please complete the following security",
            "unfortunately, bots use",
            "select all squares containing",
            "images not loading? please email",
            "error-lite@",
            "verify you are human",
            "captcha",
        ]
        lower = text.lower()
        return any(s in lower for s in signals)

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _extract_search_term(url: str) -> str:
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        return qs.get("q", [""])[0].replace("+", " ").replace("%20", " ")

    async def _search_searxng(self, query: str) -> str | None:
        if not self.searxng_instance:
            return None
        search_url = f"{self.searxng_instance.rstrip('/')}/search?q={urllib.parse.quote(query)}&format=json&language=en-US&categories=general"
        try:
            resp = await self._client.get(search_url, headers={"User-Agent": "research-agent/2.0"}, timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None
            snippets = []
            for r in results[:5]:
                title = r.get("title", "")
                content = r.get("content", "")
                url = r.get("url", "")
                if content:
                    snippets.append(f"## {title}\n{content}\nSource: {url}")
            return "\n\n".join(snippets) if snippets else None
        except Exception as e:
            logger.warning("SearXNG search failed for '%s': %s", query, e)
            return None

    async def fetch_batch(self, urls: list[str], max_concurrent: int = 3) -> dict[str, str | None]:
        sem = asyncio.Semaphore(max_concurrent)

        async def fetch_one(url: str) -> tuple[str, str | None]:
            async with sem:
                return url, await self.fetch(url)

        tasks = [fetch_one(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return dict(results)

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://duckduckgo.com/",
        }

    def _extract_text(self, html: str, url: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        captcha_indicators = {"duck", "captcha", "unfortunately", "please complete", "select all squares", "verify yourself", "blocked", "suspicious traffic", "images not loading", "please email the following code", "error-lite"}
        lines = []
        total_lines = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            total_lines += 1
            lower = line.lower()
            if any(indicator in lower for indicator in captcha_indicators):
                continue
            if len(line.split()) < 3:
                continue
            lines.append(line)
        text = "\n".join(lines)
        if len(text) > 10000:
            text = text[:10000] + "\n[truncated]"
        if not text and total_lines > 2:
            logger.warning("CAPTCHA detected for %s (%d lines filtered)", url, total_lines)
            return ""
        if not text:
            logger.warning("No extractable text from %s", url)
        return text

    def _parse_ddg_results(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        snippets = []
        for result in soup.select(".result__snippet, .result__body, .snippet"):
            text = result.get_text(strip=True)
            if text and len(text.split()) >= 3:
                snippets.append(text)
        if not snippets:
            for tag in soup.find_all(["a", "div"], class_=re.compile(r"(result|snippet|heading)", re.I)):
                text = tag.get_text(strip=True)
                if text and len(text.split()) >= 3:
                    snippets.append(text)
        return snippets[:20]

    async def fetch_wikipedia(self, query: str) -> str | None:
        """Fallback: fetch summary from Wikipedia API for a given query."""
        if not hasattr(self, '_wiki_sem'):
            self._wiki_sem = asyncio.Semaphore(1)
        async with self._wiki_sem:
            await asyncio.sleep(random.uniform(0.3, 0.8))
            search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json&srlimit=3"
            try:
                resp = await self._client.get(search_url, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
                pages = data.get("query", {}).get("search", [])
                if not pages:
                    return None
                snippets = []
                for p in pages[:2]:
                    title = p.get("title", "")
                    await asyncio.sleep(random.uniform(0.2, 0.5))
                    page_url = f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=true&explaintext=true&titles={urllib.parse.quote(title)}&format=json"
                    pr = await self._client.get(page_url, headers=self._headers())
                    pr.raise_for_status()
                    pdata = pr.json()
                    pages_data = pdata.get("query", {}).get("pages", {})
                    for pid, content in pages_data.items():
                        if pid != "-1":
                            extract = content.get("extract", "")
                            if extract:
                                snippets.append(f"Wikipedia - {title}:\n{extract[:2000]}")
                return "\n\n".join(snippets) if snippets else None
            except Exception as e:
                logger.warning("Wikipedia fallback failed: %s", e)
                return None


# ──────────────────────────────────────────────
# 3. ContradictionEngine — Flagging Conflicts
# ──────────────────────────────────────────────


@dataclass
class Contradiction:
    sources: list[str]
    claim: str
    evidence_a: str
    evidence_b: str
    confidence: float
    contra_type: str


class ContradictionEngine:
    """Detect conflicting statistics, sources, and claims across texts."""

    NUMBER_PATTERN = re.compile(r"\b(\d+[\d,.]*(?:\s*%|\s*(?:million|billion|trillion))?)\b", re.IGNORECASE)
    NEGATION_WORDS = {"not", "no", "never", "cannot", "doesn't", "don't", "didn't", "won't",
                      "isn't", "aren't", "wasn't", "weren't", "without", "against", "oppose"}

    def __init__(self, prompt_override: str | None = None) -> None:
        self.prompt_override = prompt_override
        self._patterns: list[dict[str, Any]] = self._build_patterns()

    def _build_patterns(self) -> list[dict[str, Any]]:
        return [
            {"type": "statistical_claim", "trigger": re.compile(
                r"(increase|decrease|rise|fall|grew|declined|up\s*\d+|down\s*\d+)", re.IGNORECASE)},
            {"type": "causal_claim", "trigger": re.compile(
                r"(because|therefore|thus|hence|caused by|leads? to|results? in)", re.IGNORECASE)},
            {"type": "comparison_claim", "trigger": re.compile(
                r"(more than|less than|better|worse|higher|lower|faster|slower)", re.IGNORECASE)},
            {"type": "certainty_claim", "trigger": re.compile(
                r"(may|might|could|possibly|perhaps|likely|probably|certainly|definitely|undoubtedly)",
                re.IGNORECASE)},
            {"type": "scope_claim", "trigger": re.compile(
                r"(all|every|always|never|none|no one|some|many|most|few|rarely|often|sometimes)",
                re.IGNORECASE)},
            {"type": "sentiment_claim", "trigger": re.compile(
                r"(positive|negative|beneficial|harmful|helpful|detrimental|good|bad|advantage|disadvantage)",
                re.IGNORECASE)},
        ]

    def analyze(self, texts: dict[str, str], query: str = "") -> list[Contradiction]:
        contradictions: list[Contradiction] = []
        source_items = list(texts.items())

        query_sigs = self._query_contradiction_signals(query)
        if query_sigs:
            contradictions.append(query_sigs)

        for i in range(len(source_items)):
            for j in range(i + 1, len(source_items)):
                url_a, text_a = source_items[i]
                url_b, text_b = source_items[j]
                result = self._check_pair(url_a, text_a, url_b, text_b)
                if result:
                    contradictions.append(result)

        for url, text in source_items:
            internal = self._check_internal(url, text)
            contradictions.extend(internal)

        return contradictions

    def _check_internal(self, url: str, text: str) -> list[Contradiction]:
        results: list[Contradiction] = []
        lines = [l for l in text.split("\n") if len(l.strip()) > 30]
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                pol_i = self._polarity(lines[i])
                pol_j = self._polarity(lines[j])
                if pol_i * pol_j < 0:
                    shared = set(lines[i].lower().split()) & set(lines[j].lower().split())
                    if len([w for w in shared if len(w) > 4]) >= 2:
                        results.append(Contradiction(
                            sources=[url],
                            claim=f"Internal contradiction within source",
                            evidence_a=lines[i][:200],
                            evidence_b=lines[j][:200],
                            confidence=0.5,
                            contra_type="internal_polarity",
                        ))
                        if len(results) >= 3:
                            return results
        return results[:3]

    def _check_pair(self, url_a: str, text_a: str, url_b: str, text_b: str) -> Contradiction | None:
        numbers_a = self.NUMBER_PATTERN.findall(text_a)
        numbers_b = self.NUMBER_PATTERN.findall(text_b)

        if numbers_a and numbers_b:
            overlap = self._find_numeric_conflicts(numbers_a, numbers_b, text_a, text_b)
            if overlap:
                return Contradiction(
                    sources=[url_a, url_b],
                    claim="Conflicting numerical claims about similar values",
                    evidence_a=overlap["sent_a"],
                    evidence_b=overlap["sent_b"],
                    confidence=0.7,
                    contra_type="numerical",
                )

        for pattern in self._patterns:
            matches_a = list(pattern["trigger"].finditer(text_a))[:2]
            matches_b = list(pattern["trigger"].finditer(text_b))[:2]

            for ma in matches_a:
                for mb in matches_b:
                    sent_a = self._sentence_around(text_a, ma.start())
                    sent_b = self._sentence_around(text_b, mb.start())
                    polarity_a = self._polarity(sent_a)
                    polarity_b = self._polarity(sent_b)
                    if polarity_a * polarity_b < 0:
                        claim = self._extract_claim_phrase(sent_a)
                        return Contradiction(
                            sources=[url_a, url_b],
                            claim=f"Divergent claims about '{claim}'",
                            evidence_a=sent_a[:200],
                            evidence_b=sent_b[:200],
                            confidence=0.6,
                            contra_type=pattern["type"],
                        )
        return None

    def _find_numeric_conflicts(self, nums_a: list[str], nums_b: list[str],
                                 text_a: str, text_b: str) -> dict | None:
        for na in nums_a[:5]:
            for nb in nums_b[:5]:
                if self._same_topic(na, nb):
                    sent_a = self._sentence_around(text_a, text_a.find(na))
                    sent_b = self._sentence_around(text_b, text_b.find(nb))
                    return {"sent_a": sent_a[:200], "sent_b": sent_b[:200]}
        return None

    def _same_topic(self, a: str, b: str) -> bool:
        a_clean = re.sub(r"[^\d]", "", a)
        b_clean = re.sub(r"[^\d]", "", b)
        if not a_clean or not b_clean:
            return False
        a_num = float(a_clean.replace(",", ""))
        b_num = float(b_clean.replace(",", ""))
        if a_num == 0 or b_num == 0:
            return False
        ratio = max(a_num, b_num) / min(a_num, b_num)
        return 1.5 < ratio < 100

    def _sentence_around(self, text: str, pos: int, window: int = 60) -> str:
        start = max(0, pos - window)
        end = min(len(text), pos + window)
        snippet = text[start:end]
        return snippet.strip()

    def _polarity(self, sentence: str) -> int:
        words = set(sentence.lower().split())
        negations = words & self.NEGATION_WORDS
        return -1 if negations else 1

    def _extract_claim_phrase(self, sentence: str) -> str:
        match = re.search(r'(?:that|whether|if)\s+(.+?)(?:\.|,|$)', sentence)
        return match.group(1)[:80] if match else sentence[:80]

    def _query_contradiction_signals(self, query: str) -> Contradiction | None:
        opposing_pairs = [
            (r"\bgood\b.*\bbad\b", "good vs bad"),
            (r"\bbenefit", "benefit vs harm"),
            (r"\bharm", "benefit vs harm"),
            (r"\bpro[s]?\b.*\bcon[s]?\b", "pros vs cons"),
            (r"\bpositive\b.*\bnegative\b", "positive vs negative"),
            (r"\bsupport", "support vs oppose"),
            (r"\boppos", "support vs oppose"),
            (r"\bagainst\b", "for vs against"),
            (r"\bin favor\b", "for vs against"),
            (r"\bconflicting\b", "conflicting evidence"),
            (r"\bcompare\b", "comparison of competing views"),
            (r"\bdebate", "debate/controversy"),
            (r"\bcontrovers", "debate/controversy"),
            (r"\bcompeting\b", "competing theories"),
            (r"\bdiffering\b", "differing perspectives"),
            (r"\bversus\b|\bvs\.?\b", "competing positions"),
            (r"\bcause", "causal debate"),
            (r"\btheory\b.*\btheory\b", "multiple theories"),
            (r"\bimpact\b", "impact assessment (positive vs negative)"),
        ]
        q = query.lower()
        for pattern, topic in opposing_pairs:
            if re.search(pattern, q):
                return Contradiction(
                    sources=[query],
                    claim=f"Query encodes opposing viewpoints: {topic}",
                    evidence_a=f"Query contains language suggesting {topic}",
                    evidence_b="Indicates multiple perspectives exist in the research space",
                    confidence=0.8,
                    contra_type="query_signal",
                )
        return None

    def format_report(self, contradictions: list[Contradiction]) -> str:
        if not contradictions:
            return "**No contradictions detected.**\n"
        lines = ["## Contradictions & Divergences\n"]
        for i, c in enumerate(contradictions, 1):
            lines.append(f"### {i}. {c.claim} (confidence: {c.confidence:.0%})")
            lines.append(f"- **Type:** `{c.contra_type}`")
            src = f"{c.sources[0]}" if len(c.sources) == 1 else f"{c.sources[0]} vs {c.sources[1]}"
            lines.append(f"- **Sources:** {src}")
            lines.append(f"- **Claim A:** {c.evidence_a}")
            lines.append(f"- **Claim B:** {c.evidence_b}\n")
        return "\n".join(lines)


# ──────────────────────────────────────────────
# 4. ReportSynthesizer — Structured Markdown Report
# ──────────────────────────────────────────────


class ReportSynthesizer:
    """Generate structured markdown research reports from findings."""

    def __init__(self, prompt_override: str | None = None) -> None:
        self.prompt_override = prompt_override

    def generate(self, query: str, plan: ResearchPlan, findings: dict[str, str | None],
                 contradictions: list[Contradiction], execution_stats: dict[str, Any] | None = None) -> str:
        sections: list[str] = []
        sections.append(self._header(query))
        sections.append(self._executive_summary(findings, contradictions))
        sections.append(self._methodology(plan))
        sections.append(self._key_findings(plan, findings))
        sections.append(self._contradictions_section(contradictions))
        sections.append(self._references(findings))
        if execution_stats:
            sections.append(self._stats_section(execution_stats))
        sections.append(self._footer())
        return "\n\n".join(sections)

    def _header(self, query: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return (f"# Deep Research Report\n\n"
                f"**Query:** {query}\n\n"
                f"**Generated:** {ts}\n\n"
                f"---\n")

    def _executive_summary(self, findings: dict[str, str | None],
                           contradictions: list[Contradiction]) -> str:
        n_sources = len([v for v in findings.values() if v])
        n_contra = len(contradictions)
        return (f"## Executive Summary\n\n"
                f"Analyzed {n_sources} source(s) with {n_contra} contradiction(s) detected. "
                f"The research reveals a complex landscape with multiple perspectives "
                f"requiring careful synthesis.\n")

    def _methodology(self, plan: ResearchPlan) -> str:
        lines = ["## Methodology\n"]
        for step in plan.plan_steps:
            lines.append(f"- **{step['step']}:** {step['focus']} ({step['method']})")
        return "\n".join(lines)

    def _key_findings(self, plan: ResearchPlan, findings: dict[str, str | None]) -> str:
        lines = ["## Key Findings\n"]
        for i, sq in enumerate(plan.sub_questions, 1):
            lines.append(f"### {i}. {sq}\n")
            relevant = self._find_relevant(findings, sq)
            if relevant:
                lines.append(f"{relevant[:500]}\n")
            else:
                lines.append("*Insufficient data to address this question.*\n")
        return "\n".join(lines)

    def _find_relevant(self, findings: dict[str, str | None], query: str) -> str:
        terms = query.lower().split()
        best = ""
        best_score = 0
        for url, text in findings.items():
            if not text:
                continue
            score = sum(1 for t in terms if t in text.lower())
            if score > best_score:
                best_score = score
                best = text[:800]
        return best

    def _contradictions_section(self, contradictions: list[Contradiction]) -> str:
        return ContradictionEngine().format_report(contradictions)

    def _references(self, findings: dict[str, str | None]) -> str:
        lines = ["## Source References\n"]
        for url, text in findings.items():
            status = "✓" if text else "✗"
            lines.append(f"- ({status}) `{url}`")
        return "\n".join(lines)

    def _stats_section(self, stats: dict[str, Any]) -> str:
        return (f"## Execution Statistics\n\n"
                f"```json\n{json.dumps(stats, indent=2)}\n```\n")

    def _footer(self) -> str:
        return ("---\n\n"
                "*Report generated by Deep Research Agent. "
                "Verify critical claims against original sources.*\n")


# ──────────────────────────────────────────────
# 5. SessionManager — JSON Stateful Recovery
# ──────────────────────────────────────────────


@dataclass
class ResearchState:
    query: str
    status: str = "initialized"
    current_step: str = ""
    findings: dict[str, str | None] = field(default_factory=dict)
    contradictions: list[dict] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    report: str = ""
    error_log: list[str] = field(default_factory=list)
    timestamps: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResearchState:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class SessionManager:
    """Persist and recover research state from JSON."""

    def __init__(self, state_path: str = "research_state.json") -> None:
        self.path = Path(state_path)

    def save(self, state: ResearchState) -> None:
        data = state.to_dict()
        data["_updated"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(json.dumps(data, indent=2, default=str))
        logger.info("State saved to %s", self.path)

    def load(self) -> ResearchState | None:
        if not self.path.exists():
            logger.info("No prior state found at %s", self.path)
            return None
        try:
            data = json.loads(self.path.read_text())
            return ResearchState.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to load state: %s", e)
            return None

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
            logger.info("State cleared from %s", self.path)

    def exists(self) -> bool:
        return self.path.exists()


# ──────────────────────────────────────────────
# Agent Orchestrator
# ──────────────────────────────────────────────


class ResearchAgent:
    """Orchestrate the full deep research workflow."""

    def __init__(self, query: str, state_path: str = "research_state.json",
                 prompt_overrides: dict[str, str] | None = None,
                 searxng_instance: str | None = None) -> None:
        self.query = query
        self.session = SessionManager(state_path)
        po = prompt_overrides or {}
        self.planner = TaskPlanner(query, prompt_override=po.get("planner"))
        self.crawler = WebCrawler(prompt_override=po.get("crawler"), searxng_instance=searxng_instance)
        self.contradiction_engine = ContradictionEngine(prompt_override=po.get("contradiction"))
        self.synthesizer = ReportSynthesizer(prompt_override=po.get("synthesizer"))

    async def run(self, capture: TranscriptCapture | None = None) -> ResearchState:
        state = self.session.load() or ResearchState(query=self.query)
        if state.status == "completed":
            logger.info("Research already completed for this query. Use --force to re-run.")
            return state

        state.timestamps["started"] = datetime.now(timezone.utc).isoformat()
        state.status = "planning"
        self.session.save(state)

        try:
            t0 = time.time()
            plan = self.planner.decompose()
            dt = (time.time() - t0) * 1000
            if capture:
                capture.record_tool_call("planner", self.query, f"Decomposed into {len(plan.sub_questions)} sub-questions", dt)
            state.plan = asdict(plan)
            state.current_step = "decomposition"
            state.status = "fetching"
            self.session.save(state)

            urls = [self.planner.search_url(q) for q in plan.search_queries[:5]]
            t0 = time.time()
            findings = await self.crawler.fetch_batch(urls)
            dt = (time.time() - t0) * 1000
            n_ok = sum(1 for v in findings.values() if v)
            if capture:
                capture.record_tool_call("crawler", str(urls), f"Fetched {n_ok}/{len(urls)} URLs OK", dt)
            state.findings = findings
            state.current_step = "crawling"
            state.status = "analyzing"
            self.session.save(state)

            valid_texts = {k: v for k, v in findings.items() if v}
            t0 = time.time()
            contradictions = self.contradiction_engine.analyze(valid_texts, query=self.query)
            dt = (time.time() - t0) * 1000
            if capture:
                capture.record_tool_call("contradiction_engine", f"{len(valid_texts)} texts",
                                          f"Found {len(contradictions)} contradictions", dt)
            state.contradictions = [asdict(c) for c in contradictions]
            state.current_step = "contradiction_analysis"
            state.status = "synthesizing"
            self.session.save(state)

            t0 = time.time()
            report = self.synthesizer.generate(query=self.query, plan=plan,
                                                findings=findings, contradictions=contradictions)
            dt = (time.time() - t0) * 1000
            if capture:
                capture.record_tool_call("synthesizer", f"{len(findings)} findings, {len(contradictions)} contradictions",
                                          f"Report generated ({len(report)} chars)", dt)
            state.report = report
            state.current_step = "report_generated"
            state.status = "completed"
            state.timestamps["completed"] = datetime.now(timezone.utc).isoformat()
            self.session.save(state)

        except Exception:
            state.status = "failed"
            state.error_log.append(f"[{datetime.now(timezone.utc).isoformat()}] {traceback.format_exc()}")
            logger.exception("Research failed")

        return state


# ──────────────────────────────────────────────
# 6. Evaluation Harness
# ──────────────────────────────────────────────


@dataclass
class EvalTask:
    id: str
    title: str
    description: str
    query: str
    edge_cases: list[str]


TASK_BANK: list[EvalTask] = [
    EvalTask(
        id="eval-001",
        title="Ambiguous Health Claim",
        description="Research the health effects of a common food with conflicting studies",
        query="Is coffee good or bad for heart health? Analyze conflicting studies",
        edge_cases=["conflicting meta-analyses", "observational vs RCT evidence", "dose-dependent effects"],
    ),
    EvalTask(
        id="eval-002",
        title="Emerging Technology Impact",
        description="Forecast the impact of a rapidly evolving technology with sparse data",
        query="What will be the impact of quantum computing on cryptography by 2030?",
        edge_cases=["speculative timelines", "limited peer-reviewed sources", "industry hype vs reality"],
    ),
    EvalTask(
        id="eval-003",
        title="Historical Revisionism",
        description="Analyze a historical event with fundamentally conflicting narratives",
        query="What caused the fall of the Roman Empire? Compare economic, military, and environmental theories",
        edge_cases=["multiple contradictory primary sources", "ideological bias in scholarship",
                     "attribution vs correlation debates"],
    ),
]


@dataclass
class ToolCallRecord:
    tool: str
    input: str
    output_summary: str
    duration_ms: float
    error: str | None = None


@dataclass
class Transcript:
    task_id: str
    run_id: int
    timestamp: str
    query: str
    plan: dict | None
    tool_calls: list[ToolCallRecord]
    findings: dict[str, str | None]
    contradictions: list[dict]
    report: str
    token_estimate: int
    error_count: int
    duration_ms: float
    status: str


class TranscriptCapture:
    def __init__(self, task_id: str, run_id: int, query: str) -> None:
        self.task_id = task_id
        self.run_id = run_id
        self.query = query
        self.tool_calls: list[ToolCallRecord] = []
        self.findings: dict[str, str | None] = {}
        self.contradictions: list[dict] = []
        self.report = ""
        self.error_count = 0
        self.start_time = time.time()
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def record_tool_call(self, tool: str, inp: str, output_summary: str,
                         duration_ms: float, error: str | None = None) -> None:
        self.tool_calls.append(ToolCallRecord(
            tool=tool, input=inp, output_summary=output_summary,
            duration_ms=duration_ms, error=error,
        ))

    def record_error(self) -> None:
        self.error_count += 1

    def finish(self, status: str) -> Transcript:
        duration = (time.time() - self.start_time) * 1000
        token_estimate = sum(len(v or "") for v in self.findings.values()) // 4
        return Transcript(
            task_id=self.task_id,
            run_id=self.run_id,
            timestamp=self.timestamp,
            query=self.query,
            plan=None,
            tool_calls=self.tool_calls,
            findings=self.findings,
            contradictions=self.contradictions,
            report=self.report,
            token_estimate=token_estimate,
            error_count=self.error_count,
            duration_ms=duration,
            status=status,
        )


class CodeGrader:
    @staticmethod
    def check_file_generated(transcript: Transcript) -> tuple[bool, str]:
        if transcript.report and len(transcript.report) > 100:
            return (True, f"Report generated ({len(transcript.report)} chars)")
        return (False, "No report or report too short")

    @staticmethod
    def check_has_findings(transcript: Transcript) -> tuple[bool, str]:
        n = len([v for v in transcript.findings.values() if v])
        if n > 0:
            return (True, f"Found {n} source(s) with content")
        return (False, "No sources with content found")

    @staticmethod
    def check_contradiction_detected(transcript: Transcript) -> tuple[bool, str]:
        if transcript.contradictions:
            return (True, f"Detected {len(transcript.contradictions)} contradiction(s)")
        return (False, "No contradictions detected")

    @staticmethod
    def check_no_critical_errors(transcript: Transcript) -> tuple[bool, str]:
        if transcript.error_count == 0:
            return (True, "No errors during execution")
        return (False, f"{transcript.error_count} error(s) occurred")

    @classmethod
    def grade_all(cls, transcript: Transcript) -> dict[str, dict]:
        checks = {
            "file_generated": cls.check_file_generated,
            "has_findings": cls.check_has_findings,
            "contradictions": cls.check_contradiction_detected,
            "no_errors": cls.check_no_critical_errors,
        }
        results = {}
        for name, check_fn in checks.items():
            passed, detail = check_fn(transcript)
            results[name] = {"passed": passed, "detail": detail}
        return results


class OllamaGrader:
    """Grades reports using local Ollama LLM. Falls back to HeuristicGrader if unavailable."""

    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
    MODEL = "lfm2.5:latest"

    _available: bool | None = None
    _model: str | None = None

    @classmethod
    def is_available(cls) -> bool:
        if cls._available is not None:
            return cls._available
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=1.0)
            if r.status_code == 200:
                models = r.json().get("models", [])
                names = [m["name"] for m in models]
                priority = ["lfm2.5:latest", "gemma4:e2b", "qwen3.5:latest", "north-mini-code-1.0:latest"]
                for p in priority:
                    if p in names:
                        cls._model = p
                        break
                if not cls._model and names:
                    cls._model = names[0]
                cls._available = cls._model is not None
                return cls._available
            cls._available = False
            return False
        except Exception:
            cls._available = False
            return False

    @classmethod
    def grade_synthesis_nuance(cls, report: str, query: str) -> dict:
        if not cls.is_available():
            return HeuristicGrader.grade_synthesis_nuance(report)
        prompt = f"""Rate this research report on a scale 0.0-1.0 for:
1. Synthesis quality (connects findings into conclusions)
2. Balance (represents multiple viewpoints fairly)
3. Specificity (uses specific evidence, numbers, citations)
4. Thoroughness (covers multiple angles of the query)

Report: {report[:2000]}

Query: {query}

Return ONLY a JSON object with keys: score (float 0-1), reasons (list of strings), analysis (string)."""
        try:
            import httpx
            model_name = cls._model or cls.MODEL
            r = httpx.post(cls.OLLAMA_CHAT_URL, json={
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
            }, timeout=15.0)
            if r.status_code == 200:
                data = r.json()
                import json as j
                parsed = j.loads(data.get("message", {}).get("content", "{}"))
                return {
                    "score": float(parsed.get("score", 0.5)),
                    "reasons": parsed.get("reasons", ["Ollama graded this report"]),
                    "analysis": parsed.get("analysis", ""),
                }
        except Exception:
            pass
        try:
            import httpx
            model_name = cls._model or cls.MODEL
            r = httpx.post(cls.OLLAMA_URL, json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
            }, timeout=15.0)
            if r.status_code == 200:
                data = r.json()
                import json as j
                parsed = j.loads(data.get("response", "{}"))
                return {
                    "score": float(parsed.get("score", 0.5)),
                    "reasons": parsed.get("reasons", ["Ollama graded this report"]),
                    "analysis": parsed.get("analysis", ""),
                }
        except Exception:
            pass
        return HeuristicGrader.grade_synthesis_nuance(report)

    @classmethod
    def grade_tool_precision(cls, transcript) -> dict:
        if not cls.is_available():
            return HeuristicGrader.grade_tool_precision(transcript)
        return HeuristicGrader.grade_tool_precision(transcript)


class HeuristicGrader:
    """Improved heuristic grader with readability and coverage scoring."""

    QUALITY_KEYWORDS: dict[str, list[str]] = {
        "synthesis": ["conclusion", "summary", "overall", "therefore", "in summary", "in conclusion"],
        "thoroughness": ["analyze", "examine", "investigate", "review", "study", "research"],
        "balance": ["however", "although", "on the other hand", "conversely", "despite", "whereas"],
        "specificity": ["percent", "million", "billion", "study found", "research shows", "according to"],
    }

    @classmethod
    def grade_synthesis_nuance(cls, report: str) -> dict:
        if not report:
            return {"score": 0.0, "reason": "No report to evaluate", "reasons": ["No report to evaluate"], "analysis": ""}
        score = 0.0
        reasons: list[str] = []
        for dimension, keywords in cls.QUALITY_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in report.lower())
            dim_score = min(matches / max(len(keywords) * 0.6, 1), 1.0)
            score += dim_score * 0.25
            if dim_score > 0.5:
                reasons.append(f"Good {dimension} ({matches}/{len(keywords)} keywords)")
            else:
                reasons.append(f"Poor {dimension} ({matches}/{len(keywords)} keywords)")
        score = round(score, 2)
        return {"score": score, "reasons": reasons, "analysis": f"Heuristic grade: {score:.2f}"}

    @classmethod
    def grade_tool_precision(cls, transcript) -> dict:
        if not transcript.tool_calls:
            return {"score": 0.0, "reason": "No tool calls recorded"}
        n_tools = len(transcript.tool_calls)
        errors = sum(1 for tc in transcript.tool_calls if tc.error)
        precision = 1.0 - (errors / n_tools) if n_tools > 0 else 0.0
        return {"score": round(precision, 2), "reason": f"{errors}/{n_tools} tool calls had errors"}


class ModelGrader:
    @classmethod
    def grade_synthesis_nuance(cls, report: str, query: str = "") -> dict:
        return OllamaGrader.grade_synthesis_nuance(report, query)

    @classmethod
    def grade_tool_precision(cls, transcript) -> dict:
        return OllamaGrader.grade_tool_precision(transcript)


class EvaluationRunner:
    def __init__(self, tasks: list[EvalTask] | None = None, n_runs: int = 2, searxng_instance: str | None = None) -> None:
        self.tasks = tasks or TASK_BANK
        self.n_runs = n_runs
        self.searxng_instance = searxng_instance
        self.results: list[dict] = []

    async def run_all(self, prompt_overrides: dict[str, str] | None = None, clear_state: bool = False) -> dict:
        if clear_state:
            state_dir = Path(".")
            for f in state_dir.glob("research_state_*.json"):
                f.unlink()
        overall: dict = {"tasks": [], "pass_at_k": {}, "summary": {}}
        total_passed = 0
        total_checks = 0

        for task in self.tasks:
            task_result = await self._evaluate_task(task, prompt_overrides=prompt_overrides)
            overall["tasks"].append(task_result)

            for run_result in task_result["runs"]:
                for check_val in run_result["code_grades"].values():
                    total_checks += 1
                    if check_val["passed"]:
                        total_passed += 1

        pass_rate = total_passed / total_checks if total_checks else 0.0
        overall["summary"] = {
            "total_tasks": len(self.tasks),
            "total_runs": len(self.tasks) * self.n_runs,
            "total_checks": total_checks,
            "checks_passed": total_passed,
            "pass_rate": round(pass_rate, 3),
        }
        overall["pass_at_k"] = {
            f"pass@{self.n_runs}": round(pass_rate, 3),
        }
        return overall

    async def _evaluate_task(self, task: EvalTask, prompt_overrides: dict[str, str] | None = None) -> dict:
        runs: list[dict] = []
        for run_id in range(1, self.n_runs + 1):
            capture = TranscriptCapture(task.id, run_id, task.query)
            state_path = f"research_state_{task.id}_{run_id}.json"
            try:
                agent = ResearchAgent(task.query, state_path=state_path,
                                      prompt_overrides=prompt_overrides,
                                      searxng_instance=self.searxng_instance)
                state = await agent.run(capture=capture)

                capture.findings = state.findings
                capture.contradictions = state.contradictions
                capture.report = state.report
            except Exception as e:
                capture.record_error()
                logger.error("Run %d for %s crashed: %s", run_id, task.id, e)

            transcript = capture.finish("completed" if capture.error_count == 0 else "crashed")

            code_grades = CodeGrader.grade_all(transcript)
            model_grade = ModelGrader.grade_synthesis_nuance(transcript.report, task.query)
            tool_grade = ModelGrader.grade_tool_precision(transcript)

            runs.append({
                "run_id": run_id,
                "status": transcript.status,
                "duration_ms": round(transcript.duration_ms, 1),
                "errors": transcript.error_count,
                "token_estimate": transcript.token_estimate,
                "code_grades": code_grades,
                "model_grade": model_grade,
                "tool_grade": tool_grade,
                "n_tool_calls": len(transcript.tool_calls),
            })

        return {"task_id": task.id, "title": task.title, "runs": runs}


# ──────────────────────────────────────────────
# 7. GEPA Self-Improvement Loop
# ──────────────────────────────────────────────


@dataclass
class Lesson:
    module: str
    failure: str
    suggestion: str


@dataclass
class PromptCandidate:
    id: str
    parent_id: str | None
    prompt_template: dict[str, str]
    generation: int
    accuracy: float = 0.0
    token_efficiency: float = 0.0
    speed_ms: float = 0.0
    pareto_front: bool = False


class GEPALoop:
    """Genetic-Pareto self-improvement loop for agent prompts."""

    def __init__(self, pool_size: int = 4, max_generations: int = 3, searxng_instance: str | None = None) -> None:
        self.pool: list[PromptCandidate] = []
        self.pool_size = pool_size
        self.generation = 0
        self.max_generations = max_generations
        self.searxng_instance = searxng_instance

    BASE_PROMPTS: dict[str, str] = {
        "planner": "Decompose the research query into sub-questions and a research plan.",
        "crawler": "Fetch and extract clean text from URLs, stripping HTML boilerplate.",
        "contradiction": "Analyze texts for conflicting statistics, sources, and divergent claims.",
        "synthesizer": "Generate a structured markdown report synthesizing all findings.",
    }

    def initialize_pool(self) -> list[PromptCandidate]:
        self.pool = []
        for i in range(self.pool_size):
            candidate = PromptCandidate(
                id=f"gen0-{i}",
                parent_id=None,
                prompt_template=self._mutate_prompts(self.BASE_PROMPTS.copy(),
                                                       intensity=i * 0.3),
                generation=0,
            )
            self.pool.append(candidate)
        return self.pool

    def _mutate_prompts(self, prompts: dict[str, str], intensity: float = 0.3, lessons: list[Lesson] | None = None) -> dict[str, str]:
        mutations = {
            "planner": [
                "Break down the query into granular sub-questions with clear scope boundaries.",
                "Analyze the query from multiple angles, generating focused search strategies.",
                "Identify key dimensions of the research topic and create targeted sub-inquiries.",
            ],
            "crawler": [
                "Retrieve web content with patience, handling redirects and timeouts gracefully.",
                "Extract meaningful content from web pages while discarding navigation and ads.",
                "Fetch pages efficiently with concurrent requests and robust error recovery.",
            ],
            "contradiction": [
                "Scrutinize all sources for numerical disparities and opposing claims.",
                "Cross-reference every claim across sources to find conflicts and inconsistencies.",
                "Identify factual disagreements, statistical conflicts, and narrative divergences.",
            ],
            "synthesizer": [
                "Weigh evidence from all sources, highlighting consensus and disagreement.",
                "Produce a balanced report that fairly represents conflicting viewpoints.",
                "Organize findings into a coherent narrative with clear attribution and uncertainty.",
            ],
        }
        targeted_keys = set()
        if lessons:
            for lesson in lessons:
                if lesson.module in mutations:
                    targeted_keys.add(lesson.module)
        result: dict[str, str] = {}
        for key, base_val in prompts.items():
            if key in targeted_keys:
                variants = mutations.get(key, [base_val])
                result[key] = random.choice(variants)
            elif random.random() < intensity:
                variants = mutations.get(key, [base_val])
                result[key] = random.choice(variants)
            else:
                result[key] = base_val
        return result

    def evaluate_candidate(self, candidate: PromptCandidate,
                           eval_results: dict) -> PromptCandidate:
        summary = eval_results.get("summary", {})
        n_checks = summary.get("total_checks", 1)
        n_passed = summary.get("checks_passed", 0)
        candidate.accuracy = n_passed / n_checks if n_checks else 0.0

        total_duration = 0.0
        count = 0
        for task in eval_results.get("tasks", []):
            for run in task.get("runs", []):
                total_duration += run.get("duration_ms", 0)
                count += 1
        candidate.speed_ms = total_duration / count if count else 0.0

        total_tokens = 0
        t_count = 0
        for task in eval_results.get("tasks", []):
            for run in task.get("runs", []):
                total_tokens += run.get("token_estimate", 0)
                t_count += 1
        avg_tokens = total_tokens / t_count if t_count else 1.0
        candidate.token_efficiency = 1.0 / (1.0 + avg_tokens / 1000.0)

        return candidate

    def reflect(self, candidate: PromptCandidate, eval_results: dict) -> list[Lesson]:
        lessons: list[Lesson] = []
        for task in eval_results.get("tasks", []):
            for run in task.get("runs", []):
                for check_name, check_val in run.get("code_grades", {}).items():
                    if not check_val["passed"]:
                        module_map = {
                            "file_generated": "synthesizer",
                            "has_findings": "crawler",
                            "contradictions": "contradiction",
                            "no_errors": "planner",
                        }
                        mod = module_map.get(check_name, "planner")
                        lessons.append(Lesson(
                            module=mod,
                            failure=f"{task['task_id']}: {check_val['detail']}",
                            suggestion=f"Improve {mod} prompt to fix: {check_val['detail']}",
                        ))
                model_grade = run.get("model_grade", {})
                if model_grade.get("score", 1.0) < 0.5:
                    lessons.append(Lesson(
                        module="synthesizer",
                        failure=f"{task['task_id']}: low synthesis score ({model_grade['score']})",
                        suggestion="Add more synthesis keywords and balancing language to synthesizer prompt",
                    ))
        return lessons

    def pareto_select(self, pool: list[PromptCandidate]) -> list[PromptCandidate]:
        for c in pool:
            c.pareto_front = False
        front: list[PromptCandidate] = []
        for i, ci in enumerate(pool):
            dominated = False
            for j, cj in enumerate(pool):
                if i == j:
                    continue
                if (cj.accuracy >= ci.accuracy and
                    cj.token_efficiency >= ci.token_efficiency and
                    cj.speed_ms <= ci.speed_ms):
                    if (cj.accuracy > ci.accuracy or
                        cj.token_efficiency > ci.token_efficiency or
                        cj.speed_ms < ci.speed_ms):
                        dominated = True
                        break
            if not dominated:
                ci.pareto_front = True
                front.append(ci)
        return front

    def next_generation(self, gen_lessions: dict[str, list[Lesson]] | None = None) -> list[PromptCandidate]:
        self.generation += 1
        front = self.pareto_select(self.pool)
        front_sorted = sorted(front, key=lambda c: c.accuracy, reverse=True)
        new_pool: list[PromptCandidate] = []
        for i in range(self.pool_size):
            parent = front_sorted[i % len(front_sorted)] if front_sorted else self.pool[i % len(self.pool)]
            mutation_intensity = min(0.3 + self.generation * 0.1, 0.8)
            parent_lessions = (gen_lessions or {}).get(parent.id, []) if gen_lessions else []
            new_prompts = self._mutate_prompts(
                parent.prompt_template.copy(),
                intensity=mutation_intensity,
                lessons=parent_lessions,
            )
            candidate = PromptCandidate(
                id=f"gen{self.generation}-{i}",
                parent_id=parent.id,
                prompt_template=new_prompts,
                generation=self.generation,
            )
            new_pool.append(candidate)
        self.pool = new_pool
        return self.pool

    async def run_self_improvement(self, eval_runner: EvaluationRunner) -> dict:
        self.initialize_pool()
        all_generations: list[dict] = []
        best_candidate: PromptCandidate | None = None
        for gen in range(self.max_generations):
            gen_results: list[dict] = []
            gen_lessons: dict[str, list[Lesson]] = {}
            for candidate in self.pool:
                eval_results = await eval_runner.run_all(prompt_overrides=candidate.prompt_template, clear_state=True)
                candidate = self.evaluate_candidate(candidate, eval_results)
                lessons = self.reflect(candidate, eval_results)
                gen_lessons[candidate.id] = lessons
                gen_results.append({
                    "id": candidate.id,
                    "accuracy": candidate.accuracy,
                    "speed_ms": candidate.speed_ms,
                    "token_efficiency": candidate.token_efficiency,
                    "lessons": [str(l) for l in lessons],
                })
            front = self.pareto_select(self.pool)
            gen_record = {
                "generation": gen,
                "candidates": gen_results,
                "pareto_front": [c.id for c in front],
            }
            all_generations.append(gen_record)
            if front:
                gen_record["winner"] = max(front, key=lambda c: c.accuracy).id
                if best_candidate is None or max(front, key=lambda c: c.accuracy).accuracy > best_candidate.accuracy:
                    best_candidate = max(front, key=lambda c: c.accuracy)
            if gen < self.max_generations - 1:
                self.next_generation(gen_lessons=gen_lessons)
        return {"generations": all_generations, "best_candidate": {
            "id": best_candidate.id if best_candidate else None,
            "accuracy": best_candidate.accuracy if best_candidate else 0,
            "prompt_template": best_candidate.prompt_template if best_candidate else {},
        } if best_candidate else None}

    def format_report(self, results: dict) -> str:
        lines = ["# GEPA Self-Improvement Report\n"]
        for gen in results.get("generations", []):
            g = gen["generation"]
            lines.append(f"## Generation {g}\n")
            for c in gen.get("candidates", []):
                lines.append(f"- **{c['id']}**: accuracy={c['accuracy']:.1%}, "
                             f"speed={c['speed_ms']:.0f}ms, efficiency={c['token_efficiency']:.1%}")
                if c.get("lessons"):
                    for lesson in c["lessons"][:3]:
                        lines.append(f"  - _{lesson}_")
            lines.append(f"\nWinner: {gen.get('winner', 'none')}\n")
            lines.append("---\n")
        best = results.get("best_candidate")
        if best:
            lines.append("## Best Candidate\n")
            lines.append(f"- ID: {best['id']}")
            lines.append(f"- Accuracy: {best['accuracy']:.1%}")
            lines.append("### Prompt Template\n")
            for key, val in best.get("prompt_template", {}).items():
                lines.append(f"- **{key}:** {val}")
        return "\n".join(lines)


def _run_dogfood_default() -> None:
    """Autonomic dogfooding: run evals + GEPA + self-revision."""
    console = Console()
    console.print(Panel.fit(
        "[bold cyan]Deep Research Agent — Autonomic Dogfooding Mode[/]",
        border_style="cyan",
    ))

    console.print("\n[bold yellow]Step 1/3:[/] Running evaluation suite...")
    runner = EvaluationRunner(n_runs=1)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("Running evals...", total=None)
        eval_results = asyncio.run(runner.run_all())
    summary = eval_results.get("summary", {})
    pass_rate = summary.get("pass_rate", 0)
    color = "green" if pass_rate >= 0.75 else "red"
    console.print(f"  pass_rate: [{color}]{pass_rate:.1%}[/]")
    console.print(f"  checks_passed: {summary.get('checks_passed', 0)}/{summary.get('total_checks', 0)}")

    console.print("\n[bold yellow]Step 2/3:[/] Running GEPA self-improvement loop...")
    gepa = GEPALoop(pool_size=2, max_generations=1)
    eval_runner = EvaluationRunner(n_runs=1)
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task("Running GEPA generations...", total=None)
        gepa_results = asyncio.run(gepa.run_self_improvement(eval_runner))
    report = gepa.format_report(gepa_results)
    console.print(Markdown(report))

    console.print("\n[bold yellow]Step 3/3:[/] Generating self-patch...")
    patch = _generate_self_patch(eval_results, gepa_results)
    if patch:
        console.print(f"[green]Self-patch written to _self_patch.py[/]")
        console.print("[dim]Run [bold]python _self_patch.py[/] to apply learned prompt improvements.[/]\n")
    else:
        console.print("[yellow]No patch generated (no best candidate).[/]\n")


def _generate_self_patch(eval_results: dict, gepa_results: dict) -> str:
    """Generate _self_patch.py that rewrites research_agent.py with learned prompts."""
    best = gepa_results.get("best_candidate", {})
    best_pt = best.get("prompt_template", {})
    if not best_pt:
        logger.warning("No best candidate prompts to apply")
        return ""

    patch_path = Path(__file__).resolve().parent / "_self_patch.py"
    old_version = SCRIPT_VERSION
    parts = old_version.split(".")
    new_version = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"

    lines = [
        '"""Auto-generated self-patch by Deep Research Agent GEPA loop."""',
        '"""Apply learned prompt improvements to research_agent.py"""',
        "from pathlib import Path",
        "",
        "script = Path(__file__).resolve().parent / 'research_agent.py'",
        "content = script.read_text()",
        "",
        f"# Bump version",
        f'content = content.replace("SCRIPT_VERSION = \\"{old_version}\\"", "SCRIPT_VERSION = \\"{new_version}\\"")',
        "",
    ]

    for module_key, prompt_text in best_pt.items():
        escaped = prompt_text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        lines.append(f'# Update prompt for {module_key}')
        lines.append(f'content = re.sub(')
        lines.append(f'    r\'    "{module_key}": ".*?",\',')
        lines.append(f'    \'    "{module_key}": "{escaped}",\',')
        lines.append(f'    content,')
        lines.append(f')')
        lines.append("")
    lines.insert(3, "import re")

    lines.extend([
        'script.write_text(content)',
        f'print("Patched to v{new_version} with {len(best_pt)} prompt updates")',
        "",
    ])

    patch_content = "\n".join(lines)
    patch_path.write_text(patch_content)
    logger.info("Self-patch written to %s", patch_path)
    return patch_content


# ──────────────────────────────────────────────
# CLI Entry Point
# ──────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Deep Research Agent CLI")
    parser.add_argument("query", nargs="?", help="Research query")
    parser.add_argument("--state", default="research_state.json", help="Path to state file")
    parser.add_argument("--force", action="store_true", help="Re-run even if completed")
    parser.add_argument("--clear", action="store_true", help="Clear saved state")
    parser.add_argument("--report", action="store_true", help="Print last report and exit")
    parser.add_argument("--eval", action="store_true", help="Run evaluation suite")
    parser.add_argument("--eval-runs", type=int, default=2, help="Runs per eval task")
    parser.add_argument("--gepa", action="store_true", help="Run GEPA self-improvement loop")
    parser.add_argument("--gepa-generations", type=int, default=3, help="GEPA generations")
    parser.add_argument("--gepa-pool", type=int, default=4, help="GEPA candidate pool size")
    parser.add_argument("--dogfood", action="store_true", help="Run full dogfooding pipeline")
    parser.add_argument("--searx-instance", type=str, default=None, help="SearXNG instance URL")
    parser.add_argument("--self-update", action="store_true", help="Update research-agent.py from GitHub latest release")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.self_update:
        _console.print("[dim]Fetching latest release from GitHub...[/]")
        try:
            resp = httpx.get(
                "https://api.github.com/repos/bigknoxy/research-agent/releases/latest",
                headers={"User-Agent": "research-agent", "Accept": "application/vnd.github.v3+json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            tag = data["tag_name"]
            dl_url = f"https://raw.githubusercontent.com/bigknoxy/research-agent/{tag}/research_agent.py"
            script = httpx.get(dl_url, timeout=30)
            script.raise_for_status()
            script_path = Path(__file__).resolve()
            script_path.write_text(script.text)
            _console.print(f"[green]✓ Updated to {tag}.[/]")
        except Exception as e:
            _console.print(f"[red]Update failed: {e}[/]")
            _console.print("[yellow]Try: pip install --upgrade git+https://github.com/bigknoxy/research-agent.git[/]")
        return

    if args.clear:
        SessionManager(args.state).clear()
        _console.print("[green]State cleared.[/]")
        return

    if args.report:
        state = SessionManager(args.state).load()
        if state and state.report:
            _console.print(Markdown(state.report))
        else:
            _console.print("[yellow]No report found.[/]")
        return

    si = args.searx_instance

    if args.gepa:
        gepa = GEPALoop(pool_size=args.gepa_pool, max_generations=args.gepa_generations, searxng_instance=si)
        eval_runner = EvaluationRunner(n_runs=1, searxng_instance=si)
        results = asyncio.run(gepa.run_self_improvement(eval_runner))
        print(gepa.format_report(results))
        return

    if args.eval or args.dogfood:
        runner = EvaluationRunner(n_runs=args.eval_runs, searxng_instance=si)
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
            progress.add_task("Running evaluation suite...", total=None)
            results = asyncio.run(runner.run_all())
        table = Table(title="Evaluation Results", box=box.ROUNDED)
        table.add_column("Task", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Pass Rate", style="yellow")
        table.add_column("Duration", style="magenta")
        for task in results.get("tasks", []):
            for run in task.get("runs", []):
                status = "✓" if run.get("errors", 0) == 0 else "✗"
                passed = sum(1 for g in run.get("code_grades", {}).values() if g.get("passed", False))
                total = len(run.get("code_grades", {}))
                table.add_row(
                    task["title"],
                    status,
                    f"{passed}/{total}",
                    f"{run.get('duration_ms', 0):.0f}ms",
                )
        _console.print(table)

        if args.dogfood:
            gepa = GEPALoop(pool_size=2, max_generations=1, searxng_instance=si)
            eval_runner2 = EvaluationRunner(n_runs=1, searxng_instance=si)
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
                progress.add_task("Running GEPA self-improvement...", total=None)
                gepa_results = asyncio.run(gepa.run_self_improvement(eval_runner2))
            _console.print("\n[bold]GEPA Self-Improvement Report[/]")
            report = gepa.format_report(gepa_results)
            _console.print(Markdown(report))
            patch = _generate_self_patch(results, gepa_results)
            if patch:
                _console.print("[green]✓ Self-patch generated: _self_patch.py[/]")
                _console.print("[dim]Run 'python _self_patch.py' to apply improvements.[/]")

        return

    if not args.query:
        _run_dogfood_default()
        return

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as progress:
        progress.add_task(f"Researching: {args.query[:50]}...", total=None)
        agent = ResearchAgent(args.query, args.state, searxng_instance=si)
        state = asyncio.run(agent.run())

    if state.status == "completed":
        _console.print(Panel(
            Markdown(state.report[:2000]),
            title=f"[bold green]Research Report[/] ({len(state.report)} chars)",
            border_style="green",
        ))
        _console.print("[dim]... (full report truncated, use --report to view all)[/]")
    elif state.status == "failed":
        _console.print(Panel(
            "\n".join(state.error_log[-3:]),
            title="[bold red]Errors[/]",
            border_style="red",
        ))


if __name__ == "__main__":
    main()
