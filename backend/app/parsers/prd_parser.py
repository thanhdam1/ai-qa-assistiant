import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AcceptanceCriteria(BaseModel):
    id: str = Field(description="Unique AC Identifier e.g. AC-01")
    description: str = Field(description="Given-When-Then or clear acceptance statement")
    gherkin_given: Optional[str] = None
    gherkin_when: Optional[str] = None
    gherkin_then: Optional[str] = None

class UserStory(BaseModel):
    id: str = Field(description="User story ID e.g. US-01")
    title: str
    as_a: Optional[str] = None
    i_want_to: Optional[str] = None
    so_that: Optional[str] = None
    acceptance_criteria: List[AcceptanceCriteria] = Field(default_factory=list)
    business_rules: List[str] = Field(default_factory=list)

class ParsedPRD(BaseModel):
    title: str
    version: Optional[str] = "1.0.0"
    overview: str = ""
    user_stories: List[UserStory] = Field(default_factory=list)
    global_business_rules: List[str] = Field(default_factory=list)
    raw_sections: Dict[str, str] = Field(default_factory=dict)

class PRDParser:
    """
    Parses PRD, SRS, and User Stories from Markdown or plain text into structured objects.
    Extracts Gherkin criteria (Given-When-Then) and business rules.
    """

    @staticmethod
    def parse_markdown(content: str, filename: str = "PRD.md") -> ParsedPRD:
        lines = content.splitlines()
        title = filename.replace(".md", "").replace("_", " ").title()
        overview = []
        user_stories: List[UserStory] = []
        global_rules = []
        raw_sections: Dict[str, str] = {}
        
        current_section = "Header"
        current_section_lines = []
        
        current_us: Optional[UserStory] = None
        us_counter = 1
        ac_counter = 1

        for line in lines:
            stripped = line.strip()
            
            # Heading 1: Main Title
            if stripped.startswith("# "):
                title = stripped.replace("#", "").strip()
                continue
                
            # Heading 2 or 3: Sections or User Stories
            if stripped.startswith("## ") or stripped.startswith("### "):
                if current_section_lines:
                    raw_sections[current_section] = "\n".join(current_section_lines).strip()
                    current_section_lines = []
                    
                current_section = stripped.replace("#", "").strip()
                
                # Check if heading describes a User Story or Feature
                if any(k in current_section.lower() for k in ["story", "user story", "feature", "tính năng"]):
                    if current_us:
                        user_stories.append(current_us)
                    current_us = UserStory(
                        id=f"US-{us_counter:02d}",
                        title=current_section
                    )
                    us_counter += 1
                continue
            
            current_section_lines.append(line)
            
            # Extract User Story syntax: As a [role], I want [action], so that [outcome]
            if current_us:
                us_match = re.search(r"as a\s+(.+?),\s*i want (?:to\s+)?(.+?),\s*so that\s+(.+)", stripped, re.IGNORECASE)
                if us_match:
                    current_us.as_a = us_match.group(1).strip()
                    current_us.i_want_to = us_match.group(2).strip()
                    current_us.so_that = us_match.group(3).strip()
                    continue
                
                # Extract Acceptance Criteria (Given-When-Then)
                if any(prefix in stripped.lower() for prefix in ["ac:", "acceptance criteria", "- given", "* given", "tiêu chí"]):
                    pass
                
                gherkin_match = re.search(r"given\s+(.+?)\s+when\s+(.+?)\s+then\s+(.+)", stripped, re.IGNORECASE)
                if gherkin_match:
                    current_us.acceptance_criteria.append(AcceptanceCriteria(
                        id=f"AC-{ac_counter:02d}",
                        description=stripped,
                        gherkin_given=gherkin_match.group(1).strip(),
                        gherkin_when=gherkin_match.group(2).strip(),
                        gherkin_then=gherkin_match.group(3).strip(),
                    ))
                    ac_counter += 1
                    continue
                
                # Bullet acceptance criteria
                if stripped.startswith(("- ", "* ", "1. ", "2. ", "3. ")) and len(stripped) > 5:
                    clean_item = re.sub(r"^[-*\d.]+\s*", "", stripped)
                    if any(term in clean_item.lower() for term in ["phải", "must", "should", "yêu cầu", "then", "khi", "when"]):
                        current_us.acceptance_criteria.append(AcceptanceCriteria(
                            id=f"AC-{ac_counter:02d}",
                            description=clean_item
                        ))
                        ac_counter += 1
                        continue

            # Global business rules
            if any(term in stripped.lower() for term in ["quy tắc", "rule:", "business rule", "điều kiện"]):
                if stripped.startswith(("- ", "* ")):
                    global_rules.append(re.sub(r"^[-*]\s*", "", stripped))

        # Save final section & user story
        if current_section_lines:
            raw_sections[current_section] = "\n".join(current_section_lines).strip()
        if current_us:
            user_stories.append(current_us)
            
        # Fallback: If no explicit user stories were found, create a default one with the content
        if not user_stories:
            user_stories.append(UserStory(
                id="US-01",
                title=title,
                acceptance_criteria=[
                    AcceptanceCriteria(id=f"AC-{i+1:02d}", description=line.strip("- *"))
                    for i, line in enumerate(lines) if line.strip().startswith(("- ", "* ")) and len(line.strip()) > 8
                ]
            ))

        return ParsedPRD(
            title=title,
            overview=overview[0] if overview else (raw_sections.get("Overview", "") or raw_sections.get("Mô tả", "")),
            user_stories=user_stories,
            global_business_rules=global_rules,
            raw_sections=raw_sections,
        )
