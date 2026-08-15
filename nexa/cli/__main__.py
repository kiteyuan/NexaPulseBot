from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

from nexa.cli.app import build_parser, dispatch


def main(argv: Optional[list[str]] = None) -> int:
    logging.Formatter.converter = __import__("time").gmtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(dispatch(args))
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
