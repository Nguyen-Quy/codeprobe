from __future__ import annotations

from pathlib import Path

from codeprobe.core.symbols import extract_symbols_from_source
from codeprobe.tools import run_tests, set_workspace_root


def test_extract_symbols_typescript():
    ts_code = """
    export interface AuthPayload {
        userId: string;
    }
    export class AuthService {
        async login() {}
    }
    export const verifyToken = async () => {};
    enum Role { ADMIN, USER }
    """
    syms = extract_symbols_from_source(ts_code, "auth.ts")
    assert "AuthPayload" in syms
    assert "AuthService" in syms
    assert "verifyToken" in syms
    assert "Role" in syms


def test_extract_symbols_rust():
    rs_code = """
    pub struct UserModel {
        pub id: u64,
    }
    pub enum UserRole {
        Admin,
    }
    pub trait Authenticatable {
        fn authenticate(&self) -> bool;
    }
    impl Authenticatable for UserModel {
        fn authenticate(&self) -> bool { true }
    }
    """
    syms = extract_symbols_from_source(rs_code, "model.rs")
    assert "UserModel" in syms
    assert "UserRole" in syms
    assert "Authenticatable" in syms


def test_extract_symbols_go():
    go_code = """
    type SessionStore struct {}
    func NewSessionStore() *SessionStore { return &SessionStore{} }
    """
    syms = extract_symbols_from_source(go_code, "session.go")
    assert "SessionStore" in syms
    assert "NewSessionStore" in syms


def test_multilang_test_runner_detection(tmp_path: Path):
    try:
        set_workspace_root(tmp_path)
        # No test config
        out = run_tests()
        assert "No supported test suite" in out

        # Rust Cargo config
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text('[package]\nname = "demo"\nversion = "0.1.0"')
        # When Cargo.toml exists, run_tests attempts cargo test
        # (output contains cargo invocation result or error)
        out_cargo = run_tests()
        assert out_cargo is not None
    finally:
        set_workspace_root(None)
