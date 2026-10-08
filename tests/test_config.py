import pytest

from conftest import run_python
from yandex_tracker_mcp import config

LIST_TOOLS = "import asyncio; from yandex_tracker_mcp.server import mcp; print(len(asyncio.run(mcp.list_tools())))"
RUN_MAIN = "from yandex_tracker_mcp.server import main; main()"
PRINT_TOKEN = "import os, yandex_tracker_mcp.config; print(os.environ.get('TRACKER_TOKEN', ''))"


def test_headers(clean_config):
    assert config.get_config().headers == {"Authorization": "OAuth test-token", "X-Org-ID": "42"}


def test_iam_and_cloud_org(clean_config):
    clean_config.setenv("TRACKER_AUTH_TYPE", " IAM ")
    clean_config.delenv("TRACKER_ORG_ID")
    clean_config.setenv("TRACKER_CLOUD_ORG_ID", "bpf123")
    assert config.get_config().headers == {"Authorization": "Bearer test-token", "X-Cloud-Org-ID": "bpf123"}


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"TRACKER_TOKEN": ""}, "TRACKER_TOKEN"),
        ({"TRACKER_AUTH_TYPE": "bearer"}, "TRACKER_AUTH_TYPE"),
        ({"TRACKER_CLOUD_ORG_ID": "bpf123"}, "only one"),
        ({"TRACKER_ORG_ID": " "}, "Set TRACKER_ORG_ID"),
        ({"TRACKER_API_URL": "http://evil.example"}, "https"),
    ],
)
def test_invalid_config(clean_config, env, message):
    for name, value in env.items():
        clean_config.setenv(name, value)
    with pytest.raises(config.ConfigError, match=message):
        config.get_config()


@pytest.mark.parametrize("value", ["1", "true", "Yes", " on "])
def test_parse_bool_true(monkeypatch, value):
    monkeypatch.setenv("TRACKER_READ_ONLY", value)
    assert config.parse_bool("TRACKER_READ_ONLY") is True


def test_parse_bool_typo_is_error(monkeypatch):
    monkeypatch.setenv("TRACKER_READ_ONLY", "enabled")
    with pytest.raises(config.ConfigError):
        config.parse_bool("TRACKER_READ_ONLY")


def test_all_tools_registered():
    assert run_python(LIST_TOOLS).stdout.strip() == "21"


def test_read_only_hides_write_tools():
    assert run_python(LIST_TOOLS, TRACKER_READ_ONLY="1").stdout.strip() == "14"


def test_read_only_typo_fails_safe_and_main_exits():
    assert run_python(LIST_TOOLS, TRACKER_READ_ONLY="enabled").stdout.strip() == "14"
    result = run_python(RUN_MAIN, TRACKER_READ_ONLY="enabled")
    assert result.returncode == 1
    assert "TRACKER_READ_ONLY" in result.stderr


def test_main_reports_missing_token():
    result = run_python(RUN_MAIN, TRACKER_TOKEN="")
    assert result.returncode == 1
    assert "TRACKER_TOKEN is not set" in result.stderr


def test_env_file_in_cwd_is_ignored(tmp_path):
    (tmp_path / ".env").write_text("TRACKER_TOKEN=from-cwd\n")
    assert run_python(PRINT_TOKEN, cwd=tmp_path, TRACKER_TOKEN=None).stdout.strip() == ""


def test_env_file_from_tracker_env_file(tmp_path):
    env_file = tmp_path / "custom.env"
    env_file.write_text("TRACKER_TOKEN=from-file\n")
    result = run_python(PRINT_TOKEN, TRACKER_TOKEN=None, TRACKER_ENV_FILE=str(env_file))
    assert result.stdout.strip() == "from-file"
