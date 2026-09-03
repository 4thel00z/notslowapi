import os
import subprocess
import sys
from unittest.mock import patch

import notslowapi.cli
import pytest


def test_fastapi_cli():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "-m",
            "notslowapi",
            "dev",
            "non_existent_file.py",
        ],
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 1, result.stdout
    assert "Path does not exist non_existent_file.py" in result.stdout


def test_fastapi_cli_not_installed():
    with patch.object(notslowapi.cli, "cli_main", None):
        with pytest.raises(RuntimeError) as exc_info:
            notslowapi.cli.main()
        assert "To use the fastapi command, please install" in str(exc_info.value)
