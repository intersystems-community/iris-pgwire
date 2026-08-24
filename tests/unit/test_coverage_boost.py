"""
Coverage-boost tests for boolean_translator, pg_constraint, and security_validator.
"""

from unittest.mock import MagicMock, patch
import pytest

# ============================================================================
# boolean_translator.py
# ============================================================================
from iris_pgwire.sql_translator.boolean_translator import BooleanTranslator


class TestBooleanTranslator:
    def setup_method(self):
        self.t = BooleanTranslator()

    def test_empty_sql(self):
        result, count = self.t.translate("")
        assert result == ""
        assert count == 0

    def test_no_booleans(self):
        sql = "SELECT id FROM users WHERE id = 1"
        result, count = self.t.translate(sql)
        assert result == sql
        assert count == 0

    def test_default_true(self):
        sql = "CREATE TABLE t (active BIT DEFAULT true)"
        result, count = self.t.translate(sql)
        assert "DEFAULT 1" in result
        assert count == 1

    def test_default_false(self):
        sql = "CREATE TABLE t (deleted BIT DEFAULT false)"
        result, count = self.t.translate(sql)
        assert "DEFAULT 0" in result
        assert count == 1

    def test_default_true_uppercase(self):
        sql = "CREATE TABLE t (flag BIT DEFAULT TRUE)"
        result, count = self.t.translate(sql)
        assert "DEFAULT 1" in result
        assert count == 1

    def test_default_false_uppercase(self):
        sql = "CREATE TABLE t (flag BIT DEFAULT FALSE)"
        result, count = self.t.translate(sql)
        assert "DEFAULT 0" in result
        assert count == 1

    def test_default_mixed_case(self):
        sql = "ALTER TABLE t ALTER COLUMN flag SET DEFAULT True"
        result, count = self.t.translate(sql)
        assert "DEFAULT 1" in result
        assert count == 1

    def test_string_literal_protected(self):
        sql = "INSERT INTO t VALUES ('DEFAULT true')"
        result, count = self.t.translate(sql)
        assert result == sql
        assert count == 0

    def test_line_comment_protected(self):
        sql = "SELECT * FROM t -- DEFAULT true\nWHERE id = 1"
        result, count = self.t.translate(sql)
        assert count == 0

    def test_block_comment_protected(self):
        sql = "SELECT * FROM t /* DEFAULT true */ WHERE id = 1"
        result, count = self.t.translate(sql)
        assert count == 0

    def test_multiple_defaults(self):
        sql = "CREATE TABLE t (a BIT DEFAULT true, b BIT DEFAULT false)"
        result, count = self.t.translate(sql)
        assert count == 2
        assert "DEFAULT 1" in result
        assert "DEFAULT 0" in result

    def test_word_boundary_no_match_truetype(self):
        # 'truetype' should NOT be translated
        sql = "SELECT truetype FROM fonts"
        result, count = self.t.translate(sql)
        assert count == 0
        assert result == sql

    def test_escaped_quote_in_string(self):
        sql = "INSERT INTO t (v) VALUES ('it''s DEFAULT true')"
        result, count = self.t.translate(sql)
        assert count == 0
        assert result == sql

    def test_string_then_default(self):
        # String before the DEFAULT — literal protected, actual DEFAULT translated
        sql = "INSERT INTO t SELECT 'true', DEFAULT true FROM x"
        # Only the DEFAULT true should be translated
        result, count = self.t.translate(sql)
        assert "DEFAULT 1" in result

    def test_line_comment_no_newline(self):
        # Line comment at end of file (no trailing newline)
        sql = "SELECT 1 -- DEFAULT true"
        result, count = self.t.translate(sql)
        assert count == 0

    def test_block_comment_unclosed(self):
        # Unclosed block comment should treat rest of string as protected
        sql = "SELECT /* DEFAULT true"
        result, count = self.t.translate(sql)
        assert count == 0

    def test_find_protected_regions_single_quote(self):
        regions = self.t._find_protected_regions("'hello'")
        assert len(regions) == 1
        assert regions[0] == (0, 7)

    def test_find_protected_regions_escaped_quote(self):
        regions = self.t._find_protected_regions("'it''s'")
        assert len(regions) == 1
        assert regions[0] == (0, 7)

    def test_find_protected_regions_line_comment(self):
        regions = self.t._find_protected_regions("x -- comment\ny")
        assert any(r[0] == 2 for r in regions)

    def test_find_protected_regions_block_comment(self):
        regions = self.t._find_protected_regions("x /* block */ y")
        assert any(r[0] == 2 for r in regions)

    def test_is_in_protected_region_true(self):
        assert self.t._is_in_protected_region(3, [(0, 10)]) is True

    def test_is_in_protected_region_false(self):
        assert self.t._is_in_protected_region(15, [(0, 10)]) is False

    def test_is_in_protected_region_boundary(self):
        # pos == end is NOT in region
        assert self.t._is_in_protected_region(10, [(0, 10)]) is False

    def test_is_in_protected_region_empty(self):
        assert self.t._is_in_protected_region(5, []) is False


# ============================================================================
# pg_constraint.py
# ============================================================================
from iris_pgwire.catalog.pg_constraint import PgConstraintEmulator, PgConstraint
from iris_pgwire.catalog.oid_generator import OIDGenerator


class TestPgConstraintEmulator:
    def setup_method(self):
        self.oid_gen = OIDGenerator()
        self.emu = PgConstraintEmulator(self.oid_gen)

    def test_from_iris_constraint_pk(self):
        c = self.emu.from_iris_constraint("users", "pk_users", "PRIMARY KEY", [1])
        assert c.contype == "p"
        assert c.conname == "pk_users"
        assert c.conkey == [1]
        assert c.confrelid == 0

    def test_from_iris_constraint_fk(self):
        c = self.emu.from_iris_constraint(
            "orders", "fk_user", "FOREIGN KEY", [2], ref_table_name="users", ref_column_positions=[1]
        )
        assert c.contype == "f"
        assert c.confrelid != 0
        assert c.confkey == [1]
        assert c.confupdtype == "a"
        assert c.confdeltype == "a"

    def test_from_iris_constraint_unique(self):
        c = self.emu.from_iris_constraint("users", "uq_email", "UNIQUE", [3])
        assert c.contype == "u"

    def test_from_iris_constraint_check(self):
        c = self.emu.from_iris_constraint("users", "chk_age", "CHECK", [4])
        assert c.contype == "c"

    def test_from_iris_constraint_defaults(self):
        c = self.emu.from_iris_constraint("t", "pk_t", "PRIMARY KEY", [1])
        assert c.condeferrable is False
        assert c.condeferred is False
        assert c.convalidated is True
        assert c.conislocal is True
        assert c.coninhcount == 0
        assert c.connoinherit is True
        assert c.conbin is None
        assert c.conpfeqop == []

    def test_add_constraint_and_get_all(self):
        c = self.emu.from_iris_constraint("t1", "pk_t1", "PRIMARY KEY", [1])
        self.emu.add_constraint(c)
        assert len(self.emu.get_all()) == 1
        assert self.emu.get_all()[0].conname == "pk_t1"

    def test_get_all_as_rows(self):
        c = self.emu.from_iris_constraint("t1", "pk_t1", "PRIMARY KEY", [1])
        self.emu.add_constraint(c)
        rows = self.emu.get_all_as_rows()
        assert len(rows) == 1
        assert isinstance(rows[0], tuple)
        assert len(rows[0]) == 25  # pg_constraint has 25 columns

    def test_get_by_table_oid(self):
        c = self.emu.from_iris_constraint("t1", "pk_t1", "PRIMARY KEY", [1])
        self.emu.add_constraint(c)
        results = self.emu.get_by_table_oid(c.conrelid)
        assert len(results) == 1
        assert results[0].conname == "pk_t1"

    def test_get_by_table_oid_missing(self):
        assert self.emu.get_by_table_oid(99999) == []

    def test_get_by_table_oid_as_rows(self):
        c = self.emu.from_iris_constraint("t1", "pk_t1", "PRIMARY KEY", [1])
        self.emu.add_constraint(c)
        rows = self.emu.get_by_table_oid_as_rows(c.conrelid)
        assert len(rows) == 1
        assert isinstance(rows[0], tuple)

    def test_get_by_referenced_table(self):
        c = self.emu.from_iris_constraint(
            "orders", "fk_user", "FOREIGN KEY", [2], ref_table_name="users", ref_column_positions=[1]
        )
        self.emu.add_constraint(c)
        results = self.emu.get_by_referenced_table(c.confrelid)
        assert len(results) == 1
        assert results[0].contype == "f"

    def test_get_by_referenced_table_missing(self):
        assert self.emu.get_by_referenced_table(99999) == []

    def test_fk_no_ref_table(self):
        c = self.emu.from_iris_constraint("orders", "fk_orphan", "FOREIGN KEY", [2])
        assert c.confrelid == 0
        assert c.confkey == []

    def test_get_column_definitions(self):
        cols = PgConstraintEmulator.get_column_definitions()
        assert len(cols) == 25
        names = [c["name"] for c in cols]
        assert "oid" in names
        assert "contype" in names
        assert "conbin" in names

    def test_to_row_structure(self):
        c = self.emu.from_iris_constraint("t1", "pk_t1", "PRIMARY KEY", [1, 2])
        self.emu.add_constraint(c)
        row = self.emu.get_all_as_rows()[0]
        # oid is first
        assert isinstance(row[0], int)
        # conname is second, lowercased
        assert row[1] == "pk_t1"
        # contype
        assert row[3] == "p"


# ============================================================================
# security_validator.py — validate_security logic (mock subprocess)
# ============================================================================
from iris_pgwire.quality.security_validator import SecurityValidator


class TestSecurityValidator:
    def setup_method(self):
        self.v = SecurityValidator()

    def test_validate_security_path_not_found(self):
        with pytest.raises(FileNotFoundError):
            self.v.validate_security("/nonexistent/path/xyz")

    def test_scan_code_security_json_parse_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="not json", returncode=1)
            ok, issues = self.v.scan_code_security("/tmp")
            assert ok is False
            assert issues[0]["issue_type"] == "TOOL_ERROR"
            assert "JSON" in issues[0]["description"]

    def test_scan_code_security_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bandit", 120)):
            ok, issues = self.v.scan_code_security("/tmp")
            assert ok is False
            assert "timed out" in issues[0]["description"]

    def test_scan_code_security_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            ok, issues = self.v.scan_code_security("/tmp")
            assert ok is False
            assert "not installed" in issues[0]["description"]

    def test_scan_code_security_generic_exception(self):
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            ok, issues = self.v.scan_code_security("/tmp")
            assert ok is False
            assert "boom" in issues[0]["description"]

    def test_scan_code_security_clean(self):
        clean_json = '{"results": [], "errors": []}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=clean_json, returncode=0)
            ok, issues = self.v.scan_code_security("/tmp")
            assert ok is True
            assert issues == []

    def test_scan_code_security_with_issues(self):
        issues_json = '{"results": [{"issue_severity": "HIGH", "issue_confidence": "HIGH", "test_id": "B101", "filename": "foo.py", "line_number": 5, "issue_text": "assert used"}], "errors": []}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=issues_json, returncode=1)
            ok, issues = self.v.scan_code_security("/tmp")
            assert ok is False
            assert issues[0]["severity"] == "HIGH"

    def test_scan_dependency_vulnerabilities_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pip-audit", 120)):
            ok, vulns = self.v.scan_dependency_vulnerabilities()
            assert ok is False
            assert "timed out" in vulns[0]["description"]

    def test_scan_dependency_vulnerabilities_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            ok, vulns = self.v.scan_dependency_vulnerabilities()
            assert ok is False
            assert "not installed" in vulns[0]["description"]

    def test_scan_dependency_vulnerabilities_json_error(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="not json", returncode=1)
            ok, vulns = self.v.scan_dependency_vulnerabilities()
            assert ok is False
            assert vulns[0]["vulnerability_id"] == "TOOL_ERROR"

    def test_scan_dependency_vulnerabilities_clean(self):
        clean_json = '{"dependencies": []}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=clean_json, returncode=0)
            ok, vulns = self.v.scan_dependency_vulnerabilities()
            assert ok is True
            assert vulns == []

    def test_scan_dependency_vulnerabilities_generic_exception(self):
        with patch("subprocess.run", side_effect=RuntimeError("oops")):
            ok, vulns = self.v.scan_dependency_vulnerabilities()
            assert ok is False
            assert "oops" in vulns[0]["description"]

    def test_check_license_compatibility_mit(self):
        ok, incompatible = self.v.check_license_compatibility("MIT")
        assert ok is True
        assert incompatible == []

    def test_check_license_compatibility_gpl(self):
        ok, incompatible = self.v.check_license_compatibility("GPL-3.0")
        assert ok is False
        assert "GPL-3.0" in incompatible

    def test_check_license_compatibility_list(self):
        ok, incompatible = self.v.check_license_compatibility(["MIT", "Apache-2.0", "AGPL-3.0"])
        assert ok is False
        assert "AGPL-3.0" in incompatible

    def test_validate_security_with_high_issue(self):
        issues_json = '{"results": [{"issue_severity": "HIGH", "issue_confidence": "HIGH", "test_id": "B101", "filename": "foo.py", "line_number": 1, "issue_text": "desc"}], "errors": []}'
        clean_pip = '{"dependencies": []}'
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout=issues_json, returncode=1),
                MagicMock(stdout=clean_pip, returncode=0),
            ]
            result = self.v.validate_security("/tmp")
            assert result["is_secure"] is False
            assert result["high_count"] == 1

    def test_validate_security_no_dep_scan(self):
        clean_json = '{"results": [], "errors": []}'
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=clean_json, returncode=0)
            result = self.v.validate_security("/tmp", scan_dependencies=False)
            assert result["is_secure"] is True
            assert result["dependency_vulnerabilities"] == []

    def test_validate_security_critical_cvss(self):
        issues_json = '{"results": [], "errors": []}'
        vuln_json = '{"dependencies": [{"name": "pkg", "version": "1.0", "vulns": [{"id": "CVE-123", "description": "bad", "fix_versions": [{"cvss": {"score": 9.5}}]}]}]}'
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout=issues_json, returncode=0),
                MagicMock(stdout=vuln_json, returncode=1),
            ]
            result = self.v.validate_security("/tmp")
            assert result["critical_count"] == 1
            assert result["is_secure"] is False

    def test_get_security_report_returns_string(self):
        clean_json = '{"results": [], "errors": []}'
        clean_pip = '{"dependencies": []}'
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(stdout=clean_json, returncode=0),
                MagicMock(stdout=clean_pip, returncode=0),
            ]
            report = self.v.get_security_report("/tmp")
            assert isinstance(report, str)
            assert "Security Validation Report" in report
