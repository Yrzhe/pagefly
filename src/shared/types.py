"""Type definitions."""

from dataclasses import dataclass, field
from enum import Enum


class SourceType(str, Enum):
    TEXT = "text"
    PDF = "pdf"
    IMAGE = "image"
    VOICE = "voice"
    DOCX = "docx"
    URL = "url"
    BOOK = "book"


class DocumentStatus(str, Enum):
    RAW = "raw"
    CLASSIFIED = "classified"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"


class OperationType(str, Enum):
    INGEST = "ingest"
    CLASSIFY = "classify"
    MOVE = "move"
    UPDATE_METADATA = "update_metadata"
    COMPILE = "compile"
    MANUAL_MOVE = "manual_move"


@dataclass
class ClassificationResult:
    category: str
    subcategory: str
    title: str
    description: str
    tags: list[str]
    confidence: float
    reasoning: str
    relevance_score: int = 5  # 1-10, personal value to user
    temporal_type: str = "evergreen"  # evergreen | time_sensitive
    key_claims: list[str] = field(default_factory=list)  # core assertions, max 5


@dataclass
class DocumentMetadata:
    id: str
    title: str = ""
    description: str = ""
    source_type: str = ""
    original_filename: str = ""
    ingested_at: str = ""
    classified_at: str = ""
    status: str = DocumentStatus.RAW.value
    location: str = "raw/"
    tags: list[str] = field(default_factory=list)
    category: str = ""
    subcategory: str = ""
    related: list[str] = field(default_factory=list)


@dataclass
class IngestInput:
    type: str  # file | url | text
    mime_type: str = ""
    file_path: str = ""
    url: str = ""
    text: str = ""
    original_filename: str = ""


@dataclass
class ImageAsset:
    """Image asset extracted during conversion."""
    filename: str
    data: bytes
    description: str = ""


@dataclass
class ConvertResult:
    markdown: str
    title: str
    suggested_tags: list[str] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)
