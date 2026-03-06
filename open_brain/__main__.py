"""Allow running as: python3 -m open_brain.mcp_server"""

from open_brain.mcp_server import main
import asyncio

asyncio.run(main())
