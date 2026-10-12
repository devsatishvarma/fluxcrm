"""Domain errors shared by HTML views and the API."""


class VersionConflict(Exception):
    """The caller edited a record version that is no longer current."""
