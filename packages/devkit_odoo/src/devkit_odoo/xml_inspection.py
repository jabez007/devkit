"""Bounded XML syntax inspection with no resource resolution or code evaluation."""

from collections.abc import Callable
from pathlib import Path
from xml.parsers import expat

from devkit.contracts import DevkitError, JSONObject

LIMITS = {
    "file_bytes": 1_048_576,
    "total_bytes": 16_777_216,
    "files": 256,
    "elements": 100_000,
    "depth": 128,
}


class XMLInspection:
    """Share one inspection budget across all modules in an invocation."""

    def __init__(self, checkpoint: Callable[[], None]) -> None:
        self.checkpoint = checkpoint
        self.files = 0
        self.bytes = 0
        self.elements = 0

    def inspect(self, path: Path, relative: str, phase: str) -> JSONObject:
        document = _Document(self)
        result: JSONObject = {
            "path": relative,
            "phase": phase,
            "status": "valid",
            "reason": None,
            "message": "XML is well formed; Odoo runtime semantics are unverified",
            "line": None,
            "column": None,
        }
        try:
            document.parse(self._read(path))
        except expat.ExpatError as exc:
            result.update(
                status="invalid", reason="INVALID_XML", message=expat.ErrorString(exc.code)
            )
        except DevkitError as exc:
            if not exc.reason.startswith("XML_"):
                raise
            result.update(status="blocked", reason=exc.reason, message=str(exc))
        except (LookupError, ValueError):
            result.update(
                status="blocked", reason="XML_UNSUPPORTED", message="Unsupported XML encoding"
            )
        except OSError:
            result.update(
                status="blocked", reason="XML_UNAVAILABLE", message="Cannot read XML; check access"
            )
        if result["status"] != "valid":
            result.update(
                line=document.parser.CurrentLineNumber,
                column=document.parser.CurrentColumnNumber + 1,
            )
        return result

    def _read(self, path: Path) -> bytes:
        self.checkpoint()
        self.files += 1
        if self.files > LIMITS["files"] or self.bytes >= LIMITS["total_bytes"]:
            raise DevkitError("XML_LIMIT", "XML invocation budget exhausted; select fewer modules")
        with path.open("rb") as stream:
            content = stream.read(LIMITS["file_bytes"] + 1)
        self.bytes += len(content)
        if len(content) > LIMITS["file_bytes"] or self.bytes > LIMITS["total_bytes"]:
            raise DevkitError("XML_LIMIT", "XML byte limit exceeded; narrow the inspection")
        return content


class _Document:
    def __init__(self, inspection: XMLInspection) -> None:
        self.inspection = inspection
        self.depth = 0
        self.parser = expat.ParserCreate(namespace_separator="}")
        self.parser.StartElementHandler = self._start
        self.parser.EndElementHandler = self._end
        self.parser.StartDoctypeDeclHandler = self._doctype
        self.parser.ExternalEntityRefHandler = self._external
        self.parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def parse(self, content: bytes) -> None:
        # Chunks allow cooperative cancellation; the input is capped before parsing.
        for start in range(0, len(content), 65_536):
            self.inspection.checkpoint()
            self.parser.Parse(content[start : start + 65_536], False)
        self.inspection.checkpoint()
        self.parser.Parse(b"", True)

    def _start(self, name: str, attributes: dict[str, str]) -> None:
        self.inspection.checkpoint()
        self.depth += 1
        self.inspection.elements += 1
        if self.depth > LIMITS["depth"] or self.inspection.elements > LIMITS["elements"]:
            raise DevkitError("XML_LIMIT", "XML element or nesting limit exceeded")

    def _end(self, name: str) -> None:
        self.depth -= 1

    def _doctype(self, name: str, system: str | None, public: str | None, internal: int) -> None:
        raise DevkitError(
            "XML_UNSUPPORTED", "DTD declarations are not supported; no entities loaded"
        )

    def _external(
        self, context: str, base: str | None, system: str | None, public: str | None
    ) -> int:
        raise DevkitError("XML_UNSUPPORTED", "External entities are not supported")
