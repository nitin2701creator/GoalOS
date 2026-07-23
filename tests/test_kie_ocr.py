"""Tests for the OCR provider framework."""

from pathlib import Path

from app.kie.ocr.factory import OCRFactory
from app.kie.ocr.mock_provider import MockOCRProvider
from app.kie.ocr.router import OCRRouter


def test_factory_creates_three_providers():
    providers = OCRFactory.create_providers()

    assert len(providers) == 3


def test_factory_returns_mock_provider():
    provider = OCRFactory.create_provider("mock")

    assert isinstance(provider, MockOCRProvider)


def test_router_falls_back_to_mock():
    router = OCRRouter(
        providers=(
            MockOCRProvider(),
        )
    )

    provider = router.select_provider()

    assert provider.engine_name() == "mock"


def test_mock_provider_extracts_text():
    provider = MockOCRProvider()

    result = provider.extract_text(Path("invoice.pdf"))

    assert "invoice.pdf" in result.text
    assert result.engine == "mock"


def test_router_extract_text():
    router = OCRRouter(
        providers=(
            MockOCRProvider(),
        )
    )

    result = router.extract_text("invoice.pdf")

    assert result.engine == "mock"
    assert "invoice.pdf" in result.text