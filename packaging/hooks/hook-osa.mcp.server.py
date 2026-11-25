"""Dynamic ASGI/MCP dependencies required by the embedded HTTP server."""

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

hiddenimports = (
    collect_submodules("mcp", filter=lambda name: name != "mcp.cli" and not name.startswith("mcp.cli."))
    + collect_submodules("anyio._backends", filter=lambda name: "trio" not in name)
    + [
        "uvicorn.logging",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
    ]
)
datas = copy_metadata("mcp") + copy_metadata("uvicorn")
