from __future__ import annotations

from codeprobe.core.declarations import DeclarationParser


def test_parse_python_declarations():
    code = '''
"""Module docstring."""

class UserService:
    """Service handling users."""
    def __init__(self, db):
        self.db = db

    def get_user(self, user_id: str):
        validate_id(user_id)
        return self.db.find(user_id)

def helper_func():
    print("helper")
'''
    units = DeclarationParser.parse(code, file_path="src/user.py")
    names = {u.name: u for u in units}

    assert "UserService" in names
    assert names["UserService"].kind == "class"
    assert "Service handling users." in (names["UserService"].docstring or "")
    assert names["UserService"].start_line > 0

    assert "get_user" in names
    assert names["get_user"].kind == "function"
    assert "validate_id" in names["get_user"].calls
    assert "find" in names["get_user"].calls

    assert "helper_func" in names


def test_parse_typescript_declarations():
    code = """
export interface UserPayload {
    id: string;
    email: string;
}

export class AuthService {
    async login(token: string) {
        verifyJwt(token);
        return true;
    }
}

export const fetchProfile = async (id: string) => {
    httpGet(id);
};
"""
    units = DeclarationParser.parse(code, file_path="src/auth.ts")
    names = {u.name: u for u in units}

    assert "UserPayload" in names
    assert names["UserPayload"].kind == "interface"

    assert "AuthService" in names
    assert names["AuthService"].kind == "class"

    assert "fetchProfile" in names
    assert names["fetchProfile"].kind == "function"
    assert "httpGet" in names["fetchProfile"].calls


def test_parse_go_declarations():
    code = """
package main

type Config struct {
    Port int
}

func HandleRequest(req Request) {
    validate(req)
    process()
}
"""
    units = DeclarationParser.parse(code, file_path="main.go")
    names = {u.name: u for u in units}

    assert "Config" in names
    assert names["Config"].kind == "struct"

    assert "HandleRequest" in names
    assert names["HandleRequest"].kind == "function"
    assert "validate" in names["HandleRequest"].calls


def test_parse_rust_declarations():
    code = """
pub struct ConnectionPool {
    size: usize,
}

pub trait Database {
    fn execute(&self);
}

pub fn establish_connection(url: &str) {
    connect(url);
}
"""
    units = DeclarationParser.parse(code, file_path="src/db.rs")
    names = {u.name: u for u in units}

    assert "ConnectionPool" in names
    assert names["ConnectionPool"].kind == "struct"

    assert "Database" in names
    assert names["Database"].kind == "trait"

    assert "establish_connection" in names
    assert names["establish_connection"].kind == "function"
    assert "connect" in names["establish_connection"].calls


def test_parse_fallback_declarations():
    text = "line 1\nline 2\nline 3"
    units = DeclarationParser.parse(text, file_path="notes.txt")
    assert len(units) == 1
    assert units[0].name == "notes"
    assert units[0].kind == "file"
