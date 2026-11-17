"""MCP transport for the shared AheadSubs automation operations."""
import json
import sys

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp_types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

from .automation import OPERATIONS, OperationError, invoke


def serve_stdio(port, *, desktop=False):
    if desktop:
        from .desktop.automation import mcp_enabled
    else:
        def mcp_enabled():
            return True

    if not mcp_enabled():
        print("MCP access is off. Enable it in the AheadSubs desktop app.", file=sys.stderr)
        return 1

    def checkpoint():
        anyio.from_thread.check_cancelled()
        if not mcp_enabled():
            raise OperationError("mcp_disabled", "MCP access is off in the AheadSubs desktop app.")

    async def list_tools(_ctx, _params):
        return ListToolsResult(tools=[
            Tool(name=f"aheadsubs_{name}", description=operation.description,
                 input_schema=operation.arguments.model_json_schema(),
                 annotations=ToolAnnotations(read_only_hint=(name == "status"), open_world_hint=(name != "status")))
            for name, operation in OPERATIONS.items()
        ])

    async def call_tool(_ctx, params):
        def run():
            try:
                checkpoint()
            except OperationError as error:
                return error.result()
            name = params.name.removeprefix("aheadsubs_") if params.name.startswith("aheadsubs_") else ""
            return invoke(name, params.arguments if params.arguments is not None else {}, port, checkpoint)

        result = await anyio.to_thread.run_sync(run)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                              structured_content=result, is_error=not result["ok"])

    async def run_stdio():
        server = Server("AheadSubs", on_list_tools=list_tools, on_call_tool=call_tool)
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())

    try:
        anyio.run(run_stdio)
    except KeyboardInterrupt:
        return 130
    return 0
