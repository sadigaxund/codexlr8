"""Tests for the code scanner."""

from codexlr8.scanner import scan_project, extract_symbols


def test_scan_project(sample_project):
    results = scan_project(str(sample_project))
    paths = {r["path"] for r in results}
    assert "auth/session.py" in paths
    assert "auth/permissions.py" in paths
    assert "cart/cart.py" in paths
    assert "config.py" in paths
    assert "tests/test_auth.py" in paths


def test_extract_python_functions():
    source = '''
def login(username, password):
    """Auth login."""
    pass

def logout():
    pass
'''
    symbols, docstring = extract_symbols(source, ".py")
    names = {s["name"] for s in symbols}
    assert "login" in names
    assert "logout" in names


def test_extract_python_classes():
    source = '''
class ShoppingCart:
    """A cart."""

    def add_item(self):
        pass
'''
    symbols, docstring = extract_symbols(source, ".py")
    classes = [s for s in symbols if s["kind"] == "class"]
    assert len(classes) == 1
    assert classes[0]["name"] == "ShoppingCart"
    assert "add_item" in classes[0]["methods"]


def test_extract_module_docstring():
    source = '"""Module doc."""\n\nx = 1\n'
    symbols, docstring = extract_symbols(source, ".py")
    assert docstring == "Module doc."
