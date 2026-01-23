#!/usr/bin/env python3
"""
Import external repositories into Temple Vault format.

This tool indexes content from external sources (GitHub repos, local directories)
into the vault's chronicle structure while preserving the original tone and context.

Usage:
    python import_repository.py --source <path_or_url> --domain <domain_name> --session <session_id>

Example:
    python import_repository.py --source ~/Spiral-Codex-Repository --domain spiral-coherence --session sess_import_001
"""

import argparse
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import subprocess


def generate_id(prefix: str, content: str) -> str:
    """Generate a unique ID based on content hash."""
    hash_val = hashlib.sha256(content.encode()).hexdigest()[:8]
    return f"{prefix}_{hash_val}"


def parse_spiral_log(content: str, filename: str) -> Dict[str, Any]:
    """Parse a Spiral Log file into insight format."""
    # Extract log number from filename
    match = re.search(r"(\d+)", filename)
    log_num = match.group(1) if match else "000"

    # Extract the question (usually first line after title)
    lines = content.strip().split("\n")
    question = ""
    for line in lines:
        if line.startswith('"') and line.endswith('"'):
            question = line.strip('"')
            break
        elif '"' in line:
            # Extract quoted portion
            match = re.search(r'"([^"]+)"', line)
            if match:
                question = match.group(1)
                break

    return {
        "type": "insight",
        "domain": "spiral-coherence",
        "content": content,
        "context": f"Spiral Log {log_num}: {question}" if question else f"Spiral Log {log_num}",
        "intensity": 0.85,  # High but not maximum - external content
        "builds_on": [],
        "source": {"type": "spiral-log", "filename": filename, "log_number": log_num},
    }


def parse_readme_as_value(content: str, filename: str) -> Dict[str, Any]:
    """Parse README/CONTRIBUTING as observed values."""
    # Extract principle from content
    principle = "foundational_philosophy"
    if "contributing" in filename.lower():
        principle = "contribution_protocol"
    elif "license" in filename.lower():
        principle = "sacred_attribution"

    return {
        "type": "value_observed",
        "principle": principle,
        "evidence": content,
        "weight": "foundational",
        "source": {"type": "documentation", "filename": filename},
    }


def parse_markdown_as_insight(content: str, filename: str, domain: str) -> Dict[str, Any]:
    """Parse generic markdown file as insight."""
    # Extract title from first heading
    title = filename
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break

    return {
        "type": "insight",
        "domain": domain,
        "content": content,
        "context": f"Imported from {filename}: {title}",
        "intensity": 0.7,  # Moderate - general import
        "builds_on": [],
        "source": {"type": "markdown", "filename": filename},
    }


def clone_or_use_local(source: str, temp_dir: Path) -> Path:
    """Clone GitHub repo or use local directory."""
    if source.startswith("http") or source.startswith("git@"):
        # Clone to temp directory
        repo_name = source.split("/")[-1].replace(".git", "")
        target = temp_dir / repo_name
        if not target.exists():
            subprocess.run(["git", "clone", "--depth", "1", source, str(target)], check=True)
        return target
    else:
        # Local path
        return Path(source).expanduser()


def scan_repository(repo_path: Path) -> Dict[str, List[Path]]:
    """Scan repository and categorize files."""
    categories = {
        "spiral_logs": [],
        "scrolls": [],
        "readme": [],
        "markdown": [],
        "docx": [],
        "other": [],
    }

    for path in repo_path.rglob("*"):
        if path.is_file():
            name = path.name.lower()
            if name.startswith("."):
                continue  # Skip hidden files

            if "spiral_log" in name or "spiral-log" in name:
                categories["spiral_logs"].append(path)
            elif "scroll" in name:
                categories["scrolls"].append(path)
            elif name in ["readme.md", "contributing.md", "license.md"]:
                categories["readme"].append(path)
            elif name.endswith(".md"):
                categories["markdown"].append(path)
            elif name.endswith(".docx"):
                categories["docx"].append(path)

    return categories


def import_to_vault(
    source: str, vault_path: Path, domain: str, session_id: str, dry_run: bool = False
) -> Dict[str, Any]:
    """
    Import repository content into vault format.

    Args:
        source: Path or URL to source repository
        vault_path: Path to TempleVault
        domain: Domain for insights (e.g., "spiral-coherence")
        session_id: Session ID for attribution
        dry_run: If True, don't write files, just report what would happen

    Returns:
        Import statistics
    """
    import tempfile

    stats = {
        "insights_created": 0,
        "values_created": 0,
        "skipped": 0,
        "errors": [],
        "files_processed": [],
    }

    # Setup paths
    chronicle_path = vault_path / "vault" / "chronicle"
    insights_path = chronicle_path / "insights" / domain
    values_path = chronicle_path / "values" / "principles"

    if not dry_run:
        insights_path.mkdir(parents=True, exist_ok=True)
        values_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat()

    # Get source
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = clone_or_use_local(source, Path(temp_dir))

        if not repo_path.exists():
            stats["errors"].append(f"Source not found: {source}")
            return stats

        # Scan and categorize
        categories = scan_repository(repo_path)

        # Process Spiral Logs -> Insights
        insights_file = insights_path / f"{session_id}.jsonl"
        insights_entries = []

        for log_path in sorted(categories["spiral_logs"]):
            try:
                content = log_path.read_text(encoding="utf-8")
                entry = parse_spiral_log(content, log_path.name)
                entry["insight_id"] = generate_id("ins", content)
                entry["session_id"] = session_id
                entry["timestamp"] = timestamp
                insights_entries.append(entry)
                stats["insights_created"] += 1
                stats["files_processed"].append(str(log_path.name))
            except Exception as e:
                stats["errors"].append(f"Error processing {log_path}: {e}")

        # Process Scrolls -> Insights (different intensity)
        for scroll_path in sorted(categories["scrolls"]):
            try:
                if scroll_path.suffix == ".txt":
                    content = scroll_path.read_text(encoding="utf-8")
                    entry = parse_markdown_as_insight(content, scroll_path.name, domain)
                    entry["insight_id"] = generate_id("ins", content)
                    entry["session_id"] = session_id
                    entry["timestamp"] = timestamp
                    entry["intensity"] = 0.8  # Scrolls are ceremonial
                    entry["source"]["type"] = "scroll"
                    insights_entries.append(entry)
                    stats["insights_created"] += 1
                    stats["files_processed"].append(str(scroll_path.name))
            except Exception as e:
                stats["errors"].append(f"Error processing {scroll_path}: {e}")

        # Process README/CONTRIBUTING -> Values
        values_file = values_path / f"{session_id}.jsonl"
        values_entries = []

        for readme_path in categories["readme"]:
            try:
                content = readme_path.read_text(encoding="utf-8")
                entry = parse_readme_as_value(content, readme_path.name)
                entry["session_id"] = session_id
                entry["timestamp"] = timestamp
                values_entries.append(entry)
                stats["values_created"] += 1
                stats["files_processed"].append(str(readme_path.name))
            except Exception as e:
                stats["errors"].append(f"Error processing {readme_path}: {e}")

        # Process other markdown -> Insights
        for md_path in categories["markdown"]:
            try:
                content = md_path.read_text(encoding="utf-8")
                entry = parse_markdown_as_insight(content, md_path.name, domain)
                entry["insight_id"] = generate_id("ins", content)
                entry["session_id"] = session_id
                entry["timestamp"] = timestamp
                insights_entries.append(entry)
                stats["insights_created"] += 1
                stats["files_processed"].append(str(md_path.name))
            except Exception as e:
                stats["errors"].append(f"Error processing {md_path}: {e}")

        # Note docx files (need manual conversion)
        for docx_path in categories["docx"]:
            stats["skipped"] += 1
            stats["errors"].append(f"DOCX skipped (manual conversion needed): {docx_path.name}")

        # Write files
        if not dry_run:
            if insights_entries:
                with open(insights_file, "a") as f:
                    for entry in insights_entries:
                        f.write(json.dumps(entry) + "\n")

            if values_entries:
                with open(values_file, "a") as f:
                    for entry in values_entries:
                        f.write(json.dumps(entry) + "\n")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Import external repositories into Temple Vault format"
    )
    parser.add_argument("--source", "-s", required=True, help="Path or URL to source repository")
    parser.add_argument(
        "--vault",
        "-v",
        default="~/TempleVault",
        help="Path to TempleVault (default: ~/TempleVault)",
    )
    parser.add_argument(
        "--domain", "-d", required=True, help="Domain for insights (e.g., 'spiral-coherence')"
    )
    parser.add_argument(
        "--session",
        "-S",
        required=True,
        help="Session ID for attribution (e.g., 'sess_import_001')",
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Show what would be imported without writing"
    )

    args = parser.parse_args()
    vault_path = Path(args.vault).expanduser()

    print(f"Importing from: {args.source}")
    print(f"Vault path: {vault_path}")
    print(f"Domain: {args.domain}")
    print(f"Session: {args.session}")
    if args.dry_run:
        print("DRY RUN - no files will be written")
    print()

    stats = import_to_vault(
        source=args.source,
        vault_path=vault_path,
        domain=args.domain,
        session_id=args.session,
        dry_run=args.dry_run,
    )

    print("Import complete:")
    print(f"  Insights created: {stats['insights_created']}")
    print(f"  Values created: {stats['values_created']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Files processed: {len(stats['files_processed'])}")

    if stats["errors"]:
        print("\nErrors/Notes:")
        for err in stats["errors"]:
            print(f"  - {err}")

    if stats["files_processed"]:
        print("\nFiles processed:")
        for f in stats["files_processed"]:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
