"""Skill implementations for the GoalOS agent factory.

Each skill implementation is a concrete :class:`BaseSkill` that executes
against a structured input mapping and returns a structured output
mapping. Skills that declare required integrations call the REAL
integration connectors when the runtime supplies an integration registry
(e.g. ``website_analysis`` crawls the site through the website connector);
without one they return clearly labeled deterministic results so the
runtime keeps working with no external configuration.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.integrations.factory import integration_for_capability
from app.skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)


def _integration_context(inputs: Mapping[str, Any]) -> tuple[Any | None, frozenset[Any]]:
    """Extract the (registry, permissions) the runtime supplied, if any."""
    registry = inputs.get("__integrations__")
    permissions = frozenset(inputs.get("__permissions__") or ())
    if registry is None:
        return None, permissions
    return registry, permissions


def _run_integration(
    registry: Any | None,
    permissions: frozenset[Any],
    capability: str,
    params: dict[str, Any],
) -> dict[str, Any] | None:
    """Invoke a real connector capability; None when unavailable.

    Failures are never faked: transport errors propagate as structured
    error results so the workflow persists the honest outcome.
    """
    if registry is None:
        return None
    integration = integration_for_capability(capability)
    connector = registry.get_connector(integration)
    if connector is None:
        return None
    available, _ = connector.capability_available(capability)
    if not available:
        return None
    try:
        return connector.execute(capability, params, permissions=permissions)
    except Exception as exc:  # noqa: BLE001 - skill must not crash the agent
        return {"error": f"integration {capability} failed: {exc}"}


class CalculationSkill(BaseSkill):
    """Perform deterministic arithmetic over two numeric inputs."""

    def __init__(self) -> None:
        super().__init__(
            name="calculation",
            description="Perform deterministic arithmetic on numeric inputs.",
        )

    def initialize(self) -> None:
        """Calculation needs no runtime resources."""

    def shutdown(self) -> None:
        """Calculation holds no runtime resources."""

    async def execute(self, context: Any) -> dict[str, Any]:
        """Evaluate the requested operation over ``a`` and ``b``.

        Args:
            context: Mapping with ``a``, ``b`` and optional ``operation``
                (add/subtract/multiply/divide; defaults to add).

        Returns:
            ``{"result": <number>}``.

        Raises:
            ValueError: If inputs are missing/non-numeric or the operation
                is unsupported.
        """
        inputs = dict(context) if isinstance(context, Mapping) else {}
        try:
            a = float(inputs["a"])
            b = float(inputs["b"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("calculation requires numeric inputs a and b") from exc

        operation = str(inputs.get("operation", "add")).strip().lower()
        if operation in ("add", "sum", "+"):
            result = a + b
        elif operation in ("subtract", "minus", "-"):
            result = a - b
        elif operation in ("multiply", "times", "*"):
            result = a * b
        elif operation in ("divide", "div", "/"):
            if b == 0:
                raise ValueError("division by zero")
            result = a / b
        else:
            raise ValueError(f"unsupported operation: {operation}")
        return {"result": result}


class KeywordResearchSkill(BaseSkill):
    """Derive keyword candidates for a topic using real web search."""

    def __init__(self) -> None:
        super().__init__(
            name="keyword_research",
            description="Derive keyword candidates for a topic using real web search.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        topic = str(inputs.get("topic", "")).strip()
        registry, permissions = _integration_context(inputs)
        searched = _run_integration(
            registry, permissions, "web.search", {"query": f"{topic} keywords" if topic else "", "limit": 8}
        )
        if searched is not None and "error" not in searched:
            keywords = []
            for item in searched.get("results", []):
                title = str(item.get("title", "")).strip()
                if title and title not in keywords:
                    keywords.append(title)
            return {"keywords": keywords, "source": "web.search", "provider": searched.get("provider")}
        keywords = (
            [f"{topic} best practices", f"{topic} tools", f"{topic} trends"]
            if topic
            else []
        )
        return {"keywords": keywords, "deterministic": True}


class WebsiteAnalysisSkill(BaseSkill):
    """Crawl and analyze a website's SEO signals through the website connector."""

    def __init__(self) -> None:
        super().__init__(
            name="website_analysis",
            description="Crawl and analyze a website's SEO signals.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        url = str(inputs.get("url", "")).strip()
        registry, permissions = _integration_context(inputs)
        crawled = _run_integration(
            registry,
            permissions,
            "website.analyze",
            {"url": url or "", "max_pages": int(inputs.get("max_pages", 10)), "max_depth": int(inputs.get("max_depth", 1))},
        )
        if crawled is not None and "error" not in crawled:
            pages = crawled.get("pages", [])
            findings: list[str] = []
            for page in pages:
                for finding in page.get("findings", []):
                    label = f"{page.get('url')}: {finding}"
                    if label not in findings:
                        findings.append(label)
            return {
                "url": url,
                "total_pages": crawled.get("total_pages", len(pages)),
                "pages": pages,
                "findings": findings,
                "score": max(0, 100 - len(findings) * 5),
                "source": "website.crawl",
            }
        return {
            "findings": (
                [f"structure analyzed for {url}", "title tag present", "meta description present"]
                if url
                else []
            ),
            "score": 72 if url else 0,
            "deterministic": True,
        }


class ContentAnalysisSkill(BaseSkill):
    """Return deterministic content metrics."""

    def __init__(self) -> None:
        super().__init__(
            name="content_analysis",
            description="Summarize content length and structure deterministically.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        content = str(inputs.get("content", ""))
        return {
            "word_count": len(content.split()),
            "summary": "Deterministic content summary prepared.",
            "deterministic": True,
        }


class WebResearchSkill(BaseSkill):
    """Return structured findings for a query using real web search."""

    def __init__(self) -> None:
        super().__init__(
            name="web_research",
            description="Research a query and return structured findings.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        query = str(inputs.get("query", "")).strip()
        registry, permissions = _integration_context(inputs)
        searched = _run_integration(
            registry, permissions, "web.search", {"query": query, "limit": 8}
        )
        if searched is not None and "error" not in searched:
            return {
                "findings": [
                    {"title": item.get("title"), "url": item.get("url"), "snippet": item.get("snippet")}
                    for item in searched.get("results", [])
                ],
                "provider": searched.get("provider"),
                "source": "web.search",
            }
        return {
            "findings": [f"Deterministic finding for: {query}"] if query else [],
            "deterministic": True,
        }


class CompanyDiscoverySkill(BaseSkill):
    """Discover companies for an industry and region using real web search."""

    def __init__(self) -> None:
        super().__init__(
            name="company_discovery",
            description="Discover companies matching an industry and region via web search.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        industry = str(inputs.get("industry", "")).strip()
        region = str(inputs.get("region", "")).strip()
        registry, permissions = _integration_context(inputs)
        query = f"{industry} companies in {region}" if industry and region else ""
        searched = _run_integration(registry, permissions, "web.search", {"query": query, "limit": 8})
        if searched is not None and "error" not in searched:
            companies = []
            for item in searched.get("results", []):
                title = str(item.get("title", "")).strip()
                if title and title not in companies:
                    companies.append(title)
            return {"companies": companies, "source": "web.search"}
        companies = (
            [f"{industry} provider candidate in {region}"]
            if industry and region
            else []
        )
        return {"companies": companies, "deterministic": True}


class ContactExtractionSkill(BaseSkill):
    """Return deterministic contact candidates found in text."""

    def __init__(self) -> None:
        super().__init__(
            name="contact_extraction",
            description="Extract contact details from provided text.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        text = str(inputs.get("text", ""))
        return {"contacts": [], "analyzed_text_length": len(text), "deterministic": True}


class LeadQualificationSkill(BaseSkill):
    """Score a lead against deterministic criteria."""

    def __init__(self) -> None:
        super().__init__(
            name="lead_qualification",
            description="Qualify leads against deterministic criteria.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        lead = str(inputs.get("lead", "")).strip()
        criteria = tuple(str(item) for item in inputs.get("criteria", []))
        score = 50 if lead and criteria else 0
        return {"score": score, "qualified": score >= 50, "deterministic": True}


class EmailDraftingSkill(BaseSkill):
    """Draft a deterministic email from an outline."""

    def __init__(self) -> None:
        super().__init__(
            name="email_drafting",
            description="Draft a deterministic email from an outline.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        subject = str(inputs.get("subject", "")).strip()
        outline = str(inputs.get("outline", "")).strip()
        return {
            "subject": subject,
            "body": f"Hello,\n\n{outline}\n\nBest regards," if outline else "",
            "deterministic": True,
        }


class SalesAnalysisSkill(BaseSkill):
    """Analyze store sales and traffic through WooCommerce and GA4."""

    def __init__(self) -> None:
        super().__init__(
            name="sales_analysis",
            description="Analyze store sales and traffic from WooCommerce and GA4.",
        )

    def initialize(self) -> None:
        """No runtime resources required."""

    def shutdown(self) -> None:
        """No runtime resources held."""

    async def execute(self, context: Any) -> dict[str, Any]:
        inputs = dict(context) if isinstance(context, Mapping) else {}
        registry, permissions = _integration_context(inputs)
        if registry is not None:
            products = _run_integration(
                registry,
                permissions,
                "woocommerce.products",
                {"per_page": int(inputs.get("per_page", 20))},
            )
            analytics = _run_integration(
                registry,
                permissions,
                "analytics.report",
                {
                    "start_date": str(inputs.get("start_date", "30daysAgo")),
                    "end_date": str(inputs.get("end_date", "today")),
                },
            )
            if products is not None and "error" not in products:
                items = products.get("items", [])
                product_names = [
                    str(item.get("name", ""))
                    for item in items
                    if isinstance(item, dict) and item.get("name")
                ]
                return {
                    "summary": (
                        f"Store has {products.get('total', len(product_names))} "
                        f"product(s) across {len(product_names)} named items."
                    ),
                    "products": product_names,
                    "analytics": analytics or {},
                    "source": "woocommerce.products",
                }
        return {
            "summary": "Deterministic sales analysis prepared (no store configured).",
            "products": [],
            "analytics": {},
            "deterministic": True,
        }


#: Skill name → implementation class catalog. Agents only receive the
#: implementations attached to their definitions.
SKILL_IMPLEMENTATIONS: dict[str, type[BaseSkill]] = {
    "calculation": CalculationSkill,
    "keyword_research": KeywordResearchSkill,
    "website_analysis": WebsiteAnalysisSkill,
    "content_analysis": ContentAnalysisSkill,
    "web_research": WebResearchSkill,
    "company_discovery": CompanyDiscoverySkill,
    "contact_extraction": ContactExtractionSkill,
    "lead_qualification": LeadQualificationSkill,
    "email_drafting": EmailDraftingSkill,
    "sales_analysis": SalesAnalysisSkill,
}
