"""Tests for the .meta.yaml sidecar module."""

import yaml

from codexlr8.meta import (
    meta_path_for,
    source_path_for,
    read_meta,
    write_meta,
    generate_meta_skeleton,
    generate_missing_sidecars,
    validate_meta,
)


class TestPathHelpers:
    def test_meta_path_for(self):
        assert meta_path_for("auth/session.py") == "auth/session.py.meta.yaml"
        assert meta_path_for("/abs/path/main.py") == "/abs/path/main.py.meta.yaml"

    def test_source_path_for(self):
        assert source_path_for("auth/session.py.meta.yaml") == "auth/session.py"
        assert source_path_for("main.py.meta.yaml") == "main.py"


class TestReadWrite:
    def test_read_missing_meta(self, tmp_path):
        result = read_meta(str(tmp_path / "nonexistent.meta.yaml"))
        assert result is None

    def test_write_and_read_meta(self, tmp_path):
        meta_path = str(tmp_path / "test.meta.yaml")
        data = {
            "public_api": ["login", "logout"],
            "summary": "Auth module",
            "tags": ["auth", "security"],
        }
        write_meta(meta_path, data)

        result = read_meta(meta_path)
        assert result is not None
        assert result["public_api"] == ["login", "logout"]
        assert result["summary"] == "Auth module"
        assert result["tags"] == ["auth", "security"]

    def test_read_empty_yaml(self, tmp_path):
        meta_path = str(tmp_path / "empty.meta.yaml")
        (tmp_path / "empty.meta.yaml").write_text("")
        result = read_meta(meta_path)
        assert result == {}

    def test_write_preserves_order(self, tmp_path):
        meta_path = str(tmp_path / "ordered.meta.yaml")
        data = {
            "public_api": [],
            "summary": "test",
            "tags": ["a", "b"],
        }
        write_meta(meta_path, data)

        with open(meta_path, "r") as f:
            raw = f.read()
        assert raw.index("public_api") < raw.index("summary") < raw.index("tags")


class TestGenerateMetaSkeleton:
    def test_generates_fresh_skeleton(self):
        result = generate_meta_skeleton()
        assert result["public_api"] == []
        assert result["dependencies"] == []
        assert result["used_by"] == []
        assert "last_modified" in result

    def test_preserves_curated_fields(self):
        existing = {
            "summary": "Auth module",
            "tags": ["auth"],
            "invariants": ["db first"],
            "examples": "x = login()",
        }
        result = generate_meta_skeleton(existing_meta=existing)
        assert result["summary"] == "Auth module"
        assert result["tags"] == ["auth"]
        assert result["invariants"] == ["db first"]
        assert result["examples"] == "x = login()"

    def test_overwrites_auto_fields(self):
        existing = {
            "public_api": ["old_func"],
            "dependencies": ["old_dep"],
            "used_by": ["old_user"],
        }
        result = generate_meta_skeleton(existing_meta=existing)
        assert result["public_api"] == []  # reset to empty
        assert result["dependencies"] == []
        assert result["used_by"] == []
        assert "last_modified" in result


class TestGenerateMissingSidecars:
    def test_creates_missing_sidecars(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")
        (project / "util.py").write_text("def bar(): pass\n")

        created = generate_missing_sidecars(str(project))
        assert len(created) == 2
        assert "main.py.meta.yaml" in created
        assert "util.py.meta.yaml" in created

        assert (project / "main.py.meta.yaml").exists()
        assert (project / "util.py.meta.yaml").exists()

    def test_skips_existing_sidecars(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")
        (project / "main.py.meta.yaml").write_text("summary: already here\n")

        created = generate_missing_sidecars(str(project))
        assert created == []

    def test_handles_empty_project(self, tmp_path):
        project = tmp_path / "empty"
        project.mkdir()
        created = generate_missing_sidecars(str(project))
        assert created == []

    def test_created_content_is_valid(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "auth.py").write_text("def login(): pass\n")

        generate_missing_sidecars(str(project))
        meta = read_meta(str(project / "auth.py.meta.yaml"))
        assert meta is not None
        assert "public_api" in meta
        assert "last_modified" in meta
        assert "dependencies" in meta


class TestValidateMeta:
    def test_valid_meta(self, tmp_path):
        meta_path = str(tmp_path / "test.meta.yaml")
        write_meta(meta_path, {
            "public_api": ["login"],
            "dependencies": [],
            "used_by": [],
            "summary": "Auth",
        })
        warnings = validate_meta(meta_path)
        assert warnings == []

    def test_missing_file(self, tmp_path):
        warnings = validate_meta(str(tmp_path / "nonexistent.meta.yaml"))
        assert warnings == ["No .meta.yaml found"]

    def test_missing_required_fields(self, tmp_path):
        meta_path = str(tmp_path / "test.meta.yaml")
        write_meta(meta_path, {"summary": "just summary"})
        warnings = validate_meta(meta_path)
        assert any("public_api" in w for w in warnings)
        assert any("dependencies" in w for w in warnings)

    def test_wrong_field_type(self, tmp_path):
        meta_path = str(tmp_path / "test.meta.yaml")
        write_meta(meta_path, {
            "public_api": "not_a_list",
            "dependencies": [],
            "used_by": [],
        })
        warnings = validate_meta(meta_path)
        assert any("must be a list" in w for w in warnings)

    def test_invalid_yaml(self, tmp_path):
        meta_path = str(tmp_path / "bad.meta.yaml")
        (tmp_path / "bad.meta.yaml").write_text(":: invalid yaml :::")
        warnings = validate_meta(meta_path)
        assert any("Failed to parse" in w for w in warnings)


class TestCLIInit:
    def test_init_creates_sidecars(self, tmp_path):
        from click.testing import CliRunner
        from codexlr8.cli import init

        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")

        runner = CliRunner()
        result = runner.invoke(init, [str(project)])
        assert result.exit_code == 0
        assert "Created 1" in result.output
        assert (project / "main.py.meta.yaml").exists()

    def test_init_all_exist(self, tmp_path):
        from click.testing import CliRunner
        from codexlr8.cli import init

        project = tmp_path / "proj"
        project.mkdir()
        (project / "main.py").write_text("def foo(): pass\n")
        (project / "main.py.meta.yaml").write_text("summary: exists\n")

        runner = CliRunner()
        result = runner.invoke(init, [str(project)])
        assert result.exit_code == 0
        assert "All files already have" in result.output
