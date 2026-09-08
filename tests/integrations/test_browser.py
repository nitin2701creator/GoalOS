"""Tests for the BrowserOperator integration."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
from typing_extensions import Self

import pytest
from playwright.async_api import BrowserContext, Page

from app.agents.permissions import Permission
from app.integrations.browser import BrowserConfig, BrowserOperator, PlaywrightBrowser
from app.integrations.exceptions import CapabilityUnavailableError


import pytest_asyncio

@pytest_asyncio.fixture
async def browser_operator() -> BrowserOperator:
    import os
    os.environ['GOALOS_BROWSER_ENABLED'] = 'True'

    config = BrowserConfig(
        enabled=True,
        headless=True,
        timeout=5.0,
        persistent_profile_directory=tempfile.mkdtemp(),
        screenshot_directory=tempfile.mkdtemp(),
        trace_directory=tempfile.mkdtemp(),
    )
    provider = PlaywrightBrowser()
    operator = BrowserOperator(config=config, provider=provider)
    yield operator
    await operator.disconnect()


@pytest.mark.asyncio
async def test_browser_launch(browser_operator: BrowserOperator) -> None:
    result = await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "browser launched"


@pytest.mark.asyncio
async def test_browser_navigate(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.navigate", {"url": "https://example.com"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "navigated to https://example.com"


@pytest.mark.asyncio
async def test_browser_click(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://example.com"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.click", {"selector": "a"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "clicked a"


@pytest.mark.asyncio
async def test_browser_fill(browser_operator: BrowserOperator) -> None:
    # Use a page with a known input field for testing
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://www.wikipedia.org"}, permissions={Permission.BROWSE_WEBSITE}
    )
    # Wait for the search input field to load
    await browser_operator.execute(
        "browser.wait_for_selector", {"selector": "input[name='search']"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.fill", {"selector": "input[name='search']", "value": "test"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "filled input[name='search'] with value"


@pytest.mark.asyncio
async def test_browser_type(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://www.wikipedia.org"}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.wait_for_selector", {"selector": "input[name='search']"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.type", {"selector": "input[name='search']", "value": "test"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "typed input[name='search'] with value"


@pytest.mark.asyncio
async def test_browser_select(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://www.wikipedia.org"}, permissions={Permission.BROWSE_WEBSITE}
    )
    # Wait for the language select element to load
    await browser_operator.execute(
        "browser.wait_for_selector", {"selector": "select[name='language']"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.select", {"selector": "select[name='language']", "value": "en"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "selected en in select[name='language']"


@pytest.mark.asyncio
async def test_browser_wait_for_selector(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://example.com"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.wait_for_selector", {"selector": "a"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "waited for a"


@pytest.mark.asyncio
async def test_browser_wait_for_url(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://example.com"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.wait_for_url", {"url_regex": "example.com"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "waited for URL matching example.com"


@pytest.mark.asyncio
async def test_browser_extract_text(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://example.com"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.extract_text", {"selector": "h1"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["selector"] == "h1"


@pytest.mark.asyncio
async def test_browser_extract_attribute(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://example.com"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.extract_attribute", {"selector": "a", "attribute": "href"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["selector"] == "a"
    assert result["attribute"] == "href"


@pytest.mark.asyncio
async def test_browser_screenshot(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    await browser_operator.execute(
        "browser.navigate", {"url": "https://example.com"}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.screenshot", {"filename": "test.png"}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == f"screenshot saved to {browser_operator.config.screenshot_directory}/test.png"
    assert os.path.exists(result["path"])


@pytest.mark.asyncio
async def test_browser_close(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    result = await browser_operator.execute(
        "browser.close", {}, permissions={Permission.BROWSE_WEBSITE}
    )
    assert result["status"] == "success"
    assert result["message"] == "browser closed"


@pytest.mark.asyncio
async def test_browser_disabled() -> None:
    config = BrowserConfig(enabled=False)
    operator = BrowserOperator(config=config)
    with pytest.raises(CapabilityUnavailableError):
        await operator.execute(
            "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
        )


@pytest.mark.asyncio
async def test_browser_invalid_url(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    with pytest.raises(ValueError):
        await browser_operator.execute(
            "browser.navigate", {"url": "invalid-url"}, permissions={Permission.BROWSE_WEBSITE}
        )


@pytest.mark.asyncio
async def test_browser_internal_network_blocked(browser_operator: BrowserOperator) -> None:
    await browser_operator.execute(
        "browser.launch", {"headless": True}, permissions={Permission.BROWSE_WEBSITE}
    )
    with pytest.raises(ValueError):
        await browser_operator.execute(
            "browser.navigate", {"url": "http://localhost"}, permissions={Permission.BROWSE_WEBSITE}
        )
