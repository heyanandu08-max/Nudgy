#!/usr/bin/env bash
# Type-checks the Tauri crate for Linux, Windows and macOS from one machine.
# Needs: rustup targets x86_64-pc-windows-msvc + aarch64-apple-darwin, and clang
# (objc2's exception helper compiles an Objective-C file for the macOS target).
# LIBSQLITE3_SYS_USE_PKG_CONFIG=1 skips compiling bundled SQLite's C code for foreign
# targets (type-checking only; real builds on each OS bundle SQLite).
set -euo pipefail
cd "$(dirname "$0")/../app/src-tauri"
echo "== linux (native)";  cargo check --all-targets
export LIBSQLITE3_SYS_USE_PKG_CONFIG=1
echo "== windows";         cargo check --target x86_64-pc-windows-msvc
echo "== macos";           CC_aarch64_apple_darwin=clang cargo check --target aarch64-apple-darwin
