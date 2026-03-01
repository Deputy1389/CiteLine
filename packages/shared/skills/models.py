from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class SkillMeta(BaseModel):
    """Metadata for a skill parsed from YAML frontmatter."""
    name: str
    description: str
    version: str = "v1.0"

class Skill(BaseModel):
    """Full definition of a skill including instructions."""
    meta: SkillMeta
    instructions: str
    path: str

class SkillCallInput(BaseModel):
    """Standard envelope for calling a skill."""
    skill_name: str
    skill_version: Optional[str] = None
    run_id: str
    case_id: str
    input_data: Dict[str, Any]
    created_at_utc: datetime = Field(default_factory=datetime.utcnow)

class SkillCallResponse(BaseModel):
    """Standard envelope for skill output."""
    status: str = "ok"
    output_data: Dict[str, Any]
    warnings: List[str] = []
    execution_time_ms: int
