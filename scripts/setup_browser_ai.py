"""Install pinned browser AI assets using the same provisioner as Studio."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ai_setup import AISetup, MANIFEST


def main():
    setup = AISetup()
    try:
        if setup.snapshot()["status"] != "ready":
            print(f"Downloading {MANIFEST['model']}; at most {MANIFEST['download_max_bytes']:,} bytes.", flush=True)
            setup.start(consent=True)
            while setup.wait(timeout=1)["status"] in {"downloading", "verifying"}:
                status = setup.snapshot()
                print(f"{status['status']}: {status['bytes_downloaded']:,} bytes", flush=True)
        status = setup.snapshot()
        if status["status"] != "ready":
            print(f"AI setup {status['status']}: {status['error'] or 'not completed'}", file=sys.stderr)
            return 1
        print(f"Browser AI ready: {MANIFEST['model']}, {MANIFEST['runtime']}.", flush=True)
        return 0
    except KeyboardInterrupt:
        print("Cancelling AI setup...", file=sys.stderr)
        return 130
    finally:
        setup.close()


if __name__ == "__main__":
    raise SystemExit(main())
