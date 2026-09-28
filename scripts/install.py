#!/usr/bin/env python3
"""Link the skill into user discovery; optionally install an old-client prompt."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-dir', type=Path, default=Path.home() / '.agents/skills')
    parser.add_argument('--codex-home', type=Path,
                        default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    parser.add_argument('--legacy-prompt', action='store_true',
                        help='Also install /prompts:token-audit for clients retaining custom prompts')
    args = parser.parse_args()
    source = ROOT / 'skills/token-audit'
    target = args.skills_dir.expanduser().absolute() / 'token-audit'
    prompt = args.codex_home.expanduser().absolute() / 'prompts/token-audit.md'
    text = (ROOT / 'prompts/token-audit.md').read_text().replace(
        '__SKILL_PATH__', str(target / 'SKILL.md').replace('$', '$$'))
    try:
        if target.exists() or target.is_symlink():
            if not target.is_symlink() or target.resolve() != source.resolve():
                raise ValueError(f'Refusing to replace existing skill: {target}')
        if args.legacy_prompt and (prompt.exists() or prompt.is_symlink()):
            if prompt.is_symlink() or not prompt.is_file() or prompt.read_text() != text:
                raise ValueError(f'Refusing to replace existing prompt: {prompt}')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_symlink():
            target.symlink_to(source, target_is_directory=True)
        if args.legacy_prompt:
            prompt.parent.mkdir(parents=True, exist_ok=True)
            if not prompt.exists():
                with prompt.open('x') as stream:
                    stream.write(text)
            print(f'Legacy prompt: {prompt} (unsupported in Codex 0.158.0)')
        print(f'Skill: {target}\nOpen a new chat. Use /skills to select token-audit, or $token-audit.')
        return 0
    except (OSError, ValueError) as exc:
        print(f'token-audit install: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
