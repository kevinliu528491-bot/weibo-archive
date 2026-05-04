import os
import subprocess
import datetime
import sys
import shutil
import tempfile
import glob

# Minimum free disk space (GiB) required to run git sync
from dotenv import load_dotenv
load_dotenv()

MIN_FREE_GB = 5.0

# GitHub repo URL
_token = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = f"https://{_token}@github.com/kevinliu528491-bot/weibo-archive.git" if _token else "https://github.com/kevinliu528491-bot/weibo-archive.git"

# Git identity for commits
GIT_USER_NAME = "kevinliu528491-bot"
GIT_USER_EMAIL = "kevinliu528491-bot@users.noreply.github.com"

# Project root (parent of backend/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] git_sync: {msg}", file=sys.stderr, flush=True)

def run_git_command(command, cwd):
    """Runs a git command and prints output."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120  # 2 minute timeout to prevent hangs
        )
        _log(f"Success: {' '.join(command)}")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.TimeoutExpired:
        _log(f"TIMEOUT: {' '.join(command)} (killed after 120s)")
        return False
    except subprocess.CalledProcessError as e:
        _log(f"Error running {' '.join(command)}: {e.stderr}")
        return False

def _ensure_project_git():
    """Ensure there is a .git repo scoped to the project directory (scratch/), not ~.
    
    Returns the project root directory if git is set up, or None if it fails.
    """
    git_dir = os.path.join(PROJECT_ROOT, ".git")
    
    if os.path.isdir(git_dir):
        # Verify it's OUR repo, not the home-dir one
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=PROJECT_ROOT, capture_output=True, text=True
            )
            toplevel = result.stdout.strip()
            if toplevel == PROJECT_ROOT:
                return PROJECT_ROOT
            else:
                _log(f"WARNING: git toplevel is {toplevel}, not {PROJECT_ROOT}")
                # Fall through to re-init
        except Exception:
            pass
    
    # Initialize a fresh git repo scoped to the project
    _log(f"Initializing project-level git repo in {PROJECT_ROOT}")
    try:
        subprocess.run(["git", "init"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
        subprocess.run(["git", "config", "user.name", GIT_USER_NAME], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
        subprocess.run(["git", "config", "user.email", GIT_USER_EMAIL], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
        
        # Set remote
        subprocess.run(["git", "remote", "add", "origin", GITHUB_REPO], cwd=PROJECT_ROOT, capture_output=True, text=True)
        # If remote already exists, update it
        subprocess.run(["git", "remote", "set-url", "origin", GITHUB_REPO], cwd=PROJECT_ROOT, capture_output=True, text=True)
        
        _log("Project-level git repo initialized.")
        return PROJECT_ROOT
    except Exception as e:
        _log(f"Failed to init project git repo: {e}")
        return None


def _deploy_gh_pages(base_dir):
    """Deploy static dir to gh-pages using a lightweight temp-repo approach.
    
    Creates a fresh temporary git repo with just the static files
    and force-pushes it to the gh-pages branch.
    """
    static_dir = os.path.join(base_dir, "static")
    if not os.path.isdir(static_dir):
        _log("No static directory found, skipping gh-pages deploy.")
        return

    _log("Deploying to gh-pages (lightweight method)...")
    
    # Use a temp directory to create a minimal repo with just static files
    tmp_dir = tempfile.mkdtemp(prefix="ghpages_")
    try:
        # Copy static files to temp dir
        for item in os.listdir(static_dir):
            src = os.path.join(static_dir, item)
            dst = os.path.join(tmp_dir, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        
        # Init a fresh git repo in the temp dir
        subprocess.run(["git", "init"], cwd=tmp_dir, capture_output=True, text=True, check=True)
        subprocess.run(["git", "config", "user.name", GIT_USER_NAME], cwd=tmp_dir, capture_output=True, text=True, check=True)
        subprocess.run(["git", "config", "user.email", GIT_USER_EMAIL], cwd=tmp_dir, capture_output=True, text=True, check=True)
        subprocess.run(["git", "checkout", "-b", "gh-pages"], cwd=tmp_dir, capture_output=True, text=True, check=True)
        subprocess.run(["git", "add", "."], cwd=tmp_dir, capture_output=True, text=True, check=True)
        
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(
            ["git", "commit", "-m", f"Deploy: {date_str}"],
            cwd=tmp_dir, capture_output=True, text=True, check=True
        )
        
        # Force push to gh-pages
        push_ok = run_git_command(
            ["git", "push", "--force", GITHUB_REPO, "gh-pages"],
            cwd=tmp_dir
        )
        if push_ok:
            _log("gh-pages deployed successfully.")
        else:
            _log("ERROR: Failed to push to gh-pages!")
    except Exception as e:
        import traceback
        _log(f"Error deploying to gh-pages: {e}")
        traceback.print_exc(file=sys.stderr)
    finally:
        # Clean up temp dir
        shutil.rmtree(tmp_dir, ignore_errors=True)

def sync_content():
    """Syncs the Weibo content to GitHub.
    
    Uses a project-level git repo (in scratch/) to commit changes,
    then deploys static files to gh-pages via a temp repo.
    """
    # Check disk space before proceeding
    disk = shutil.disk_usage("/")
    free_gb = disk.free / (1024**3)
    _log(f"Disk free: {free_gb:.1f} GiB (minimum: {MIN_FREE_GB} GiB)")
    if free_gb < MIN_FREE_GB:
        _log(f"WARNING: Less than {MIN_FREE_GB} GiB free. Skipping git sync.")
        return
    
    _log("Starting GitHub sync...")
    
    # Ensure we have a project-level git repo (not home-dir level)
    repo_dir = _ensure_project_git()
    if not repo_dir:
        _log("ERROR: Could not set up project git repo. Skipping sync.")
        return
    
    base_dir = os.path.join(repo_dir, "backend")
    
    # 1. Create .gitignore to keep the repo small
    gitignore_path = os.path.join(repo_dir, ".gitignore")
    if not os.path.exists(gitignore_path):
        with open(gitignore_path, "w") as f:
            f.write("__pycache__/\n*.pyc\n.DS_Store\n")
    
    # 2. Add specific files (relative to project root)
    files_to_add = [
        "backend/weibo_data.db",
        "backend/weibo_history.xlsx",
        "backend/static/",
        "backend/*.py",
        "backend/requirements.txt",
        "run.sh",
        ".gitignore",
    ]
    for path in files_to_add:
        run_git_command(["git", "add", "-f", path], cwd=repo_dir)
        
    # 3. Commit
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_msg = f"Auto-update: Weibo content {date_str}"
    
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir, capture_output=True, text=True
        )
        if result.stdout.strip():
             run_git_command(["git", "commit", "-m", commit_msg], cwd=repo_dir)
             # Update origin URL with token and push main branch
             run_git_command(["git", "remote", "set-url", "origin", GITHUB_REPO], cwd=repo_dir)
             run_git_command(["git", "push", "origin", "main"], cwd=repo_dir)
        else:
             _log("No changes to commit.")
    except Exception as e:
        _log(f"Error checking status: {e}")

    # 4. Deploy to gh-pages (lightweight, no subtree split)
    _deploy_gh_pages(base_dir)

    _log("GitHub sync completed.")

if __name__ == "__main__":
    sync_content()
