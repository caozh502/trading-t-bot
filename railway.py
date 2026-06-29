"""
Railway entry point — runs the original polling bot 24/7.
No webhook, no timeout issues. Just a long-running Python process.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from bot import main

if __name__ == "__main__":
    main()
