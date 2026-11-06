from __future__ import annotations

import re
from pathlib import Path


def extract_symbols_from_source(content: str, file_path: str = "") -> set[str]:
    """
    Extract key symbols across Rust, TypeScript, JavaScript, Go, and Python source files.
    """
    symbols: set[str] = set()
    ext = Path(file_path).suffix.lower() if file_path else ""

    # Python (.py, .pyi)
    if not ext or ext in (".py", ".pyi"):
        for sym in re.findall(r"\b(?:def|class)\s+([A-Za-z0-9_]+)", content):
            symbols.add(sym)

    # TypeScript & JavaScript (.ts, .tsx, .js, .jsx, .mjs, .cjs)
    if not ext or ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        # standard functions, classes, interfaces, types, enums
        for sym in re.findall(
            r"\b(?:function|class|interface|type|enum)\s+([A-Za-z0-9_]+)", content
        ):
            symbols.add(sym)
        # arrow functions: const myFunc = () =>
        for sym in re.findall(
            r"\b(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
            content,
        ):
            symbols.add(sym)
        # export declarations
        for sym in re.findall(
            r"\bexport\s+(?:default\s+)?(?:const|let|var|function|class|interface|type|enum)\s+([A-Za-z0-9_]+)",
            content,
        ):
            symbols.add(sym)

    # Rust (.rs)
    if not ext or ext in (".rs",):
        for sym in re.findall(
            r"\b(?:fn|struct|enum|trait|type|mod)\s+([A-Za-z0-9_]+)", content
        ):
            symbols.add(sym)
        for sym in re.findall(r"\bimpl(?:<[^>]+>)?\s+([A-Za-z0-9_]+)", content):
            symbols.add(sym)

    # Go (.go)
    if not ext or ext in (".go",):
        for sym in re.findall(r"\bfunc\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)", content):
            symbols.add(sym)
        for sym in re.findall(
            r"\btype\s+([A-Za-z0-9_]+)\s+(?:struct|interface)", content
        ):
            symbols.add(sym)

    return symbols
