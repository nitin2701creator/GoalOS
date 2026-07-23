from pathlib import Path
from unittest.mock import patch

from app.kie.engine import KnowledgeEngine
from app.kie.ocr.base_ocr import OCRProvider, OCRResult
from app.kie.ocr.factory import OCRFactory
from app.kie.ocr.mock_provider import MockOCRProvider
from app.kie.ocr.paddle_provider import PaddleOCRProvider
from app.kie.ocr.router import OCRRouter
from app.kie.ocr.tesseract_provider import TesseractProvider


class StubProvider(OCRProvider):
    def __init__(self, name: str, is_available: bool) -> None:
        self.name = name
        self.is_available = is_available

    def available(self) -> bool:
        return self.is_available

    def extract_text(self, file_path: str | Path) -> OCRResult:
        return OCRResult(text=self.name, engine=self.name)

    def engine_name(self) -> str:
        return self.name


def test_factory_creates_providers_in_selection_order() -> None:
    assert [provider.engine_name() for provider in OCRFactory.create_providers()] == [
        "paddleocr", "tesseract", "mock"
    ]


def test_factory_creates_a_provider_by_name() -> None:
    assert OCRFactory.create_provider("mock").engine_name() == "mock"


def test_router_uses_first_available_provider() -> None:
    router = OCRRouter([StubProvider("first", False), StubProvider("second", True)])
    assert router.select_provider().engine_name() == "second"


def test_router_falls_back_to_mock_provider() -> None:
    router = OCRRouter([StubProvider("unavailable", False), MockOCRProvider()])
    assert router.extract_text("scan.png").engine == "mock"


def test_mock_provider_output_is_predictable() -> None:
    result = MockOCRProvider().extract_text("C:/documents/receipt.png")
    assert result.text == "[Mock OCR text extracted from receipt.png]"
    assert result.engine == "mock"


def test_optional_providers_report_unavailable_without_dependencies() -> None:
    with patch("app.kie.ocr.paddle_provider.find_spec", return_value=None):
        assert PaddleOCRProvider().available() is False
    with patch("app.kie.ocr.tesseract_provider.which", return_value=None):
        assert TesseractProvider().available() is False


def test_engine_uses_ocr_router_for_images(tmp_path: Path) -> None:
    image = tmp_path / "scan.png"
    image.write_bytes(b"not an image")
    engine = KnowledgeEngine(ocr_router=OCRRouter([StubProvider("test-ocr", True)]))

    result = engine.process(image)

    assert result.raw_text == "test-ocr"
