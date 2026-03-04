#!/usr/bin/env python3
"""
Minimal git push script using GitPython.
Commits local changes and pushes to origin main.
"""

from git import Repo
import sys

try:
    repo = Repo('.')
    
    # Show changed files
    print("\n📝 Changed files:")
    for item in repo.index.diff(None):
        print(f"  - {item.a_path if item.a_path else item.b_path}")
    
    # Stage all changes
    repo.index.add('*')
    print("\n✅ Staged all changes")
    
    # Commit
    message = "Fix AI summary setter & update tests to pass all checks"
    repo.index.commit(message)
    print(f"✅ Committed: '{message}'")
    
    # Push to origin main
    repo.remotes.origin.push('main')
    print("✅ Pushed to GitHub")
    
    print("\n🎉 Push successful! CI workflow will run automatically.")
    sys.exit(0)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print("Ensure:")
    print("  1. You have a GitHub remote configured: git remote -v")
    print("  2. You have auth set up (SSH key or personal token)")
    sys.exit(1)
