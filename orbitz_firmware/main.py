import argparse
import logging
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .diagnostics import DiagnosticRunner
from .runtime import OrbitzRuntime


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="orbitz-firmware")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--diagnostics", nargs="*", choices=("all", "display", "input", "led", "buzzer", "gps", "adsb", "orbit-cache"))
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> int:
    options = arguments()
    try:
        config = load_config(options.config)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    configure_logging(config.log_level)
    if options.diagnostics is not None:
        results = DiagnosticRunner(config).run(tuple(options.diagnostics))
        for result in results:
            print(f"{result.name}: {'PASS' if result.success else 'FAIL'}: {result.detail}")
        return 0 if all(result.success for result in results) else 1
    runtime = OrbitzRuntime(config)
    runtime.install_signal_handlers()
    try:
        runtime.initialize()
        return runtime.run()
    except Exception:
        logging.getLogger(__name__).exception("ORBITZ firmware stopped after an unrecoverable error")
        return 1
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
