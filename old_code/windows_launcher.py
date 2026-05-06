#!/usr/bin/env python3
"""
Windows launcher for Medical RAG Desktop Application.
This is the main entry point for the bundled Windows .exe.
"""

import sys
import os
from pathlib import Path

def main():
    """Main entry point with comprehensive error handling for Windows."""
    try:
        print("=" * 60)
        print("Medical RAG - Starting...")
        print("=" * 60)

        # Ensure src is in the path
        sys.path.insert(0, str(Path(__file__).parent))

        # Import and run the app in desktop mode
        print("Loading application modules...")
        from app import run_desktop

        print("Starting desktop application...\n")
        run_desktop()

    except KeyboardInterrupt:
        print("\n\nApplication stopped by user")
        input("\nPress Enter to exit...")
        sys.exit(0)

    except ImportError as e:
        print(f"\n\nERROR: Failed to import required module")
        print(f"Details: {e}")
        print("\nThis usually means a dependency is missing from the build.")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")
        sys.exit(1)

    except Exception as e:
        print(f"\n\nERROR: Application crashed")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")
        print("\nFull traceback:")
        import traceback
        traceback.print_exc()

        print("\n" + "=" * 60)
        print("Troubleshooting:")
        print("1. Make sure Ollama is installed and running")
        print("2. Run: ollama pull deepseek-r1:1.5b")
        print("3. Run: ollama pull nomic-embed-text")
        print("=" * 60)

        input("\nPress Enter to exit...")
        sys.exit(1)

if __name__ == "__main__":
    main()
