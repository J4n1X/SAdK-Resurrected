#!/usr/bin/env python3
"""
Back-compat launcher.

The monolithic server has been split into the ``sadk_lobby`` package. This shim
keeps the original workflow working — ``python tincat_server.py`` now runs the
package. The original 1200-line monolith is preserved as
``legacy_tincat_server.py`` for reference / A-B testing.

Equivalent invocations:
    python tincat_server.py
    python -m sadk_lobby
"""
from sadk_lobby.server import main

if __name__ == "__main__":
    main()
