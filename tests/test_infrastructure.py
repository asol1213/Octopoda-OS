"""
Tests for infrastructure, configuration, and DevOps concerns.

Covers: SynrixConfig, environment variable handling, Dockerfile validation,
pyproject.toml validation, data directory management, backend auto-detection,
logging configuration, CLI entry points, and health endpoint format.
"""

import os
import logging
import pytest


# ---------------------------------------------------------------------------
# SynrixConfig.from_env() defaults
# ---------------------------------------------------------------------------

class TestSynrixConfigDefaults:
    """Verify default values when no env vars are set."""

    def test_default_backend(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_BACKEND", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.backend == "sqlite"

    def test_default_data_dir(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_DATA_DIR", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.data_dir == os.path.expanduser("~/.synrix/data")

    def test_default_sqlite_db_name(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_SQLITE_DB", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.sqlite_db_name == "synrix.db"

    def test_default_api_port(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_API_PORT", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.api_port == 8741

    def test_default_dashboard_port(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_DASHBOARD_PORT", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.dashboard_port == 7842

    def test_default_log_level(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_LOG_LEVEL", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.log_level == "INFO"

    def test_default_gc_enabled(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_GC_ENABLED", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.gc_enabled is True

    def test_default_api_key_empty(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_API_KEY", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.api_key == ""


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------

class TestSynrixConfigEnvOverrides:
    """Verify environment variables override defaults."""

    def test_backend_override(self, monkeypatch):
        monkeypatch.setenv("SYNRIX_BACKEND", "postgres")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.backend == "postgres"

    def test_data_dir_override(self, monkeypatch, tmp_dir):
        monkeypatch.setenv("SYNRIX_DATA_DIR", tmp_dir)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.data_dir == tmp_dir

    def test_api_port_override(self, monkeypatch):
        monkeypatch.setenv("SYNRIX_API_PORT", "9999")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.api_port == 9999

    def test_log_level_override(self, monkeypatch):
        monkeypatch.setenv("SYNRIX_LOG_LEVEL", "DEBUG")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.log_level == "DEBUG"

    def test_gc_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("SYNRIX_GC_ENABLED", "false")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.gc_enabled is False

    def test_api_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("SYNRIX_API_ENABLED", "false")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.api_enabled is False

    def test_dashboard_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("SYNRIX_DASHBOARD", "false")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.dashboard_enabled is False

    def test_lattice_max_nodes_override(self, monkeypatch):
        monkeypatch.setenv("SYNRIX_MAX_NODES", "50000")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.lattice_max_nodes == 50000

    def test_gc_interval_hours_override(self, monkeypatch):
        monkeypatch.setenv("SYNRIX_GC_INTERVAL_HOURS", "12")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert cfg.gc_interval_hours == 12


# ---------------------------------------------------------------------------
# Dockerfile validation
# ---------------------------------------------------------------------------

class TestDockerfile:
    """Validate Dockerfile structure and required directives."""

    @pytest.fixture(autouse=True)
    def _load_dockerfile(self):
        dockerfile_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "Dockerfile",
        )
        with open(dockerfile_path) as f:
            self.content = f.read()
        self.lines = [line.strip() for line in self.content.splitlines()]

    def test_has_from_directive(self):
        assert any(line.startswith("FROM ") for line in self.lines)

    def test_base_image_is_python(self):
        from_lines = [l for l in self.lines if l.startswith("FROM ")]
        assert any("python" in l for l in from_lines)

    def test_has_expose(self):
        assert any(line.startswith("EXPOSE") for line in self.lines)

    def test_has_healthcheck(self):
        assert "HEALTHCHECK" in self.content

    def test_has_cmd(self):
        assert any(line.startswith("CMD") for line in self.lines)

    def test_sets_synrix_backend_env(self):
        assert "SYNRIX_BACKEND" in self.content

    def test_copies_synrix_source(self):
        assert "COPY synrix/" in self.content or "COPY synrix_runtime/" in self.content


# ---------------------------------------------------------------------------
# pyproject.toml validation
# ---------------------------------------------------------------------------

class TestPyprojectToml:
    """Validate pyproject.toml has required fields."""

    @pytest.fixture(autouse=True)
    def _load_pyproject(self):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib

        pyproject_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "pyproject.toml",
        )
        with open(pyproject_path, "rb") as f:
            self.data = tomllib.load(f)

    def test_has_project_name(self):
        assert "project" in self.data
        assert "name" in self.data["project"]
        assert len(self.data["project"]["name"]) > 0

    def test_has_version(self):
        assert "version" in self.data["project"]
        parts = self.data["project"]["version"].split(".")
        assert len(parts) >= 2  # At least major.minor

    def test_has_description(self):
        assert "description" in self.data["project"]

    def test_has_build_system(self):
        assert "build-system" in self.data
        assert "requires" in self.data["build-system"]

    def test_has_scripts(self):
        scripts = self.data["project"].get("scripts", {})
        assert "octopoda" in scripts

    def test_has_dev_dependencies(self):
        optional = self.data["project"].get("optional-dependencies", {})
        assert "dev" in optional
        dev_deps = " ".join(optional["dev"])
        assert "pytest" in dev_deps


# ---------------------------------------------------------------------------
# Data directory creation
# ---------------------------------------------------------------------------

class TestDataDirectory:
    """Test data directory creation and path helpers."""

    def test_get_sqlite_path_creates_dir(self, tmp_dir):
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig(data_dir=os.path.join(tmp_dir, "new_subdir"))
        path = cfg.get_sqlite_path()
        assert os.path.isdir(os.path.join(tmp_dir, "new_subdir"))
        assert path.endswith("synrix.db")

    def test_get_lattice_path_creates_dir(self, tmp_dir):
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig(data_dir=os.path.join(tmp_dir, "lattice_dir"))
        path = cfg.get_lattice_path()
        assert os.path.isdir(os.path.join(tmp_dir, "lattice_dir"))
        assert path.endswith("synrix.lattice")

    def test_data_dir_expands_tilde(self, monkeypatch):
        monkeypatch.delenv("SYNRIX_DATA_DIR", raising=False)
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig.from_env()
        assert "~" not in cfg.data_dir


# ---------------------------------------------------------------------------
# Backend auto-detection
# ---------------------------------------------------------------------------

class TestBackendAutoDetection:
    """Test resolve_backend logic."""

    def test_explicit_sqlite_unchanged(self):
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig(backend="sqlite")
        assert cfg.resolve_backend() == "sqlite"

    def test_explicit_postgres_unchanged(self):
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig(backend="postgres")
        assert cfg.resolve_backend() == "postgres"

    def test_explicit_mock_unchanged(self):
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig(backend="mock")
        assert cfg.resolve_backend() == "mock"

    def test_auto_falls_back_to_sqlite(self):
        """Auto mode should fall back to sqlite when no lattice lib exists."""
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig(backend="auto")
        result = cfg.resolve_backend()
        # Without lattice lib installed, should fall to sqlite
        assert result in ("sqlite", "lattice")

    def test_get_backend_kwargs_sqlite(self, tmp_dir):
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig(backend="sqlite", data_dir=tmp_dir)
        kwargs = cfg.get_backend_kwargs()
        assert kwargs["backend"] == "sqlite"
        assert "sqlite_path" in kwargs

    def test_get_backend_kwargs_postgres(self, monkeypatch, tmp_dir):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        from synrix_runtime.config import SynrixConfig
        cfg = SynrixConfig(backend="postgres", data_dir=tmp_dir)
        kwargs = cfg.get_backend_kwargs()
        assert kwargs["backend"] == "postgres"
        assert kwargs["dsn"] == "postgresql://localhost/test"


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

class TestLogging:
    """Test logging setup."""

    def test_get_logger_returns_logger(self):
        from synrix_runtime.log import get_logger
        logger = get_logger("test_infra")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "synrix.test_infra"

    def test_logger_has_handler(self):
        from synrix_runtime.log import get_logger
        get_logger("probe")
        root = logging.getLogger("synrix")
        assert len(root.handlers) >= 1

    def test_root_logger_level(self):
        from synrix_runtime.log import get_logger
        get_logger("probe2")
        root = logging.getLogger("synrix")
        assert root.level <= logging.INFO


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------

class TestCLIEntryPoints:
    """Verify CLI modules are importable and have main()."""

    def test_start_main_exists(self):
        from synrix_runtime.start import main
        assert callable(main)

    def test_mcp_server_main_exists(self):
        from synrix_runtime.api.mcp_server import main
        assert callable(main)

    def test_auth_flow_cli_login_exists(self):
        from synrix_runtime.auth_flow import _cli_login
        assert callable(_cli_login)


# ---------------------------------------------------------------------------
# Health endpoint format
# ---------------------------------------------------------------------------

class TestHealthEndpointFormat:
    """Validate the HealthResponse model structure."""

    def test_health_response_fields(self):
        from synrix_runtime.api.cloud_models import HealthResponse
        resp = HealthResponse(
            status="ok", version="3.0.3",
            backend="sqlite", uptime_seconds=42.5,
        )
        assert resp.status == "ok"
        assert resp.version == "3.0.3"
        assert resp.backend == "sqlite"
        assert resp.uptime_seconds == 42.5

    def test_health_response_serializable(self):
        from synrix_runtime.api.cloud_models import HealthResponse
        resp = HealthResponse(
            status="ok", version="3.0.3",
            backend="sqlite", uptime_seconds=0.0,
        )
        data = resp.model_dump()
        assert "status" in data
        assert "version" in data
        assert "backend" in data
        assert "uptime_seconds" in data

    def test_health_endpoint_returns_200(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "backend" in body
        assert "uptime_seconds" in body
