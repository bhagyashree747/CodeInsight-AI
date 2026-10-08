import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)


def parse_python(source: str):
    """Parse Python source code into a Tree-sitter tree."""
    return _parser.parse(bytes(source, "utf8"))