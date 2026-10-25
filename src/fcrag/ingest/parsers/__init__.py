"""Parser registry. Parsers register themselves here and the pipeline routes files by type."""

from fcrag.models import Parser, SourceFile

_REGISTRY: list[Parser] = []


def register(parser: Parser) -> Parser:
    _REGISTRY.append(parser)
    return parser


def parser_for(file: SourceFile) -> Parser:
    """Return the first registered parser that handles the file's MIME type or extension."""
    extension = file.path.suffix.lower()
    for parser in _REGISTRY:
        if file.mime_type in parser.supported_types or extension in parser.supported_types:
            return parser
    raise LookupError(f"No parser registered for {file.path.name} ({file.mime_type})")
