"""Quick syntax check for all backend python files."""
import ast
import pathlib

root = pathlib.Path("apps/api")
files = sorted(root.rglob("*.py"))
errors = []
for f in files:
    try:
        ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
    except SyntaxError as exc:
        errors.append(f"{f}:{exc.lineno} {exc.msg}")
if errors:
    print("SYNTAX ERRORS:")
    for e in errors:
        print(" ", e)
    raise SystemExit(1)
print(f"OK: parsed {len(files)} python files")