from pathlib import Path


# repo-root/prompts/stylist/<name>.v<N>.md  (versioned so prompts can be iterated and rolled back)
def _find_prompts_dir() -> Path:
    """repo-root/prompts/stylist locally; /app/prompts/stylist in a container."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "prompts" / "stylist").is_dir():
            return parent / "prompts" / "stylist"
    raise FileNotFoundError("prompts/stylist not found next to the code")


PROMPTS_DIR = _find_prompts_dir()


def load_prompt(name: str, version: int = 1) -> str:
    return (PROMPTS_DIR / f"{name}.v{version}.md").read_text(encoding="utf-8")
