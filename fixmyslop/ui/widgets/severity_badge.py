"""
Severity badge widget — colored label showing CRITICAL/HIGH/MEDIUM/LOW/INFO.
"""
from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt
from fixmyslop.macros import SEVERITY_COLORS


def _badge_style(severity: str) -> str:
    """Outlined badge in the severity color (Qt hex alpha is #AARRGGBB, so use rgba)."""
    color = SEVERITY_COLORS.get(severity, "#90A4AE").lstrip("#")
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return (
        f"background-color: rgba({r}, {g}, {b}, 0.12); "
        f"color: rgb({r}, {g}, {b}); "
        f"border: 1px solid rgba({r}, {g}, {b}, 0.45); "
        "border-radius: 4px; padding: 2px 8px; font-size: 11px; font-weight: 600;"
    )


class SeverityBadge(QLabel):
    """A colored badge label for issue severity levels."""

    def __init__(self, severity: str, parent=None):
        """Initialize badge with severity level text and color."""
        super().__init__(severity, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(_badge_style(severity))
        self.setFixedHeight(22)

    def set_severity(self, severity: str):
        """Update the badge to a new severity level."""
        self.setText(severity)
        self.setStyleSheet(_badge_style(severity))
