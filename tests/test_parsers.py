import pytest
from atlasindex.parsers.tree_sitter_parser import PythonAstParser, RegexFallbackParser, MasterParser

def test_python_ast_parser():
    parser = PythonAstParser()
    code = """
import os
from sys import argv
import requests as req

class MockUser(BaseModel):
    name: str
    def get_name(self):
        return self.name

@app.get("/api/v1/users")
def get_users(limit: int = 10, offset: int = 0):
    \"\"\"Fetches user records from database.\"\"\"
    pass
"""
    result = parser.parse(code)
    
    # Assert imports
    import_names = {i.name for i in result.imports}
    assert "os" in import_names
    assert "argv" in import_names
    assert "requests" in import_names

    # Assert class
    assert len(result.classes) == 1
    assert result.classes[0].name == "MockUser"
    assert "get_name" in result.classes[0].methods

    # Assert function
    func_names = {f.name for f in result.functions}
    assert "get_users" in func_names
    func = [f for f in result.functions if f.name == "get_users"][0]
    assert "limit" in func.parameters
    assert "offset" in func.parameters
    assert "Fetches user records" in func.docstring

    # Assert endpoints
    assert len(result.endpoints) == 1
    assert result.endpoints[0].method == "GET"
    assert result.endpoints[0].path == "/api/v1/users"


def test_js_regex_fallback_parser():
    parser = RegexFallbackParser("javascript")
    code = """
const express = require('express');
import { debounce } from 'lodash';

class AuthController extends Controller {
    login() {}
}

function processPayment(amount, gateway) {
    return true;
}

const formatCurrency = (val) => {
    return '$' + val;
}

router.post('/checkout/pay', processPayment);
"""
    result = parser.parse(code)

    # Assert imports
    import_names = {i.name for i in result.imports}
    assert "express" in import_names
    assert "lodash" in import_names

    # Assert class
    assert len(result.classes) == 1
    assert result.classes[0].name == "AuthController"
    assert "Controller" in result.classes[0].inheritance

    # Assert functions
    func_names = {f.name for f in result.functions}
    assert "processPayment" in func_names
    assert "formatCurrency" in func_names
    
    pay_func = [f for f in result.functions if f.name == "processPayment"][0]
    assert "amount" in pay_func.parameters
    assert "gateway" in pay_func.parameters

    # Assert endpoints
    assert len(result.endpoints) == 1
    assert result.endpoints[0].method == "POST"
    assert result.endpoints[0].path == "/checkout/pay"
