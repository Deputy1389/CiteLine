import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packages.shared.skills.registry import SkillRegistry

def main():
    registry = SkillRegistry()
    skills = registry.list_skills()
    
    print("\nCiteLine Skill Registry")
    print("=======================")
    print(f"Directory: {registry.skills_dir}")
    print(f"Found {len(skills)} skills:\n")
    
    for meta in skills:
        print(f"- {meta.name} ({meta.version})")
        print(f"  {meta.description}\n")

if __name__ == "__main__":
    main()
