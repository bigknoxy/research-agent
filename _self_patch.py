"""Auto-generated self-patch by Deep Research Agent GEPA loop."""
"""Apply learned prompt improvements to research_agent.py"""
from pathlib import Path
import re

script = Path(__file__).resolve().parent / 'research_agent.py'
content = script.read_text()

# Bump version
content = content.replace("SCRIPT_VERSION = \"2.0.0\"", "SCRIPT_VERSION = \"2.0.1\"")

# Update prompt for planner
content = re.sub(
    r'    "planner": ".*?",',
    '    "planner": "Decompose the research query into sub-questions and a research plan.",',
    content,
)

# Update prompt for crawler
content = re.sub(
    r'    "crawler": ".*?",',
    '    "crawler": "Fetch and extract clean text from URLs, stripping HTML boilerplate.",',
    content,
)

# Update prompt for contradiction
content = re.sub(
    r'    "contradiction": ".*?",',
    '    "contradiction": "Analyze texts for conflicting statistics, sources, and divergent claims.",',
    content,
)

# Update prompt for synthesizer
content = re.sub(
    r'    "synthesizer": ".*?",',
    '    "synthesizer": "Generate a structured markdown report synthesizing all findings.",',
    content,
)

script.write_text(content)
print("Patched to v2.0.1 with 4 prompt updates")
