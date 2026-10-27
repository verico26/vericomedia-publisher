import argparse
import json
import logging
from pathlib import Path
from .planner import plan

logger = logging.getLogger("vericomedia_publisher")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline plan; no Tilda writes")
    parser.add_argument("--content", type=Path, default=Path("content"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.publish:
        logger.error("publication_disabled: test-page validation and write adapter required")
        return 2
    try:
        result = plan(args.content)
        serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized, encoding="utf-8")
        else:
            print(serialized, end="")
        logger.info("plan_ready articles=%d publishing_enabled=false", len(result["articles"]))
        return 0
    except (ValueError, OSError) as exc:
        # Exception text can contain content or credentials: log class only.
        logger.error("plan_failed error_type=%s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
