"""Bounded XML syntax inspection with no resource resolution or code evaluation."""

from codecs import BOM_UTF32_BE, BOM_UTF32_LE
from collections.abc import Callable
from pathlib import Path
from xml.parsers import expat

from devkit.contracts import DevkitError, JSONObject

from devkit_odoo.data_references import LiteralReferences
from devkit_odoo.file_inspection import FileBudget

PARSER_VERSION = expat.EXPAT_VERSION

LIMITS = {
    "file_bytes": 1_048_576,
    "total_bytes": 16_777_216,
    "files": 256,
    "elements": 100_000,
    "depth": 128,
    "reference_events": 4000,
}


class XMLInspection:
    """Share one inspection budget across all modules in an invocation."""

    def __init__(self, checkpoint: Callable[[], None]) -> None:
        self.checkpoint = checkpoint
        self.budget = FileBudget("XML", LIMITS, checkpoint)
        self.elements = 0
        self.events = 0

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
            "events": [],
        }
        try:
            document.parse(self.budget.read(path))
            result["events"] = document.references.events
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

    def consume_event(self) -> None:
        self.events += 1
        if self.events > LIMITS["reference_events"]:
            raise DevkitError(
                "XML_LIMIT", "XML reference event limit exceeded; select fewer modules"
            )


class _Document:
    def __init__(self, inspection: XMLInspection) -> None:
        self.inspection = inspection
        self.depth = 0
        self.references = LiteralReferences(inspection.consume_event)
        self.parser = expat.ParserCreate(namespace_separator="}")
        self.parser.StartElementHandler = self._start
        self.parser.EndElementHandler = self._end
        self.parser.StartDoctypeDeclHandler = self._doctype
        self.parser.ExternalEntityRefHandler = self._external
        self.parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def parse(self, content: bytes) -> None:
        # Expat can report valid UTF-32 as an invalid token; keep this a coverage gap.
        if (
            content.startswith((BOM_UTF32_BE, BOM_UTF32_LE))
            or content[:3] == b"\x00\x00\x00"
            or content[1:4] == b"\x00\x00\x00"
        ):
            raise DevkitError("XML_UNSUPPORTED", "UTF-32 XML is not supported by this inspector")
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
        self.references.start(
            name, attributes, self.parser.CurrentLineNumber, self.parser.CurrentColumnNumber + 1
        )

    def _end(self, name: str) -> None:
        self.references.end()
        self.depth -= 1

    def _doctype(self, name: str, system: str | None, public: str | None, internal: int) -> None:
        raise DevkitError(
            "XML_UNSUPPORTED", "DTD declarations are not supported; no entities loaded"
        )

    def _external(
        self, context: str, base: str | None, system: str | None, public: str | None
    ) -> int:
        raise DevkitError("XML_UNSUPPORTED", "External entities are not supported")
