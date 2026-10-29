"""Parser registry. Parsers register themselves here and the pipeline routes files by type."""

from fcrag.models import Parser, SourceFile

_REGISTRY: list[Parser] = []


def register(parser: Parser) -> Parser:
    _REGISTRY.append(parser)
    return parser


def release_models() -> None:
    """Let parsers free GPU memory before the embedding phase (see ``Pipeline.run``)."""
    for parser in _REGISTRY:
        release = getattr(parser, "release", None)
        if callable(release):
            release()


def parser_for(file: SourceFile) -> Parser:
    """Return the parser claiming the file's document type (a PDF registered as a drawing),
    else the first registered parser that handles its MIME type or extension."""
    for parser in _REGISTRY:
        if file.doc_type is not None and file.doc_type in getattr(parser, "doc_types", ()):
            return parser
    extension = file.path.suffix.lower()
    for parser in _REGISTRY:
        if file.mime_type in parser.supported_types or extension in parser.supported_types:
            return parser
    raise LookupError(f"No parser registered for {file.path.name} ({file.mime_type})")
