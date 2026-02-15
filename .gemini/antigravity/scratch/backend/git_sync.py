import os
import subprocess
import datetime
import sys

# Configuration
# Only sync these specific paths to avoid messing with the user's home dir
SYNC_PATHS = [
    "weibo_data.db",
    "images/",
    "static/",
    "weibo_history.xlsx",
    "*.json",
    "*.py", # Also sync python scripts for backup
    "*.sh", # Sync shell scripts
    "requirements.txt"
]

def run_git_command(command, cwd):
    """Runs a git command and prints output."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"Success: {' '.join(command)}")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running {' '.join(command)}: {e.stderr}", file=sys.stderr)
        return False

def sync_content():
    """Syncs the Weibo content to GitHub."""
    print("Starting GitHub sync...")
    
    # Ensure we are in the backend directory
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Add specific files
    for path in SYNC_PATHS:
        # Construct the command. If it's a wildcard, let the shell expand it or git handle it.
        # But subprocess doesn't expand wildcards by default without shell=True.
        # Safer to use git's wildcard handling.
        cmd = ["git", "add", "-f", path]
        run_git_command(cmd, cwd=base_dir)
        
    # 2. Commit
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"Auto-update: Weibo content {date_str}"
    
    # Check if there are changes to commit
    status_cmd = ["git", "status", "--porcelain"]
    try:
        result = subprocess.run(status_cmd, cwd=base_dir, capture_output=True, text=True)
        if result.stdout.strip():
             run_git_command(["git", "commit", "-m", commit_msg], cwd=base_dir)
        else:
             print("No changes to commit.")
    except Exception as e:
        print(f"Error checking status: {e}")

    # 3. Pull --rebase (to avoid conflicts)
    # Get current branch
    try:
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=base_dir,
            check=True,
            capture_output=True,
            text=True
        )
        current_branch = branch_result.stdout.strip()
    except:
        current_branch = "main" # Fallback

    # Try simple pull first
    if not run_git_command(["git", "pull", "--rebase"], cwd=base_dir):
        print("Pull failed, possibly no upstream. Continuing to push...")
    
    # 4. Push
    # Try simple push
    if not run_git_command(["git", "push"], cwd=base_dir):
        print(f"Simple push failed. Trying to set upstream for {current_branch}...")
        run_git_command(["git", "push", "--set-upstream", "origin", current_branch], cwd=base_dir)
    
    # 5. Push to gh-pages (Deploy static site)
    print("Deploying to gh-pages...")
    try:
        # Find repo root
        root_res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=base_dir,
            check=True,
            capture_output=True,
            text=True
        )
        repo_root = root_res.stdout.strip()
        
        # Calculate relative path to static dir
        static_dir = os.path.join(base_dir, "static")
        rel_path = os.path.relpath(static_dir, repo_root)
        
        # We need to run git subtree from the repo root
        # Start with a split to get the hash (safer/faster than push sometimes)
        split_cmd = ["git", "subtree", "split", "--prefix", rel_path, "main"]
        split_res = subprocess.run(
            split_cmd,
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True
        )
        commit_hash = split_res.stdout.strip()
        
        if commit_hash:
            print(f"Subtree split successful: {commit_hash}")
            # Force push to gh-pages
            push_cmd = ["git", "push", "origin", f"{commit_hash}:gh-pages", "--force"]
            run_git_command(push_cmd, cwd=repo_root)
        else:
            print("Failed to split subtree: No hash returned.")
            
    except Exception as e:
        print(f"Error deploying to gh-pages: {e}")

    print("GitHub sync completed.")

if __name__ == "__main__":
    sync_content()
