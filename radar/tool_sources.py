"""Official release endpoints; no model APIs or authentication required."""


def _source(id_, name, product, product_name, url, parser, lab, **extra):
    return dict(id=id_, name=name, product=product, product_name=product_name,
                url=url, parser=parser, lab=lab, publisher=lab, kind="changelog",
                group="tool", first_wave=False, **extra)


SOURCES = [
    _source("claude-code-feed", "Claude Code · official changelog feed", "claude-code", "Claude Code",
            "https://raw.githubusercontent.com/anthropics/claude-code/main/feed.xml", "atom", "anthropic",
            release_prefix="https://github.com/anthropics/claude-code/releases/tag/"),
    _source("claude-code-changelog", "Claude Code · CHANGELOG", "claude-code", "Claude Code",
            "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md", "markdown", "anthropic",
            entry_prefix="https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md#"),
    _source("codex-changelog", "Codex · official changelog", "codex", "Codex",
            "https://developers.openai.com/codex/changelog", "codex_html", "openai",
            entry_base="https://learn.chatgpt.com/docs/changelog",
            products={"codex": "Codex", "codex-cli": "Codex CLI", "codex-desktop": "Codex desktop"}),
]
