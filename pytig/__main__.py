"""允许通过 python -m pytig 运行"""
from .cli import main
import sys

if __name__ == "__main__":
    sys.exit(main())
