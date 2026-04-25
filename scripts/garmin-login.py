"""One-shot Garmin login. Saves OAuth tokens to ./out so they can be
shipped to hd:~/compose/hack-the-body/data/garmin-session/.

Usage:
  GARMIN_EMAIL=...  GARMIN_PASSWORD=...  python scripts/garmin-login.py [output-dir]

Run from a different egress IP (phone hotspot, exit node, cloud VM) than the
production host — once tokens are cached on the host, login is never needed
again unless the session expires (months).
"""
import os
import sys
from pathlib import Path

from garminconnect import Garmin


def main() -> int:
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        print("GARMIN_EMAIL and GARMIN_PASSWORD env vars are required", file=sys.stderr)
        return 2

    out = Path(sys.argv[1] if len(sys.argv) > 1 else "./out").resolve()
    out.mkdir(parents=True, exist_ok=True)

    print(f"Logging in as {email} ...")
    g = Garmin(email=email, password=password)
    try:
        g.login()
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate" in msg.lower():
            print(
                "FAILED: Garmin returned 429 (IP rate limit). "
                "Try again from a different egress IP.",
                file=sys.stderr,
            )
        else:
            print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    g.garth.dump(str(out))
    print(f"\nOK. Tokens saved to: {out}")
    print(f"Username: {g.garth.username}")
    print("Files written:")
    for p in sorted(out.iterdir()):
        print(f"  {p.name}  ({p.stat().st_size} bytes)")
    print(
        "\nNext step: scp these to the prod host, e.g.:\n"
        f"  scp {out}/* hd:~/compose/hack-the-body/data/garmin-session/\n"
        "  ssh hd 'docker compose -f ~/compose/hack-the-body/docker-compose.yml restart ingestor-garmin'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
