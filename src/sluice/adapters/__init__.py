"""Pluggable adapter protocols for chat, forge, and AI backends."""

from sluice.adapters.agy_cli import AgyBackendAdapter
from sluice.adapters.backend import BackendAdapter
from sluice.adapters.backend_factory import build_backends
from sluice.adapters.chat import ChatAdapter, IncomingMessage, OutgoingMessage
from sluice.adapters.claude_code import ClaudeCodeBackendAdapter
from sluice.adapters.cursor_cli import CursorBackendAdapter
from sluice.adapters.forge import ForgeAdapter
from sluice.adapters.github_forge import GitHubForgeAdapter
from sluice.adapters.matrix_chat import MatrixChatAdapter

__all__ = [
    "AgyBackendAdapter",
    "BackendAdapter",
    "ChatAdapter",
    "ClaudeCodeBackendAdapter",
    "CursorBackendAdapter",
    "ForgeAdapter",
    "GitHubForgeAdapter",
    "IncomingMessage",
    "MatrixChatAdapter",
    "OutgoingMessage",
    "build_backends",
]
