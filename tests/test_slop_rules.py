"""Tests for the deterministic slop rules — each rule must fire on slop and stay quiet on clean code."""
from pathlib import Path

import pytest

from core.slop.engine import SlopEngine


def scan(tmp_path: Path, name: str, content: str, extra: dict | None = None) -> list:
    """Write files into a throwaway project and return rule ids found in `name`."""
    for rel, text in (extra or {}).items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    engine = SlopEngine(tmp_path)
    issues = engine.check_file(path, content) + engine.finalize()
    return [i.rule_id for i in issues]


@pytest.mark.parametrize("rule_id, name, sloppy, clean", [
    ("ui/ai-gradient", "Hero.tsx",
     '<div className="bg-gradient-to-r from-purple-600 to-pink-500" />',
     '<div className="bg-slate-900" />'),
    ("ui/ai-gradient", "style.css",
     ".hero { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }",
     ".hero { background: var(--surface); }"),
    ("ui/gradient-text", "Hero.tsx",
     '<h1 className="bg-clip-text text-transparent">Hi</h1>',
     '<h1 className="text-slate-900">Hi</h1>'),
    ("ui/marketing-slop", "Hero.tsx",
     "<p>Unlock the power of AI to supercharge your workflow</p>",
     "<p>Invoices are matched to bank transactions every night.</p>"),
    ("ui/fake-social-proof", "Hero.tsx",
     "<p>Trusted by 10,000+ happy users</p>",
     "<p>Used by the finance team at our company</p>"),
    ("ui/placeholder-copy", "Hero.tsx",
     "<p>Lorem ipsum dolor sit amet</p>",
     "<p>Real copy</p>"),
    ("ui/blur-blobs", "Hero.tsx",
     '<div className="absolute rounded-full bg-pink-400 blur-3xl" />',
     '<div className="rounded-full bg-pink-400" />'),
    ("a11y/img-alt", "Hero.tsx",
     '<img src="/a.png" />',
     '<img src="/a.png" alt="Dashboard screenshot" />'),
    ("a11y/clickable-div", "Hero.tsx",
     "<div onClick={() => go()}>Go</div>",
     '<button type="button" onClick={() => go()}>Go</button>'),
    ("a11y/icon-button", "Hero.tsx",
     "<button onClick={close}>\n  <XIcon />\n</button>",
     '<button onClick={close} aria-label="Close">\n  <XIcon />\n</button>'),
    ("a11y/dead-link", "Hero.tsx",
     '<a href="#">Docs</a>',
     '<a href="/docs">Docs</a>'),
    ("a11y/focus-removed", "Hero.tsx",
     '<input className="outline-none border" />',
     '<input className="outline-none focus-visible:ring-2 border" />'),
    ("slop/elided-code", "api.ts",
     "export function a() {}\n// ... existing code ...\n",
     "export function a() {}\n// Retries are handled by the caller.\n"),
    ("slop/placeholder-impl", "auth.py",
     "def login(u):\n    # In a real application, you would hash the password\n    return True\n",
     "def login(u):\n    # bcrypt cost 12 keeps hashing under 250ms on our servers\n    return True\n"),
    ("slop/swallowed-exception", "io.py",
     "try:\n    x = 1\nexcept Exception:\n    pass\n",
     "try:\n    x = 1\nexcept ValueError:\n    pass\n"),
    ("slop/bare-except", "io.py",
     "try:\n    x = 1\nexcept:\n    raise\n",
     "try:\n    x = 1\nexcept OSError:\n    raise\n"),
    ("slop/empty-catch", "api.ts",
     "try { run() } catch (e) {}",
     "try { run() } catch (e) { report(e) }"),
    ("slop/narrating-comment", "app.py",
     "# Initialize the user list\nuser_list = []\n",
     "# Kept sorted so bisect lookups stay O(log n)\nuser_list = []\n"),
    ("slop/stub-function", "svc.py",
     'def charge(card):\n    """Charge the card."""\n    pass\n',
     'def charge(card):\n    """Charge the card."""\n    return gateway.charge(card)\n'),
    ("slop/debugger", "app.ts",
     "function f() {\n  debugger;\n}\n",
     "function f() {\n  return 1;\n}\n"),
    ("slop/emoji-log", "server.js",
     'console.log("🚀 Server started");',  # fixmyslop-ignore[slop/emoji-log] fixture
     'console.log("Server started on port %d", port);'),
    ("sec/leaked-key", "config.py",
     'KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"\n',
     'KEY = os.environ["OPENAI_API_KEY"]\n'),
    ("sec/hardcoded-credential", "config.py",
     'DB_PASSWORD = "hunter2-prod-99"\n',
     'DB_PASSWORD = os.environ.get("DB_PASSWORD")\n'),
    ("sec/public-env-secret", "client.ts",
     "const k = process.env.NEXT_PUBLIC_OPENAI_API_KEY;",  # fixmyslop-ignore[sec/public-env-secret] fixture
     "const k = process.env.NEXT_PUBLIC_APP_URL;"),
    ("sec/sql-injection", "db.py",
     'cur.execute(f"SELECT * FROM users WHERE id = {uid}")\n',
     'cur.execute("SELECT * FROM users WHERE id = %s", (uid,))\n'),
    ("sec/cors-wildcard", "main.py",
     'app.add_middleware(CORSMiddleware, allow_origins=["*"])\n',
     'app.add_middleware(CORSMiddleware, allow_origins=settings.origins)\n'),
    ("sec/tls-disabled", "net.py",
     "requests.get(url, verify=False)\n",
     "requests.get(url, timeout=10)\n"),
    ("sec/raw-html", "Post.tsx",
     "<div dangerouslySetInnerHTML={{ __html: body }} />",
     "<div>{body}</div>"),
])
def test_rule_fires_on_slop_and_not_on_clean(tmp_path, rule_id, name, sloppy, clean):
    """Every rule: positive example flagged, negative example quiet."""
    assert rule_id in scan(tmp_path / "bad", name, sloppy)
    assert rule_id not in scan(tmp_path / "good", name, clean)


def test_threshold_rules_need_repetition(tmp_path):
    """hover-scale only reports once the pattern is repeated across the project."""
    once = '<div className="hover:scale-105" />\n'
    assert "ui/hover-scale" not in scan(tmp_path / "a", "A.tsx", once)
    assert "ui/hover-scale" in scan(tmp_path / "b", "A.tsx", once * 5)


def test_rainbow_palette_is_project_level(tmp_path):
    """Seven-plus accent families across the project triggers one finding."""
    colors = " ".join(f"text-{c}-500" for c in
                      ["red", "orange", "green", "teal", "sky", "violet", "pink", "lime"])
    found = scan(tmp_path, "A.tsx", f'<div className="{colors}" />')
    assert found.count("ui/rainbow-palette") == 1


def test_ui_rules_skip_test_files(tmp_path):
    """UI/copy rules don't fire on tests or stories."""
    assert "ui/marketing-slop" not in scan(tmp_path, "src/__tests__/Hero.test.tsx",
                                           "<p>Revolutionize everything</p>")


def test_python_phantom_and_undeclared_imports(tmp_path):
    """Unknown package → phantom; installed-but-undeclared → undeclared; declared/stdlib/local → fine."""
    code = ("import os\nimport yaml\nimport totally_made_up_pkg_xyz\nimport localmod\nimport pytest\n")
    found = scan(tmp_path, "app.py", code, extra={"requirements.txt": "pyyaml\n", "localmod.py": "X = 1\n"})
    assert found.count("deps/phantom-import") == 1
    assert "deps/undeclared-import" in found  # pytest is installed but not declared


def test_guarded_imports_are_ignored(tmp_path):
    """Optional imports inside try/except ImportError are not phantom."""
    code = "try:\n    import totally_made_up_pkg_xyz\nexcept ImportError:\n    totally_made_up_pkg_xyz = None\n"
    assert "deps/phantom-import" not in scan(tmp_path, "app.py", code, extra={"requirements.txt": ""})


def test_js_imports(tmp_path):
    """npm packages are checked against package.json; aliases, relatives and builtins are fine."""
    code = ('import React from "react";\nimport x from "@/lib/x";\nimport y from "./y";\n'
            'import fs from "node:fs";\nimport path from "path";\nimport z from "react-quantum-forms";\n')
    found = scan(tmp_path, "src/App.tsx", code, extra={"package.json": '{"dependencies": {"react": "18"}}'})
    assert found.count("deps/phantom-import") == 1


def test_inline_suppression(tmp_path):
    """fixmyslop-ignore[rule] on the line or the line above silences that rule only."""
    code = ('// fixmyslop-ignore[ui/gradient-text] brand requirement\n'
            '<h1 className="bg-clip-text text-transparent">Hi</h1>\n'
            '<a href="#">x</a>\n')
    found = scan(tmp_path, "A.tsx", code)
    assert "ui/gradient-text" not in found
    assert "a11y/dead-link" in found


def test_file_level_ignore(tmp_path):
    """fixmyslop-ignore-file in the header skips the file."""
    assert scan(tmp_path, "A.tsx", "// fixmyslop-ignore-file\n<a href=\"#\">x</a>\n") == []


def test_config_disable_and_exclude(tmp_path):
    """.fixmyslop.yml can disable rule groups and exclude paths."""
    (tmp_path / ".fixmyslop.yml").write_text('disable: ["a11y"]\nexclude: ["legacy/**"]\n', encoding="utf-8")
    assert "a11y/dead-link" not in scan(tmp_path, "A.tsx", '<a href="#">x</a>')
    assert scan(tmp_path, "legacy/B.tsx", '<a href="#">x</a> <p>Lorem ipsum</p>') == []


def test_secrets_are_redacted(tmp_path):
    """The leaked key never appears in evidence or descriptions."""
    path = tmp_path / "c.py"
    content = 'KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"\n'
    path.write_text(content, encoding="utf-8")
    issues = SlopEngine(tmp_path).check_file(path, content)
    leaked = [i for i in issues if i.rule_id == "sec/leaked-key"]
    assert leaked
    assert "abcdefghijklmnop" not in leaked[0].evidence + leaked[0].description
