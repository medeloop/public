"""Phase 3 execution harness.

Public entry points:

    from runner.codeset_loader import bootstrap_all_codesets, bootstrap_codeset
    from runner.harness import run_port, PortExecutionResult
    from runner.mcp import MedeloopSession

Everything under `runner/` is pure Python + PyYAML + the Medeloop MCP tools.
No side effects at import time.
"""

from .codeset_loader import (  # noqa: F401
    CodesetSpec,
    bootstrap_all_codesets,
    bootstrap_codeset,
    code_column_for,
    collect_codeset_specs,
)
from .harness import PortExecutionResult, run_port  # noqa: F401
from .mcp import MedeloopSession  # noqa: F401

__all__ = [
    "CodesetSpec",
    "MedeloopSession",
    "PortExecutionResult",
    "bootstrap_all_codesets",
    "bootstrap_codeset",
    "code_column_for",
    "collect_codeset_specs",
    "run_port",
]
