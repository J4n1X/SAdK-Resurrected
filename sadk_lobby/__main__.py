"""Entry point: ``python -m sadk_lobby``."""
import os
import sys

from . import config

if __name__ == "__main__":
    if not os.path.isfile(config.MSGDEFS_PATH):
        # The game's own message schema; not distributed with the server.
        print(f"\n  msgdefs.ini not found at {config.MSGDEFS_PATH}\n"
              "  Copy it from the bin folder of your game installation (bin\\msgdefs.ini) to that path.\n")
        sys.exit(2)
    from .server import main
    main()
