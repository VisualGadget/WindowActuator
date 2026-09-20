import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'ext_modules' / 'utemplate'))

from utemplate.source import Compiler  # type: ignore[import-not-found]  # noqa: E402

TEMPLATE_ROOT = PROJECT_ROOT / 'templates'
FROZEN_TEMPLATE_ROOT = PROJECT_ROOT / 'freeze' / 'templates'


def compile_template(source_path: Path) -> None:
    """
    Compile a utemplate source file to a frozen Python module.

    :param source_path: Template source path.
    """
    target_path = FROZEN_TEMPLATE_ROOT / f'{source_path.stem}_html.py'
    with source_path.open(encoding='utf8') as source_file:
        with target_path.open('w', encoding='utf8') as target_file:
            Compiler(source_file, target_file).compile()


def main() -> None:
    """
    Compile all web templates for inclusion in the firmware.
    """
    FROZEN_TEMPLATE_ROOT.mkdir(exist_ok=True)
    for source_path in sorted(TEMPLATE_ROOT.glob('*.html')):
        compile_template(source_path=source_path)


if __name__ == '__main__':
    main()
