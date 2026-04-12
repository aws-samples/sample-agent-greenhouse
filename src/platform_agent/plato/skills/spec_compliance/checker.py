"""Spec compliance checker — verifies code against spec.md acceptance criteria.

Parses spec.md content, extracts acceptance criteria (AC-xxx patterns),
and checks a repository for implementation evidence and test coverage.

Traces to: spec SS3.3 (Spec Compliance Checker)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComplianceEntry:
    """Result of checking a single acceptance criterion.

    Attributes:
        ac_id: Acceptance criterion ID (e.g. "AC-001").
        description: Human-readable description of the criterion.
        section: Spec section where the AC is defined (e.g. "3.3").
        implemented: Whether implementation evidence was found.
        impl_file: File path where implementation was found (or None).
        impl_line: Line reference in the implementation file (or None).
        test_exists: Whether a corresponding test was found.
        test_file: File path of the matching test (or None).
        status: Overall status — "PASS", "PARTIAL", or "NOT_FOUND".
    """

    ac_id: str
    description: str
    section: str = ""
    implemented: bool = False
    impl_file: str | None = None
    impl_line: str | None = None
    test_exists: bool = False
    test_file: str | None = None
    status: str = "NOT_FOUND"


@dataclass
class ComplianceReport:
    """Aggregated compliance report for all acceptance criteria.

    Attributes:
        entries: List of ComplianceEntry results.
        summary: Counts of pass/partial/not_found statuses.
        repo: Repository that was checked.
        branch: Branch that was checked.
    """

    entries: list[ComplianceEntry] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    repo: str = ""
    branch: str = "main"

    def compute_summary(self) -> None:
        """Recompute summary counts from entries."""
        counts = {"PASS": 0, "PARTIAL": 0, "NOT_FOUND": 0}
        for entry in self.entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        self.summary = counts


class SpecComplianceChecker:
    """Checks a repository's code against spec.md acceptance criteria.

    Parses spec content to extract AC-xxx patterns, then searches the
    repository via GitHub API for implementation evidence and test coverage.

    Args:
        spec_content: Raw markdown content of the spec.md file.
    """

    # Pattern matches lines like: "- AC-001: Description", "- **AC-001:** Description",
    # or "- **AC-001**: Description" (plain and bold markdown formats)
    _AC_PATTERN = re.compile(
        r"(?:^|\n)\s*[-*]?\s*\*{0,2}(AC-\d+)\*{0,2}\s*:\s*\*{0,2}\s*(.+?)(?:\n|$)",
        re.MULTILINE,
    )
    # Pattern matches section headers like "### 3.3 Spec Compliance"
    _SECTION_PATTERN = re.compile(
        r"^#{1,4}\s+(\d+(?:\.\d+)*)\s+(.+)$", re.MULTILINE
    )

    def __init__(self, spec_content: str) -> None:
        """Initialize with spec.md content.

        Args:
            spec_content: Raw markdown content of the spec.md file.
        """
        self._spec_content = spec_content
        self._criteria: list[dict[str, str]] = []
        self._parse_spec()

    def _parse_spec(self) -> None:
        """Parse spec content and extract acceptance criteria with sections."""
        # Build a section map: line_number -> section_id
        section_ranges: list[tuple[int, str]] = []
        for match in self._SECTION_PATTERN.finditer(self._spec_content):
            section_ranges.append((match.start(), match.group(1)))

        for match in self._AC_PATTERN.finditer(self._spec_content):
            ac_id = match.group(1)
            description = match.group(2).strip()
            pos = match.start()

            # Find which section this AC belongs to
            section = ""
            for sec_start, sec_id in reversed(section_ranges):
                if sec_start <= pos:
                    section = sec_id
                    break

            self._criteria.append({
                "id": ac_id,
                "description": description,
                "section": section,
            })

    def extract_acceptance_criteria(self) -> list[dict[str, str]]:
        """Return the list of extracted acceptance criteria.

        Returns:
            List of dicts with keys: id, description, section.
        """
        return list(self._criteria)

    def check_compliance(
        self,
        repo: str,
        branch: str = "main",
        *,
        _github_get_tree: object | None = None,
        _github_get_file: object | None = None,
    ) -> ComplianceReport:
        """Check repo compliance against all extracted acceptance criteria.

        For each AC, searches the codebase for:
        1. Implementation evidence (comments like "Traces to: AC-xxx")
        2. Test coverage (TC-xxx matching AC-xxx in test files)

        Args:
            repo: Full repository name (e.g. "org/repo").
            branch: Branch to check. Default "main".
            _github_get_tree: Optional override for github_get_tree (for testing).
            _github_get_file: Optional override for github_get_file (for testing).

        Returns:
            ComplianceReport with an entry for each acceptance criterion.
        """
        get_tree = _github_get_tree or _import_github_get_tree()
        get_file = _github_get_file or _import_github_get_file()

        # Fetch file tree
        all_files = _collect_files(repo, branch, get_tree)

        # Separate source and test files
        source_files = [
            f for f in all_files
            if not _is_test_file(f) and _is_code_file(f)
        ]
        test_files = [f for f in all_files if _is_test_file(f)]

        # Read file contents (limit to avoid API overload)
        source_contents = _read_files(repo, branch, source_files[:100], get_file)
        test_contents = _read_files(repo, branch, test_files[:50], get_file)

        entries: list[ComplianceEntry] = []
        for criterion in self._criteria:
            ac_id = criterion["id"]
            tc_id = ac_id.replace("AC-", "TC-")

            # Search for implementation evidence
            impl_file, impl_line = _search_for_reference(
                ac_id, source_contents
            )
            implemented = impl_file is not None

            # Search for test evidence
            test_file, _ = _search_for_reference(tc_id, test_contents)
            if test_file is None:
                # Also check if AC-xxx is referenced in tests
                test_file, _ = _search_for_reference(ac_id, test_contents)
            test_exists = test_file is not None

            # Determine status
            if implemented and test_exists:
                status = "PASS"
            elif implemented or test_exists:
                status = "PARTIAL"
            else:
                status = "NOT_FOUND"

            entries.append(ComplianceEntry(
                ac_id=ac_id,
                description=criterion["description"],
                section=criterion["section"],
                implemented=implemented,
                impl_file=impl_file,
                impl_line=impl_line,
                test_exists=test_exists,
                test_file=test_file,
                status=status,
            ))

        report = ComplianceReport(entries=entries, repo=repo, branch=branch)
        report.compute_summary()
        return report

    def format_report(self, report: ComplianceReport) -> str:
        """Render a ComplianceReport as a parseable markdown table.

        Args:
            report: The compliance report to format.

        Returns:
            Markdown string with a summary and detailed table.

        Traces to: AC-13 (Output is structured/parseable)
        """
        lines: list[str] = [
            "## Spec Compliance Report",
            "",
            f"**Repository:** {report.repo} (branch: {report.branch})",
            f"**Criteria checked:** {len(report.entries)}",
            f"**PASS:** {report.summary.get('PASS', 0)} | "
            f"**PARTIAL:** {report.summary.get('PARTIAL', 0)} | "
            f"**NOT_FOUND:** {report.summary.get('NOT_FOUND', 0)}",
            "",
            "| AC ID | Description | Implemented? | Test Exists? | Status |",
            "|-------|-------------|-------------|-------------|--------|",
        ]

        for entry in report.entries:
            impl_cell = (
                f"yes {entry.impl_file}"
                + (f":{entry.impl_line}" if entry.impl_line else "")
                if entry.implemented
                else "no"
            )
            test_cell = (
                f"yes {entry.test_file}" if entry.test_exists else "no"
            )
            lines.append(
                f"| {entry.ac_id} | {entry.description} "
                f"| {impl_cell} | {test_cell} | {entry.status} |"
            )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _import_github_get_tree():
    """Lazy-import github_get_tree to avoid circular imports."""
    from platform_agent.foundation.tools.github import github_get_tree
    return github_get_tree


def _import_github_get_file():
    """Lazy-import github_get_file to avoid circular imports."""
    from platform_agent.foundation.tools.github import github_get_file
    return github_get_file


def _is_code_file(path: str) -> bool:
    """Check if a file path looks like a source code file."""
    code_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go",
        ".rs", ".rb", ".md", ".yaml", ".yml", ".toml",
    }
    return any(path.endswith(ext) for ext in code_extensions)


def _is_test_file(path: str) -> bool:
    """Check if a file path looks like a test file."""
    return (
        "/test" in path
        or "/tests" in path
        or path.startswith("test")
        or "test_" in path.split("/")[-1]
        or "_test." in path
    )


def _collect_files(
    repo: str,
    branch: str,
    get_tree: object,
) -> list[str]:
    """Recursively collect all file paths from a repo tree.

    Args:
        repo: Full repository name.
        branch: Branch to browse.
        get_tree: The github_get_tree callable.

    Returns:
        List of file path strings.
    """
    try:
        tree_json = get_tree(repo=repo, path="", branch=branch)
        tree_data = json.loads(tree_json)
    except Exception:
        logger.warning("Failed to fetch repo tree for %s@%s", repo, branch)
        return []

    files: list[str] = []
    entries = tree_data.get("entries", [])
    for entry in entries:
        if entry.get("type") == "file":
            files.append(entry["path"])
        elif entry.get("type") == "dir":
            try:
                sub_json = get_tree(
                    repo=repo, path=entry["path"], branch=branch
                )
                sub_data = json.loads(sub_json)
                for sub_entry in sub_data.get("entries", []):
                    if sub_entry.get("type") == "file":
                        files.append(sub_entry["path"])
            except Exception:
                logger.debug("Skipping directory %s", entry["path"])

    return files


def _read_files(
    repo: str,
    branch: str,
    file_paths: list[str],
    get_file: object,
) -> dict[str, str]:
    """Read file contents from GitHub.

    Args:
        repo: Full repository name.
        branch: Branch to read from.
        file_paths: List of file paths to read.
        get_file: The github_get_file callable.

    Returns:
        Dict mapping file path to file content.
    """
    contents: dict[str, str] = {}
    for path in file_paths:
        try:
            content = get_file(repo=repo, path=path, branch=branch)
            contents[path] = content
        except Exception:
            logger.debug("Could not read %s from %s@%s", path, repo, branch)
    return contents


def _search_for_reference(
    reference_id: str,
    file_contents: dict[str, str],
) -> tuple[str | None, str | None]:
    """Search file contents for a reference ID (AC-xxx or TC-xxx).

    Args:
        reference_id: The ID to search for (e.g. "AC-001", "TC-001").
        file_contents: Dict mapping file path to content.

    Returns:
        Tuple of (file_path, line_number) if found, else (None, None).
    """
    for path, content in file_contents.items():
        lines = content.split("\n")
        for i, line in enumerate(lines, start=1):
            if reference_id in line:
                return path, str(i)
    return None, None
