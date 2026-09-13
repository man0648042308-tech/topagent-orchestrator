"""TopAgent MCP Bridge v3 兼容启动入口。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from topagent.bus.mcp_server import main


if __name__ == "__main__":
    main()
