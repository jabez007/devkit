"""Bounded Odoo CSV source inspection, without runtime imports or field conversion."""

import csv
import io
import re
from collections.abc import Callable
from pathlib import Path

from mccann_hub.devkit.contracts import DevkitError, JSONObject
from mccann_hub.devkit_odoo.file_inspection import FileBudget

LIMITS = {
    "file_bytes": 1_048_576,
    "total_bytes": 16_777_216,
    "files": 256,
    "rows": 10_000,
    "columns": 128,
    "field_chars": 65_536,
    "reference_events": 4000,
}
HEADER = re.compile(r"\w+(?:(?:/|:)id)?")


class CSVInspection:
    def __init__(self, checkpoint: Callable[[], None]) -> None:
        self.checkpoint = checkpoint
        self.budget = FileBudget("CSV", LIMITS, checkpoint)
        self.rows = 0
        self.events = 0

    def inspect(self, path: Path, relative: str, phase: str) -> JSONObject:
        result: JSONObject = {
            "path": relative,
            "phase": phase,
            "status": "valid",
            "reason": None,
            "message": "CSV structure inspected; runtime field semantics are unverified",
            "line": None,
            "column": None,
            "events": [],
            "headers": [],
            "row_count": 0,
            "model": Path(relative).stem.split("-")[0],
        }
        try:
            content = self.budget.read(path).decode("utf-8")
            if content.startswith("\ufeff"):
                raise DevkitError("CSV_UNSUPPORTED", "Save CSV as UTF-8 without a BOM")
            self._parse(content, result)
        except UnicodeDecodeError:
            result.update(status="invalid", reason="INVALID_CSV", message="Odoo CSV requires UTF-8")
        except csv.Error as exc:
            limit = "field larger than field limit" in str(exc)
            result.update(
                status="blocked",
                reason="CSV_LIMIT" if limit else "CSV_UNSUPPORTED",
                message="CSV parser field limit exceeded"
                if limit
                else "CSV quoting requires permissive parsing; inspect the source",
            )
        except DevkitError as exc:
            if not (exc.reason.startswith("CSV_") or exc.reason == "INVALID_CSV"):
                raise
            result.update(
                status="invalid" if exc.reason == "INVALID_CSV" else "blocked",
                reason=exc.reason,
                message=str(exc),
            )
        except OSError:
            result.update(
                status="blocked", reason="CSV_UNAVAILABLE", message="Cannot read CSV; check access"
            )
        if result["status"] != "valid":
            result["events"] = []
        else:
            result["line"] = None
        return result

    def _parse(self, content: str, result: JSONObject) -> None:
        reader = csv.reader(
            io.StringIO(content, newline=""), delimiter=",", quotechar='"', strict=True
        )
        try:
            header = next(reader, None)
            if header is None:
                raise DevkitError("INVALID_CSV", "CSV is empty; a header row is required")
            self._validate_header(header)
            result["headers"] = header
            # Odoo removes translation columns before filtering empty rows.
            selected = [(index, name) for index, name in enumerate(header) if "@" not in name]
            while True:
                self.checkpoint()
                result["line"] = reader.line_num + 1
                row = next(reader, None)
                if row is None:
                    break
                self._row(row, header, selected, result)
        finally:
            result["line"] = max(1, reader.line_num)

    def _validate_header(self, header: list[str]) -> None:
        self._cells(header)
        selected = [name for name in header if "@" not in name]
        normalized = [name.replace(":id", "/id") for name in selected]
        if len(set(normalized)) != len(normalized):
            raise DevkitError("CSV_UNSUPPORTED", "Duplicate or aliased CSV columns are ambiguous")
        if any(len(name) > 256 or HEADER.fullmatch(name) is None for name in selected):
            raise DevkitError(
                "CSV_UNSUPPORTED",
                "Only flat fields and direct field:id or field/id references are inspected",
            )

    def _row(
        self,
        row: list[str],
        header: list[str],
        selected: list[tuple[int, str]],
        result: JSONObject,
    ) -> None:
        self.rows += 1
        if self.rows > LIMITS["rows"]:
            raise DevkitError("CSV_LIMIT", "CSV row budget exhausted; select fewer modules")
        self._cells(row)
        if not any(
            value
            for index, value in enumerate(row)
            if index >= len(header) or "@" not in header[index]
        ):
            return
        if len(row) != len(header):
            raise DevkitError("CSV_UNSUPPORTED", "CSV row width differs from the header")
        values = [(index, name, row[index]) for index, name in selected]
        result["row_count"] += 1
        self._events(values, result)

    def _cells(self, cells: list[str]) -> None:
        if len(cells) > LIMITS["columns"] or any(
            len(cell) > LIMITS["field_chars"] for cell in cells
        ):
            raise DevkitError("CSV_LIMIT", "CSV column or field-size limit exceeded")

    def _events(self, values: list[tuple[int, str, str]], result: JSONObject) -> None:
        for index, name, value in values:
            if value and name.endswith((":id", "/id")):
                self._emit("reference", value, name, index, result)
        for index, name, value in values:
            if name == "id" and value:
                self._emit("definition", value, name, index, result)

    def _emit(self, kind: str, value: str, name: str, index: int, result: JSONObject) -> None:
        self.events += 1
        if self.events > LIMITS["reference_events"]:
            raise DevkitError(
                "CSV_LIMIT", "CSV reference event limit exceeded; select fewer modules"
            )
        result["events"].append(
            {
                "kind": kind,
                "value": value[:512],
                "line": result["line"],
                "column": index + 1,
                "conditional": False,
                "attribute": name,
                "truncated": len(value) > 512,
            }
        )
