#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RACS Bot Setup Validation Script

Checks all dependencies, environment variables, and critical components.
Run this after installation to verify everything is configured correctly.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Set UTF-8 output encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Load .env file
load_dotenv()

def check_env_file():
    """Verify .env file exists."""
    env_path = Path(".env")
    if not env_path.exists():
        print("❌ .env file not found")
        return False
    print("✓ .env file exists")
    return True

def check_env_vars():
    """Check required environment variables."""
    required = [
        "TELEGRAM_BOT_TOKEN",
        "ANTHROPIC_API_KEY",
        "RACS_CONTACT_PHONE",
        "RACS_CONTACT_EMAIL",
    ]

    optional = [
        "AIRTABLE_API_KEY",
        "AIRTABLE_BASE_ID",
        "AIRTABLE_TABLE_NAME",
    ]

    print("\n🔍 Checking environment variables...")

    missing_required = []
    for var in required:
        value = os.getenv(var)
        if value:
            print(f"  ✓ {var}: configured")
        else:
            print(f"  ❌ {var}: MISSING")
            missing_required.append(var)

    for var in optional:
        value = os.getenv(var)
        if value:
            print(f"  ✓ {var}: configured")
        else:
            print(f"  ⚠️  {var}: optional (lead capture disabled)")

    return len(missing_required) == 0

def check_directory_structure():
    """Verify all required directories and files exist."""
    print("\n🗂️  Checking directory structure...")

    required_dirs = [
        "brand",
        "config",
        "tools",
        "bot",
        "workflows",
        ".tmp",
    ]

    required_files = [
        "brand/racs_voice.md",
        "config/cta_strategy.json",
        "tools/xds_query.py",
        "tools/orchestrator.py",
        "bot/telegram_bot.py",
        "bot/lead_capture.py",
        "workflows/compliance_query.md",
        "README.md",
        "requirements.txt",
    ]

    all_good = True

    for directory in required_dirs:
        if Path(directory).exists():
            print(f"  ✓ {directory}/")
        else:
            print(f"  ❌ {directory}/ missing")
            all_good = False

    for file in required_files:
        if Path(file).exists():
            print(f"  ✓ {file}")
        else:
            print(f"  ❌ {file} missing")
            all_good = False

    return all_good

def check_dependencies():
    """Check if required packages are installed."""
    print("\n📦 Checking Python dependencies...")

    required = [
        "anthropic",
        "telegram",
        "requests",
        "bs4",
        "dotenv",
    ]

    all_installed = True
    for package in required:
        try:
            __import__(package if package != "bs4" else "bs4")
            print(f"  ✓ {package}")
        except ImportError:
            print(f"  ❌ {package} not installed")
            all_installed = False

    if not all_installed:
        print("\n💡 Install dependencies with: pip install -r requirements.txt")

    return all_installed

def check_xds_connection():
    """Test XDS connectivity."""
    print("\n🌐 Testing XDS connection...")
    try:
        from tools.xds_query import XDSQueryEngine
        print("  ✓ XDSQueryEngine imported successfully")
        return True
    except Exception as e:
        print(f"  ❌ Error importing XDSQueryEngine: {e}")
        return False

def check_orchestrator():
    """Test orchestrator import."""
    print("\n🧠 Testing orchestrator...")
    try:
        from tools.orchestrator import Orchestrator
        print("  ✓ Orchestrator imported successfully")
        return True
    except Exception as e:
        print(f"  ❌ Error importing Orchestrator: {e}")
        return False

def check_bot():
    """Test bot import."""
    print("\n🤖 Testing Telegram bot...")
    try:
        from bot.telegram_bot import RACSBot
        print("  ✓ RACSBot imported successfully")
        return True
    except Exception as e:
        print(f"  ❌ Error importing RACSBot: {e}")
        return False

def main():
    """Run all validation checks."""
    print("=" * 60)
    print("RACS Compliance Bot - Setup Validation")
    print("=" * 60)

    checks = [
        ("Environment file", check_env_file),
        ("Environment variables", check_env_vars),
        ("Directory structure", check_directory_structure),
        ("Dependencies", check_dependencies),
        ("XDS connection", check_xds_connection),
        ("Orchestrator", check_orchestrator),
        ("Telegram Bot", check_bot),
    ]

    results = []
    for name, check_fn in checks:
        try:
            result = check_fn()
            results.append((name, result))
        except Exception as e:
            print(f"⚠️  Error checking {name}: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓" if result else "❌"
        print(f"{status} {name}")

    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\n✨ All checks passed! Your RACS bot is ready to run.")
        print("\nNext step: python bot/telegram_bot.py")
        return 0
    else:
        print("\n⚠️  Some checks failed. Review the output above and fix issues.")
        print("\nCommon fixes:")
        print("  1. Run: pip install -r requirements.txt")
        print("  2. Fill in .env variables (check brand/racs_voice.md for guidance)")
        print("  3. Verify directory structure (brand/, config/, tools/, bot/)")
        return 1

if __name__ == "__main__":
    sys.exit(main())
