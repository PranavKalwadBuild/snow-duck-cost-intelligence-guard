"""
Base class for all skills.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any


class Skill(ABC):
    """Abstract base skill."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for the skill."""

    @abstractmethod
    def run(self, context: Dict[str, Any]) -> Any:
        """
        Execute the skill with the given context.

        Args:
            context: Dictionary of inputs needed by the skill.

        Returns:
            Skill-specific output.
        """
