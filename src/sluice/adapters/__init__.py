"""Pluggable adapter protocols for chat, forge, and AI backends."""

from sluice.adapters.backend import BackendAdapter
from sluice.adapters.chat import ChatAdapter, IncomingMessage, OutgoingMessage
from sluice.adapters.claude_code import ClaudeCodeBackendAdapter
from sluice.adapters.forge import ForgeAdapter
from sluice.adapters.github_forge import GitHubForgeAdapter
from sluice.adapters.matrix_chat import MatrixChatAdapter

__all__ = [
    "BackendAdapter",
    "ChatAdapter",
    "ClaudeCodeBackendAdapter",
    "ForgeAdapter",
    "GitHubForgeAdapter",
    "IncomingMessage",
    "MatrixChatAdapter",
    "OutgoingMessage",
]
