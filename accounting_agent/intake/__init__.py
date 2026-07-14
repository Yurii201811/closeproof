"""Local-first intake prototype for accounting documents."""

from .local import (
    ClientMapper,
    LocalIntakeProcessor,
    manual_upload_source,
    onedrive_file_source,
    outlook_attachment_source,
    teams_message_file_source,
)
from .models import (
    ClientMappingResult,
    ClientMappingRule,
    ExtractionTask,
    IntakeCase,
    IntakeSource,
    IntakeSourceType,
)
from .store import SQLiteIntakeStore

__all__ = [
    "ClientMapper",
    "ClientMappingResult",
    "ClientMappingRule",
    "ExtractionTask",
    "IntakeCase",
    "IntakeSource",
    "IntakeSourceType",
    "LocalIntakeProcessor",
    "SQLiteIntakeStore",
    "manual_upload_source",
    "onedrive_file_source",
    "outlook_attachment_source",
    "teams_message_file_source",
]
