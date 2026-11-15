"""Export the translator's test expectations as PostgreSQL-in / IRIS-out pairs for SQLGlot.

The IRIS SQLGlot dialect (irispython-dx, working name `sqlglot-intersystems-iris`) uses these
pairs as test fixtures. A pair is kept only when a unit test asserts the exact output
(`assert f(sql) == "..."`, the reverse, through a local name, or through parametrize) and
running the same call today gives that output. So every `iris` value is a hand-written
expectation that still holds, never the translator's output standing in for one.

Each pair's `note` names the test and the stage it exercised. Many tests cover one stage of
the translator, not the whole chain, so a pair says what that stage produces. `iris_version`
is left out: the unit tests do not run on IRIS.

    PYTHONPATH=src python scripts/export_sqlglot_corpus.py          # write the corpus
    PYTHONPATH=src python scripts/export_sqlglot_corpus.py --check  # exit 1 if stale
"""

from __future__ import annotations

import argparse
import ast
import functools
import importlib.util
import inspect
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "sqlglot_corpus.jsonl"
FRAGMENTS = ROOT / "tests" / "fixtures" / "sqlglot_fragments.jsonl"
TEST_DIR = ROOT / "tests" / "unit"

_SQL = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH|TRUNCATE|SET|SHOW|BEGIN|COMMIT"
    r"|ROLLBACK|SAVEPOINT|RELEASE|EXPLAIN|COPY|VALUES|START|LOCK|COMMENT|GRANT)\b",
    re.IGNORECASE,
)

# Stages whose result is not a statement for IRIS: command tags, column labels, catalog
# routing, parsers that return a piece of the input, parameter inlining.
_NOT_A_TRANSLATION = re.compile(
    r"command_tag|(^|\.)_?parse|column_name|column_label|catalog|quote|sanitize|CacheKey"
    r"|^run$|refusal|^fmt$|returning_clause|inline|_strip",
    re.IGNORECASE,
)

# The exporter runs fixtures and calls, so outside tests/unit a file that may reach a live
# server is not scanned at all.
_CONNECTS = re.compile(r"psycopg|asyncpg|\.connect\(|createConnection|iris\.dbapi|socket\.")

# pytest.skip() inside a fixture or at module level raises this, a BaseException.
_FAILED = (Exception, pytest.skip.Exception)

skipped: Counter[str] = Counter()


def _is_sql(value: object) -> bool:
    return isinstance(value, str) and bool(_SQL.match(value))


def _not_a_translation(stage: str) -> bool:
    return bool(_NOT_A_TRANSLATION.search(stage.split(" (via")[0]))


def _load(path: Path):
    name = f"_corpus_{path.stem}_{abs(hash(path)) % 10**8}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _eval(node: ast.AST, namespace: dict, local: dict | None = None):
    return eval(compile(ast.Expression(node), "<expr>", "eval"), namespace, local)


def _parametrize_sets(func: ast.FunctionDef, namespace: dict) -> list[dict]:
    """One dict of argument values per parametrize combination; raises if one can't be read."""
    groups = []
    for deco in func.decorator_list:
        if not (
            isinstance(deco, ast.Call)
            and ast.unparse(deco.func).endswith("mark.parametrize")
            and len(deco.args) >= 2
        ):
            continue
        names = _eval(deco.args[0], namespace)
        values = _eval(deco.args[1], namespace)
        names = [n.strip() for n in names.split(",")] if isinstance(names, str) else list(names)
        rows = []
        for value in values:
            if hasattr(value, "values") and hasattr(value, "marks"):  # pytest.param
                value = value.values if len(names) > 1 else value.values[0]
            rows.append(
                dict(zip(names, value, strict=True)) if len(names) > 1 else {names[0]: value}
            )
        groups.append(rows)
    return [
        dict(itertools.chain.from_iterable(row.items() for row in combo))
        for combo in itertools.product(*groups)
    ]


def _sql_call(node: ast.AST, namespace: dict, local: dict):
    """The call inside `node` that takes a SQL string, and that string."""
    for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        for arg in [*call.args, *(k.value for k in call.keywords)]:
            try:
                value = _eval(arg, namespace, local)
            except Exception:
                continue
            if _is_sql(value):
                return call, value
    return None, None


class _Case:
    def __init__(
        self, path: Path, test_id: str, func: ast.FunctionDef, namespace: dict, local: dict
    ):
        self.path, self.test_id, self.func = path, test_id, func
        self.namespace, self.local = namespace, local
        self.from_call: dict[str, tuple[ast.Call, str]] = {}
        self.expected_names: set[str] = set(local) - {"self"}

    def _output(self, node: ast.AST):
        """(stage, input SQL) if `node` is a translation result, else None."""
        if isinstance(node, ast.Name) and node.id in self.from_call:
            call, sql = self.from_call[node.id]
            return ast.unparse(call.func), sql
        if isinstance(node, ast.Constant) or (
            isinstance(node, ast.Name) and node.id in self.expected_names
        ):
            return None
        call, sql = _sql_call(node, self.namespace, self.local)
        if call is None:
            return None
        stage = ast.unparse(call.func)
        return (stage if node is call else f"{stage} (via `{ast.unparse(node)}`)"), sql

    def _expected(self, node: ast.AST) -> bool:
        return (isinstance(node, ast.Constant) and isinstance(node.value, str)) or (
            isinstance(node, ast.Name) and node.id in self.expected_names
        )

    def _comparisons(self):
        """(operator, left, right) of each one-operator assert, after the assignments before it."""
        for stmt in self.func.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                self._assign(stmt)
            elif (
                isinstance(stmt, ast.Assert)
                and isinstance(stmt.test, ast.Compare)
                and len(stmt.test.ops) == 1
            ):
                yield type(stmt.test.ops[0]), stmt.test.left, stmt.test.comparators[0]

    def pairs(self):
        for op, left, right in self._comparisons():
            if op is ast.Eq:
                pair = self._compare(left, right)
                if pair:
                    yield pair

    def fragments(self):
        """One case per translation output the test checks with `in` / `not in`. A case whose
        checks do not all hold today is dropped whole."""
        cases: dict[tuple[str, str], dict] = {}
        broken: set[tuple[str, str]] = set()
        for op, left, right in self._comparisons():
            if op not in (ast.In, ast.NotIn) or not self._expected(left):
                continue
            found = self._output(right)
            if not found:
                continue
            case = cases.setdefault(
                found, {"pg": found[1], "iris_contains": [], "iris_excludes": []}
            )
            try:
                fragment = _eval(left, self.namespace, self.local)
                actual = _eval(right, self.namespace, self.local)
            except Exception:
                skipped["fragment raised"] += 1
                broken.add(found)
                continue
            if not isinstance(actual, str) or (fragment in actual) != (op is ast.In):
                skipped["fragment does not hold"] += 1
                broken.add(found)
                continue
            case["iris_contains" if op is ast.In else "iris_excludes"].append(fragment)
        for (stage, sql), case in cases.items():
            if (stage, sql) in broken:
                continue
            if _not_a_translation(stage):
                skipped["not a translation"] += 1
                continue
            yield {**case, "note": f"{self.test_id}; stage: {stage}"}

    def _assign(self, stmt: ast.Assign) -> None:
        target = stmt.targets[0]
        try:
            value = _eval(stmt.value, self.namespace, self.local)
        except Exception:
            skipped["assignment raised"] += 1
            return
        names = [target] if isinstance(target, ast.Name) else list(getattr(target, "elts", []))
        if not names or not all(isinstance(n, ast.Name) for n in names):
            return
        values = [value] if len(names) == 1 else list(value)
        call, sql = _sql_call(stmt.value, self.namespace, self.local)
        for name, val in zip(names, values, strict=False):
            self.local[name.id] = val
            if call is not None:
                self.from_call[name.id] = (call, sql)
                self.expected_names.discard(name.id)
            elif isinstance(val, str):
                self.expected_names.add(name.id)

    def _compare(self, left: ast.AST, right: ast.AST):
        for out_node, exp_node in ((left, right), (right, left)):
            if not self._expected(exp_node):
                continue
            found = self._output(out_node)
            if not found:
                continue
            stage, sql = found
            try:
                actual = _eval(out_node, self.namespace, self.local)
                expected = _eval(exp_node, self.namespace, self.local)
            except Exception:
                skipped["assertion raised"] += 1
                return None
            if not isinstance(expected, str) or actual != expected:
                skipped["assertion does not hold"] += 1
                return None
            if _not_a_translation(stage) or not _is_sql(expected):
                skipped["not a translation"] += 1
                return None
            return {"pg": sql, "iris": expected, "note": f"{self.test_id}; stage: {stage}"}
        return None


@functools.cache
def _conftest_namespaces() -> list[dict]:
    return [vars(_load(ROOT / "tests" / "conftest.py"))]


def _fixture(name: str, namespace: dict, owner=None, depth: int = 0):
    """A fixture defined on the test class, in the test module or in tests/conftest.py, built
    with its own fixtures. LookupError for anything else (pytest's tmp_path, monkeypatch, ...)."""
    places = [vars(type(owner))] if owner is not None else []
    places += [namespace, *_conftest_namespaces()]
    definition = next(
        (ns[name] for ns in places if type(ns.get(name)).__name__ == "FixtureFunctionDefinition"),
        None,
    )
    if definition is None or depth > 5:
        raise LookupError(name)
    func = definition._get_wrapped_function()
    signature = inspect.signature(func).parameters
    params = [p for p in signature if p != "self"]
    if "request" in params:
        raise LookupError(name)
    kwargs = {arg: _fixture(arg, namespace, owner, depth + 1) for arg in params}
    value = func(owner, **kwargs) if "self" in signature else func(**kwargs)
    return next(value) if inspect.isgenerator(value) else value


def _instance(cls):
    obj = cls()
    setup = getattr(obj, "setup_method", None)
    if setup:
        setup(*([None] if len(inspect.signature(setup).parameters) else []))
    return obj


def _cases(path: Path, module, tree: ast.Module):
    namespace = vars(module)
    tests = [(None, f) for f in tree.body if isinstance(f, ast.FunctionDef)]
    for cls in (c for c in tree.body if isinstance(c, ast.ClassDef) and c.name.startswith("Test")):
        tests += [(cls.name, f) for f in cls.body if isinstance(f, ast.FunctionDef)]
    for cls_name, func in tests:
        if not func.name.startswith("test_"):
            continue
        test_id = "::".join(filter(None, [_test_name(path), cls_name, func.name]))
        try:
            param_sets = _parametrize_sets(func, namespace)
        except Exception:
            skipped["parametrize unreadable"] += 1
            continue
        args = [a.arg for a in func.args.args if a.arg != "self"]
        for params in param_sets:
            local = dict(params)
            if cls_name:
                try:
                    local["self"] = _instance(namespace[cls_name])
                except _FAILED:
                    skipped["class setup raised"] += 1
                    break
            try:
                for arg in args:
                    if arg not in local:
                        local[arg] = _fixture(arg, namespace, local.get("self"))
            except LookupError:
                skipped["needs a fixture"] += 1
                break
            except _FAILED:
                skipped["fixture raised"] += 1
                break
            yield _Case(path, test_id, func, namespace, local)


def _cases_in(paths):
    for path in paths:
        path = Path(path)
        try:
            tree = ast.parse(path.read_text())
            module = _load(path)
        except _FAILED:
            skipped["module would not import"] += 1
            continue
        yield from _cases(path, module, tree)


def _unique(items) -> list[dict]:
    seen, kept = set(), []
    for item in items:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            kept.append(item)
    return kept


def extract_pairs(paths) -> list[dict]:
    return _unique(pair for case in _cases_in(paths) for pair in case.pairs())


def extract_fragments(paths) -> list[dict]:
    return _unique(frag for case in _cases_in(paths) for frag in case.fragments())


def _test_files() -> list[Path]:
    """Unit, contract and protocol tests, and the top-level tests/test_*.py. Not integration or
    e2e: their fixtures start servers."""
    tests = ROOT / "tests"
    files = [
        *TEST_DIR.glob("test_*.py"),
        *(tests / "contract").glob("test_*.py"),
        *(tests / "protocol").glob("test_*.py"),
        *tests.glob("test_*.py"),
    ]
    return sorted(
        p
        for p in files
        if p.name != "test_sqlglot_corpus_export.py"
        and (p.parent == TEST_DIR or not _CONNECTS.search(p.read_text()))
    )


def _test_name(path: Path) -> str:
    """`test_x.py` for a unit test (as before), `contract/test_x.py` for the others."""
    try:
        relative = path.resolve().relative_to(ROOT / "tests")
    except ValueError:
        return path.name
    return path.name if relative.parts[0] == "unit" else str(relative)


def _lines(pairs) -> list[str]:
    return sorted(json.dumps(p, ensure_ascii=False, sort_keys=True) for p in pairs)


def _diff(path: Path, extract) -> list[str]:
    """Lines of the committed file that today's tests no longer give, plus ones they add."""
    committed = set(path.read_text().splitlines())
    current = set(_lines(extract(_test_files())))
    return sorted(f"- {line}" for line in committed - current) + sorted(
        f"+ {line}" for line in current - committed
    )


def verify_corpus() -> list[str]:
    return _diff(CORPUS, extract_pairs)


def verify_fragments() -> list[str]:
    return _diff(FRAGMENTS, extract_fragments)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the corpus is stale")
    args = parser.parse_args()
    if args.check:
        diff = verify_corpus() + verify_fragments()
        print("\n".join(diff) or "corpus up to date")
        return 1 if diff else 0
    files = _test_files()
    pairs = extract_pairs(files)
    CORPUS.write_text("".join(f"{line}\n" for line in _lines(pairs)))
    fragments = extract_fragments(files)
    FRAGMENTS.write_text("".join(f"{line}\n" for line in _lines(fragments)))
    print(f"{len(fragments)} fragment cases")
    stages = Counter(p["note"].split("; stage: ")[1].split(" (via")[0] for p in pairs)
    print(f"{len(pairs)} pairs from {len({p['note'].split('::')[0] for p in pairs})} test files")
    print("skipped:", dict(skipped))
    print("top stages:", stages.most_common(15))
    return 0


if __name__ == "__main__":
    sys.exit(main())
