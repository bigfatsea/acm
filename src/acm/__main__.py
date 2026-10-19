"""Allow ``python -m acm``."""

import sys

from acm.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
