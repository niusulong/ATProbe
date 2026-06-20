"""支持 `python -m atprobe` 启动."""

from atprobe.cli.main import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
