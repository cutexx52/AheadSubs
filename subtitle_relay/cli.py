"""Machine-readable AheadSubs command line."""
import argparse
import json
import sys
from pathlib import Path

from .automation import DEFAULT_PORT, OPERATIONS, invoke


def port_number(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def add_operation(commands, name, operation):
    command = commands.add_parser(name.replace("_", "-"), help=operation.description,
                                  description=operation.description)
    command.set_defaults(operation=name)
    command.add_argument("--port", type=port_number, default=argparse.SUPPRESS)
    schema = operation.arguments.model_json_schema()
    for field, details in schema["properties"].items():
        kind = details.get("type") or next((item.get("type") for item in details.get("anyOf", ())
                                            if item.get("type") != "null"), None)
        required = field in schema.get("required", ())
        argument = field if required else "--" + field.replace("_", "-")
        options = {"default": argparse.SUPPRESS, "help": details.get("description")}
        if kind == "boolean":
            options["action"] = argparse.BooleanOptionalAction
        else:
            options["type"] = {"integer": int, "number": float, "string": str}.get(kind, json.loads)
        if name == "translate_text" and field == "text":
            options["help"] += " (use - to read from stdin)"
        command.add_argument(argument, **options)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="aheadsubs", description="Automate the local AheadSubs subtitle service.")
    parser.add_argument("--port", type=port_number, default=DEFAULT_PORT, help="Local subtitle service port")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, operation in OPERATIONS.items():
        add_operation(commands, name, operation)
    mcp = commands.add_parser("mcp", help="Run the MCP stdio server for a local agent")
    mcp.add_argument("--port", type=port_number, default=argparse.SUPPRESS)
    mcp.add_argument("--desktop", action="store_true", help="Honor the desktop app's MCP access switch")
    values = vars(parser.parse_args(argv))
    command, port = values.pop("command"), values.pop("port")
    if command == "mcp":
        from .mcp_server import serve_stdio

        bundled = (Path(sys.base_prefix).parent / "cli" / "aheadsubs.exe").is_file()
        return serve_stdio(port, desktop=values["desktop"] or bundled)
    name = values.pop("operation")
    try:
        if name == "translate_text" and values["text"] == "-":
            values["text"] = sys.stdin.read(4001)
        result = invoke(name, values, port)
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
