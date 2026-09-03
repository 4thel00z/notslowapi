try:
    from fastapi_cli.cli import main as cli_main

except ImportError:  # pragma: no cover
    cli_main = None  # type: ignore # ty: ignore[unused-ignore-comment]


def main() -> None:
    if not cli_main:  # type: ignore[truthy-function]
        message = 'To use the notslowapi command, install fastapi-cli:\n\n\tpip install "fastapi-cli[standard]"\n'
        print(message)
        raise RuntimeError(message)  # noqa: B904
    cli_main()
