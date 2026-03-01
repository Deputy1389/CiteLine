import os
import yaml
from typing import List, Optional
from pathlib import Path
from packages.shared.skills.models import Skill, SkillMeta

class SkillRegistry:
    def __init__(self, root_dir: str = "c:\\CiteLine"):
        self.root_dir = Path(root_dir)
        self.skills_dir = self.root_dir / ".gemini" / "skills"
        self._skills: Dict[str, Skill] = {}
        self.reload()

    def reload(self):
        """Scan the skills directory and load all skills."""
        if not self.skills_dir.exists():
            return

        for skill_path in self.skills_dir.rglob("SKILL.md"):
            skill = self._parse_skill_file(skill_path)
            if skill:
                self._skills[skill.meta.name] = skill

    def _parse_skill_file(self, file_path: Path) -> Optional[Skill]:
        try:
            content = file_path.read_text(encoding="utf-8")
            # Basic YAML frontmatter parser
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1])
                    instructions = parts[2].strip()
                    
                    meta = SkillMeta(
                        name=frontmatter.get("name"),
                        description=frontmatter.get("description", ""),
                        version=frontmatter.get("version", "v1.0")
                    )
                    
                    return Skill(
                        meta=meta,
                        instructions=instructions,
                        path=str(file_path)
                    )
        except Exception as e:
            # In a production system we'd log this
            pass
        return None

    def list_skills(self) -> List[SkillMeta]:
        return [s.meta for s in self._skills.values()]

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)
