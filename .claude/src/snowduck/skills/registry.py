"""
Skill registry with hot-reload capability using watchdog.
"""
import importlib
import inspect
import sys
from pathlib import Path
from typing import Dict, Type, Any, Optional
import logging

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .base import Skill

logger = logging.getLogger(__name__)


class _SkillChangeHandler(FileSystemEventHandler):
    """Handle file changes in the skills directory."""

    def __init__(self, registry: "SkillRegistry"):
        self.registry = registry

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            logger.info(f"Skill file changed: {event.src_path}; reloading...")
            self.registry._load_skills()

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            logger.info(f"Skill file created: {event.src_path}; loading...")
            self.registry._load_skills()

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            logger.info(f"Skill file deleted: {event.src_path}; reloading...")
            self.registry._load_skills()


class SkillRegistry:
    """Discovers and loads Skill implementations from a directory."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir.resolve()
        self._skills: Dict[str, Skill] = {}
        self._observer: Optional[Observer] = None
        self._load_skills()

    def _load_skills(self):
        """Load all Skill subclasses from .py files in the skills directory."""
        new_skills: Dict[str, Skill] = {}
        # Ensure src is in sys.path (added by agent); snowduck is a package
        for py_file in self.skills_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_name = f"snowduck.skills.{py_file.stem}"
            try:
                # Import or reload module
                if module_name in sys.modules:
                    module = importlib.reload(sys.modules[module_name])
                else:
                    module = importlib.import_module(module_name)

                # Find all subclasses of Skill (excluding base)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, Skill) and obj is not Skill:
                        # Instantiate (assuming no required args; we can pass config later)
                        try:
                            instance = obj()
                            if instance.name in new_skills:
                                logger.warning(
                                    f"Duplicate skill name '{instance.name}' from {module_name}.{name}; overwriting."
                                )
                            new_skills[instance.name] = instance
                            logger.debug(f"Loaded skill: {instance.name} from {module_name}.{name}")
                        except Exception as e:
                            logger.error(
                                f"Failed to instantiate skill {module_name}.{name}: {e}", exc_info=True
                            )
            except Exception as e:
                logger.error(f"Failed to load skill module {module_name}: {e}", exc_info=True)

        self._skills = new_skills
        logger.info(f"Loaded {len(self._skills)} skills: {list(self._skills.keys())}")

    def start_watching(self):
        """Start file system watcher for hot-reloading."""
        if self._observer is not None:
            return
        event_handler = _SkillChangeHandler(self)
        self._observer = Observer()
        self._observer.schedule(event_handler, str(self.skills_dir), recursive=False)
        self._observer.start()
        logger.info(f"Started watching skill directory: {self.skills_dir}")

    def stop_watching(self):
        """Stop the file system watcher."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Stopped watching skill directory.")

    def get(self, name: str) -> Optional[Skill]:
        """Retrieve a skill instance by name."""
        return self._skills.get(name)

    def all(self) -> Dict[str, Skill]:
        """Return a copy of all loaded skills."""
        return self._skills.copy()
