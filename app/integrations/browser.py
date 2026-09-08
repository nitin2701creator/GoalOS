"""Browser automation integration for GoalOS."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol
from typing_extensions import Self
from urllib.parse import urlparse

import trio
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from app.agents.permissions import Permission
from app.integrations.exceptions import CapabilityUnavailableError


class BrowserProvider(Protocol):
    """Abstraction over a browser automation provider."""

    name: str

    @asynccontextmanager
    async def launch(
        self,
        headless: bool,
        timeout: float,
        persistent_profile_path: str | None,
    ) -> (
        tuple[Browser, BrowserContext, Page]
        | tuple[Browser, BrowserContext]
    ): ...

    async def goto(self, page: Page, url: str, timeout: float) -> None: ...
    async def click(self, page: Page, selector: str, timeout: float) -> None: ...
    async def fill(self, page: Page, selector: str, value: str, timeout: float) -> None: ...
    async def type(self, page: Page, selector: str, value: str, timeout: float) -> None: ...
    async def select(
        self, page: Page, selector: str, value: str, timeout: float
    ) -> None: ...
    async def wait_for_selector(
        self, page: Page, selector: str, timeout: float
    ) -> None: ...
    async def wait_for_url(
        self, page: Page, url_regex: str, timeout: float
    ) -> None: ...
    async def extract_text(self, page: Page, selector: str) -> str | None: ...
    async def extract_attribute(
        self, page: Page, selector: str, attribute: str
    ) -> str | None: ...
    async def screenshot(self, page: Page, path: str) -> None: ...
    async def close(self, browser: Browser) -> None: ...

logger = logging.getLogger(__name__)


class BrowserProvider(Protocol):
    """Abstraction over a browser automation provider."""

    name: str

    @asynccontextmanager
    async def launch(
        self,
        headless: bool,
        timeout: float,
        persistent_profile_path: str | None,
    ) -> (
        tuple[Browser, BrowserContext, Page]
        | tuple[BrowserContext, Page]
    ): ...

    async def goto(self, page: Page, url: str, timeout: float) -> None: ...
    async def click(self, page: Page, selector: str, timeout: float) -> None: ...
    async def fill(self, page: Page, selector: str, value: str, timeout: float) -> None: ...
    async def type(self, page: Page, selector: str, value: str, timeout: float) -> None: ...
    async def select(
        self, page: Page, selector: str, value: str, timeout: float
    ) -> None: ...
    async def wait_for_selector(
        self, page: Page, selector: str, timeout: float
    ) -> None: ...
    async def wait_for_url(
        self, page: Page, url_regex: str, timeout: float
    ) -> None: ...
    async def extract_text(self, page: Page, selector: str) -> str | None: ...
    async def extract_attribute(
        self, page: Page, selector: str, attribute: str
    ) -> str | None: ...
    async def screenshot(self, page: Page, path: str) -> None: ...
    async def close(self, browser: PlaywrightBrowserInstance) -> None: ...


class PlaywrightBrowser(BrowserProvider):
    """Playwright implementation of the browser provider."""

    name: str = "playwright"
    _playwright: Playwright | None = None
    _browser_instances: dict[str, PlaywrightBrowserInstance] = {}

    @classmethod
    async def _ensure_playwright_context(cls) -> None:
        if cls._playwright is None:
            cls._playwright = await async_playwright().start()

    @classmethod
    async def _close_playwright_context(cls) -> None:
        if cls._playwright:
            await cls._playwright.stop()
            cls._playwright = None


    async def launch(
        self,
        headless: bool,
        timeout: float,
        persistent_profile_path: str | None,
    ) -> tuple[Browser, BrowserContext, Page]:
        await self._ensure_playwright_context()
        browser_type = self._playwright.chromium
        launch_options = {
            "headless": headless,
            "timeout": int(timeout * 1000),  # Playwright expects ms
        }

        if persistent_profile_path:
            browser_context = await browser_type.launch_persistent_context(
                persistent_profile_path, **launch_options
            )
            self._browser_instances[persistent_profile_path] = browser_context
            page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
            return browser_context.browser, browser_context, page
        else:
            browser = await browser_type.launch(**launch_options)
            context = await browser.new_context()
            page = await context.new_page()
            return browser, context, page

    async def goto(self, page: Page, url: str, timeout: float) -> None:
        await page.goto(url, timeout=int(timeout * 1000))

    async def click(self, page: Page, selector: str, timeout: float) -> None:
        await page.click(selector, timeout=int(timeout * 1000))

    async def fill(self, page: Page, selector: str, value: str, timeout: float) -> None:
        await page.fill(selector, value, timeout=int(timeout * 1000))

    async def type(self, page: Page, selector: str, value: str, timeout: float) -> None:
        await page.type(selector, value, timeout=int(timeout * 1000))

    async def select(
        self, page: Page, selector: str, value: str, timeout: float
    ) -> None:
        await page.select_option(selector, value, timeout=int(timeout * 1000))

    async def wait_for_selector(
        self, page: Page, selector: str, timeout: float
    ) -> None:
        await page.wait_for_selector(selector, timeout=int(timeout * 1000))

    async def wait_for_url(
        self, page: Page, url_regex: str, timeout: float
    ) -> None:
        await page.wait_for_url(re.compile(url_regex), timeout=int(timeout * 1000))

    async def extract_text(self, page: Page, selector: str) -> str | None:
        element = await page.query_selector(selector)
        if element:
            return await element.inner_text()
        return None

    async def extract_attribute(
        self, page: Page, selector: str, attribute: str
    ) -> str | None:
        element = await page.query_selector(selector)
        if element:
            return await element.get_attribute(attribute)
        return None

    async def screenshot(self, page: Page, path: str) -> None:
        await page.screenshot(path=path)

    async def close(self, browser: Browser | BrowserContext) -> None:
        if isinstance(browser, Browser):
            await browser.close()
        else:
            await browser.close()
            await browser.browser.close()


    async def close_all_persistent_sessions(self) -> None:
        for profile_path, browser in list(self._browser_instances.items()):
            if isinstance(browser, BrowserContext):
                await browser.close()
            else:
                await browser.close()
            del self._browser_instances[profile_path]
        await self._close_playwright_context()


@dataclass(frozen=True, slots=True)
class BrowserConfig:
    """Browser operator configuration."""

    enabled: bool = True
    headless: bool = True
    timeout: float = 30.0
    persistent_profile_directory: str = field(default_factory=lambda: tempfile.mkdtemp(prefix="goalos_browser_"))
    screenshot_directory: str = field(default_factory=lambda: tempfile.mkdtemp(prefix="goalos_browser_screenshots_"))
    trace_directory: str = field(default_factory=lambda: tempfile.mkdtemp(prefix="goalos_browser_traces_"))


from app.agents.permissions import Permission
from app.integrations.exceptions import CapabilityUnavailableError
from app.integrations.integration_connector import IntegrationConnector
from typing import Any


class BrowserOperator(IntegrationConnector):
    def connect(self) -> None:
        pass

    def get_capabilities(self) -> tuple[str, ...]:
        return self.capabilities

    def health_check(self) -> ConnectorHealth:
        return self.configuration_health()
    """Browser automation operator with Playwright."""

    required_env_vars: tuple[str, ...] = ("GOALOS_BROWSER_ENABLED",)
    CAPABILITY_PERMISSIONS: dict[str, Permission] = {
        "browser.launch": Permission.BROWSE_WEBSITE,
        "browser.navigate": Permission.BROWSE_WEBSITE,
        "browser.click": Permission.BROWSE_WEBSITE,
        "browser.fill": Permission.BROWSE_WEBSITE,
        "browser.type": Permission.BROWSE_WEBSITE,
        "browser.select": Permission.BROWSE_WEBSITE,
        "browser.wait_for_selector": Permission.BROWSE_WEBSITE,
        "browser.wait_for_url": Permission.BROWSE_WEBSITE,
        "browser.extract_text": Permission.BROWSE_WEBSITE,
        "browser.extract_attribute": Permission.BROWSE_WEBSITE,
        "browser.screenshot": Permission.BROWSE_WEBSITE,
        "browser.close": Permission.BROWSE_WEBSITE,
    }

    def __init__(
        self,
        config: BrowserConfig | None = None,
        provider: BrowserProvider | None = None,
    ) -> None:
        super().__init__(
            name="browser",
            description="Browser automation with Playwright",
        )
        self.config = config or self._load_config()
        self.provider = provider or PlaywrightBrowser()
        self._page: Page | None = None
        self._browser_instance: Browser | BrowserContext | None = None

    def _load_config(self) -> BrowserConfig:
        return BrowserConfig(
            enabled=self._env_to_bool("GOALOS_BROWSER_ENABLED", True),
            headless=self._env_to_bool("GOALOS_BROWSER_HEADLESS", True),
            timeout=self._env_to_float("GOALOS_BROWSER_TIMEOUT", 30.0),
            persistent_profile_directory=self._env(
                "GOALOS_BROWSER_PERSISTENT_PROFILE_DIRECTORY"
            )
            or tempfile.mkdtemp(prefix="goalos_browser_"),
            screenshot_directory=self._env("GOALOS_BROWSER_SCREENSHOT_DIRECTORY")
            or tempfile.mkdtemp(prefix="goalos_browser_screenshots_"),
            trace_directory=self._env("GOALOS_BROWSER_TRACE_DIRECTORY")
            or tempfile.mkdtemp(prefix="goalos_browser_traces_"),
        )

    def _env_to_bool(self, name: str, default: bool) -> bool:
        value = self._env(name)
        if value is None:
            return default
        return value.lower() == "true"

    def _env_to_float(self, name: str, default: float) -> float:
        value = self._env(name)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            logger.warning(
                "Invalid float value for %s: %s. Using default %s", name, value, default
            )
            return default

    def _capabilities(self) -> tuple[str, ...]:
        return tuple(self.CAPABILITY_PERMISSIONS.keys())

    def capability_available(self, capability: str) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "browser integration is disabled"
        return super().capability_available(capability)

    async def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._page or not self._browser_instance:
            if capability != "browser.launch":
                raise CapabilityUnavailableError(
                    "browser not launched; call 'browser.launch' first"
                )

        if capability == "browser.launch":
            return await self._launch_browser(params)
        elif capability == "browser.navigate":
            return await self._navigate(params)
        elif capability == "browser.click":
            return await self._click(params)
        elif capability == "browser.fill":
            return await self._fill(params)
        elif capability == "browser.type":
            return await self._type(params)
        elif capability == "browser.select":
            return await self._select(params)
        elif capability == "browser.wait_for_selector":
            return await self._wait_for_selector(params)
        elif capability == "browser.wait_for_url":
            return await self._wait_for_url(params)
        elif capability == "browser.extract_text":
            return await self._extract_text(params)
        elif capability == "browser.extract_attribute":
            return await self._extract_attribute(params)
        elif capability == "browser.screenshot":
            return await self._screenshot(params)
        elif capability == "browser.close":
            return await self._close_browser()
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    async def _launch_browser(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._browser_instance:
            logger.warning("Browser already launched. Closing existing session.")
            await self._close_browser()

        headless = params.get("headless", self.config.headless)
        persistent = params.get("persistent", False)
        profile_path = (
            self.config.persistent_profile_directory if persistent else None
        )

        try:
            if persistent:
                browser_context, page = await self.provider.launch(
                    headless=headless,
                    timeout=self.config.timeout,
                    persistent_profile_path=profile_path,
                )
                self._browser_instance = browser_context
                self._page = page
            else:
                browser, context, page = await self.provider.launch(
                    headless=headless,
                    timeout=self.config.timeout,
                    persistent_profile_path=None,
                )
                self._browser_instance = browser
                self._page = page

            logger.info("Browser launched successfully: headless=%s, persistent=%s", headless, persistent)
            return {"status": "success", "message": "browser launched", "url": self._page.url if self._page else ''}
        except Exception as e:
            logger.error("Failed to launch browser: %s", e)
            raise CapabilityUnavailableError(f"failed to launch browser: {e}") from e

    async def _navigate(self, params: dict[str, Any]) -> dict[str, Any]:
        url = params["url"]
        self._validate_url(url)
        await self.provider.goto(self._page, url, self.config.timeout) # type: ignore
        return {"status": "success", "message": f"navigated to {url}", "url": self._page.url} # type: ignore

    async def _click(self, params: dict[str, Any]) -> dict[str, Any]:
        selector = params["selector"]
        await self.provider.click(self._page, selector, self.config.timeout) # type: ignore
        return {"status": "success", "message": f"clicked {selector}"}

    async def _fill(self, params: dict[str, Any]) -> dict[str, Any]:
        selector = params["selector"]
        value = params["value"]
        await self.provider.fill(self._page, selector, value, self.config.timeout) # type: ignore
        return {"status": "success", "message": f"filled {selector} with value"}

    async def _type(self, params: dict[str, Any]) -> dict[str, Any]:
        selector = params["selector"]
        value = params["value"]
        await self.provider.type(self._page, selector, value, self.config.timeout) # type: ignore
        return {"status": "success", "message": f"typed {selector} with value"}

    async def _select(self, params: dict[str, Any]) -> dict[str, Any]:
        selector = params["selector"]
        value = params["value"]
        await self.provider.select(self._page, selector, value, self.config.timeout) # type: ignore
        return {"status": "success", "message": f"selected {value} in {selector}"}

    async def _wait_for_selector(self, params: dict[str, Any]) -> dict[str, Any]:
        selector = params["selector"]
        await self.provider.wait_for_selector(self._page, selector, self.config.timeout) # type: ignore
        return {"status": "success", "message": f"waited for {selector}"}

    async def _wait_for_url(self, params: dict[str, Any]) -> dict[str, Any]:
        url_regex = params["url_regex"]
        await self.provider.wait_for_url(self._page, url_regex, self.config.timeout) # type: ignore
        return {"status": "success", "message": f"waited for URL matching {url_regex}"}

    async def _extract_text(self, params: dict[str, Any]) -> dict[str, Any]:
        selector = params["selector"]
        text = await self.provider.extract_text(self._page, selector) # type: ignore
        return {"status": "success", "selector": selector, "text": text}

    async def _extract_attribute(self, params: dict[str, Any]) -> dict[str, Any]:
        selector = params["selector"]
        attribute = params["attribute"]
        value = await self.provider.extract_attribute(self._page, selector, attribute) # type: ignore
        return {"status": "success", "selector": selector, "attribute": attribute, "value": value}

    async def _screenshot(self, params: dict[str, Any]) -> dict[str, Any]:
        filename = params.get("filename", "screenshot.png")
        path = os.path.join(self.config.screenshot_directory, filename)
        await self.provider.screenshot(self._page, path) # type: ignore
        return {"status": "success", "message": f"screenshot saved to {path}", "path": path}

    async def _close_browser(self) -> dict[str, Any]:
        if self._browser_instance:
            await self.provider.close(self._browser_instance)
            self._browser_instance = None
            self._page = None
            logger.info("Browser closed successfully.")
        else:
            logger.warning("No browser instance to close.")
        return {"status": "success", "message": "browser closed"}

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"invalid URL: {url}")
        if (
            parsed.netloc == "localhost"
            or parsed.netloc.startswith("127.")
            or parsed.netloc.startswith("10.")
            or parsed.netloc.startswith("192.168.")
        ):
            logger.warning("Access to internal network resource blocked: %s", url)
            raise ValueError("access to internal network resources is blocked")

    async def disconnect(self) -> None:
        if isinstance(self.provider, PlaywrightBrowser):
            await self.provider.close_all_persistent_sessions()
        # Check if parent class has a disconnect method and call it if it exists
        parent_class = type(super())
        if hasattr(parent_class, 'disconnect') and callable(getattr(parent_class, 'disconnect')):
            parent_disconnect = getattr(parent_class, 'disconnect')
            if parent_disconnect.__qualname__.startswith('disconnect'):
                await parent_disconnect(self)
