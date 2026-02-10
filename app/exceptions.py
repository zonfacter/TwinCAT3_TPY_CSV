from __future__ import annotations


class AppError(Exception):
    """Base exception for the application."""


class ConfigError(AppError):
    """Raised when config cannot be loaded/saved."""


class InputFileError(AppError):
    """Raised when input files are missing/invalid."""


class RegexFileError(AppError):
    """Raised when whitelist/blacklist regex files are invalid."""


class ConversionError(AppError):
    """Raised when conversion fails."""
