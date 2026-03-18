from benchmark.loaders.exa_loader import load_exa_csv
from benchmark.loaders.juicebox_loader import load_juicebox_csv
from benchmark.loaders.lessie_loader import load_lessie_csv
from benchmark.loaders.claude_code_loader import (
    load_claude_code_csv,
    load_claude_code_csv_raw,
)

PLATFORM_LOADERS = {
    "exa": load_exa_csv,
    "juicebox": load_juicebox_csv,
    "lessie": load_lessie_csv,
    "claude_code": load_claude_code_csv,
}

__all__ = [
    "load_exa_csv",
    "load_juicebox_csv",
    "load_lessie_csv",
    "load_claude_code_csv",
    "load_claude_code_csv_raw",
    "PLATFORM_LOADERS",
]
