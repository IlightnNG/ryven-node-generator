"""Shared exceptions for AI assistant orchestration."""


class GenerationStopped(RuntimeError):
    """Raised when the user requests stop during generation."""
